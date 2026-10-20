"""Editor for validated user behavior JSON files."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QPlainTextEdit, QVBoxLayout,
)

from jarvis.config.behavior_config import BehaviorConfig


class BehaviorConfigDialog(QDialog):
    def __init__(self, behavior: BehaviorConfig, router, parent=None) -> None:
        super().__init__(parent)
        self._behavior = behavior
        self._router = router
        self.setWindowTitle("Behavior & Responses")
        self.setMinimumSize(700, 580)
        self.setStyleSheet(
            "QDialog,QWidget{background:rgba(8,18,42,235);color:#c0e8ff;"
            "font-family:'Segoe UI',Arial;font-size:12px;}"
            "QPlainTextEdit,QLineEdit,QComboBox{background:rgba(0,30,60,220);"
            "color:#c0e8ff;border:1px solid rgba(0,200,255,100);padding:6px;}"
            "QPushButton{background:rgba(0,150,200,160);color:white;"
            "border:1px solid rgba(0,200,255,100);border-radius:6px;padding:6px 10px;}"
        )
        layout = QVBoxLayout(self)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Configuration:"))
        self._selector = QComboBox()
        self._selector.addItem("Assistant responses", "responses")
        self._selector.addItem("Custom commands", "commands")
        self._selector.addItem("Robot animations", "animations")
        self._selector.currentIndexChanged.connect(self._reload)
        selector_row.addWidget(self._selector)
        selector_row.addStretch()
        layout.addLayout(selector_row)
        self._path = QLabel()
        self._path.setWordWrap(True)
        layout.addWidget(self._path)
        self._editor = QPlainTextEdit()
        self._editor.setTabStopDistance(28)
        layout.addWidget(self._editor, 1)
        help_text = QLabel(
            "Custom commands use registered safe actions only. Example: "
            "triggers ['show my tasks'], action 'show_tasks', arguments {}."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        test_row = QHBoxLayout()
        self._test_input = QLineEdit()
        self._test_input.setPlaceholderText("Try a trigger phrase or response key")
        test_button = QPushButton("Test")
        test_button.clicked.connect(self._test)
        test_row.addWidget(self._test_input)
        test_row.addWidget(test_button)
        layout.addLayout(test_row)
        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        buttons = QHBoxLayout()
        for label, handler in (
            ("Validate JSON", self._validate),
            ("Save", self._save),
            ("Reload", self._reload),
            ("Reset to Defaults", self._reset),
            ("Open Config Folder", self._open_folder),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._reload()
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, getattr(parent, "_s", None) or getattr(parent, "_settings", None))

    def _kind(self) -> str:
        return str(self._selector.currentData())

    def _reload(self, *_args) -> None:
        try:
            data = self._behavior.load(self._kind())
            self._editor.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
            path = self._behavior.path(self._kind())
            self._path.setText(f"Active file: {path}")
            self._status.setText("Loaded and validated.")
            self._status.setStyleSheet("color:#80ffab")
        except Exception as exc:
            self._path.setText(f"Active file: {self._behavior.path(self._kind())}")
            self._status.setText(str(exc))
            self._status.setStyleSheet("color:#ff7777")

    def _parse_and_validate(self) -> dict:
        data = json.loads(self._editor.toPlainText())
        self._behavior.validate(self._kind(), data)
        return data

    def _validate(self) -> None:
        try:
            self._parse_and_validate()
            self._status.setText("Valid JSON and supported schema.")
            self._status.setStyleSheet("color:#80ffab")
        except (json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                message = f"{self._behavior.path(self._kind()).name}:{exc.lineno}:{exc.colno}: {exc.msg}"
            else:
                message = str(exc)
            self._status.setText(message)
            self._status.setStyleSheet("color:#ff7777")

    def _save(self) -> None:
        try:
            data = self._parse_and_validate()
            self._behavior.save(self._kind(), data)
            self._apply_commands()
            if self._kind() == "responses":
                self._router.set_responses(data["responses"])
            self._status.setText(f"Saved and applied: {self._behavior.path(self._kind())}")
            self._status.setStyleSheet("color:#80ffab")
        except Exception as exc:
            self._status.setText(str(exc))
            self._status.setStyleSheet("color:#ff7777")

    def _apply_commands(self) -> None:
        if self._kind() == "commands":
            self._router.set_custom_commands(
                self._behavior.load("commands")["commands"],
                getattr(self._router, "_custom_actions", {}),
            )

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self, "Reset configuration",
            f"Replace {self._behavior.path(self._kind()).name} with shipped defaults?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._behavior.reset(self._kind())
            self._reload()
            self._apply_commands()
            if self._kind() == "responses":
                self._router.set_responses(
                    self._behavior.load("responses").get("responses", {})
                )
            self._status.setText("Reset to shipped defaults.")
        except Exception as exc:
            self._status.setText(str(exc))

    def _open_folder(self) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._behavior.directory))):
            self._status.setText(f"Could not open folder: {self._behavior.directory}")
            self._status.setStyleSheet("color:#ff7777")

    def _test(self) -> None:
        query = self._test_input.text().strip()
        if not query:
            self._status.setText("Enter a trigger phrase or response key to test.")
            return
        try:
            data = self._parse_and_validate()
            if self._kind() == "commands":
                normalized = self._router._normalize(query)
                matched = [
                    command["name"]
                    for command in data["commands"]
                    if command.get("enabled", True)
                    and normalized in {
                        self._router._normalize(phrase)
                        for phrase in command.get("triggers", []) + command.get("aliases", [])
                    }
                ]
                self._status.setText(
                    "Would match: " + ", ".join(matched)
                    if matched else "No custom command matches exactly."
                )
            elif self._kind() == "responses":
                alternatives = data["responses"].get(query)
                self._status.setText(
                    f"{len(alternatives)} response template(s): "
                    + " | ".join(alternatives)
                    if alternatives else f"No response key named '{query}'."
                )
            else:
                self._status.setText(
                    f"Animation '{query}': "
                    + ("configured" if query in data["animations"] else "not configured")
                )
        except Exception as exc:
            self._status.setText(str(exc))
