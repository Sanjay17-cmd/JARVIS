"""Preview the robot's distinct built-in animations."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout


class AnimationGalleryDialog(QDialog):
    def __init__(self, overlay, parent=None) -> None:
        super().__init__(parent)
        self._overlay = overlay
        self.setWindowTitle("Robot Appearance")
        self.setMinimumWidth(420)
        self.setStyleSheet(
            "QDialog,QWidget{background:rgba(8,18,42,235);color:#c0e8ff;"
            "font-family:'Segoe UI',Arial;font-size:12px;}"
            "QPushButton{background:rgba(0,150,200,160);color:white;"
            "border:1px solid rgba(0,200,255,100);border-radius:6px;padding:8px;}"
        )
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select an animation to preview on the desktop robot."))
        grid = QGridLayout()
        animations = (
            ("Wave", "wave"), ("Flying / Jetpack", "flying"),
            ("Repair Tools", "tools"), ("Scanning Beam", "scanning"),
            ("Holographic Keyboard", "typing"), ("Water Reminder", "thirsty"),
            ("Focus", "focus"), ("Urgent Alarm", "alarm"),
            ("Confused", "confused"), ("Celebrate", "success"),
        )
        for index, (label, name) in enumerate(animations):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, key=name: self._preview(key))
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, getattr(overlay, "_settings", None))

    def _preview(self, name: str) -> None:
        if not self._overlay.play_animation(name, duration_ms=4000):
            self.setWindowTitle(f"Animation unavailable: {name}")
