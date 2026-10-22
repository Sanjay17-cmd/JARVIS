import base64
import json

from jarvis.ai.image_generation import generate_image


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_openrouter_image_request_decodes_image_and_reports_cost(monkeypatch):
    raw_image = b"image-bytes"
    requests = []

    class ModelResponse(_Response):
        def read(self):
            return json.dumps({
                "data": [{
                    "id": "test/image:free",
                    "name": "Free test image model",
                    "architecture": {"output_modalities": ["image"]},
                    "pricing": {"prompt": "0", "image_output": "0"},
                }]
            }).encode("utf-8")

    monkeypatch.setattr(
        "jarvis.ai.image_generation.urllib.request.urlopen",
        lambda request, timeout: (
            requests.append((request, timeout))
            or (
                ModelResponse({})
                if request.full_url.endswith("?output_modalities=image")
                else _Response({
                "data": [{
                    "b64_json": base64.b64encode(raw_image).decode("ascii"),
                    "media_type": "image/png",
                }],
                "usage": {"cost": 0},
                })
            )
        ),
    )

    result = generate_image(
        "A peacock in a garden",
        "test-key",
        "test/image:free",
        timeout=45,
    )

    request, timeout = requests[1]
    assert request.full_url == "https://openrouter.ai/api/v1/images"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert json.loads(request.data) == {
        "model": "test/image:free",
        "prompt": "A peacock in a garden",
    }
    assert timeout == 45
    assert result.content == raw_image
    assert result.media_type == "image/png"
    assert result.cost_usd == 0


def test_openrouter_image_request_reports_missing_credentials():
    from jarvis.ai.image_generation import ImageGenerationError

    try:
        generate_image("A peacock", "", "qwen/qwen-image-2.1-turbo")
    except ImageGenerationError as exc:
        assert "No OpenRouter API key" in str(exc)
    else:
        raise AssertionError("Expected missing OpenRouter credentials to fail.")


def test_openrouter_image_request_rejects_invalid_image_data(monkeypatch):
    from jarvis.ai.image_generation import ImageGenerationError

    def fake_urlopen(request, **_kwargs):
        if request.full_url.endswith("?output_modalities=image"):
            return _Response({
                "data": [{
                    "id": "test/image:free",
                    "architecture": {"output_modalities": ["image"]},
                    "pricing": {"prompt": "0", "image_output": "0"},
                }]
            })
        return _Response({"data": [{"b64_json": "%%%"}]})

    monkeypatch.setattr("jarvis.ai.image_generation.urllib.request.urlopen", fake_urlopen)
    try:
        generate_image("A peacock", "test-key", "test/image:free")
    except ImageGenerationError as exc:
        assert "invalid base64" in str(exc)
    else:
        raise AssertionError("Expected invalid image data to fail.")


def test_image_generation_blocks_paid_or_unverified_models(monkeypatch):
    from jarvis.ai.image_generation import ImageGenerationError

    requests = []

    def fake_urlopen(request, **_kwargs):
        requests.append(request.full_url)
        return _Response({
            "data": [{
                "id": "google/gemini-nano-banana-2.1",
                "name": "Google Nano Banana",
                "architecture": {"output_modalities": ["image", "text"]},
                "pricing": {"prompt": "0.0000015", "image_output": "0.00003"},
            }]
        })

    monkeypatch.setattr("jarvis.ai.image_generation.urllib.request.urlopen", fake_urlopen)
    try:
        generate_image(
            "A peacock",
            "test-key",
            "google/gemini-nano-banana-2.1",
        )
    except ImageGenerationError as exc:
        assert "zero-priced image model" in str(exc)
        assert "No image request was sent" in str(exc)
    else:
        raise AssertionError("Paid Nano Banana model must be rejected.")

    assert requests == [
        "https://openrouter.ai/api/v1/models?output_modalities=image"
    ]


def test_free_image_catalog_filters_by_image_modality_and_all_zero_prices(monkeypatch):
    from jarvis.ai.image_generation import list_free_image_models

    monkeypatch.setattr(
        "jarvis.ai.image_generation.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({
            "data": [
                {
                    "id": "provider/image:free",
                    "name": "Free Image",
                    "architecture": {"output_modalities": ["image"]},
                    "pricing": {"prompt": "0", "image_output": "0"},
                },
                {
                    "id": "provider/paid-image",
                    "name": "Paid Image",
                    "architecture": {"output_modalities": ["image"]},
                    "pricing": {"prompt": "0", "image_output": "0.01"},
                },
                {
                    "id": "provider/free-text:free",
                    "name": "Free Text",
                    "architecture": {"output_modalities": ["text"]},
                    "pricing": {"prompt": "0", "completion": "0"},
                },
            ]
        }),
    )

    assert list_free_image_models() == [
        {"id": "provider/image:free", "name": "Free Image", "free": True}
    ]


def test_image_dialog_previews_saves_and_confirms_clipboard_copy(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QMessageBox
    from jarvis.ai.image_generation import GeneratedImage
    from jarvis.ui.image_creation_dialog import ImageCreationDialog

    class Settings:
        def get(self, key, default=None):
            return default

        def set(self, *_args):
            pass

        def save(self):
            pass

    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFF00FFFF)
    buffer = QBuffer()
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    content = bytes(buffer.data())

    monkeypatch.setattr(
        ImageCreationDialog,
        "_image_directory",
        staticmethod(lambda: tmp_path),
    )
    monkeypatch.setattr(ImageCreationDialog, "_load_models", lambda _self: None)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog = ImageCreationDialog(None, Settings())
    qtbot.addWidget(dialog)
    dialog._catalog_thread = None
    dialog._on_generated(GeneratedImage(content, "image/png", 0.01))

    assert dialog._saved_path is not None
    assert dialog._saved_path.read_bytes() == content
    assert dialog._copy.isEnabled()
    dialog._copy_image()
    assert not QApplication.clipboard().image().isNull()
    assert "copied to the clipboard" in dialog._status.text()
    dialog.close()
