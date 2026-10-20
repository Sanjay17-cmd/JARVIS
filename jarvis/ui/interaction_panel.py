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

from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QLabel, QFrame, QSizePolicy,
)

from jarvis.core.state import RobotState

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

    def __init__(
        self,
        state_manager: "StateManager",
        event_bus: "EventBus",
        router: "CommandRouter",
        panels_always_on_top: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state_manager = state_manager
        self._event_bus     = event_bus
        self._router        = router
        self._dragging      = False
        self._drag_offset   = None

        self.setObjectName("InteractionPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_PANEL_STYLE)
        self.setFixedWidth(360)
        self.setMinimumHeight(360)

        # Apply always-on-top from initial setting
        self.apply_topmost(panels_always_on_top)

        self._build_ui()
        state_manager.add_listener(self._on_state_change)

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
        self._btn_cancel = QPushButton("✕")
        self._btn_cancel.setObjectName("cancel_btn")
        self._btn_cancel.setFixedWidth(32)
        self._btn_cancel.setVisible(False)
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.clicked.connect(self._on_cancel)
        input_row.addWidget(self._input)
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
        self._add_message(
            "👋 Hi! I'm JARVIS v2. Type a command to get started.\n"
            "Try: demo, help, status, version",
            is_user=False,
        )

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

    def _add_message(self, text: str, is_user: bool = True) -> None:
        ts = datetime.now().strftime("%H:%M")
        bubble = _MessageBubble(text, is_user=is_user, timestamp=ts)
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)
        QTimer.singleShot(
            50,
            lambda: self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            ),
        )

    def _set_busy(self, busy: bool) -> None:
        self._input.setEnabled(not busy)
        self._btn_send.setEnabled(not busy)
        self._btn_cancel.setVisible(busy)
        if busy:
            self._lbl_status.setText("⏳ Processing…")
            self._lbl_status.setVisible(True)
        else:
            self._lbl_status.setVisible(False)

    # ── Command handling ──────────────────────────────────────────────────

    @Slot()
    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._add_message(text, is_user=True)
        self._set_busy(True)
        self._state_manager.transition(RobotState.THINKING)

        # Route synchronously (Phase 2: non-blocking worker comes in Part C)
        response = self._router.route(text)

        if text.lower().startswith("demo"):
            self._state_manager.transition(RobotState.SUCCESS)
            QTimer.singleShot(2000, lambda: self._state_manager.transition(RobotState.IDLE))
        else:
            self._state_manager.transition(RobotState.SUCCESS)
            QTimer.singleShot(1500, lambda: self._state_manager.transition(RobotState.IDLE))

        self._add_message(response, is_user=False)
        self._set_busy(False)
        self.command_issued.emit(text)

    @Slot()
    def _on_cancel(self) -> None:
        self._set_busy(False)
        self._state_manager.transition(RobotState.IDLE)
        self._add_message("⚠ Cancelled.", is_user=False)

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
