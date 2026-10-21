"""
ui/settings_dialog.py — Slim settings dialog for JARVIS v2.

Only the 8 most-used settings are shown here.
All advanced settings live in advanced_settings.ini (opened via a button).
"""
from __future__ import annotations
import logging, os
from typing import TYPE_CHECKING
from PySide6.QtCore import Qt, Signal, QPoint, QTimer
from PySide6.QtGui import QMouseEvent, QPainter, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QSlider, QCheckBox, QSpinBox, QLineEdit,
    QPushButton, QFormLayout, QFrame, QScrollArea, QComboBox,
    QTabWidget,
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
                 behavior=None,
                 router=None,
                 voice_controller=None,
                 overlay=None,
                 ai_gateway=None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._s = settings
        self._behavior = behavior
        self._router = router
        self._voice = voice_controller
        self._overlay = overlay
        self._ai_gateway = ai_gateway
        self._drag_offset: QPoint | None = None
        self._dragging = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.apply_topmost(panels_always_on_top)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_STYLE)
        self.setFixedWidth(440)
        self._build()
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, self._s)

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

        self._sections = QTabWidget()
        self._section_forms = {}
        for title in ("General", "Notifications", "AI & Voice", "Focus & Tools"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_form = QFormLayout()
            page_form.setSpacing(12)
            page_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            page_layout.addLayout(page_form)
            page_layout.addStretch()
            self._sections.addTab(page, title)
            self._section_forms[title] = page_form
        form = self._section_forms["General"]

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
        form = self._section_forms["Notifications"]
        self._no = QCheckBox("Desktop notifications")
        self._no.setChecked(self._s.get("notifications_enabled", True))
        form.addRow("", self._no)
        self._notification_category_controls = {}
        for key, label in (
            ("notification_reminders", "Reminder and task notifications"),
            ("notification_alarms", "Alarm notifications"),
            ("notification_focus", "Focus notifications"),
            ("notification_wellness", "Wellness notifications"),
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(self._s.get(key, True))
            checkbox.setEnabled(self._no.isChecked())
            self._no.toggled.connect(checkbox.setEnabled)
            form.addRow("", checkbox)
            self._notification_category_controls[key] = checkbox
        self._alarm_sound = QCheckBox("Play sound for alarms")
        self._alarm_sound.setChecked(self._s.get("sound_enabled", False))
        form.addRow("", self._alarm_sound)

        # 8. Wellness
        self._wl = QCheckBox("Wellness reminders")
        self._wl.setChecked(self._s.get("wellness_enabled", True))
        form.addRow("", self._wl)
        from jarvis.config.advanced_config import AdvancedConfig
        adv = AdvancedConfig()
        self._wellness_controls = {}
        for key, title, setting_key, interval_key, default_minutes in (
            ("hydration", "Water reminders", "wellness_hydration_enabled", "wellness_hydration_interval_seconds", 60),
            ("stretch", "Stretch reminders", "wellness_stretch_enabled", "wellness_stretch_interval_seconds", 60),
            ("eyerest", "Eye-rest reminders", "wellness_eyerest_enabled", "wellness_eyerest_interval_seconds", 20),
        ):
            enabled = QCheckBox(title)
            enabled.setChecked(self._s.get(setting_key, key == "hydration"))
            interval = QSpinBox()
            interval.setRange(5, 172800)
            interval.setSuffix(" sec")
            saved_interval = int(self._s.get(interval_key, 0))
            if saved_interval <= 0:
                saved_interval = int(adv.get(f"wellness_{key}_interval", default_minutes) * 60)
            interval.setValue(saved_interval)
            row = QHBoxLayout()
            row.addWidget(enabled)
            row.addStretch()
            row.addWidget(interval)
            form.addRow("", row)
            self._wellness_controls[key] = (enabled, interval, setting_key, interval_key)

        form = self._section_forms["AI & Voice"]
        self._ai_enabled = QCheckBox("Enable AI trigger prefix")
        self._ai_enabled.setChecked(self._s.get("ai_trigger_enabled", True))
        form.addRow("", self._ai_enabled)
        ai_pipeline = QPushButton("Open AI Pipeline Settings")
        ai_pipeline.clicked.connect(self._open_ai_pipeline)
        form.addRow("AI provider & models:", ai_pipeline)
        self._ai_keyword = QLineEdit(str(self._s.get("ai_trigger_keyword", "Friday")))
        self._ai_keyword.setPlaceholderText("Friday")
        form.addRow("AI Trigger Keyword:", self._ai_keyword)
        self._ai_aliases = QLineEdit(
            ", ".join(self._s.get("ai_trigger_aliases", []))
        )
        self._ai_aliases.setPlaceholderText("Optional aliases, separated by commas")
        form.addRow("Aliases:", self._ai_aliases)
        self._tts_enabled = QCheckBox("Speak all assistant responses")
        self._tts_enabled.setChecked(self._s.get("tts_enabled", False))
        form.addRow("", self._tts_enabled)
        voice_setup = QPushButton("Voice input and voice selection…")
        voice_setup.clicked.connect(self._open_voice)
        form.addRow("Voice:", voice_setup)
        ai_note = _MarqueeLabel(
            "Configured trigger words at the start of a message always use the AI pipeline."
        )
        ai_note.setStyleSheet("QLabel{color:rgba(180,180,255,160);font-size:10px;}")
        form.addRow("", ai_note)

        form = self._section_forms["Focus & Tools"]
        self._focus_duration = QSpinBox()
        self._focus_duration.setRange(1, 240)
        self._focus_duration.setSuffix(" min")
        self._focus_duration.setValue(self._s.get("focus_duration_minutes", 25))
        form.addRow("Focus session:", self._focus_duration)
        self._focus_nudges = QCheckBox("Nudge only for configured distracting apps")
        self._focus_nudges.setChecked(
            self._s.get("focus_distraction_nudge", False)
        )
        form.addRow("", self._focus_nudges)
        self._focus_cooldown = QSpinBox()
        self._focus_cooldown.setRange(1, 120)
        self._focus_cooldown.setSuffix(" min")
        self._focus_cooldown.setValue(
            self._s.get("focus_nudge_cooldown_minutes", 10)
        )
        form.addRow("Nudge cooldown:", self._focus_cooldown)
        bl.addWidget(self._sections)

        # Divider
        div = QFrame(); div.setObjectName("div")
        div.setFrameShape(QFrame.Shape.HLine)
        bl.addWidget(div)

        # Advanced config note
        note = _MarqueeLabel(
            "Advanced settings (FPS, speed, intervals) are in the config file:"
        )
        note.setStyleSheet("QLabel{color:rgba(180,180,255,160);font-size:10px;}")
        bl.addWidget(note)

        btn_adv = QPushButton("📄  Open advanced_settings.ini")
        btn_adv.setObjectName("adv")
        btn_adv.clicked.connect(self._open_advanced)
        bl.addWidget(btn_adv)

        tool_actions = (
            ("Behavior & Responses", self._open_behavior),
            ("Focus App Rules", self._open_focus_rules),
            ("Robot Appearance", self._open_animations),
            ("Tasks", self._open_tasks),
            ("Reminders & Alarms", self._open_reminders),
        )
        for offset in range(0, len(tool_actions), 2):
            row = QHBoxLayout()
            for label, callback in tool_actions[offset:offset + 2]:
                button = QPushButton(label)
                button.clicked.connect(callback)
                row.addWidget(button)
            bl.addLayout(row)

        div2 = QFrame(); div2.setObjectName("div")
        div2.setFrameShape(QFrame.Shape.HLine)
        bl.addWidget(div2)

        chest_legend = _MarqueeLabel(
            "Chest lights: Purple = Voice • Blue = Focus • Amber = Reminders • "
            "Pink = Actions • Cyan = listening • Red = muted / reminder due • "
            "Green = Focus active. Click a light to use its function."
        )
        chest_legend.setStyleSheet(
            "QLabel{color:#fff0bd;font-size:10px;"
            "background:rgba(35,24,8,150);border-radius:6px;padding:3px;}"
        )
        chest_legend.setAccessibleName(
            "Chest button color legend: purple voice, blue focus, amber reminders, "
            "pink actions, cyan listening, red muted or reminder due, green focus active."
        )
        bl.addWidget(chest_legend)

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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        scroll.setMinimumHeight(400)
        scroll.setMaximumHeight(650)
        root.addWidget(scroll)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _open_advanced(self) -> None:
        from jarvis.config.advanced_config import AdvancedConfig
        p = AdvancedConfig().path
        os.startfile(p)  # type: ignore[attr-defined]

    def _open_ai_pipeline(self) -> None:
        from jarvis.ui.ai_pipeline_dialog import AIPipelineDialog
        dialog = AIPipelineDialog(self._s, self, gateway=self._ai_gateway)
        dialog.settings_changed.connect(self.settings_changed.emit)
        dialog.exec()

    def _open_behavior(self) -> None:
        if self._behavior is None or self._router is None:
            return
        from jarvis.ui.behavior_config_dialog import BehaviorConfigDialog
        BehaviorConfigDialog(self._behavior, self._router, self).exec()

    def _open_voice(self) -> None:
        if self._voice is None:
            return
        from jarvis.ui.voice_setup_dialog import VoiceSetupDialog
        VoiceSetupDialog(self._s, self._voice, self).exec()
        self._tts_enabled.setChecked(self._s.get("tts_enabled", False))

    def _open_focus_rules(self) -> None:
        from jarvis.ui.focus_rules_dialog import FocusRulesDialog
        FocusRulesDialog(self._s, self).exec()

    def _open_animations(self) -> None:
        if self._overlay is None:
            return
        from jarvis.ui.animation_gallery_dialog import AnimationGalleryDialog
        AnimationGalleryDialog(self._overlay, self).exec()

    def _open_tasks(self) -> None:
        from jarvis.ui.task_dialog import TaskDialog
        TaskDialog(self._s.get("panels_always_on_top", True), self).exec()

    def _open_reminders(self) -> None:
        from jarvis.ui.reminders_dialog import RemindersDialog
        RemindersDialog(self._s.get("panels_always_on_top", True), self).exec()

    def _reset_all(self) -> None:
        from jarvis.config.advanced_config import AdvancedConfig
        credentials = self._s.get("ai_credentials", [])
        AdvancedConfig().reset_to_defaults()
        self._s.reset_to_defaults()
        self._s.set("ai_credentials", credentials)
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
        for key, checkbox in self._notification_category_controls.items():
            s.set(key, checkbox.isChecked())
        s.set("sound_enabled", self._alarm_sound.isChecked())
        s.set("tts_enabled", self._tts_enabled.isChecked())
        s.set("wellness_enabled",     self._wl.isChecked())
        for enabled, interval, setting_key, interval_key in self._wellness_controls.values():
            s.set(setting_key, enabled.isChecked())
            s.set(interval_key, interval.value())
        keyword = self._ai_keyword.text().strip()
        s.set("ai_trigger_enabled", self._ai_enabled.isChecked())
        s.set("ai_trigger_keyword", keyword or "Friday")
        s.set(
            "ai_trigger_aliases",
            [item.strip() for item in self._ai_aliases.text().split(",") if item.strip()],
        )
        s.set("focus_duration_minutes", self._focus_duration.value())
        s.set("focus_distraction_nudge", self._focus_nudges.isChecked())
        s.set("focus_nudge_cooldown_minutes", self._focus_cooldown.value())
        s.save()
        self.settings_changed.emit()
        self.accept()


class _MarqueeLabel(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self._offset = 0
        self.setMinimumHeight(22)
        self.setToolTip(text)
        self._timer = QTimer(self)
        self._timer.setInterval(35)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._offset += 1
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QColor(180, 180, 255, 200))
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(self._text)
        gap = max(32, self.width() // 5)
        cycle = text_width + gap
        if cycle <= 0:
            return
        x = -(self._offset % cycle)
        while x < self.width():
            painter.drawText(x, (self.height() + metrics.ascent() - metrics.descent()) // 2, self._text)
            x += cycle
        painter.end()
