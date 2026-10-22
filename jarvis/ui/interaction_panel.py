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
import inspect
import html
import re
from threading import Event
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, Slot, QTimer, QThread, QObject
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QLabel, QFrame, QSizePolicy, QDialog,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox,
)

from jarvis.core.state import RobotState


class _CommandWorker(QObject):
    chunk = Signal(str)
    reset_stream = Signal()
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        router,
        text: str,
        force_search: bool = False,
        voice_request: bool = False,
    ) -> None:
        super().__init__()
        self._router = router
        self._text = text
        self._force_search = force_search
        self._voice_request = voice_request
        self.cancel_event = Event()

    @Slot()
    def run(self) -> None:
        try:
            route_stream = self._router.route_stream
            try:
                parameters = list(inspect.signature(route_stream).parameters.values())
            except (TypeError, ValueError):
                parameters = []
            parameter_names = {parameter.name for parameter in parameters}
            supports_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
            supported = parameter_names | ({"cancel_event", "on_reset", "force_search", "voice_request"} if supports_kwargs else set())
            kwargs = {
                key: value for key, value in {
                    "cancel_event": self.cancel_event,
                    "on_reset": self.reset_stream.emit,
                    "force_search": self._force_search,
                    "voice_request": self._voice_request,
                }.items()
                if key in supported
            }
            response = route_stream(self._text, self.chunk.emit, **kwargs)
            self.completed.emit(response)
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

    def __init__(
        self,
        text: str,
        is_user: bool = False,
        timestamp: str = "",
        predefined: bool = False,
        web_search: bool = False,
        model_label: str = "",
    ) -> None:
        super().__init__()
        # Combine timestamp + text
        ts = f"  [{timestamp}]" if timestamp else ""
        prefix = ("◆ " if predefined else "") + ("🌐 " if web_search else "")
        self.setText(prefix + text + ts)
        if predefined:
            self.setToolTip("Predefined local response")
        elif web_search:
            self.setToolTip("Web-search answer with sources returned by the configured provider")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setOpenExternalLinks(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._model_caption: QLabel | None = None
        self._display_model_label = model_label
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

    def set_response_text(self, text: str) -> None:
        if not re.search(r"(?:^|\n)Sources(?:\s+\([^)]*\))?:\n", text):
            self.setTextFormat(Qt.TextFormat.PlainText)
            self.setText(text)
            return
        escaped = html.escape(text)
        escaped = re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            lambda match: (
                f'<a href="{html.escape(match.group(2), quote=True)}" '
                f'style="color:#8ceeff">{match.group(1)}</a>'
            ),
            escaped,
        )
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setText(escaped.replace("\n", "<br>"))


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
    message_added = Signal(str, str)
    conversation_changed = Signal(str)

    def __init__(
        self,
        state_manager: "StateManager",
        event_bus: "EventBus",
        router: "CommandRouter",
        panels_always_on_top: bool = True,
        parent: QWidget | None = None,
        settings=None,
        ai_gateway=None,
    ) -> None:
        super().__init__(parent)
        self._state_manager = state_manager
        self._event_bus     = event_bus
        self._router        = router
        self._settings      = settings
        self._ai_gateway = ai_gateway
        self._dragging      = False
        self._drag_offset   = None
        self._command_thread: QThread | None = None
        self._command_worker: _CommandWorker | None = None
        self._cancelled = False
        self._stream_bubble: _MessageBubble | None = None
        self._streamed_response = ""
        self._stream_timestamp = ""
        self._response_model_label = ""
        self._confirmation_row: QWidget | None = None
        self._last_request_text = ""
        self._force_search_next = False
        self._search_in_progress = False
        self._next_request_is_voice = False
        self._last_request_was_search = False
        self._voice_waiting_for_tts = False
        self._voice_restart_pending = False
        from jarvis.scheduling.database import active_conversation_id
        self._conversation_id = active_conversation_id()

        self.setObjectName("InteractionPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_PANEL_STYLE)
        self.setFixedWidth(560)
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
            self._voice.speech_finished.connect(self._on_speech_finished)
        state_manager.add_listener(self._on_state_change)
        self._restore_history()

    # ── topmost control (called live from app when setting changes) ───────

    def apply_topmost(self, on: bool) -> None:
        """Apply or remove WindowStaysOnTopHint without closing the window."""
        if self.isVisible():
            from jarvis.platform.windows_window import set_topmost_in_place
            if set_topmost_in_place(int(self.winId()), on):
                return
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
        self._btn_chats = QPushButton("Chats")
        self._btn_chats.setFixedWidth(54)
        self._btn_chats.clicked.connect(self._show_chat_history)
        self._btn_new_chat = QPushButton("New")
        self._btn_new_chat.setFixedWidth(44)
        self._btn_new_chat.clicked.connect(self.new_chat)

        title_row.addWidget(lbl_icon)
        title_row.addWidget(lbl_title)
        title_row.addStretch()
        title_row.addWidget(self._lbl_state)
        title_row.addWidget(self._btn_chats)
        title_row.addWidget(self._btn_new_chat)
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
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._scroll_to_bottom)
        root.addWidget(self._scroll)

        # ── Status bar ───────────────────────────────────────────────────
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(
            "QLabel{color:rgba(255,200,0,200);font-size:11px;"
            "font-family:'Segoe UI',Arial;}"
        )
        self._lbl_status.setVisible(False)
        status_row = QHBoxLayout()
        status_row.addWidget(self._lbl_status, 1)
        self._btn_retry = QPushButton("Retry")
        self._btn_retry.setVisible(False)
        self._btn_retry.clicked.connect(self._retry_last_request)
        status_row.addWidget(self._btn_retry)
        root.addLayout(status_row)

        # ── Input row ────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…  (try: hello, demo, help)")
        self._input.returnPressed.connect(self._on_send)
        self._btn_send = QPushButton("Send")
        self._btn_send.setFixedWidth(52)
        self._btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_send.clicked.connect(self._on_send)
        self._btn_search = QPushButton("Search")
        self._btn_search.setFixedWidth(55)
        self._btn_search.setCheckable(True)
        self._btn_search.setToolTip(
            "Search the web for this message using the configured search provider"
        )
        self._btn_search.toggled.connect(self._on_search_toggled)
        self._btn_image = QPushButton("Image")
        self._btn_image.setFixedWidth(44)
        self._btn_image.setToolTip(
            "Generate an image with OpenRouter; usage may incur provider charges"
        )
        self._btn_image.clicked.connect(self._open_image_creator)
        self._btn_mic = QPushButton("Mic")
        self._btn_mic.setFixedWidth(38)
        self._btn_mic.setToolTip("Start or stop local push-to-talk")
        self._btn_mic.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mic.clicked.connect(self.toggle_voice)
        self._btn_tasks = QPushButton("Tasks")
        self._btn_tasks.setFixedWidth(48)
        self._btn_tasks.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_tasks.clicked.connect(self.open_tasks_requested)
        self._btn_cancel = QPushButton("✕")
        self._btn_cancel.setObjectName("cancel_btn")
        self._btn_cancel.setFixedWidth(28)
        self._btn_cancel.setVisible(False)
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.clicked.connect(self._on_cancel)
        input_row.addWidget(self._input)
        input_row.addWidget(self._btn_mic)
        input_row.addWidget(self._btn_tasks)
        input_row.addWidget(self._btn_search)
        input_row.addWidget(self._btn_image)
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
        predefined: bool = False,
        web_search: bool = False,
        model_label: str = "",
    ) -> _MessageBubble:
        ts = timestamp or datetime.now().strftime("%H:%M")
        bubble = _MessageBubble(
            text,
            is_user=is_user,
            timestamp=ts,
            predefined=predefined,
            web_search=web_search,
            model_label=model_label,
        )
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)
        if model_label:
            self._set_message_model(bubble, model_label)
        self._scroll_timer.start()
        if persist and self._settings is not None and self._settings.get(
            "retain_conversation", True
        ):
            self._persist_message("user" if is_user else "assistant", text)
        return bubble

    def _set_message_model(self, bubble: _MessageBubble, model_label: str) -> None:
        bubble._display_model_label = model_label
        if bubble._model_caption is None:
            caption = QLabel()
            caption.setWordWrap(True)
            caption.setStyleSheet(
                "QLabel{color:rgba(180,205,225,165);font-size:10px;"
                "margin:0px 10px 2px 38px;padding:0px;}"
            )
            index = self._msg_layout.indexOf(bubble)
            self._msg_layout.insertWidget(index + 1, caption)
            bubble._model_caption = caption
        bubble._model_caption.setText(model_label)

    @Slot()
    def _scroll_to_bottom(self) -> None:
        scrollbar = self._scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _persist_message(
        self, role: str, text: str, model_label: str = ""
    ) -> None:
        from time import time
        from jarvis.scheduling.database import save_conversation_message

        try:
            save_conversation_message(
                role,
                text,
                time(),
                conversation_id=self._conversation_id,
                model_label=model_label,
            )
        except Exception as exc:
            log.exception("Could not save conversation history")
            self._lbl_status.setText(f"⚠ Conversation history could not be saved: {exc}")
            self._lbl_status.setVisible(True)

    @staticmethod
    def _has_search_sources(response: str) -> bool:
        return bool(
            re.search(r"(?:^|\n)Sources\s+\(via [^)]+\):\n", response)
            and re.search(r"\]\(https?://[^)\s]+\)", response)
        )

    def _restore_history(self) -> None:
        if self._settings is not None and self._settings.get("retain_conversation", True):
            try:
                from jarvis.scheduling.database import load_conversation_history

                for item in load_conversation_history(
                    conversation_id=self._conversation_id
                ):
                    timestamp = datetime.fromtimestamp(item["created_at"]).strftime("%H:%M")
                    model_label = str(item.get("model_label", ""))
                    if item["role"] == "assistant" and not model_label:
                        model_label = "Model not recorded"
                    self._add_message(
                        item["content"],
                        is_user=item["role"] == "user",
                        persist=False,
                        timestamp=timestamp,
                        model_label=model_label,
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

    def new_chat(self) -> None:
        from jarvis.scheduling.database import create_conversation

        self._conversation_id = create_conversation()
        self.conversation_changed.emit(self._conversation_id)
        self._clear_messages()
        self._add_message(
            "New conversation. Your previous chats remain available from Chats.",
            is_user=False,
            persist=False,
        )

    def open_conversation(self, conversation_id: str) -> None:
        from jarvis.scheduling.database import (
            conversation_messages,
            set_active_conversation,
        )

        set_active_conversation(conversation_id)
        self._conversation_id = conversation_id
        self.conversation_changed.emit(self._conversation_id)
        self._clear_messages()
        try:
            messages = conversation_messages(conversation_id)
            if not messages:
                self._add_message("This conversation is empty.", is_user=False, persist=False)
            for item in messages:
                model_label = str(item.get("model_label", ""))
                if item["role"] == "assistant" and not model_label:
                    model_label = "Model not recorded"
                self._add_message(
                    item["content"],
                    is_user=item["role"] == "user",
                    persist=False,
                    timestamp=datetime.fromtimestamp(item["created_at"]).strftime("%H:%M"),
                    model_label=model_label,
                )
        except Exception as exc:
            log.exception("Could not open conversation %s", conversation_id)
            self._lbl_status.setText(f"⚠ Could not open conversation: {exc}")
            self._lbl_status.setVisible(True)

    def _clear_messages(self) -> None:
        self._confirmation_row = None
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_chat_history(self) -> None:
        from jarvis.scheduling.database import (
            delete_conversation,
            list_conversations,
            rename_conversation,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Chat history")
        dialog.setMinimumSize(420, 340)
        layout = QVBoxLayout(dialog)
        items = QListWidget(dialog)
        layout.addWidget(items)

        def refresh() -> None:
            items.clear()
            for conversation in list_conversations():
                updated = datetime.fromtimestamp(
                    conversation["updated_at"]
                ).strftime("%Y-%m-%d %H:%M")
                item = QListWidgetItem(
                    f"{conversation['title']}  ·  {updated}"
                )
                item.setData(Qt.ItemDataRole.UserRole, conversation["id"])
                items.addItem(item)

        refresh()
        buttons = QHBoxLayout()
        open_button = QPushButton("Open")
        rename_button = QPushButton("Rename")
        delete_button = QPushButton("Delete")
        close_button = QPushButton("Close")
        buttons.addWidget(open_button)
        buttons.addWidget(rename_button)
        buttons.addWidget(delete_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        def selected_id() -> str | None:
            item = items.currentItem()
            return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

        def open_selected() -> None:
            conversation_id = selected_id()
            if conversation_id:
                try:
                    self.open_conversation(conversation_id)
                    dialog.accept()
                except Exception as exc:
                    QMessageBox.warning(dialog, "Chat history", str(exc))

        def rename_selected() -> None:
            conversation_id = selected_id()
            if not conversation_id:
                return
            current = items.currentItem().text().split("  ·  ", 1)[0]
            title, accepted = QInputDialog.getText(
                dialog, "Rename chat", "Title:", text=current
            )
            if accepted:
                try:
                    rename_conversation(conversation_id, title)
                    refresh()
                except Exception as exc:
                    QMessageBox.warning(dialog, "Chat history", str(exc))

        def delete_selected() -> None:
            conversation_id = selected_id()
            if not conversation_id:
                return
            answer = QMessageBox.question(
                dialog, "Delete chat", "Delete this conversation permanently?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            delete_conversation(conversation_id)
            if conversation_id == self._conversation_id:
                self.new_chat()
            refresh()

        open_button.clicked.connect(open_selected)
        items.itemDoubleClicked.connect(lambda _: open_selected())
        rename_button.clicked.connect(rename_selected)
        delete_button.clicked.connect(delete_selected)
        close_button.clicked.connect(dialog.accept)
        dialog.exec()

    def _set_busy(self, busy: bool) -> None:
        self._input.setEnabled(not busy)
        self._btn_send.setEnabled(not busy)
        self._btn_cancel.setVisible(busy)
        self._btn_cancel.setEnabled(True)
        if busy:
            self._lbl_status.setText(
                "🔎 Searching the web…"
                if self._search_in_progress
                else "⏳ Processing…"
            )
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
        voice_request = self._next_request_is_voice
        self._next_request_is_voice = False
        self._last_request_text = text
        self._force_search_next = self._btn_search.isChecked()
        self._last_request_was_search = bool(
            self._force_search_next
            or getattr(self._router, "requires_search", lambda *_: False)(text)
        )
        self._search_in_progress = self._last_request_was_search
        self._btn_search.setChecked(False)
        if self._search_in_progress:
            self._lbl_status.setText("🔎 Searching the web…")
            self._lbl_status.setVisible(True)
        self._btn_retry.setVisible(False)
        self._input.clear()
        self._add_message(text, is_user=True)
        self.message_added.emit("user", text)
        self._set_busy(True)
        self._state_manager.transition(RobotState.THINKING)
        self._cancelled = False
        self._stream_bubble = None
        self._streamed_response = ""
        self._stream_timestamp = datetime.now().strftime("%H:%M")
        self._response_model_label = ""
        self._pending_predefined_response = False
        if self._ai_gateway is not None:
            self._ai_gateway.last_provider = ""
            self._ai_gateway.last_model = ""
        self.command_issued.emit(text)
        voice_actions_disabled = bool(
            voice_request
            and self._settings is not None
            and not self._settings.get("voice_actions_enabled", True)
        )
        if (
            self._router.has_builtin(text)
            and not self._force_search_next
            and not voice_actions_disabled
        ):
            response = self._router.route(text)
            self._pending_predefined_response = bool(
                getattr(self._router, "last_response_is_predefined", False)
            )
            self._on_response_chunk(response)
            self._on_command_completed(response)
            self._set_busy(False)
            return

        thread = QThread(self)
        worker = _CommandWorker(
            self._router,
            text,
            force_search=self._force_search_next,
            voice_request=voice_request,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_response_chunk)
        worker.reset_stream.connect(self._on_stream_reset)
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
                predefined=self._pending_predefined_response,
                web_search=self._has_search_sources(self._streamed_response),
            )
        prefix = ("◆ " if self._pending_predefined_response else "") + (
            "🌐 " if self._has_search_sources(self._streamed_response) else ""
        )
        self._stream_bubble.set_response_text(
            f"{prefix}{self._streamed_response}  [{self._stream_timestamp}]"
        )

    @Slot()
    def _on_stream_reset(self) -> None:
        self._streamed_response = ""
        if self._stream_bubble is not None:
            if self._stream_bubble._model_caption is not None:
                self._msg_layout.removeWidget(self._stream_bubble._model_caption)
                self._stream_bubble._model_caption.deleteLater()
            self._msg_layout.removeWidget(self._stream_bubble)
            self._stream_bubble.deleteLater()
            self._stream_bubble = None

    @Slot(str)
    def _on_command_completed(self, response: str) -> None:
        if self._cancelled:
            return
        if self._pending_predefined_response:
            self._response_model_label = "Built-in response"
        elif self._ai_gateway is not None and self._ai_gateway.last_model:
            provider = str(self._ai_gateway.last_provider or "")
            model = str(self._ai_gateway.last_model)
            self._response_model_label = (
                f"{provider} · {model}" if provider else model
            )
        elif not self._response_model_label:
            self._response_model_label = "Local response"
        if self._stream_bubble is None:
            self._stream_bubble = self._add_message(
                response,
                is_user=False,
                persist=False,
                timestamp=self._stream_timestamp,
                predefined=self._pending_predefined_response,
                web_search=self._has_search_sources(response),
            )
        self._set_message_model(
            self._stream_bubble, self._response_model_label
        )
        prefix = ("◆ " if self._pending_predefined_response else "") + (
            "🌐 " if self._has_search_sources(response) else ""
        )
        self._stream_bubble.set_response_text(
            f"{prefix}{response}  [{self._stream_timestamp}]"
        )
        if self._settings is not None and self._settings.get("retain_conversation", True):
            self._persist_message(
                "assistant", response, self._response_model_label
            )
        if response:
            self.message_added.emit("assistant", response)
        if response.startswith("Please confirm:"):
            self._show_confirmation_controls()
        elif not response.startswith("Please answer yes or no"):
            self._clear_confirmation_controls()
        self._btn_retry.setVisible(
            response.startswith(("⚠ AI request failed:", "⚠ Web search"))
        )
        self._state_manager.transition(RobotState.SUCCESS)
        if self._voice is not None:
            self._voice_waiting_for_tts = bool(
                response
                and self._settings is not None
                and self._settings.get("tts_enabled", False)
                and not self._settings.get("voice_interrupt_tts", True)
            )
            self._voice.speak(response)
            if not self._voice_waiting_for_tts:
                self._schedule_voice_restart()
        self._force_search_next = False
        self._search_in_progress = False
        QTimer.singleShot(1500, lambda: self._state_manager.transition(RobotState.IDLE))

    def _queue_confirmation_reply(self, reply: str) -> None:
        def submit_when_ready() -> None:
            if self._command_thread is not None:
                QTimer.singleShot(50, submit_when_ready)
                return
            self._input.setText(reply)
            self._on_send()

        QTimer.singleShot(0, submit_when_ready)

    def _show_confirmation_controls(self) -> None:
        self._clear_confirmation_controls()
        from PySide6.QtWidgets import QHBoxLayout

        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(34, 0, 8, 4)
        layout.setSpacing(8)
        yes = QPushButton("Yes")
        no = QPushButton("No")
        yes.setAccessibleName("Confirm proposed action")
        no.setAccessibleName("Cancel proposed action")
        yes.clicked.connect(lambda: self._respond_to_confirmation("yes", row))
        no.clicked.connect(lambda: self._respond_to_confirmation("no", row))
        layout.addWidget(yes)
        layout.addWidget(no)
        layout.addStretch(1)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, row)
        self._confirmation_row = row

    def _respond_to_confirmation(self, answer: str, row: QWidget) -> None:
        for button in row.findChildren(QPushButton):
            button.setEnabled(False)
        self._queue_confirmation_reply(answer)

    def _clear_confirmation_controls(self) -> None:
        if self._confirmation_row is None:
            return
        self._msg_layout.removeWidget(self._confirmation_row)
        self._confirmation_row.deleteLater()
        self._confirmation_row = None

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
        self._force_search_next = False
        self._search_in_progress = False
        if self._cancelled:
            self._state_manager.transition(RobotState.IDLE)
            self._add_message("⚠ Response cancelled.", is_user=False)

    @Slot()
    def _on_cancel(self) -> None:
        if self._command_thread is None:
            return
        self._cancelled = True
        if self._command_worker is not None:
            self._command_worker.cancel_event.set()
        self._btn_cancel.setEnabled(False)
        self._lbl_status.setText("Stopping response…")
        self._lbl_status.setVisible(True)

    @Slot()
    def _retry_last_request(self) -> None:
        if self._command_thread is not None or not self._last_request_text:
            return
        self._btn_search.setChecked(self._last_request_was_search)
        self._input.setText(self._last_request_text)
        self._on_send()

    def _on_search_toggled(self, enabled: bool) -> None:
        self._btn_search.setText("Search ON" if enabled else "Search")
        if enabled:
            self._input.setPlaceholderText("Type a web search query…")
        else:
            self._input.setPlaceholderText("Type a command…  (try: hello, demo, help)")

    def set_input_text(self, text: str) -> None:
        self._input.setText(text)
        self._input.setFocus()

    def add_reminder_message(self, title: str, description: str = "") -> None:
        text = f"🔔 Reminder: {title}"
        if description.strip():
            text += f"\n{description.strip()}"
        self._add_message(
            text,
            is_user=False,
            persist=bool(
                self._settings is not None
                and self._settings.get("retain_conversation", True)
            ),
        )
        self.message_added.emit("assistant", text)

    def toggle_voice(self) -> None:
        if self._voice is None:
            self._on_voice_error("Voice settings are not available.")
        elif self._voice.listening_session_active:
            self._voice.stop_listening()
            if not self._voice.is_listening:
                self._on_voice_state(False)
        else:
            self._voice.start_listening()

    @Slot()
    def _on_speech_finished(self) -> None:
        if self._voice_waiting_for_tts:
            self._voice_waiting_for_tts = False
        if (
            self._settings is not None
            and self._settings.get("voice_interrupt_tts", True)
        ):
            self._schedule_voice_restart()

    def _schedule_voice_restart(self) -> None:
        if (
            self._voice is None
            or not self._voice.listening_session_active
            or not self._settings.get("voice_auto_listen", True)
        ):
            return
        QTimer.singleShot(300, self._restart_voice_when_ready)

    def _restart_voice_when_ready(self) -> None:
        if (
            self._voice is None
            or not self._voice.listening_session_active
            or not self._settings.get("voice_auto_listen", True)
        ):
            self._voice_restart_pending = False
            return
        if self._voice.is_listening:
            self._voice_restart_pending = True
            return
        self._voice_restart_pending = False
        self._voice.start_listening()

    def _open_image_creator(self) -> None:
        from jarvis.ui.image_creation_dialog import ImageCreationDialog

        dialog = ImageCreationDialog(
            self._ai_gateway,
            self._settings,
            parent=self,
        )
        dialog.exec()

    @Slot(bool)
    def _on_voice_state(self, active: bool) -> None:
        session_active = bool(
            self._voice is not None and self._voice.listening_session_active
        )
        self._btn_mic.setText("Stop" if session_active else "Mic")
        self._btn_mic.setStyleSheet(
            "QPushButton{background:#a02030;}" if session_active else ""
        )
        self.voice_active_changed.emit(session_active)
        if active:
            self._lbl_status.setText("🎤 Listening — click Stop when finished.")
            self._lbl_status.setVisible(True)
        elif not session_active and self._lbl_status.text().startswith("🎤"):
            self._lbl_status.setVisible(False)
        if not active and self._voice_restart_pending:
            QTimer.singleShot(100, self._restart_voice_when_ready)

    @Slot(str)
    def _on_transcription(self, text: str) -> None:
        self._input.setText(text)
        self._next_request_is_voice = True
        self._on_send()

    @Slot(str)
    def _on_voice_error(self, message: str) -> None:
        self._add_message(f"⚠ Voice: {message}", is_user=False)
        self.message_added.emit("assistant", f"Voice error: {message}")

    @property
    def current_conversation_id(self) -> str:
        return self._conversation_id

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
