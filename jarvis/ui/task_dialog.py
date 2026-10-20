"""Small SQLite-backed task manager window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)


class TaskDialog(QDialog):
    def __init__(
        self,
        panels_always_on_top: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        flags = self.windowFlags() | Qt.WindowType.Tool
        if panels_always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("JARVIS Tasks")
        self.setMinimumSize(380, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Open tasks"))
        self._tasks = QListWidget()
        layout.addWidget(self._tasks)

        input_row = QHBoxLayout()
        self._title = QLineEdit()
        self._title.setPlaceholderText("Add a task…")
        self._title.returnPressed.connect(self._add_task)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_task)
        input_row.addWidget(self._title)
        input_row.addWidget(add_button)
        layout.addLayout(input_row)

        action_row = QHBoxLayout()
        complete_button = QPushButton("Mark complete")
        complete_button.clicked.connect(self._complete_task)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        action_row.addWidget(complete_button)
        action_row.addStretch()
        action_row.addWidget(close_button)
        layout.addLayout(action_row)

        self._refresh()

    def _refresh(self) -> None:
        from jarvis.scheduling.task_service import format_task, get_tasks

        self._tasks.clear()
        for task in get_tasks():
            item = QListWidgetItem(f"#{task['id']}  {format_task(task)}")
            item.setData(Qt.ItemDataRole.UserRole, task["id"])
            self._tasks.addItem(item)

    def _add_task(self) -> None:
        title = self._title.text().strip()
        if not title:
            return
        from jarvis.scheduling.task_service import add_task

        add_task(title)
        self._title.clear()
        self._refresh()

    def _complete_task(self) -> None:
        item = self._tasks.currentItem()
        if item is None:
            return
        from jarvis.scheduling.task_service import complete_task

        complete_task(int(item.data(Qt.ItemDataRole.UserRole)))
        self._refresh()
