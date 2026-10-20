"""Persistent reminder/alarm manager with short-duration controls."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout,
)


class RemindersDialog(QDialog):
    def __init__(self, panels_always_on_top: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reminders & Alarms")
        self.setMinimumSize(600, 520)
        flags = self.windowFlags() | Qt.WindowType.Tool
        if panels_always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setStyleSheet(
            "QDialog,QWidget{background:rgba(8,18,42,235);color:#c0e8ff;"
            "font-family:'Segoe UI',Arial;font-size:12px;}"
            "QComboBox,QLineEdit,QSpinBox{background:rgba(0,30,60,220);"
            "border:1px solid rgba(0,200,255,100);padding:5px;}"
            "QPushButton{background:rgba(0,150,200,160);color:white;"
            "border:1px solid rgba(0,200,255,100);border-radius:6px;padding:6px;}"
        )
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._reminders = QListWidget()
        self._alarms = QListWidget()
        self._tabs.addTab(self._reminders, "Reminders")
        self._tabs.addTab(self._alarms, "Alarms")
        layout.addWidget(self._tabs, 1)
        form = QFormLayout()
        self._title = QLineEdit()
        self._title.setPlaceholderText("What should JARVIS remind you about?")
        self._type = QComboBox()
        self._type.addItems(["Reminder", "Alarm"])
        self._duration = QSpinBox()
        self._duration.setRange(0, 999999)
        self._duration.setValue(5)
        self._unit = QComboBox()
        self._unit.addItem("seconds", 1)
        self._unit.addItem("minutes", 60)
        self._unit.addItem("hours", 3600)
        self._recurrence = QComboBox()
        self._recurrence.addItem("Once", "")
        self._recurrence.addItem("Every day", "daily")
        self._recurrence.addItem("Weekdays", "weekdays")
        form.addRow("Type:", self._type)
        form.addRow("Title:", self._title)
        duration_row = QHBoxLayout()
        duration_row.addWidget(self._duration)
        duration_row.addWidget(self._unit)
        form.addRow("In:", duration_row)
        form.addRow("Repeat:", self._recurrence)
        layout.addLayout(form)
        controls = QHBoxLayout()
        self._add_button = QPushButton("Add")
        self._add_button.clicked.connect(self._add)
        new_item = QPushButton("New")
        new_item.clicked.connect(self._new_item)
        complete = QPushButton("Done")
        complete.clicked.connect(self._complete)
        snooze = QPushButton("Snooze 5 minutes")
        snooze.clicked.connect(lambda: self._snooze(300))
        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(self._dismiss)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete)
        test = QPushButton("Test Notification")
        test.clicked.connect(self._test_notification)
        for button in (new_item, self._add_button, complete, snooze, dismiss, delete, test):
            controls.addWidget(button)
        layout.addLayout(controls)
        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._timer = QTimer(self)
        self._edit_id = None
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._reminders.currentItemChanged.connect(self._selection_changed)
        self._alarms.currentItemChanged.connect(self._selection_changed)
        self._timer.start()
        self._refresh()
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, getattr(parent, "_s", None) or getattr(parent, "_settings", None))

    def _refresh(self) -> None:
        from jarvis.scheduling.reminder_service import get_alarms, get_reminders

        active = self._selected()
        for widget, entries, kind in (
            (self._reminders, get_reminders(include_completed=True), "reminder"),
            (self._alarms, get_alarms(include_dismissed=True), "alarm"),
        ):
            widget.clear()
            for item in entries:
                status = item.get("status", "scheduled")
                scheduled_at = (
                    item.get("snoozed_until", 0)
                    if status == "snoozed" and item.get("snoozed_until", 0) > 0
                    else item["due_at"]
                )
                remaining = max(0, int(scheduled_at - time.time()))
                countdown = (
                    f"{remaining}s remaining" if status in {"scheduled", "snoozed"}
                    else status.capitalize()
                )
                stamp = datetime.fromtimestamp(scheduled_at).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                label = f"#{item['id']}  {item['title']}  ·  {stamp}  ·  {countdown}"
                row = QListWidgetItem(label)
                row.setData(Qt.ItemDataRole.UserRole, (kind, item["id"]))
                widget.addItem(row)
        if active:
            widget = self._reminders if active[0] == "reminder" else self._alarms
            for index in range(widget.count()):
                if widget.item(index).data(Qt.ItemDataRole.UserRole) == active:
                    widget.setCurrentRow(index)
                    break

    def _selected(self):
        widget = self._reminders if self._tabs.currentIndex() == 0 else self._alarms
        item = widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self, item, _previous=None) -> None:
        if item is None:
            return
        selection = item.data(Qt.ItemDataRole.UserRole)
        if self._edit_id == selection:
            return
        kind, item_id = selection
        from jarvis.scheduling.reminder_service import get_alarms, get_reminders
        entries = get_reminders(include_completed=True) if kind == "reminder" else get_alarms(include_dismissed=True)
        entry = next((value for value in entries if value["id"] == item_id), None)
        if entry is None:
            return
        self._edit_id = selection
        self._type.setCurrentIndex(0 if kind == "reminder" else 1)
        self._title.setText(entry["title"])
        remaining = max(1, int(entry["due_at"] - time.time()))
        unit_index = 0
        amount = remaining
        for index, scale in ((2, 3600), (1, 60)):
            if remaining >= scale and remaining % scale == 0:
                unit_index, amount = index, remaining // scale
                break
        self._duration.setValue(amount)
        self._unit.setCurrentIndex(unit_index)
        recurrence = entry.get("recurrence", "")
        if recurrence.startswith("interval:"):
            recurrence = ""
        recurrence_index = self._recurrence.findData(recurrence)
        self._recurrence.setCurrentIndex(max(0, recurrence_index))
        self._add_button.setText("Save Changes")

    def _add(self) -> None:
        title = self._title.text().strip()
        amount = self._duration.value()
        if not title or amount <= 0:
            self._status.setText("Enter a title and a duration greater than zero.")
            return
        due = time.time() + amount * int(self._unit.currentData())
        try:
            kind = "reminder" if self._type.currentIndex() == 0 else "alarm"
            recurrence = str(self._recurrence.currentData())
            from jarvis.scheduling import reminder_service
            if self._edit_id:
                original_kind, item_id = self._edit_id
                if original_kind != kind:
                    self._status.setText("An existing item cannot change between reminder and alarm.")
                    return
                if kind == "reminder":
                    reminder_service.edit_reminder(
                        item_id, title=title, due_at=due, recurrence=recurrence,
                        enabled=1,
                    )
                else:
                    reminder_service.edit_alarm(
                        item_id, title=title, due_at=due, recurrence=recurrence,
                    )
                self._status.setText(f"Updated {kind} #{item_id}.")
            elif kind == "reminder":
                item_id = reminder_service.add_reminder(title, due, recurrence=recurrence)
                self._tabs.setCurrentIndex(0)
                self._status.setText(f"Saved reminder #{item_id}.")
            else:
                item_id = reminder_service.add_alarm(title, due, recurrence=recurrence)
                self._tabs.setCurrentIndex(1)
                self._status.setText(f"Saved alarm #{item_id}.")
            self._title.clear()
            self._edit_id = None
            self._add_button.setText("Add")
            self._refresh()
        except Exception as exc:
            self._status.setText(f"Could not save: {exc}")

    def _new_item(self) -> None:
        self._edit_id = None
        self._reminders.setCurrentRow(-1)
        self._alarms.setCurrentRow(-1)
        self._title.clear()
        self._duration.setValue(5)
        self._unit.setCurrentIndex(0)
        self._recurrence.setCurrentIndex(0)
        self._add_button.setText("Add")
        self._status.setText("Ready to add a new reminder or alarm.")

    def _complete(self) -> None:
        selected = self._selected()
        if not selected:
            return
        kind, item_id = selected
        if kind == "reminder":
            from jarvis.scheduling.reminder_service import complete_reminder
            complete_reminder(item_id)
        else:
            from jarvis.scheduling.reminder_service import dismiss_alarm
            dismiss_alarm(item_id)
        self._status.setText(f"{kind.capitalize()} #{item_id} completed.")
        self._refresh()

    def _snooze(self, seconds: int) -> None:
        selected = self._selected()
        if not selected:
            return
        kind, item_id = selected
        from jarvis.scheduling import reminder_service
        if kind == "reminder":
            reminder_service.snooze_reminder(item_id, seconds=seconds)
        else:
            reminder_service.snooze_alarm(item_id, seconds=seconds)
        self._status.setText(f"Snoozed {kind} #{item_id}.")
        self._refresh()

    def _dismiss(self) -> None:
        selected = self._selected()
        if not selected:
            return
        kind, item_id = selected
        from jarvis.scheduling import reminder_service
        if kind == "reminder":
            reminder_service.dismiss_reminder(item_id)
        else:
            reminder_service.dismiss_alarm(item_id)
        self._status.setText(f"Dismissed {kind} #{item_id}.")
        self._refresh()

    def _delete(self) -> None:
        selected = self._selected()
        if not selected:
            return
        if QMessageBox.question(self, "Delete", "Delete this scheduled item permanently?") != QMessageBox.StandardButton.Yes:
            return
        kind, item_id = selected
        from jarvis.scheduling import reminder_service
        if kind == "reminder":
            reminder_service.delete_reminder(item_id)
        else:
            reminder_service.delete_alarm(item_id)
        self._status.setText(f"Deleted {kind} #{item_id}.")
        self._edit_id = None
        self._add_button.setText("Add")
        self._refresh()

    def _test_notification(self) -> None:
        from jarvis.ui.notification import notify

        notify("🔔", "JARVIS test notification", "Notifications are working.", duration_ms=5000)
        self._status.setText("Test notification displayed.")
