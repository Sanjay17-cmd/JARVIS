"""
ui/interaction_panel.py — Compact floating chat/command panel.

Phase 2 changes:
  • Optionally always-on-top (controlled by settings key panels_always_on_top)
  • apply_topmost(on) method — called live from app when setting changes
  • Drag-to-move (title-bar drag)
  • Improved message history with timestamps
  • Loading spinner state during command processing
  • Cancel button to abort long operations
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, Slot, QTimer, QThread, QObject
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QLabel, QFrame, QSizePolicy,
)

from jarvis.core.state import RobotState


class _CommandWorker(QObject):
    chunk = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, router, text: str) -> None:
        super().__init__()
        self._router = router
        self._text = text

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(
                self._router.route_stream(self._text, self.chunk.emit)
            )
        except Exception as exc:
            log.exception("Command worker failed")
            self.failed.emit(str(exc))


if TYPE_CHECKING:
    from jarvis.core.state import StateManager
    from jarvis.core.event_bus import EventBus
    from jarvis.core.command_router import CommandRouter

log = logging.getLogger(__name__)

_PANEL_STYLE = """
QWidget#InteractionPanel {
    background: rgba(8, 18, 42, 235);
    border: 1px solid rgba(0, 200, 255, 160);
    border-radius: 14px;
}
QLabel {
    color: #c0e8ff;
    font-family: 'Segoe UI', Arial;
    font-size: 13px;
}
QLabel#title {
    color: #00dcff;
    font-size: 15px;
    font-weight: bold;
}
QLineEdit {
    background: rgba(0, 30, 60, 200);
    color: #00dcff;
    border: 1px solid rgba(0, 200, 255, 100);
    border-radius: 8px;
    padding: 6px 10px;
    font-family: 'Segoe UI', Arial;
    font-size: 13px;
    selection-background-color: rgba(0, 200, 255, 80);
}
QLineEdit:focus {
    border: 1px solid rgba(0, 220, 255, 200);
}
QPushButton {
    background: rgba(0, 150, 200, 160);
    color: #ffffff;
    border: 1px solid rgba(0, 200, 255, 100);
    border-radius: 8px;
    padding: 6px 14px;
    font-family: 'Segoe UI', Arial;
    font-size: 13px;
    font-weight: bold;
}
QPushButton:hover {
    background: rgba(0, 200, 255, 200);
    color: #000020;
}
QPushButton#close_btn {
    background: transparent;
    border: none;
    color: rgba(0, 200, 255, 160);
    font-size: 16px;
    padding: 2px 6px;
}
QPushButton#close_btn:hover {
    color: #ff4444;
    background: rgba(255,60,60,30);
    border-radius: 6px;
}
QPushButton#cancel_btn {
    background: rgba(200, 60, 60, 120);
    border: 1px solid rgba(255,80,80,100);
    padding: 4px 10px;
    font-size: 12px;
}
QPushButton#cancel_btn:hover {
    background: rgba(255,80,80,180);
}
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: rgba(0, 30, 60, 100);
    width: 5px;
    border-radius: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 200, 255, 120);
    border-radius: 2px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""


class _MessageBubble(QLabel):
    """Single chat-message bubble (user or assistant)."""

    def __init__(self, text: str, is_user: bool = False, timestamp: str = "") -> None:
        super().__init__()
        # Combine timestamp + text
        ts = f"  [{timestamp}]" if timestamp else ""
        self.setText(text + ts)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if is_user:
            self.setStyleSheet(
                "QLabel { color: #b0d8ff; background: rgba(0,100,180,130); "
                "border-radius: 8px; padding: 6px 10px; margin: 2px 30px 2px 4px; "
                "font-family:'Segoe UI',Arial; font-size:12px; }"
            )
        else:
            self.setStyleSheet(
                "QLabel { color: #00dcff; background: rgba(0,30,70,160); "
                "border-radius: 8px; padding: 6px 10px; margin: 2px 4px 2px 30px; "
                "font-family:'Segoe UI',Arial; font-size:12px; }"
            )


class InteractionPanel(QWidget):
    """
    Floating translucent panel with command input, chat history and state display.
    Supports always-on-top toggling via apply_topmost().
    Drag-to-move via the title bar area.
    """

    command_issued   = Signal(str)
    close_requested  = Signal()
    open_tasks_requested = Signal()
    voice_active_changed = Signal(bool)

    def __init__(
        self,
        state_manager: "StateManager",
        event_bus: "EventBus",
        router: "CommandRouter",
        panels_always_on_top: bool = True,
        parent: QWidget | None = None,
        settings=None,
    ) -> None:
        super().__init__(parent)
        self._state_manager = state_manager
        self._event_bus     = event_bus
        self._router        = router
        self._settings      = settings
        self._dragging      = False
        self._drag_offset   = None
        self._command_thread: QThread | None = None
        self._command_worker: _CommandWorker | None = None
        self._cancelled = False
        self._stream_bubble: _MessageBubble | None = None
        self._streamed_response = ""
        self._stream_timestamp = ""

        self.setObjectName("InteractionPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_PANEL_STYLE)
        self.setFixedWidth(360)
        self.setMinimumHeight(360)

        # Apply always-on-top from initial setting
        self.apply_topmost(panels_always_on_top)

        self._build_ui()
        self._voice = None
        if settings is not None:
            from jarvis.voice import VoiceController
            self._voice = VoiceController(settings, self)
            self._voice.listening_changed.connect(self._on_voice_state)
            self._voice.transcription_ready.connect(self._on_transcription)
            self._voice.error.connect(self._on_voice_error)
        state_manager.add_listener(self._on_state_change)
        self._restore_history()

    # ── topmost control (called live from app when setting changes) ───────

    def apply_topmost(self, on: bool) -> None:
        """Apply or remove WindowStaysOnTopHint without closing the window."""
        base_flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if on:
            base_flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(base_flags)
        if was_visible:
            self.show()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        # ── Title bar (drag handle) ───────────────────────────────────────
        self._title_bar = QWidget(self)
        self._title_bar.setObjectName("title_bar")
        self._title_bar.setStyleSheet("QWidget#title_bar { background: transparent; }")
        self._title_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        title_row = QHBoxLayout(self._title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        lbl_icon  = QLabel("⚡")
        lbl_icon.setStyleSheet("QLabel{font-size:16px;}")
        lbl_title = QLabel("JARVIS")
        lbl_title.setObjectName("title")

        self._lbl_state = QLabel("● IDLE")
        self._lbl_state.setStyleSheet(
            "QLabel{color:#00dcff;font-size:11px;font-weight:bold;}"
        )

        btn_close = QPushButton("✕")
        btn_close.setObjectName("close_btn")
        btn_close.setFixedSize(26, 26)
        btn_close.clicked.connect(self.close_requested)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)

        title_row.addWidget(lbl_icon)
        title_row.addWidget(lbl_title)
        title_row.addStretch()
        title_row.addWidget(self._lbl_state)
        title_row.addWidget(btn_close)
        root.addWidget(self._title_bar)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("QFrame{color:rgba(0,200,255,60);}")
        root.addWidget(line)

        # ── Message area ─────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMinimumHeight(220)
        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background:transparent;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setSpacing(4)
        self._msg_layout.setContentsMargins(0, 0, 0, 0)
        self._msg_layout.addStretch()
        self._scroll.setWidget(self._msg_container)
        root.addWidget(self._scroll)

        # ── Status bar ───────────────────────────────────────────────────
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(
            "QLabel{color:rgba(255,200,0,200);font-size:11px;"
            "font-family:'Segoe UI',Arial;}"
        )
        self._lbl_status.setVisible(False)
        root.addWidget(self._lbl_status)

        # ── Input row ────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…  (try: hello, demo, help)")
        self._input.returnPressed.connect(self._on_send)
        self._btn_send = QPushButton("Send")
        self._btn_send.setFixedWidth(58)
        self._btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_send.clicked.connect(self._on_send)
        self._btn_mic = QPushButton("Mic")
        self._btn_mic.setFixedWidth(42)
        self._btn_mic.setToolTip("Start or stop local push-to-talk")
        self._btn_mic.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mic.clicked.connect(self.toggle_voice)
        self._btn_tasks = QPushButton("Tasks")
        self._btn_tasks.setFixedWidth(54)
        self._btn_tasks.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_tasks.clicked.connect(self.open_tasks_requested)
        self._btn_cancel = QPushButton("✕")
        self._btn_cancel.setObjectName("cancel_btn")
        self._btn_cancel.setFixedWidth(32)
        self._btn_cancel.setVisible(False)
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.clicked.connect(self._on_cancel)
        input_row.addWidget(self._input)
        input_row.addWidget(self._btn_mic)
        input_row.addWidget(self._btn_tasks)
        input_row.addWidget(self._btn_send)
        input_row.addWidget(self._btn_cancel)
        root.addLayout(input_row)

        # Hint
        hint = QLabel("💡 hello · demo · status · help · version · open chrome")
        hint.setStyleSheet(
            "QLabel{color:rgba(0,200,255,100);font-size:10px;"
            "font-family:'Segoe UI',Arial;}"
        )
        root.addWidget(hint)

        # Welcome message
    # ── Drag-to-move via title bar ────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # Only drag when pressing on the title-bar area
            if self._title_bar.geometry().contains(event.position().toPoint()):
                self._dragging = True
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._dragging = False
        self._drag_offset = None

    # ── Message helpers ───────────────────────────────────────────────────

    def _add_message(
        self,
        text: str,
        is_user: bool = True,
        *,
        persist: bool = True,
        timestamp: str | None = None,
    ) -> _MessageBubble:
        ts = timestamp or datetime.now().strftime("%H:%M")
        bubble = _MessageBubble(text, is_user=is_user, timestamp=ts)
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)
        QTimer.singleShot(
            50,
            lambda: self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            ),
        )
        if persist and self._settings is not None and self._settings.get(
            "retain_conversation", True
        ):
            self._persist_message("user" if is_user else "assistant", text)
        return bubble

    def _persist_message(self, role: str, text: str) -> None:
        from time import time
        from jarvis.scheduling.database import save_conversation_message

        try:
            save_conversation_message(role, text, time())
        except Exception as exc:
            log.exception("Could not save conversation history")
            self._lbl_status.setText(f"⚠ Conversation history could not be saved: {exc}")
            self._lbl_status.setVisible(True)

    def _restore_history(self) -> None:
        if self._settings is not None and self._settings.get("retain_conversation", True):
            try:
                from jarvis.scheduling.database import load_conversation_history

                for item in load_conversation_history():
                    timestamp = datetime.fromtimestamp(item["created_at"]).strftime("%H:%M")
                    self._add_message(
                        item["content"],
                        is_user=item["role"] == "user",
                        persist=False,
                        timestamp=timestamp,
                    )
                if self._msg_layout.count() > 1:
                    return
            except Exception as exc:
                log.exception("Could not load conversation history")
                self._lbl_status.setText(f"⚠ Conversation history could not be loaded: {exc}")
                self._lbl_status.setVisible(True)
        self._add_message(
            "👋 Hi! I'm JARVIS v2. Type a command to get started.\n"
            "Try: demo, help, status, version",
            is_user=False,
            persist=False,
        )

    def _set_busy(self, busy: bool) -> None:
        self._input.setEnabled(not busy)
        self._btn_send.setEnabled(not busy)
        self._btn_cancel.setVisible(busy)
        self._btn_cancel.setEnabled(True)
        if busy:
            self._lbl_status.setText("⏳ Processing…")
            self._lbl_status.setVisible(True)
        else:
            self._lbl_status.setVisible(False)

    # ── Command handling ──────────────────────────────────────────────────

    @Slot()
    def _on_send(self) -> None:
        if self._command_thread is not None:
            return
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._add_message(text, is_user=True)
        self._set_busy(True)
        self._state_manager.transition(RobotState.THINKING)
        self._cancelled = False
        self._stream_bubble = None
        self._streamed_response = ""
        self._stream_timestamp = datetime.now().strftime("%H:%M")
        self.command_issued.emit(text)
        if self._router.has_builtin(text):
            response = self._router.route(text)
            self._on_response_chunk(response)
            self._on_command_completed(response)
            self._set_busy(False)
            return

        thread = QThread(self)
        worker = _CommandWorker(self._router, text)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_response_chunk)
        worker.completed.connect(self._on_command_completed)
        worker.failed.connect(self._on_command_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_command_thread_finished)
        self._command_thread = thread
        self._command_worker = worker
        thread.start()

    @Slot(str)
    def _on_response_chunk(self, chunk: str) -> None:
        if self._cancelled or not chunk:
            return
        self._streamed_response += chunk
        if self._stream_bubble is None:
            self._stream_bubble = self._add_message(
                "",
                is_user=False,
                persist=False,
                timestamp=self._stream_timestamp,
            )
        self._stream_bubble.setText(
            f"{self._streamed_response}  [{self._stream_timestamp}]"
        )

    @Slot(str)
    def _on_command_completed(self, response: str) -> None:
        if self._cancelled:
            return
        if self._stream_bubble is None:
            self._stream_bubble = self._add_message(
                response,
                is_user=False,
                persist=False,
                timestamp=self._stream_timestamp,
            )
        else:
            self._stream_bubble.setText(
                f"{response}  [{self._stream_timestamp}]"
            )
        if self._settings is not None and self._settings.get("retain_conversation", True):
            self._persist_message("assistant", response)
        self._state_manager.transition(RobotState.SUCCESS)
        if self._voice is not None:
            self._voice.speak(response)
        QTimer.singleShot(1500, lambda: self._state_manager.transition(RobotState.IDLE))

    @Slot(str)
    def _on_command_failed(self, message: str) -> None:
        self._add_message(f"⚠ Command failed: {message}", is_user=False)
        self._state_manager.transition(RobotState.ERROR)
        QTimer.singleShot(1500, lambda: self._state_manager.transition(RobotState.IDLE))

    @Slot()
    def _on_command_thread_finished(self) -> None:
        thread = self._command_thread
        self._command_thread = None
        self._command_worker = None
        if thread is not None:
            thread.deleteLater()
        self._set_busy(False)
        if self._cancelled:
            self._state_manager.transition(RobotState.IDLE)
            self._add_message("⚠ Response cancelled.", is_user=False)

    @Slot()
    def _on_cancel(self) -> None:
        if self._command_thread is None:
            return
        self._cancelled = True
        self._btn_cancel.setEnabled(False)
        self._lbl_status.setText("Stopping response…")
        self._lbl_status.setVisible(True)

    def set_input_text(self, text: str) -> None:
        self._input.setText(text)
        self._input.setFocus()

    def toggle_voice(self) -> None:
        if self._voice is None:
            self._on_voice_error("Voice settings are not available.")
        elif self._voice.is_listening:
            self._voice.stop_listening()
        else:
            self._voice.start_listening()

    @Slot(bool)
    def _on_voice_state(self, active: bool) -> None:
        self._btn_mic.setText("Stop" if active else "Mic")
        self._btn_mic.setStyleSheet(
            "QPushButton{background:#a02030;}" if active else ""
        )
        self.voice_active_changed.emit(active)
        if active:
            self._lbl_status.setText("🎤 Listening — click Stop when finished.")
            self._lbl_status.setVisible(True)
        elif self._lbl_status.text().startswith("🎤"):
            self._lbl_status.setVisible(False)

    @Slot(str)
    def _on_transcription(self, text: str) -> None:
        self._input.setText(text)
        self._on_send()

    @Slot(str)
    def _on_voice_error(self, message: str) -> None:
        self._add_message(f"⚠ Voice: {message}", is_user=False)

    # ── State indicator ───────────────────────────────────────────────────

    def _on_state_change(self, old: RobotState, new: RobotState) -> None:
        label_map = {
            RobotState.IDLE:      "● IDLE",
            RobotState.LISTENING: "● LISTENING",
            RobotState.THINKING:  "● THINKING",
            RobotState.SPEAKING:  "● SPEAKING",
            RobotState.SUCCESS:   "● SUCCESS",
            RobotState.ERROR:     "● ERROR",
            RobotState.PAUSED:    "● PAUSED",
        }
        color_map = {
            RobotState.IDLE:      "#00dcff",
            RobotState.LISTENING: "#00ff96",
            RobotState.THINKING:  "#ffc800",
            RobotState.SPEAKING:  "#64c8ff",
            RobotState.SUCCESS:   "#00ff64",
            RobotState.ERROR:     "#ff3c3c",
            RobotState.PAUSED:    "#646482",
        }
        text  = label_map.get(new, "● ?")
        color = color_map.get(new, "#00dcff")
        self._lbl_state.setText(text)
        self._lbl_state.setStyleSheet(
            f"QLabel{{color:{color};font-size:11px;font-weight:bold;}}"
        )
