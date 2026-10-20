"""Shared transparency, opacity, and drag behavior for utility dialogs."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QAbstractButton, QDialog, QWidget


_INTERACTIVE_TYPES = (
    "QLineEdit", "QTextEdit", "QPlainTextEdit",
    "QComboBox", "QAbstractSpinBox", "QAbstractSlider", "QListView",
    "QTreeView", "QTableView", "QDateTimeEdit",
)


class _DragFilter(QObject):
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._start: QPoint | None = None
        self._origin = dialog.pos()
        self._dragging = False

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and not self._interactive(watched):
                self._start = event.globalPosition().toPoint()
                self._origin = self._dialog.pos()
                self._dragging = False
        elif event.type() == QEvent.Type.MouseMove and self._start is not None:
            point = event.globalPosition().toPoint()
            delta = point - self._start
            if not self._dragging and delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
            if self._dragging:
                self._dialog.move(self._origin + delta)
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self._dragging:
                if isinstance(watched, QAbstractButton):
                    watched.setDown(False)
                self._start = None
                self._dragging = False
                return True
            self._start = None
        return False

    @staticmethod
    def _interactive(widget) -> bool:
        if isinstance(widget, QAbstractButton):
            return False
        return any(widget.inherits(class_name) for class_name in _INTERACTIVE_TYPES)


def configure_dialog_window(dialog: QDialog, settings=None) -> None:
    """Make a utility dialog translucent and draggable without a move handle."""
    if settings is None:
        parent = dialog.parentWidget()
        settings = getattr(parent, "_s", None) or getattr(parent, "_settings", None)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    if settings is not None:
        dialog.setWindowOpacity(float(settings.get("opacity", 0.9)))
    dialog._drag_filter = _DragFilter(dialog)
    dialog.installEventFilter(dialog._drag_filter)
    for widget in dialog.findChildren(QWidget):
        widget.installEventFilter(dialog._drag_filter)
