"""Compact voice-chat window that works independently of the main chat panel."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from jarvis.scheduling import database


class VoiceChatDialog(QDialog):
    def __init__(self, panel, settings, parent=None) -> None:
        super().__init__(parent)
        self._panel = panel
        self._settings = settings
        self.setWindowTitle("JARVIS Voice Chat")
        self.setMinimumSize(360, 320)
        self.setStyleSheet(
            "QDialog,QWidget{background:rgba(8,18,42,230);color:#c8eaff;"
            "font:13px 'Segoe UI';}"
            "QComboBox{background:#102440;color:#e5f7ff;padding:5px;}"
            "QPushButton{background:rgba(0,150,200,200);color:white;"
            "border:1px solid rgba(0,200,255,100);border-radius:7px;padding:6px;}"
        )
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Voice chat is private and starts only when you press the robot's chest button "
            "or Listen below."
        ))
        self.history = QTextBrowser()
        self.history.setOpenExternalLinks(False)
        root.addWidget(self.history, 1)
        row = QHBoxLayout()
        self.conversations = QComboBox()
        self.conversations.setMinimumContentsLength(16)
        row.addWidget(self.conversations, 1)
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(self._open_selected)
        row.addWidget(self.open_button)
        root.addLayout(row)
        controls = QHBoxLayout()
        self.new_button = QPushButton("New chat")
        self.new_button.clicked.connect(self._new_chat)
        controls.addWidget(self.new_button)
        self.listen_button = QPushButton("Listen")
        self.listen_button.clicked.connect(self._toggle_listening)
        controls.addWidget(self.listen_button)
        close = QPushButton("Close")
        close.clicked.connect(self.hide)
        controls.addWidget(close)
        root.addLayout(controls)

        panel.message_added.connect(self._append_message)
        panel.conversation_changed.connect(self._load_conversation)
        if panel._voice is not None:
            panel._voice.listening_changed.connect(self._on_listening_changed)
        self._load_conversations(panel.current_conversation_id)
        self._load_history(panel.current_conversation_id)
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, settings)

    def _load_conversations(self, selected_id: str = "") -> None:
        self.conversations.clear()
        try:
            items = database.list_conversations()
        except Exception as exc:
            self.history.setPlainText(f"Could not load chat history: {exc}")
            return
        for item in items:
            updated = datetime.fromtimestamp(item["updated_at"]).strftime("%m-%d %H:%M")
            self.conversations.addItem(
                f"{item['title']} · {updated}", str(item["id"])
            )
        index = self.conversations.findData(selected_id)
        if index >= 0:
            self.conversations.setCurrentIndex(index)

    def _load_history(self, conversation_id: str) -> None:
        try:
            messages = database.conversation_messages(conversation_id)
        except Exception as exc:
            self.history.setPlainText(f"Could not load this chat: {exc}")
            return
        self.history.clear()
        for item in messages:
            self._append_message(str(item["role"]), str(item["content"]))

    def _append_message(self, role: str, text: str) -> None:
        color = "#8ddcff" if role == "user" else "#43e6ff"
        label = "You" if role == "user" else "JARVIS"
        safe_text = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        self.history.append(
            f'<p style="color:{color}"><b>{label}:</b> {safe_text}</p>'
        )

    def _load_conversation(self, conversation_id: str) -> None:
        self._load_conversations(conversation_id)
        self._load_history(conversation_id)

    def _new_chat(self) -> None:
        if self._panel._voice is not None and self._panel._voice.is_listening:
            self._panel._voice.stop_listening()
        self._panel.new_chat()
        self._load_conversation(self._panel.current_conversation_id)

    def _open_selected(self) -> None:
        conversation_id = self.conversations.currentData()
        if not conversation_id:
            return
        if self._panel._voice is not None and self._panel._voice.is_listening:
            self._panel._voice.stop_listening()
        self._panel.open_conversation(str(conversation_id))

    def _toggle_listening(self) -> None:
        if self._panel._voice is None:
            self.history.append("JARVIS: Voice input is not available.")
            return
        if self._panel._voice.is_listening:
            self._panel._voice.stop_listening()
        else:
            self._panel._voice.start_listening()

    def _on_listening_changed(self, active: bool) -> None:
        self.listen_button.setText("Stop listening" if active else "Listen")
