"""Chat-panel image generation and local image management."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QComboBox,
)

from jarvis.ai.image_generation import (
    GeneratedImage,
    ImageGenerationError,
    generate_image,
    list_free_image_models,
)

log = logging.getLogger(__name__)


class _ImageWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, prompt: str, api_key: str, model: str) -> None:
        super().__init__()
        self._prompt = prompt
        self._api_key = api_key
        self._model = model

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(
                generate_image(self._prompt, self._api_key, self._model)
            )
        except ImageGenerationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            log.exception("Unexpected image generation failure")
            self.failed.emit(f"Image generation failed: {exc}")


class _CatalogWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(list_free_image_models())
        except ImageGenerationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            log.exception("Unexpected free image model catalogue failure")
            self.failed.emit(f"Could not load free image models: {exc}")


class ImageCreationDialog(QDialog):
    def __init__(self, ai_gateway, settings, parent=None) -> None:
        super().__init__(parent)
        self._gateway = ai_gateway
        self._settings = settings
        self._image: GeneratedImage | None = None
        self._thread: QThread | None = None
        self._worker: _ImageWorker | None = None
        self._catalog_thread: QThread | None = None
        self._catalog_worker: _CatalogWorker | None = None
        self._saved_path: Path | None = None
        self.setWindowTitle("Create an Image")
        self.setMinimumSize(520, 570)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Describe the image you want to create:"))
        self._prompt = QPlainTextEdit()
        self._prompt.setPlaceholderText(
            "Example: A colorful illustration of a peacock in a South Indian garden"
        )
        self._prompt.setMaximumHeight(100)
        layout.addWidget(self._prompt)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Free image model:"))
        self._model = QComboBox()
        self._model.setMinimumWidth(250)
        model_row.addWidget(self._model, 1)
        self._refresh_models = QPushButton("Refresh")
        self._refresh_models.clicked.connect(self._load_models)
        model_row.addWidget(self._refresh_models)
        layout.addLayout(model_row)

        billing = QLabel(
            'Only models marked :free with zero listed prices are enabled. The '
            'catalogue is checked again before each request. See '
            '<a href="https://openrouter.ai/models?output_modalities=image">'
            "OpenRouter's live image model catalogue</a>."
        )
        billing.setWordWrap(True)
        billing.setOpenExternalLinks(True)
        layout.addWidget(billing)

        self._preview = QLabel("Generated image preview will appear here")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(480, 300)
        self._preview.setStyleSheet(
            "QLabel{background:rgba(0,20,45,180);border:1px solid "
            "rgba(0,200,255,100);border-radius:8px;padding:6px;}"
        )
        layout.addWidget(self._preview, 1)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._generate = QPushButton("Generate")
        self._generate.setEnabled(False)
        self._generate.clicked.connect(self._generate_image)
        self._copy = QPushButton("Copy Image")
        self._copy.setEnabled(False)
        self._copy.clicked.connect(self._copy_image)
        self._save = QPushButton("Save As…")
        self._save.setEnabled(False)
        self._save.clicked.connect(self._save_as)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self._generate)
        buttons.addWidget(self._copy)
        buttons.addWidget(self._save)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.resize(600, 700)
        self._load_models()

    def _load_models(self) -> None:
        if self._catalog_thread is not None or self._thread is not None:
            return
        self._refresh_models.setEnabled(False)
        self._generate.setEnabled(False)
        self._status.setText("Checking OpenRouter for free image models…")
        thread = QThread(self)
        worker = _CatalogWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_models_loaded)
        worker.failed.connect(self._on_models_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_catalog_thread_finished)
        self._catalog_thread = thread
        self._catalog_worker = worker
        thread.start()

    @Slot(object)
    def _on_models_loaded(self, models: list[dict[str, str]]) -> None:
        previous = str(self._settings.get("image_generation_model", ""))
        self._model.clear()
        for model in models:
            self._model.addItem(f"{model['name']} ({model['id']})", model["id"])
        if previous:
            index = self._model.findData(previous)
            if index >= 0:
                self._model.setCurrentIndex(index)
        self._generate.setEnabled(bool(models))
        if models:
            self._status.setText(
                f"Found {len(models)} verified free image model(s). "
                "Pricing will be rechecked before generation."
            )
        else:
            self._settings.set("image_generation_model", "")
            self._settings.save()
            self._status.setText(
                "OpenRouter currently lists no image-generation models that "
                "are explicitly free with zero charges. No paid model will be used."
            )

    @Slot(str)
    def _on_models_failed(self, message: str) -> None:
        self._status.setText(message + " No image request will be sent.")

    def _on_catalog_thread_finished(self) -> None:
        thread = self._catalog_thread
        self._catalog_thread = None
        self._catalog_worker = None
        self._refresh_models.setEnabled(True)
        if thread is not None:
            thread.deleteLater()

    def _generate_image(self) -> None:
        prompt = self._prompt.toPlainText().strip()
        if not prompt:
            self._status.setText("Enter an image description first.")
            return
        model = str(self._model.currentData() or "")
        if not model:
            self._status.setText(
                "No verified free image model is selected; no request was sent."
            )
            return
        self._settings.set("image_generation_model", model)
        self._settings.save()
        if self._gateway is None:
            self._status.setText("OpenRouter is not configured in AI Pipeline Settings.")
            return
        try:
            api_key = self._gateway.get_api_key("openrouter")
        except Exception as exc:
            log.exception("Could not retrieve the OpenRouter credential")
            self._status.setText(f"Could not access the secure OpenRouter key: {exc}")
            return
        if not api_key:
            self._status.setText(
                "No OpenRouter key found. Add/enable it in Settings → AI Pipeline Settings."
            )
            return

        self._generate.setEnabled(False)
        self._copy.setEnabled(False)
        self._save.setEnabled(False)
        self._refresh_models.setEnabled(False)
        self._status.setText("Verifying free model and generating with OpenRouter…")
        thread = QThread(self)
        worker = _ImageWorker(prompt, api_key, model)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_generated)
        worker.failed.connect(self._on_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(object)
    def _on_generated(self, image: GeneratedImage) -> None:
        preview = QImage.fromData(image.content)
        if preview.isNull():
            self._on_failed(
                f"OpenRouter returned unsupported image data ({image.media_type})."
            )
            return
        self._image = image
        pixmap = preview.scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(QPixmap.fromImage(pixmap))
        self._copy.setEnabled(True)
        self._save.setEnabled(True)
        details = "Image generated."
        if image.cost_usd is not None:
            details += f" Provider-reported cost: ${image.cost_usd:.4f}."
        try:
            self._saved_path = self._save_generated(image)
            details += f" Saved to {self._saved_path}"
        except OSError as exc:
            self._saved_path = None
            log.exception("Could not save generated image automatically")
            details += f" Automatic save failed: {exc}. Use Save As…"
        self._status.setText(details)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._status.setText(message)

    def _on_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        self._generate.setEnabled(True)
        self._refresh_models.setEnabled(True)
        if thread is not None:
            thread.deleteLater()

    @staticmethod
    def _image_directory() -> Path:
        app_data = Path(
            os.environ.get("APPDATA")
            or Path.home() / "AppData" / "Roaming"
        )
        return app_data / "JARVIS" / "generated_images"

    @staticmethod
    def _extension(media_type: str) -> str:
        return {
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
        }.get(media_type, ".png")

    def _save_generated(self, image: GeneratedImage) -> Path:
        directory = self._image_directory()
        directory.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("jarvis_image_%Y%m%d_%H%M%S_%f")
        target = directory / f"{filename}{self._extension(image.media_type)}"
        target.write_bytes(image.content)
        return target

    def _copy_image(self) -> None:
        if self._image is None:
            return
        answer = QMessageBox.question(
            self,
            "Copy image to clipboard",
            "Copy this generated image to the system clipboard?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        image = QImage.fromData(self._image.content)
        if image.isNull():
            QMessageBox.warning(self, "Clipboard copy failed", "The image could not be decoded.")
            return
        QApplication.clipboard().setImage(image)
        self._status.setText("Generated image copied to the clipboard.")

    def _save_as(self) -> None:
        if self._image is None:
            return
        initial = str(self._saved_path or self._image_directory())
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save generated image",
            initial,
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg);;WebP image (*.webp);;All files (*)",
        )
        if not path:
            return
        try:
            target = Path(path)
            target.write_bytes(self._image.content)
        except OSError as exc:
            QMessageBox.critical(self, "Image save failed", str(exc))
            return
        self._saved_path = target
        self._status.setText(f"Image saved to {target}")

    def reject(self) -> None:
        if self._thread is not None or self._catalog_thread is not None:
            self._status.setText(
                "Please wait for the current image request to finish before closing."
            )
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None or self._catalog_thread is not None:
            self._status.setText(
                "Please wait for the current image request to finish before closing."
            )
            event.ignore()
            return
        super().closeEvent(event)
