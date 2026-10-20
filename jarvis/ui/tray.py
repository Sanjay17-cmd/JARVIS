"""
ui/tray.py — System tray icon and menu for JARVIS.

Features:
  • Tray icon generated programmatically (cyan J on dark background)
  • Menu: Show, Hide, Pause/Resume, Settings, Exit
  • Double-click: show overlay
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QBrush
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from jarvis.core.state import RobotState

if TYPE_CHECKING:
    from jarvis.core.state import StateManager
    from jarvis.core.event_bus import EventBus

log = logging.getLogger(__name__)


def _make_tray_icon(size: int = 64) -> QIcon:
    """Programmatically generate a tray icon: cyan 'J' on dark background."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Background circle
    p.setBrush(QColor(8, 20, 50, 230))
    p.setPen(QColor(0, 200, 255, 200))
    p.drawEllipse(2, 2, size - 4, size - 4)
    # Letter J
    font = QFont("Segoe UI", size // 2, QFont.Weight.Bold)
    p.setFont(font)
    p.setPen(QColor(0, 220, 255))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "J")
    p.end()
    return QIcon(px)


class TrayManager(QObject):
    """Manages the system tray icon and its menu actions."""

    show_requested    = Signal()
    hide_requested    = Signal()
    settings_requested = Signal()
    exit_requested    = Signal()
    pause_requested   = Signal()

    def __init__(
        self,
        state_manager: "StateManager",
        event_bus: "EventBus",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._state_manager = state_manager
        self._event_bus = event_bus

        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("System tray not available on this desktop.")
            self._tray = None
            return

        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon())
        self._tray.setToolTip("JARVIS — Desktop AI Companion")

        self._menu = QMenu()
        self._menu.setStyleSheet("""
            QMenu {
                background-color: rgba(10, 20, 45, 230);
                color: #00dcff;
                border: 1px solid rgba(0, 200, 255, 120);
                border-radius: 8px;
                padding: 4px;
                font-family: 'Segoe UI', Arial;
                font-size: 13px;
            }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: rgba(0, 200, 255, 60); }
            QMenu::separator { height: 1px; background: rgba(0,200,255,60); margin: 3px 8px; }
        """)

        self._act_show    = self._menu.addAction("👁  Show JARVIS")
        self._act_hide    = self._menu.addAction("🙈  Hide JARVIS")
        self._menu.addSeparator()
        self._act_pause   = self._menu.addAction("⏸  Pause")
        self._act_settings = self._menu.addAction("⚙  Settings")
        self._menu.addSeparator()
        self._act_exit    = self._menu.addAction("❌  Exit")

        self._act_show.triggered.connect(self.show_requested)
        self._act_hide.triggered.connect(self.hide_requested)
        self._act_pause.triggered.connect(self.pause_requested)
        self._act_settings.triggered.connect(self.settings_requested)
        self._act_exit.triggered.connect(self.exit_requested)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

        state_manager.add_listener(self._on_state_change)

    def show(self) -> None:
        if self._tray:
            self._tray.show()

    def hide(self) -> None:
        if self._tray:
            self._tray.hide()

    def show_message(self, title: str, msg: str) -> None:
        if self._tray:
            self._tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 3000)

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_requested.emit()

    def _on_state_change(self, old: RobotState, new: RobotState) -> None:
        if self._tray is None:
            return
        paused = new is RobotState.PAUSED
        self._act_pause.setText("▶  Resume" if paused else "⏸  Pause")
        tip = f"JARVIS — {new.name}"
        self._tray.setToolTip(tip)
