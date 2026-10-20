"""Editor for local Windows foreground-app focus rules."""
from __future__ import annotations

import os
import uuid

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

_CATEGORIES = ("distracting", "productive", "always_allow", "neutral")


class FocusRulesDialog(QDialog):
    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Focus Application Rules")
        self.setMinimumSize(520, 420)
        self.setStyleSheet(
            "QDialog,QWidget{background:rgba(8,18,42,235);color:#c0e8ff;"
            "font-family:'Segoe UI',Arial;font-size:12px;}"
            "QPushButton{background:rgba(0,150,200,160);color:white;"
            "border:1px solid rgba(0,200,255,100);border-radius:6px;padding:6px;}"
        )
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Rules are evaluated locally while Focus is active. No screenshots, "
            "window titles, or page contents are collected."
        ))
        self._list = QListWidget()
        layout.addWidget(self._list, 1)
        form = QFormLayout()
        self._process = QLineEdit()
        self._process.setPlaceholderText("e.g. game.exe")
        self._path = QLineEdit()
        self._path.setPlaceholderText("Optional exact executable path")
        self._category = QComboBox()
        self._category.addItems(_CATEGORIES)
        form.addRow("Process:", self._process)
        form.addRow("Path:", self._path)
        form.addRow("Category:", self._category)
        layout.addLayout(form)
        row = QHBoxLayout()
        detect = QPushButton("Detect Current Application")
        detect.clicked.connect(self._detect)
        add = QPushButton("Add / Update")
        add.clicked.connect(self._add)
        toggle = QPushButton("Enable / Disable")
        toggle.clicked.connect(self._toggle_enabled)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row.addWidget(detect)
        row.addWidget(add)
        row.addWidget(toggle)
        row.addWidget(remove)
        layout.addLayout(row)
        self._status = QLabel()
        layout.addWidget(self._status)
        self._list.currentItemChanged.connect(self._select)
        self._refresh()
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, self._settings)

    def _refresh(self) -> None:
        self._list.clear()
        for rule in self._settings.get("focus_app_rules", []):
            text = f"{rule.get('process', '')} — {rule.get('category', 'neutral')}"
            if not rule.get("enabled", True):
                text += " (disabled)"
            item = QListWidgetItem(text)
            item.setData(256, rule.get("id"))
            self._list.addItem(item)

    def _select(self, item, _previous=None) -> None:
        if item is None:
            return
        rule = next(
            (value for value in self._settings.get("focus_app_rules", [])
             if value.get("id") == item.data(256)),
            None,
        )
        if rule:
            self._process.setText(rule.get("process", ""))
            self._path.setText(rule.get("path", ""))
            self._category.setCurrentText(rule.get("category", "neutral"))

    def _detect(self) -> None:
        if os.name != "nt":
            self._status.setText("Foreground application detection is Windows-only.")
            return
        try:
            from jarvis.platform.windows_foreground import foreground_application

            app = foreground_application()
            self._process.setText(app["process"])
            self._path.setText(app["path"])
            self._status.setText(f"Detected {app['process']}. Choose a category and save.")
        except Exception as exc:
            self._status.setText(f"Detection failed: {exc}")

    def _add(self) -> None:
        process = self._process.text().strip().casefold()
        path = self._path.text().strip()
        if not process and not path:
            self._status.setText("Enter a process name or executable path.")
            return
        rules = list(self._settings.get("focus_app_rules", []))
        selected = self._list.currentItem()
        rule_id = selected.data(256) if selected else uuid.uuid4().hex
        replacement = {
            "id": rule_id,
            "process": process,
            "path": path,
            "category": self._category.currentText(),
            "enabled": True,
        }
        updated = False
        for index, rule in enumerate(rules):
            if rule.get("id") == rule_id:
                rules[index] = replacement
                updated = True
                break
        if not updated:
            rules.append(replacement)
        self._settings.set("focus_app_rules", rules)
        self._settings.save()
        self._refresh()
        self._status.setText("Focus application rule saved.")

    def _remove(self) -> None:
        selected = self._list.currentItem()
        if selected is None:
            return
        if QMessageBox.question(self, "Remove rule", "Remove the selected app rule?") != QMessageBox.StandardButton.Yes:
            return
        rule_id = selected.data(256)
        self._settings.set(
            "focus_app_rules",
            [rule for rule in self._settings.get("focus_app_rules", [])
             if rule.get("id") != rule_id],
        )
        self._settings.save()
        self._refresh()
        self._status.setText("Focus application rule removed.")

    def _toggle_enabled(self) -> None:
        selected = self._list.currentItem()
        if selected is None:
            return
        rule_id = selected.data(256)
        rules = list(self._settings.get("focus_app_rules", []))
        for rule in rules:
            if rule.get("id") == rule_id:
                rule["enabled"] = not rule.get("enabled", True)
                state = "enabled" if rule["enabled"] else "disabled"
                break
        else:
            return
        self._settings.set("focus_app_rules", rules)
        self._settings.save()
        self._refresh()
        self._status.setText(f"Focus application rule {state}.")
