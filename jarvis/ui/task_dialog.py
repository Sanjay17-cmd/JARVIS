"""Theme-matched active/completed task manager backed by SQLite."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QTextEdit, QVBoxLayout,
)


class TaskDialog(QDialog):
    def __init__(
        self,
        panels_always_on_top: bool = True,
        parent=None,
        show_completed: bool = False,
    ) -> None:
        super().__init__(parent)
        flags = self.windowFlags() | Qt.WindowType.Tool
        if panels_always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("JARVIS Tasks")
        self.setMinimumSize(560, 560)
        self.setStyleSheet(
            "QDialog,QWidget{background:rgba(8,18,42,235);color:#c0e8ff;"
            "font-family:'Segoe UI',Arial;font-size:12px;}"
            "QLineEdit,QTextEdit,QComboBox,QSpinBox,QDateTimeEdit{"
            "background:rgba(0,30,60,220);border:1px solid rgba(0,200,255,100);"
            "padding:5px;}"
            "QPushButton{background:rgba(0,150,200,160);color:white;"
            "border:1px solid rgba(0,200,255,100);border-radius:6px;padding:6px;}"
        )
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._active = QListWidget()
        self._completed = QListWidget()
        self._tabs.addTab(self._active, "Active Tasks")
        self._tabs.addTab(self._completed, "Completed Tasks")
        layout.addWidget(self._tabs, 1)

        form = QFormLayout()
        self._title = QLineEdit()
        self._title.setPlaceholderText("Task title")
        self._details = QTextEdit()
        self._details.setPlaceholderText("Details")
        self._details.setMaximumHeight(70)
        self._priority = QComboBox()
        self._priority.addItems(["Low", "Medium", "High"])
        self._due_enabled = QCheckBox("Set due date")
        self._due = QDateTimeEdit()
        self._due.setCalendarPopup(True)
        self._due.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._due.setDateTime(QDateTime.currentDateTime())
        self._due.setEnabled(False)
        self._due_enabled.toggled.connect(self._due.setEnabled)
        due_row = QHBoxLayout()
        due_row.addWidget(self._due_enabled)
        due_row.addWidget(self._due, 1)
        form.addRow("Title:", self._title)
        form.addRow("Details:", self._details)
        form.addRow("Priority:", self._priority)
        form.addRow("Due:", due_row)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        new_task = QPushButton("New Task")
        new_task.clicked.connect(self._clear_form)
        self._save_button = QPushButton("Add Task")
        self._save_button.clicked.connect(self._save_task)
        self._complete_button = QPushButton("Mark Complete")
        self._complete_button.clicked.connect(self._complete_task)
        self._reopen_button = QPushButton("Reopen")
        self._reopen_button.clicked.connect(self._reopen_task)
        self._delete_button = QPushButton("Delete")
        self._delete_button.clicked.connect(self._delete_task)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for button in (
            new_task, self._save_button, self._complete_button, self._reopen_button,
            self._delete_button, close,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._status = QLabel()
        layout.addWidget(self._status)
        self._active.currentItemChanged.connect(self._active_selected)
        self._completed.currentItemChanged.connect(self._completed_selected)
        if show_completed:
            self._tabs.setCurrentIndex(1)
        self._refresh()
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, getattr(parent, "_s", None) or getattr(parent, "_settings", None))

    def _refresh(self, select_id: int | None = None) -> None:
        from jarvis.scheduling.task_service import get_all_tasks

        self._active.clear()
        self._completed.clear()
        active_count = completed_count = 0
        for task in get_all_tasks():
            is_done = task["status"] == "done"
            widget = self._completed if is_done else self._active
            if is_done:
                completed_count += 1
            else:
                active_count += 1
            details = task.get("description") or ""
            deadline = task.get("deadline")
            due = datetime.fromtimestamp(deadline).astimezone().strftime("%b %d %H:%M") if deadline else ""
            summary = f"#{task['id']}  [{('Low','Medium','High')[max(0,min(2,int(task.get('priority',1))-1))]}] {task['title']}"
            if due:
                summary += f"  ·  due {due}"
                now = datetime.now().astimezone()
                task_due = datetime.fromtimestamp(deadline).astimezone()
                if task_due.timestamp() < time.time():
                    summary += "  ·  OVERDUE"
                elif task_due.date() == now.date():
                    summary += "  ·  DUE TODAY"
            if details:
                summary += f"  —  {details}"
            item = QListWidgetItem(summary)
            item.setData(Qt.ItemDataRole.UserRole, task["id"])
            widget.addItem(item)
            if select_id == task["id"]:
                widget.setCurrentItem(item)
        self._tabs.setTabText(0, f"Active Tasks ({active_count})")
        self._tabs.setTabText(1, f"Completed Tasks ({completed_count})")

    def _selected(self):
        widget = self._completed if self._tabs.currentIndex() == 1 else self._active
        item = widget.currentItem()
        if not item:
            return None
        from jarvis.scheduling.task_service import get_all_tasks
        return next(
            (task for task in get_all_tasks() if task["id"] == item.data(Qt.ItemDataRole.UserRole)),
            None,
        )

    def _active_selected(self, item, _previous=None) -> None:
        if item is not None and self._tabs.currentIndex() == 0:
            self._load_selected()

    def _completed_selected(self, item, _previous=None) -> None:
        if item is not None and self._tabs.currentIndex() == 1:
            self._load_selected()

    def _load_selected(self) -> None:
        task = self._selected()
        if not task:
            return
        self._title.setText(task["title"])
        self._details.setPlainText(task.get("description") or "")
        self._priority.setCurrentIndex(max(0, min(2, int(task.get("priority", 1)) - 1)))
        deadline = task.get("deadline")
        self._due_enabled.setChecked(bool(deadline))
        if deadline:
            self._due.setDateTime(QDateTime.fromSecsSinceEpoch(int(deadline)))
        completed = task.get("status") == "done"
        self._save_button.setText("Save Changes")
        self._complete_button.setVisible(not completed)
        self._reopen_button.setVisible(completed)

    def _save_task(self) -> None:
        title = self._title.text().strip()
        if not title:
            self._status.setText("A task title is required.")
            return
        from jarvis.scheduling.task_service import add_task, edit_task
        deadline = self._due.dateTime().toSecsSinceEpoch() if self._due_enabled.isChecked() else None
        selected = self._selected()
        fields = {
            "title": title,
            "description": self._details.toPlainText().strip(),
            "priority": self._priority.currentIndex() + 1,
            "deadline": deadline,
        }
        if selected:
            edit_task(selected["id"], **fields)
            selected_id = selected["id"]
            self._status.setText("Task updated.")
        else:
            selected_id = add_task(**fields)
            self._status.setText(f"Task #{selected_id} created.")
        self._refresh(selected_id)

    def _complete_task(self) -> None:
        task = self._selected()
        if not task:
            return
        from jarvis.scheduling.task_service import complete_task
        complete_task(task["id"])
        self._tabs.setCurrentIndex(1)
        self._status.setText("Task moved to Completed Tasks.")
        self._refresh(task["id"])

    def _reopen_task(self) -> None:
        task = self._selected()
        if not task:
            return
        from jarvis.scheduling.task_service import set_task_status
        set_task_status(task["id"], "todo")
        self._tabs.setCurrentIndex(0)
        self._status.setText("Task reopened.")
        self._refresh(task["id"])

    def _delete_task(self) -> None:
        task = self._selected()
        if not task:
            return
        answer = QMessageBox.question(
            self, "Delete task", f"Delete '{task['title']}' permanently?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        from jarvis.scheduling.task_service import delete_task
        delete_task(task["id"])
        self._status.setText("Task deleted.")
        self._clear_form()
        self._refresh()

    def _clear_form(self) -> None:
        self._active.setCurrentRow(-1)
        self._completed.setCurrentRow(-1)
        self._title.clear()
        self._details.clear()
        self._priority.setCurrentIndex(0)
        self._due_enabled.setChecked(False)
        self._save_button.setText("Add Task")
        self._complete_button.setVisible(True)
        self._reopen_button.setVisible(False)
