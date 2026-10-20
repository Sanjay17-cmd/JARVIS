"""
ui/notification.py — Polished toast notification widget.

Features:
  • Slides in from the bottom-right, fades out automatically
  • Click to dismiss early
  • Snooze button (optional, shown for reminders)
  • Icon + title + body layout
  • Always on top, transparent background
  • Queue: multiple notifications stack without overlap
  • Thread-safe: push() can be called from any thread via QMetaObject
"""
from __future__ import annotations

import logging
from typing import Callable
from collections import deque

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    Property, Signal, Slot, QPoint, QObject
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QMouseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QApplication
)

log = logging.getLogger(__name__)

_STYLE = """
QWidget#notif{background:transparent;}
QLabel#icon{font-size:22px;background:transparent;padding:2px;}
QLabel#title{color:#ffffff;font-weight:bold;font-size:13px;
    font-family:'Segoe UI',Arial;background:transparent;}
QLabel#body{color:rgba(200,230,255,220);font-size:11px;
    font-family:'Segoe UI',Arial;background:transparent;}
QPushButton#snz{background:rgba(0,150,200,160);color:#fff;
    border:1px solid rgba(0,200,255,80);border-radius:6px;
    padding:3px 10px;font-size:11px;}
QPushButton#snz:hover{background:rgba(0,200,255,180);color:#000;}
QPushButton#cls{background:transparent;border:none;color:rgba(200,200,255,150);
    font-size:14px;padding:1px 5px;}
QPushButton#cls:hover{color:#ff4444;}
"""

_NOTIF_W = 320
_NOTIF_H = 80   # base height; expands if body is long
_MARGIN  = 14


class _ToastWidget(QWidget):
    dismissed = Signal()

    def __init__(self, icon: str, title: str, body: str,
                 snooze_cb: Callable | None = None,
                 duration_ms: int = 6000) -> None:
        super().__init__(None)
        self._opacity_val = 0.0

        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool
                 | Qt.WindowType.NoDropShadowWindowHint)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("notif")
        self.setStyleSheet(_STYLE)
        self.setFixedWidth(_NOTIF_W)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 10, 10, 10)
        outer.setSpacing(10)

        lbl_icon = QLabel(icon)
        lbl_icon.setObjectName("icon")
        lbl_icon.setFixedWidth(30)
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(lbl_icon)

        txt = QVBoxLayout()
        txt.setSpacing(2)
        lbl_t = QLabel(title); lbl_t.setObjectName("title"); lbl_t.setWordWrap(True)
        lbl_b = QLabel(body);  lbl_b.setObjectName("body");  lbl_b.setWordWrap(True)
        txt.addWidget(lbl_t)
        if body:
            txt.addWidget(lbl_b)
        if snooze_cb:
            btn_s = QPushButton("Snooze 10m"); btn_s.setObjectName("snz")
            btn_s.clicked.connect(lambda: (snooze_cb(), self._close()))
            txt.addWidget(btn_s)
        txt.addStretch()
        outer.addLayout(txt)

        btn_cls = QPushButton("✕"); btn_cls.setObjectName("cls")
        btn_cls.setFixedSize(22, 22)
        btn_cls.clicked.connect(self._close)
        outer.addWidget(btn_cls, alignment=Qt.AlignmentFlag.AlignTop)

        self.adjustSize()

        # Fade-in animation
        self._anim_in  = QPropertyAnimation(self, b"opacity", self)
        self._anim_in.setDuration(300)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim_out = QPropertyAnimation(self, b"opacity", self)
        self._anim_out.setDuration(400)
        self._anim_out.setStartValue(1.0)
        self._anim_out.setEndValue(0.0)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.finished.connect(self._finish)

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(duration_ms)
        self._auto_timer.timeout.connect(self._begin_close)

    def show_at(self, x: int, y: int) -> None:
        self.move(x, y)
        self.show()
        self._anim_in.start()
        self._auto_timer.start()

    def mousePressEvent(self, _: QMouseEvent) -> None:  # noqa: N802
        self._close()

    def _close(self) -> None:
        self._auto_timer.stop()
        self._begin_close()

    def _begin_close(self) -> None:
        if self._anim_out.state() != QPropertyAnimation.State.Running:
            self._anim_out.start()

    def _finish(self) -> None:
        self.hide()
        self.dismissed.emit()

    # Qt property for opacity animation
    def _get_opacity(self) -> float:
        return self._opacity_val

    def _set_opacity(self, v: float) -> None:
        self._opacity_val = v
        self.setWindowOpacity(v)

    opacity = Property(float, _get_opacity, _set_opacity)

    def paintEvent(self, _) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        p.fillPath(path, QColor(8, 20, 50, 230))
        p.setPen(QColor(0, 180, 255, 80))
        p.drawPath(path)
        p.end()


class NotificationQueue(QObject):
    """
    Singleton-style queue that shows one toast at a time,
    stacking them bottom-right. Thread-safe push() via invokeMethod.
    """
    _instance: "NotificationQueue | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._queue: deque[dict] = deque()
        self._active: list[_ToastWidget] = []

    @staticmethod
    def instance() -> "NotificationQueue":
        if NotificationQueue._instance is None:
            NotificationQueue._instance = NotificationQueue()
        return NotificationQueue._instance

    def push(self, icon: str, title: str, body: str = "",
             snooze_cb: Callable | None = None,
             duration_ms: int = 6000) -> None:
        """Thread-safe: can be called from any thread."""
        from PySide6.QtCore import QMetaObject, Qt as _Qt
        if QApplication.instance() and \
                QApplication.instance().thread() != self.thread():
            # Cross-thread: marshal to GUI thread
            QMetaObject.invokeMethod(
                self, "_push_main",
                _Qt.ConnectionType.QueuedConnection,
                icon, title, body, duration_ms,
            )
        else:
            self._push_main(icon, title, body, duration_ms, snooze_cb)

    @Slot(str, str, str, int)
    def _push_main(self, icon: str, title: str, body: str,
                   duration_ms: int, snooze_cb: Callable | None = None) -> None:
        toast = _ToastWidget(icon, title, body, snooze_cb, duration_ms)
        toast.dismissed.connect(lambda t=toast: self._on_dismissed(t))
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.right() - _NOTIF_W - _MARGIN
        y = screen.bottom() - _NOTIF_H - _MARGIN - (len(self._active) * (_NOTIF_H + 8))
        toast.show_at(x, max(screen.top() + _MARGIN, y))
        self._active.append(toast)
        log.debug("Notification: %s — %s", title, body)

    def _on_dismissed(self, toast: _ToastWidget) -> None:
        if toast in self._active:
            self._active.remove(toast)
        toast.deleteLater()
        # Re-position remaining
        screen = QGuiApplication.primaryScreen().availableGeometry()
        for i, t in enumerate(self._active):
            y = screen.bottom() - _NOTIF_H - _MARGIN - i * (_NOTIF_H + 8)
            t.move(t.x(), max(screen.top() + _MARGIN, y))


# ── Convenience function ──────────────────────────────────────────────────────

def notify(icon: str, title: str, body: str = "",
           snooze_cb: Callable | None = None,
           duration_ms: int = 6000) -> None:
    """Call from anywhere. Uses the global NotificationQueue."""
    NotificationQueue.instance().push(icon, title, body, snooze_cb, duration_ms)
