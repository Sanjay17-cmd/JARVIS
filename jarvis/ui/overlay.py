"""
ui/overlay.py — Transparent desktop overlay — JARVIS v2.0.0

Performance (Part L):
  • Single 33ms master timer drives both animation AND movement (was 2 timers)
  • Frame generation happens on a QThread — UI never blocks at startup
  • update() called only when frame index changes or button state changes
  • Dirty rect on status label (only repaint label area)
  • Cached window size avoids repeated property lookups

Part K — chest button indicators:
  • set_chest_indicator(btn_id, color_or_none) — called by mic/camera/focus services
  • Voice btn: green=active, red=muted, cyan=idle
  • Camera btn: green=active, red=disabled, cyan=idle

Part A — live robot resize:
  • set_robot_size(n): regenerates frames on QThread, resizes window, no restart needed
"""
from __future__ import annotations

import math
import random
import logging
from io import BytesIO
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint, QTimer, QRect, Signal, Slot, QThread, QObject
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QMouseEvent, QPaintEvent,
    QGuiApplication, QScreen, QPen,
)
from PySide6.QtWidgets import QWidget, QMenu, QLabel, QApplication

from jarvis.core.state import RobotState

if TYPE_CHECKING:
    from jarvis.config.settings import Settings
    from jarvis.core.state import StateManager
    from jarvis.core.event_bus import EventBus

log = logging.getLogger(__name__)

STATE_LABELS = {
    RobotState.IDLE:      "",
    RobotState.LISTENING: "🎤 Listening…",
    RobotState.THINKING:  "🤔 Thinking…",
    RobotState.SPEAKING:  "🔊 Speaking…",
    RobotState.SUCCESS:   "✅ Done!",
    RobotState.ERROR:     "⚠ Error",
    RobotState.PAUSED:    "⏸ Paused",
}

_BTN_DEFAULTS = [
    {"id": 0, "name": "Voice",     "action": "toggle_voice",    "color": "#B84DFF"},
    {"id": 1, "name": "Focus",     "action": "toggle_focus",    "color": "#2878FF"},
    {"id": 2, "name": "Reminders", "action": "open_reminders",  "color": "#FFB000"},
    {"id": 3, "name": "Actions",   "action": "open_quick_menu", "color": "#FF4FA3"},
]


def _chest_button_hit_rects(size: int) -> list[QRect]:
    """Return non-overlapping hit targets centered on the painted chest LEDs."""
    from jarvis.assets.robot_painter import get_led_positions

    offset = 10
    positions = get_led_positions(size)
    rects: list[QRect] = []
    for index, (x, y, led_radius) in enumerate(positions):
        spacing = (
            positions[index + 1][0] - x
            if index + 1 < len(positions)
            else x - positions[index - 1][0]
        )
        radius = max(1, min(led_radius, spacing // 3))
        rects.append(
            QRect(
                offset + x - radius,
                offset + y - radius,
                radius * 2 + 1,
                radius * 2 + 1,
            )
        )
    return rects


# ── Background frame-generation worker ───────────────────────────────────────

class _FrameWorker(QObject):
    """Runs PIL frame generation on a worker thread."""
    finished = Signal(dict, int)   # emits frames and the generated size
    failed = Signal(str, int)

    def __init__(self, images_dir, size: int) -> None:
        super().__init__()
        self._images_dir = images_dir
        self._size = size

    @Slot()
    def run(self) -> None:
        try:
            from jarvis.assets.robot_painter import ensure_assets
            pil_frames = ensure_assets(self._images_dir, size=self._size)
            result: dict[str, list[QPixmap]] = {}
            for state_name, imgs in pil_frames.items():
                result[state_name] = []
                for img in imgs:
                    buf = BytesIO()
                    img.save(buf, "PNG")
                    px = QPixmap()
                    if not px.loadFromData(buf.getvalue(), "PNG"):
                        raise RuntimeError(f"Could not load generated {state_name} frame")
                    result[state_name].append(px)
            self.finished.emit(result, self._size)
        except Exception as exc:
            log.exception("Frame generation failed for size %d", self._size)
            self.failed.emit(str(exc), self._size)


# ── Chest button ─────────────────────────────────────────────────────────────

class _ChestButton:
    __slots__ = ("id", "name", "action", "color", "indicator_color",
                 "rect", "hovered", "pressed", "active")

    def __init__(self, cfg: dict) -> None:
        self.id      = cfg["id"]
        self.name    = cfg["name"]
        self.action  = cfg["action"]
        raw = cfg.get("color", "#00dcff")
        self.color   = QColor(raw) if isinstance(raw, str) else QColor(*raw)
        self.indicator_color: QColor | None = None   # Part K override
        self.rect    = QRect()
        self.hovered = False
        self.pressed = False
        self.active  = False

    @property
    def display_color(self) -> QColor:
        return self.indicator_color if self.indicator_color else self.color


# ── Overlay ───────────────────────────────────────────────────────────────────

class RobotOverlay(QWidget):
    robot_clicked = Signal()
    state_changed = Signal(RobotState)

    # ── MASTER TIMER INTERVAL (ms) — drives both animation + movement ─────
    _TICK_MS = 33   # ~30 fps

    def __init__(self, settings: "Settings", state_manager: "StateManager",
                 event_bus: "EventBus") -> None:
        super().__init__(None)
        self._settings      = settings
        self._state_manager = state_manager
        self._event_bus     = event_bus

        self._robot_size    = settings.get("robot_size", 120)
        self._frames: dict[str, list[QPixmap]] = {}
        self._frames_ready  = False
        self._frame_gen_pending: int | None = None
        self._running_frame_size: int | None = None
        self._thread: QThread | None = None
        self._worker: _FrameWorker | None = None
        self._current_state = RobotState.IDLE
        self._animation_override: str | None = None
        self._frame_index   = 0
        self._prev_frame_index = -1   # track changes to avoid redundant update()

        # Movement
        self._auto_move   = settings.get("auto_movement", True)
        self._speed       = settings.get("movement_speed", 1.2)
        self._safe_margin = settings.get("safe_margin", 20)
        self._drag_offset: QPoint | None = None
        self._dragging    = False
        self._target: QPoint | None = None
        self._float_phase = 0.0
        self._move_accum  = 0          # sub-pixel accumulator

        # Chest buttons
        cfg_list = settings.get("chest_buttons", _BTN_DEFAULTS)
        self._buttons: list[_ChestButton] = [_ChestButton(c) for c in cfg_list]
        self._hovered_btn: _ChestButton | None = None

        # Window setup
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.Tool
                 | Qt.WindowType.NoDropShadowWindowHint)
        if settings.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowOpacity(settings.get("opacity", 0.9))

        self._win_size = self._robot_size + 40
        self.setFixedSize(self._win_size, self._win_size)

        # Status label (reuse same instance across repaints)
        self._status_label = QLabel("", self)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            "QLabel{color:rgba(0,220,255,230);font-size:11px;"
            "font-family:'Segoe UI',Arial;background:rgba(5,15,35,180);"
            "border-radius:8px;padding:2px 6px;}")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        self._status_label.setGeometry(0, self._win_size - 24, self._win_size, 20)

        # Loading placeholder shown while frames generate
        self._loading_label = QLabel("⚙ Loading…", self)
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet(
            "QLabel{color:rgba(0,200,255,180);font-size:13px;"
            "font-family:'Segoe UI',Arial;}")
        self._loading_label.setGeometry(0, 0, self._win_size, self._win_size)
        self._loading_label.setVisible(True)

        # SINGLE master timer
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._master_tick)

        self._status_hide_timer = QTimer(self)
        self._status_hide_timer.setSingleShot(True)
        self._status_hide_timer.timeout.connect(self._hide_status)
        self._animation_timer = QTimer(self)
        self._animation_timer.setSingleShot(True)
        self._animation_timer.timeout.connect(self._clear_animation)

        self._place_initial()
        state_manager.add_listener(self._on_state_change)

        # Start frame generation in background
        self._start_frame_gen(self._robot_size)

    # ── Frame generation (background thread) ─────────────────────────────────

    def _start_frame_gen(self, size: int) -> None:
        from jarvis.assets import IMAGES_DIR
        self._frames_ready = False
        self._loading_label.setVisible(True)
        if self._thread is not None and self._thread.isRunning():
            self._frame_gen_pending = (
                None if size == self._running_frame_size else size
            )
            return
        self._frame_gen_pending = size
        self._launch_frame_gen(IMAGES_DIR)

    def _launch_frame_gen(self, images_dir) -> None:
        size = self._frame_gen_pending
        if size is None:
            return
        self._frame_gen_pending = None
        self._running_frame_size = size
        self._thread = QThread(self)
        self._worker = _FrameWorker(images_dir, size)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_frames_ready)
        self._worker.failed.connect(self._on_frame_gen_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_frame_thread_finished)
        self._thread.start()
        log.info("Frame generation started in background (size=%d)…", size)

    @Slot(dict, int)
    def _on_frames_ready(self, frames: dict, size: int) -> None:
        if size != self._robot_size:
            return
        self._frames = frames
        self._frames_ready = True
        self._loading_label.setVisible(False)
        log.info("Frames loaded: %s", {k: len(v) for k, v in frames.items()})
        self._compute_button_rects()
        self.update()

    @Slot(str, int)
    def _on_frame_gen_failed(self, message: str, size: int) -> None:
        if size == self._robot_size:
            self._loading_label.setText("⚠ Robot artwork failed to load")
            self._status_label.setText(message)
            self._status_label.setVisible(True)

    @Slot()
    def _on_frame_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.deleteLater()
        if self._frame_gen_pending is not None:
            from jarvis.assets import IMAGES_DIR
            self._launch_frame_gen(IMAGES_DIR)

    # ── Live robot resize (Part A) ────────────────────────────────────────────

    def set_robot_size(self, new_size: int) -> None:
        new_size = max(60, min(300, new_size))
        if new_size == self._robot_size:
            return
        self._robot_size = new_size
        self._win_size   = new_size + 40
        self.setFixedSize(self._win_size, self._win_size)
        self.move(self._clamp_to_work(self.pos()))
        self._status_label.setGeometry(0, self._win_size - 24, self._win_size, 20)
        self._loading_label.setGeometry(0, 0, self._win_size, self._win_size)
        self._start_frame_gen(new_size)
        log.info("Robot resize → %d px", new_size)

    # ── Part K — chest indicator override ────────────────────────────────────

    def set_chest_indicator(self, btn_id: int, color: str | None) -> None:
        """
        Override a chest button's display colour for status indication.
        color: CSS hex string like '#00ff00', or None to reset to default.
        Called by mic/camera/focus services.
        """
        for btn in self._buttons:
            if btn.id == btn_id:
                btn.indicator_color = QColor(color) if color else None
                self.update()
                return

    def play_animation(self, name: str, duration_ms: int = 3000) -> bool:
        """Play a distinct built-in animation, then return to current state."""
        supported = {
            "wave", "flying", "tools", "scanning", "typing",
            "thirsty", "focus", "alarm", "confused", "success",
        }
        if name not in supported or not self._frames.get(name):
            return False
        self._animation_override = name
        self._frame_index = 0
        self._animation_timer.start(max(250, duration_ms))
        self.update()
        return True

    @Slot()
    def _clear_animation(self) -> None:
        self._animation_override = None
        self._frame_index = 0
        self.update()

    # ── Placement ─────────────────────────────────────────────────────────────

    def _place_initial(self) -> None:
        sx = self._settings.get("start_x", -1)
        sy = self._settings.get("start_y", -1)
        work = self._work_rect()
        if sx < 0 or sy < 0:
            sx = work.right() - self._win_size - 60
            sy = work.bottom() - self._win_size - 60
        self.move(self._clamp_to_work(QPoint(sx, sy)))

    def _current_screen(self) -> QScreen:
        center = self.geometry().center()
        for sc in QGuiApplication.screens():
            if sc.geometry().contains(center):
                return sc
        return QGuiApplication.primaryScreen()

    def _work_rect(self) -> QRect:
        wa = self._current_screen().availableGeometry()
        m  = self._safe_margin
        return QRect(wa.left()+m, wa.top()+m, wa.width()-2*m, wa.height()-2*m)

    def _clamp_to_work(self, pos: QPoint) -> QPoint:
        wr = self._work_rect()
        return QPoint(
            max(wr.left(), min(pos.x(), wr.right()  - self._win_size)),
            max(wr.top(),  min(pos.y(), wr.bottom() - self._win_size)),
        )

    # ── Chest button hit-rect ─────────────────────────────────────────────────

    def _compute_button_rects(self) -> None:
        for btn, rect in zip(self._buttons, _chest_button_hit_rects(self._robot_size)):
            btn.rect = rect

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._timer.start()
        if self._auto_move:
            self._pick_new_target()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def set_auto_movement(self, enabled: bool) -> None:
        self._auto_move = enabled
        self._settings["auto_movement"] = enabled
        if enabled and self._target is None:
            self._pick_new_target()

    def set_always_on_top(self, on: bool) -> None:
        if self.isVisible():
            from jarvis.platform.windows_window import set_topmost_in_place
            if set_topmost_in_place(int(self.winId()), on):
                return
        f = self.windowFlags()
        f = (f | Qt.WindowType.WindowStaysOnTopHint) if on \
            else (f & ~Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlags(f)
        if self.isVisible():
            self.show()

    def reset_position(self) -> None:
        wr = self._work_rect()
        self.move(wr.left(), wr.top())

    def show_status(self, text: str, duration_ms: int = 3000) -> None:
        if text:
            self._status_label.setText(text)
            self._status_label.setVisible(True)
            self._status_hide_timer.start(duration_ms)
        else:
            self._hide_status()

    def show_reminder_bubble(
        self, title: str, description: str = "", duration_ms: int = 8000
    ) -> None:
        message = f"🔔 Reminder: {title}"
        self._status_label.setText(message)
        self._status_label.setToolTip(
            f"{message}\n{description}" if description else message
        )
        self._status_label.setStyleSheet(
            "QLabel{color:#fff4d6;font-size:11px;font-weight:bold;"
            "font-family:'Segoe UI',Arial;background:rgba(88,42,0,235);"
            "border:1px solid #ffb000;border-radius:10px;padding:4px 8px;}"
        )
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setGeometry(
            6, self._win_size - 42, self._win_size - 12, 36
        )
        self._status_label.setVisible(True)
        self._status_hide_timer.start(duration_ms)

    @Slot()
    def _hide_status(self) -> None:
        self._status_label.setVisible(False)
        self._status_label.setToolTip("")
        self._status_label.setStyleSheet(
            "QLabel{color:rgba(0,220,255,230);font-size:11px;"
            "font-family:'Segoe UI',Arial;background:rgba(5,15,35,180);"
            "border-radius:8px;padding:2px 6px;}"
        )
        self._status_label.setGeometry(0, self._win_size - 24, self._win_size, 20)

    # ── SINGLE master tick (animation + movement combined) ────────────────────

    @Slot()
    def _master_tick(self) -> None:
        needs_repaint = False

        # --- Animation frame advance ---
        if self._frames_ready and self._settings.get("animation_enabled", True):
            state_name = self._animation_override or self._current_state.name.lower()
            frames = self._frames.get(state_name) or self._frames.get("idle", [])
            if frames:
                self._frame_index = (self._frame_index + 1) % len(frames)
                if self._frame_index != self._prev_frame_index:
                    self._prev_frame_index = self._frame_index
                    needs_repaint = True

        # --- Movement ---
        if not self._dragging and self._auto_move:
            self._float_phase += 0.04
            if self._target is None:
                self._pick_new_target()
            pos = self.pos()
            dx  = self._target.x() - pos.x()
            dy  = self._target.y() - pos.y()
            dist = math.hypot(dx, dy)
            if dist < 2:
                QTimer.singleShot(random.randint(2000, 6000), self._pick_new_target)
                self._target = None
            else:
                step = min(self._speed, dist)
                nx = pos.x() + dx / dist * step
                ny = pos.y() + dy / dist * step + math.sin(self._float_phase) * 0.4
                self.move(self._clamp_to_work(QPoint(int(nx), int(ny))))
                # move() itself triggers a repaint via Qt; no extra update() needed

        if needs_repaint:
            self.update()

    # ── Painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._frames_ready:
            state_name = self._animation_override or self._current_state.name.lower()
            frames = self._frames.get(state_name) or self._frames.get("idle", [])
            if frames:
                pad = 20
                painter.drawPixmap(pad//2, pad//2, frames[self._frame_index % len(frames)])
            else:
                painter.setBrush(QColor(0, 220, 255, 200))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(10, 10, self._robot_size, self._robot_size)
        # Chest button overlays
        for btn in self._buttons:
            if btn.hovered or btn.pressed or btn.active or btn.indicator_color:
                c = QColor(btn.display_color)
                if btn.pressed:
                    painter.setPen(QPen(c, 2))
                    painter.setBrush(QColor(c.red(), c.green(), c.blue(), 130))
                elif btn.active or btn.indicator_color:
                    painter.setPen(QPen(c, 2))
                    painter.setBrush(QColor(c.red(), c.green(), c.blue(), 80))
                else:
                    painter.setPen(QPen(c, 1))
                    painter.setBrush(QColor(c.red(), c.green(), c.blue(), 40))
                painter.drawEllipse(btn.rect)

        painter.end()

    # ── Mouse ────────────────────────────────────────────────────────────────

    def _btn_at(self, pos: QPoint) -> "_ChestButton | None":
        for btn in self._buttons:
            if btn.rect.contains(pos):
                return btn
        return None

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        p = e.position().toPoint()
        if e.button() == Qt.MouseButton.LeftButton:
            btn = self._btn_at(p)
            if btn:
                btn.pressed = True; self.update(); return
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragging = True
        elif e.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        p = e.position().toPoint()
        prev = self._hovered_btn
        self._hovered_btn = self._btn_at(p)
        for btn in self._buttons:
            btn.hovered = (btn is self._hovered_btn)
        if prev is not self._hovered_btn:
            self.setToolTip(self._hovered_btn.name if self._hovered_btn else "")
            self.update()
        if self._dragging and self._drag_offset:
            self.move(self._clamp_to_work(e.globalPosition().toPoint() - self._drag_offset))

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        p = e.position().toPoint()
        if e.button() == Qt.MouseButton.LeftButton:
            pressed_btn = next((b for b in self._buttons if b.pressed), None)
            for b in self._buttons:
                b.pressed = False
            self.update()
            if pressed_btn and self._btn_at(p) is pressed_btn:
                self._event_bus.publish(pressed_btn.action); return
            was_drag = self._dragging
            self._dragging = False; self._drag_offset = None
            if not was_drag:
                self.robot_clicked.emit()
            elif self._auto_move:
                self._pick_new_target()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            if not self._btn_at(e.position().toPoint()):
                self.robot_clicked.emit()

    def _pick_new_target(self) -> None:
        wr = self._work_rect()
        self._target = QPoint(
            random.randint(wr.left(), max(wr.left(), wr.right()  - self._win_size)),
            random.randint(wr.top(),  max(wr.top(),  wr.bottom() - self._win_size)),
        )

    # ── Context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:rgba(10,20,45,230);color:#00dcff;
                border:1px solid rgba(0,200,255,120);border-radius:8px;padding:4px;
                font-family:'Segoe UI',Arial;font-size:13px;}
            QMenu::item{padding:6px 20px;border-radius:4px;}
            QMenu::item:selected{background:rgba(0,200,255,60);}
            QMenu::separator{height:1px;background:rgba(0,200,255,60);margin:3px 8px;}
        """)
        a_panel   = menu.addAction("💬  Open Panel")
        a_pause   = menu.addAction("▶  Resume" if self._state_manager.is_paused() else "⏸  Pause")
        a_move    = menu.addAction("✅  Movement ON" if not self._auto_move else "🚫  Pause Movement")
        a_home    = menu.addAction("🏠  Reset Position")
        menu.addSeparator()
        a_settings= menu.addAction("⚙  Settings")
        menu.addSeparator()
        a_hide    = menu.addAction("👁  Hide")
        a_exit    = menu.addAction("❌  Exit JARVIS")
        c = menu.exec(pos)
        if c == a_panel:     self.robot_clicked.emit()
        elif c == a_pause:   self._event_bus.publish("toggle_pause")
        elif c == a_move:    self.set_auto_movement(not self._auto_move)
        elif c == a_home:    self.reset_position()
        elif c == a_settings:self._event_bus.publish("open_settings")
        elif c == a_hide:    self.hide()
        elif c == a_exit:    self._event_bus.publish("exit_requested")

    # ── State listener ────────────────────────────────────────────────────────

    def _on_state_change(self, old: RobotState, new: RobotState) -> None:
        self._current_state = new
        self._animation_timer.stop()
        self._animation_override = None
        self._frame_index   = 0
        label = STATE_LABELS.get(new, "")
        self.show_status(label, 4000 if label else 0)
        self.update()

    # ── Legacy timer properties (for backward compat with _apply_settings) ────

    @property
    def _anim_timer(self):
        return self._timer

    @property
    def _move_timer(self):
        return self._timer
