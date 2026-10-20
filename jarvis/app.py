"""
app.py — Application entry point and lifecycle manager — JARVIS v2.0.0

Phase 2 changes:
  • panels_always_on_top: read from settings and passed to both
    InteractionPanel and SettingsDialog at construction + every time
    settings change (live apply, no restart needed).
  • All overlay settings applied on settings_changed (opacity, movement,
    always-on-top, animation).
  • version bump to 2.0.0.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QApplication

# ── logging setup (must run before importing jarvis modules) ────────────────

def _setup_logging(level: str = "INFO") -> None:
    log_dir = Path(os.environ.get("APPDATA", Path.home())) / "JARVIS" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "jarvis.log"

    root = logging.getLogger()
    # Avoid adding duplicate handlers on repeated calls
    if not root.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
        )
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(sh)
        root.addHandler(fh)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))


_setup_logging()
log = logging.getLogger(__name__)

from jarvis.config import Settings
from jarvis.core import StateManager, RobotState, EventBus, CommandRouter
from jarvis.ui.overlay import RobotOverlay
from jarvis.ui.interaction_panel import InteractionPanel
from jarvis.ui.tray import TrayManager
from jarvis.ui.settings_dialog import SettingsDialog
from jarvis.actions.windows_app_launcher import WindowsAppLauncher


class JarvisApp:
    """Top-level application controller — JARVIS v2.0.0."""

    def __init__(self) -> None:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        self._qt_app = QApplication.instance() or QApplication(sys.argv)
        self._qt_app.setApplicationName("JARVIS")
        self._qt_app.setApplicationVersion("2.0.0")
        self._qt_app.setOrganizationName("JARVISProject")
        self._qt_app.setQuitOnLastWindowClosed(False)

        # ── Core services ─────────────────────────────────────────────────
        self._settings      = Settings()
        self._state_manager = StateManager()
        self._event_bus     = EventBus()
        self._router        = CommandRouter()

        # Advanced config (INI — user-editable)
        from jarvis.config.advanced_config import AdvancedConfig
        self._adv = AdvancedConfig()
        # Merge advanced values that the overlay/services need
        self._settings.set("movement_speed", self._adv.get("movement_speed", 1.2))
        self._settings.set("safe_margin",    self._adv.get("safe_margin",    20))
        self._settings.set("animation_fps",  self._adv.get("animation_fps",  30))
        self._settings.set("tts_rate",       self._adv.get("tts_rate",       175))

        _setup_logging(self._settings.get("log_level", "INFO"))
        log.info("JARVIS v2.0.0 starting up…")

        # ── App launcher ──────────────────────────────────────────────────
        self._launcher = WindowsAppLauncher(
            custom_apps=self._settings.get("custom_apps", [])
        )
        self._router.set_launcher(self._launcher)

        # ── Scheduling service ────────────────────────────────────────────
        from jarvis.scheduling import database as sched_db
        sched_db.get_conn()
        self._sched_timer = None

        # ── Part K — mic/camera state tracking ───────────────────────────
        self._mic_active    = False
        self._camera_active = False

        # ── Part J — AI provider ──────────────────────────────────────────
        from jarvis.ai.provider import get_provider
        self._ai_provider = get_provider(self._settings)
        self._router.register_ai_fallback(self._ai_provider.ask)
        log.info("AI provider: %s", self._ai_provider.name)

        # ── UI ────────────────────────────────────────────────────────────
        panels_top = self._settings.get("panels_always_on_top", True)

        self._overlay = RobotOverlay(
            self._settings, self._state_manager, self._event_bus
        )
        # InteractionPanel receives the panels_always_on_top flag at init
        self._panel = InteractionPanel(
            self._state_manager,
            self._event_bus,
            self._router,
            panels_always_on_top=panels_top,
        )
        self._tray = TrayManager(
            self._state_manager, self._event_bus
        )

        # ── Signal wiring ─────────────────────────────────────────────────
        self._overlay.robot_clicked.connect(self._toggle_panel)

        self._tray.show_requested.connect(self._overlay.show)
        self._tray.hide_requested.connect(self._overlay.hide)
        self._tray.hide_requested.connect(self._panel.hide)
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.pause_requested.connect(self._toggle_pause)
        self._tray.exit_requested.connect(self._exit)

        # Panel close button
        self._panel.close_requested.connect(self._panel.hide)

        # ── Event bus subscriptions ────────────────────────────────────────
        self._event_bus.subscribe("open_settings",  lambda **_: self._open_settings())
        self._event_bus.subscribe("toggle_pause",   lambda **_: self._toggle_pause())
        self._event_bus.subscribe("exit_requested", lambda **_: self._exit())

        # ── Chest button actions ───────────────────────────────────────────
        self._event_bus.subscribe("toggle_voice",    lambda **_: self._chest_voice())
        self._event_bus.subscribe("toggle_focus",    lambda **_: self._chest_focus())
        self._event_bus.subscribe("open_reminders",  lambda **_: self._chest_reminders())
        self._event_bus.subscribe("open_quick_menu", lambda **_: self._chest_quick_menu())

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> int:
        self._tray.show()
        self._overlay.start()

        # ── Notification queue (Part I) ───────────────────────────────────
        from jarvis.ui.notification import NotificationQueue
        self._notif_queue = NotificationQueue.instance()

        # ── Wellness service (Part F) ─────────────────────────────────────
        from jarvis.scheduling.wellness_service import WellnessService
        self._wellness = WellnessService(self._settings, self._adv)
        self._wellness.start()

        # ── Focus service (Part H) ────────────────────────────────────────
        from jarvis.scheduling.focus_service import FocusService
        self._focus = FocusService(
            self._settings, self._adv,
            on_indicator=lambda active: self._overlay.set_chest_indicator(
                1, "#00ff60" if active else None
            ),
        )
        # Wire focus commands to router
        self._router._commands["focus"]      = lambda t: self._focus.start_focus()
        self._router._commands["focusstop"]  = lambda t: self._focus.stop()
        self._router._commands["focusskip"]  = lambda t: self._focus.skip_break()
        self._router._commands["focusstatus"]= lambda t: self._focus.status()

        # ── Scheduler tick (Part E) ───────────────────────────────────────
        from PySide6.QtCore import QTimer as _QTimer
        self._sched_timer = _QTimer()
        self._sched_timer.setInterval(30_000)
        self._sched_timer.timeout.connect(self._on_scheduler_tick)
        self._sched_timer.start()

        log.info("JARVIS overlay started.")
        return self._qt_app.exec()

    @Slot()
    def _on_scheduler_tick(self) -> None:
        from jarvis.scheduling.reminder_service import tick as _sched_tick
        try:
            events = _sched_tick()
            for ev in events:
                title   = ev.get("title", "Reminder")
                ev_type = ev.get("type", "reminder")
                icon    = "⏰" if ev_type == "alarm" else "🔔"
                # Toast notification (Part I)
                from jarvis.ui.notification import notify
                notify(icon, title, duration_ms=8000)
                # Overlay status bar
                self._overlay.show_status(f"{icon} {title}", 6000)
                # Chest indicator (Part K)
                self.set_reminder_due(True)
                from PySide6.QtCore import QTimer as _T
                _T.singleShot(10000, lambda: self.set_reminder_due(False))
                log.info("Due %s: %s", ev_type, title)
        except Exception as exc:
            log.warning("Scheduler tick error: %s", exc)

    def _exit(self) -> None:
        log.info("JARVIS shutting down…")
        pos = self._overlay.pos()
        self._settings.set("start_x", pos.x())
        self._settings.set("start_y", pos.y())
        self._settings.save()
        if self._sched_timer:
            self._sched_timer.stop()
        if hasattr(self, "_wellness"):
            self._wellness.stop()
        if hasattr(self, "_focus"):
            self._focus.stop()
        from jarvis.scheduling import database as sched_db
        sched_db.close()
        self._overlay.stop()
        self._tray.hide()
        self._qt_app.quit()

    # ── Panel toggle ──────────────────────────────────────────────────────

    def _toggle_panel(self) -> None:
        if self._panel.isVisible():
            self._panel.hide()
            return

        # Position panel next to overlay, respecting screen edge
        ov_geo = self._overlay.geometry()
        px = ov_geo.right() + 10
        py = ov_geo.top()

        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().availableGeometry()
        panel_w = self._panel.sizeHint().width() or 360
        if px + panel_w > screen.right():
            px = ov_geo.left() - panel_w - 10
        # Clamp vertically
        py = max(screen.top(), min(py, screen.bottom() - 400))

        self._panel.move(px, py)
        self._panel.adjustSize()
        self._panel.show()
        self._panel.raise_()
        self._panel._input.setFocus()

    # ── Settings ──────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        panels_top = self._settings.get("panels_always_on_top", True)
        dlg = SettingsDialog(
            self._settings,
            panels_always_on_top=panels_top,
            parent=None,
        )
        dlg.settings_changed.connect(self._apply_settings)
        # Centre near the overlay
        ov_geo = self._overlay.geometry()
        dlg.adjustSize()
        dlg.move(
            ov_geo.center().x() - dlg.width() // 2,
            ov_geo.center().y() - dlg.height() // 2,
        )
        dlg.exec()

    def _apply_settings(self) -> None:
        """Apply every changed setting to the live runtime immediately."""
        s = self._settings

        # 1. Opacity
        self._overlay.setWindowOpacity(s.get("opacity", 0.9))

        # 2. Robot always-on-top
        self._overlay.set_always_on_top(s.get("always_on_top", True))

        # 3. Robot size (live resize — regenerates frames on QThread)
        self._overlay.set_robot_size(s.get("robot_size", 120))

        # 4. Movement
        self._overlay.set_auto_movement(s.get("auto_movement", True))
        self._overlay._speed = s.get("movement_speed", 1.2)

        # 5. Animation
        anim = s.get("animation_enabled", True)
        if not anim and self._overlay._timer.isActive():
            self._overlay._timer.stop()
        elif anim and not self._overlay._timer.isActive():
            self._overlay._timer.start()

        # 6. panels_always_on_top
        panels_top = s.get("panels_always_on_top", True)
        self._panel.apply_topmost(panels_top)

        # 7. Startup registry
        try:
            from jarvis.core.settings_service import set_startup
            set_startup(s.get("launch_on_startup", False))
        except Exception as exc:
            log.warning("Startup registry: %s", exc)

        # 8. Custom apps
        self._launcher.update_custom_apps(s.get("custom_apps", []))

        log.info(
            "Settings applied — opacity=%.2f size=%d aot=%s move=%s panels_top=%s",
            s.get("opacity", 0.9), s.get("robot_size", 120),
            s.get("always_on_top", True), s.get("auto_movement", True), panels_top,
        )

    # ── Pause / resume ────────────────────────────────────────────────────

    def _toggle_pause(self) -> None:
        if self._state_manager.is_paused():
            self._state_manager.resume()
            self._overlay.set_auto_movement(
                self._settings.get("auto_movement", True)
            )
        else:
            self._state_manager.pause()
            self._overlay.set_auto_movement(False)

    # ── Part K — Mic / Camera chest indicators ────────────────────────────

    def set_mic_active(self, active: bool) -> None:
        """Called by voice service. Button 0 = cyan idle, green active, red muted."""
        self._mic_active = active
        color = "#00ff60" if active else None   # green=on, reset=idle-cyan
        self._overlay.set_chest_indicator(0, color)

    def set_mic_muted(self, muted: bool) -> None:
        color = "#ff3030" if muted else None
        self._overlay.set_chest_indicator(0, color)

    def set_camera_active(self, active: bool) -> None:
        """Future: called by camera/vision service. Button 1 indicator."""
        self._camera_active = active
        color = "#00ff60" if active else None
        self._overlay.set_chest_indicator(1, color)

    def set_reminder_due(self, has_due: bool) -> None:
        """Button 2 flashes amber when a reminder is due."""
        color = "#ff9900" if has_due else None
        self._overlay.set_chest_indicator(2, color)

    # ── Chest button handlers ─────────────────────────────────────────────

    def _chest_voice(self) -> None:
        """Button 1 — Voice (Phase 2: show status, full impl in voice module)."""
        self._overlay.show_status("🎤 Voice (coming in Phase 2)", 3000)
        self._panel.show()
        self._panel._input.setText("Voice mode not yet active — Phase 2")

    def _chest_focus(self) -> None:
        """Button 2 — Focus session toggle (Phase 2 stub)."""
        self._overlay.show_status("🎯 Focus mode (coming in Phase 2)", 3000)
        self._toggle_panel()

    def _chest_reminders(self) -> None:
        """Button 3 — Reminders panel (Phase 2 stub)."""
        self._overlay.show_status("⏰ Reminders (coming in Phase 2)", 3000)
        self._toggle_panel()

    def _chest_quick_menu(self) -> None:
        """Button 4 — Quick actions menu."""
        self._overlay.show_status("⚡ Quick Actions", 2000)
        self._toggle_panel()


def main() -> None:
    app = JarvisApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
