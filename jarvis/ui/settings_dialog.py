"""
ui/settings_dialog.py — Slim settings dialog for JARVIS v2.

Only the 8 most-used settings are shown here.
All advanced settings live in advanced_settings.ini (opened via a button).
"""
from __future__ import annotations
import logging, os
from typing import TYPE_CHECKING
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QSlider, QCheckBox, QSpinBox,
    QPushButton, QFormLayout, QFrame,
)
if TYPE_CHECKING:
    from jarvis.config.settings import Settings

log = logging.getLogger(__name__)

_STYLE = """
QDialog,QWidget{background:rgba(8,18,42,210);color:#c0e8ff;
    font-family:'Segoe UI',Arial;font-size:13px;}
QLabel{color:#c0e8ff;}
QLabel#ttl{color:#00dcff;font-size:14px;font-weight:bold;background:transparent;}
QCheckBox{color:#c0e8ff;spacing:6px;}
QCheckBox::indicator{width:16px;height:16px;border:1px solid #00dcff;
    border-radius:3px;background:rgba(0,30,60,200);}
QCheckBox::indicator:checked{background:#00dcff;}
QSlider::groove:horizontal{background:rgba(0,30,60,200);height:6px;border-radius:3px;}
QSlider::handle:horizontal{background:#00dcff;width:16px;height:16px;
    border-radius:8px;margin:-5px 0;}
QSlider::sub-page:horizontal{background:rgba(0,200,255,120);border-radius:3px;}
QSpinBox{background:rgba(0,30,60,200);color:#00dcff;
    border:1px solid rgba(0,200,255,80);border-radius:6px;padding:4px 8px;min-width:70px;}
QPushButton{background:rgba(0,150,200,160);color:#fff;
    border:1px solid rgba(0,200,255,100);border-radius:8px;
    padding:6px 16px;font-weight:bold;}
QPushButton:hover{background:rgba(0,200,255,180);color:#000;}
QPushButton#adv{background:rgba(60,40,120,160);border-color:rgba(140,100,255,100);}
QPushButton#adv:hover{background:rgba(140,100,255,180);}
QPushButton#rst{background:rgba(80,20,20,160);border-color:rgba(200,60,60,100);}
QPushButton#rst:hover{background:rgba(200,60,60,160);}
QPushButton#ok{background:rgba(0,150,60,160);border-color:rgba(0,255,100,100);}
QPushButton#ok:hover{background:rgba(0,200,80,180);color:#000;}
QPushButton#cls{background:transparent;border:none;color:rgba(0,200,255,160);
    font-size:16px;padding:2px 6px;}
QPushButton#cls:hover{color:#ff4444;}
QFrame#div{color:rgba(0,200,255,50);}
"""


class SettingsDialog(QDialog):
    settings_changed = Signal()

    def __init__(self, settings: "Settings",
                 panels_always_on_top: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._s = settings
        self._drag_offset: QPoint | None = None
        self._dragging = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.apply_topmost(panels_always_on_top)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_STYLE)
        self.setFixedWidth(380)
        self._build()

    def apply_topmost(self, on: bool) -> None:
        f = self.windowFlags()
        f = (f | Qt.WindowType.WindowStaysOnTopHint) if on \
            else (f & ~Qt.WindowType.WindowStaysOnTopHint)
        vis = self.isVisible()
        self.setWindowFlags(f)
        if vis: self.show()

    # ── drag ──────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and \
                self._tb.geometry().contains(e.position().toPoint()):
            self._dragging = True
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._dragging and self._drag_offset:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._dragging = False

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        self._tb = QWidget()
        self._tb.setFixedHeight(42)
        self._tb.setCursor(Qt.CursorShape.SizeAllCursor)
        self._tb.setStyleSheet("QWidget{background:rgba(0,25,55,230);border-radius:12px 12px 0 0;}")
        tr = QHBoxLayout(self._tb)
        tr.setContentsMargins(14, 0, 10, 0)
        lbl = QLabel("⚙  JARVIS Settings")
        lbl.setObjectName("ttl")
        btn_cls = QPushButton("✕"); btn_cls.setObjectName("cls")
        btn_cls.setFixedSize(26, 26); btn_cls.clicked.connect(self.reject)
        tr.addWidget(lbl); tr.addStretch(); tr.addWidget(btn_cls)
        root.addWidget(self._tb)

        # Body
        body = QWidget()
        body.setStyleSheet("QWidget{background:rgba(8,18,42,210);border-radius:0 0 12px 12px;}")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 14, 18, 14)
        bl.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 1. Opacity
        self._op = QSlider(Qt.Orientation.Horizontal)
        self._op.setRange(20, 100)
        self._op.setValue(int(self._s.get("opacity", 0.9) * 100))
        self._lbl_op = QLabel(f"{self._op.value()}%")
        self._op.valueChanged.connect(lambda v: self._lbl_op.setText(f"{v}%"))
        row_op = QHBoxLayout(); row_op.addWidget(self._op); row_op.addWidget(self._lbl_op)
        form.addRow("Opacity:", row_op)

        # 2. Robot size
        self._sz = QSpinBox(); self._sz.setRange(60, 300)
        self._sz.setValue(self._s.get("robot_size", 120)); self._sz.setSuffix(" px")
        form.addRow("Robot size:", self._sz)

        # 3. Always on top (robot)
        self._aot = QCheckBox("Robot window always on top")
        self._aot.setChecked(self._s.get("always_on_top", True))
        form.addRow("", self._aot)

        # 4. Panels on top
        self._paot = QCheckBox("Chat & Settings always on top")
        self._paot.setChecked(self._s.get("panels_always_on_top", True))
        form.addRow("", self._paot)

        # 5. Auto movement
        self._mv = QCheckBox("Automatic movement")
        self._mv.setChecked(self._s.get("auto_movement", True))
        form.addRow("", self._mv)

        # 6. Animations
        self._an = QCheckBox("Enable animations")
        self._an.setChecked(self._s.get("animation_enabled", True))
        form.addRow("", self._an)

        # 7. Notifications
        self._no = QCheckBox("Desktop notifications")
        self._no.setChecked(self._s.get("notifications_enabled", True))
        form.addRow("", self._no)

        # 8. Wellness
        self._wl = QCheckBox("Wellness reminders")
        self._wl.setChecked(self._s.get("wellness_enabled", True))
        form.addRow("", self._wl)

        bl.addLayout(form)

        # Divider
        div = QFrame(); div.setObjectName("div")
        div.setFrameShape(QFrame.Shape.HLine)
        bl.addWidget(div)

        # Advanced config note
        note = QLabel("Advanced settings (FPS, speed, intervals…) are in the config file:")
        note.setStyleSheet("QLabel{color:rgba(180,180,255,160);font-size:10px;}")
        note.setWordWrap(True)
        bl.addWidget(note)

        btn_adv = QPushButton("📄  Open advanced_settings.ini")
        btn_adv.setObjectName("adv")
        btn_adv.clicked.connect(self._open_advanced)
        bl.addWidget(btn_adv)

        div2 = QFrame(); div2.setObjectName("div")
        div2.setFrameShape(QFrame.Shape.HLine)
        bl.addWidget(div2)

        # Bottom buttons
        brow = QHBoxLayout(); brow.setSpacing(8)
        btn_rst = QPushButton("↺ Reset All Defaults"); btn_rst.setObjectName("rst")
        btn_rst.clicked.connect(self._reset_all)
        btn_ok = QPushButton("✓ Apply & Close"); btn_ok.setObjectName("ok")
        btn_ok.clicked.connect(self._apply)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_rst); brow.addStretch()
        brow.addWidget(btn_cancel); brow.addWidget(btn_ok)
        bl.addLayout(brow)

        root.addWidget(body)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _open_advanced(self) -> None:
        from jarvis.config.advanced_config import AdvancedConfig
        p = AdvancedConfig().path
        os.startfile(p)  # type: ignore[attr-defined]

    def _reset_all(self) -> None:
        from jarvis.config.advanced_config import AdvancedConfig
        AdvancedConfig().reset_to_defaults()
        self._s.reset_to_defaults()
        self._s.save()
        self.settings_changed.emit()
        self.reject()

    def _apply(self) -> None:
        s = self._s
        s.set("opacity",              self._op.value() / 100.0)
        s.set("robot_size",           self._sz.value())
        s.set("always_on_top",        self._aot.isChecked())
        s.set("panels_always_on_top", self._paot.isChecked())
        s.set("auto_movement",        self._mv.isChecked())
        s.set("animation_enabled",    self._an.isChecked())
        s.set("notifications_enabled",self._no.isChecked())
        s.set("wellness_enabled",     self._wl.isChecked())
        s.save()
        self.settings_changed.emit()
        self.accept()
