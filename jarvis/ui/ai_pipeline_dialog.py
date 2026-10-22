"""Settings for the provider-independent AI gateway."""
from __future__ import annotations

import uuid
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jarvis.ai import store
from jarvis.ai.gateway import AIGateway
from jarvis.config.credential_store import CredentialStore, mask_secret

_PROVIDERS = (
    ("Gemini", "gemini", "gemini-2.5-flash"),
    ("OpenRouter", "openrouter", ""),
    ("Grok (xAI)", "grok", ""),
    ("Groq", "groq", ""),
)


class AIPipelineDialog(QDialog):
    settings_changed = Signal()

    def __init__(self, settings, parent: QWidget | None = None, gateway=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._gateway = gateway or AIGateway(settings)
        self._credential_store: CredentialStore | None = None
        self._provider_options = list(_PROVIDERS)
        if settings.get("ai_primary_provider") == "openai":
            self._provider_options.append((
                "OpenAI (legacy)", "openai",
                str(settings.get("ai_primary_model") or settings.get("ai_model", "")),
            ))
        self.setWindowTitle("JARVIS AI Pipeline")
        self.resize(620, 760)
        self.setStyleSheet(
            "QDialog,QWidget{background:#09152c;color:#c8eaff;font:13px 'Segoe UI';}"
            "QComboBox,QSpinBox,QListWidget,QLineEdit{background:#102440;"
            "color:#e5f7ff;border:1px solid #286080;padding:5px;}"
            "QPushButton{background:#087aa0;color:white;border:0;padding:7px 12px;"
            "border-radius:5px;} QPushButton:hover{background:#00a6ce;}"
        )
        self._build()
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, settings)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        root = QVBoxLayout(content)
        form = QFormLayout()
        self.provider = QComboBox()
        for label, provider_id, _model in self._provider_options:
            self.provider.addItem(label, provider_id)
        current_provider = self._settings.get("ai_primary_provider", "gemini")
        index = self.provider.findData(current_provider)
        self.provider.setCurrentIndex(max(0, index))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.credential = QComboBox()
        self.environment_name = QLineEdit(
            str(self._settings.get("ai_api_key_env_var", ""))
        )
        self.environment_name.setPlaceholderText("Provider default environment variable")
        self.provider_enabled: dict[str, QCheckBox] = {}
        provider_checks = QHBoxLayout()
        enabled_config = self._settings.get("ai_provider_enabled", {})
        for label, provider_id, _model in self._provider_options:
            checkbox = QCheckBox(label)
            checkbox.setChecked(enabled_config.get(provider_id, True))
            self.provider_enabled[provider_id] = checkbox
            provider_checks.addWidget(checkbox)
        self.free_only = QCheckBox("Filter model list to free OpenRouter models")
        self.free_only.setChecked(self._settings.get("ai_free_models_only", False))
        self.free_chat_only = QCheckBox(
            "Free-only chat (uncheck to choose Gemini, Groq, or another provider)"
        )
        self.free_chat_only.setChecked(
            self._settings.get("ai_chat_free_only", True)
        )
        self.free_chat_only.toggled.connect(self._apply_free_chat_mode)
        self.advanced_enabled = QCheckBox("Use advanced model for complex requests")
        self.advanced_enabled.setChecked(
            self._settings.get("ai_advanced_route_enabled", False)
        )
        self.advanced_model = QLineEdit(
            str(self._settings.get("ai_advanced_model", ""))
        )
        self.advanced_model.setPlaceholderText("Optional model ID for this provider")
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.free_only.toggled.connect(self._load_models)
        form.addRow("Primary provider:", self.provider)
        form.addRow("Primary model:", self.model)
        form.addRow("Primary credential:", self.credential)
        form.addRow("Environment key variable:", self.environment_name)
        form.addRow("Enabled providers:", provider_checks)
        form.addRow("", self.free_only)
        form.addRow("", self.free_chat_only)
        form.addRow(
            "",
            QLabel(
                "Free-only chat ignores other providers, paid models, advanced "
                "routing, and fallback routes. Groq is available when this mode "
                "is disabled; its API catalogue does not declare zero-priced models."
            ),
        )
        form.addRow("", self.advanced_enabled)
        form.addRow("Advanced model:", self.advanced_model)

        refresh = QPushButton("Refresh Models")
        refresh.clicked.connect(self._refresh_models)
        form.addRow("", refresh)

        self.fallback_enabled = QCheckBox("Enable ordered fallback providers")
        self.fallback_enabled.setChecked(self._settings.get("ai_fallback_enabled", True))
        form.addRow("", self.fallback_enabled)
        self.free_only.toggled.connect(self._load_models)

        root.addLayout(form)
        root.addWidget(QLabel("Fallback order (top to bottom):"))
        self.fallbacks = QListWidget()
        root.addWidget(self.fallbacks)
        fallback_controls = QHBoxLayout()
        self._fallback_buttons: list[QPushButton] = []
        for label, callback in (
            ("Add", self._add_fallback),
            ("Remove", self._remove_fallback),
            ("Move up", lambda: self._move_fallback(-1)),
            ("Move down", lambda: self._move_fallback(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            self._fallback_buttons.append(button)
            fallback_controls.addWidget(button)
        root.addLayout(fallback_controls)
        self._load_fallbacks()

        limits = QFormLayout()
        self.retries = self._spin(0, 5, "ai_max_retries", 1)
        self.timeout = self._spin(5, 300, "ai_timeout", 30)
        self.output_tokens = self._spin(64, 8192, "ai_max_output_tokens", 512)
        self.context_chars = self._spin(1000, 50000, "ai_context_max_chars", 12000)
        self.recent_count = self._spin(1, 40, "ai_recent_message_count", 8)
        self.summary_threshold = self._spin(6, 200, "ai_summary_threshold", 30)
        self.max_fallback_attempts = self._spin(0, 10, "ai_max_fallback_attempts", 3)
        self.cache_enabled = QCheckBox("Cache eligible exact responses")
        self.cache_enabled.setChecked(self._settings.get("ai_cache_enabled", True))
        self.cache_expiry = self._spin(1, 10080, "ai_cache_expiry_minutes", 60)
        limits.addRow("Maximum retries:", self.retries)
        limits.addRow("Maximum fallback routes:", self.max_fallback_attempts)
        limits.addRow("Request timeout (seconds):", self.timeout)
        limits.addRow("Maximum output tokens:", self.output_tokens)
        limits.addRow("Context limit (characters):", self.context_chars)
        limits.addRow("Recent messages:", self.recent_count)
        limits.addRow("Summarize at messages:", self.summary_threshold)
        limits.addRow("", self.cache_enabled)
        limits.addRow("Cache expiry (minutes):", self.cache_expiry)
        root.addLayout(limits)

        buttons = QHBoxLayout()
        for label, callback in (
            ("Credentials…", self._manage_credentials),
            ("Test Connection", self._test_connection),
            ("Saved Memory…", self._manage_memories),
            ("Clear Cache", self._clear_cache),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        root.addLayout(buttons)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setText(self._gateway.last_status)
        root.addWidget(self.status)
        self.usage = QLabel()
        root.addWidget(self.usage)
        save = QPushButton("Save Pipeline Settings")
        save.clicked.connect(self._save)
        root.addWidget(save)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        root.addWidget(close)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._provider_changed()
        self._apply_free_chat_mode()
        self._update_usage()

    def _spin(self, minimum: int, maximum: int, key: str, default: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(int(self._settings.get(key, default)))
        return widget

    def _provider_changed(self, *_args) -> None:
        provider = self.provider.currentData()
        if self.free_chat_only.isChecked() and provider != "openrouter":
            index = self.provider.findData("openrouter")
            if index >= 0:
                self.provider.setCurrentIndex(index)
                return
        self.free_only.setVisible(
            provider == "openrouter" or self.free_chat_only.isChecked()
        )
        self._load_models(reset_selection=True)
        self._load_credentials()

    def _apply_free_chat_mode(self, *_args) -> None:
        free_only = self.free_chat_only.isChecked()
        if free_only and self.provider.currentData() != "openrouter":
            index = self.provider.findData("openrouter")
            if index >= 0:
                self.provider.setCurrentIndex(index)
        self.provider.setEnabled(not free_only)
        for checkbox in self.provider_enabled.values():
            checkbox.setEnabled(not free_only)
        self.fallback_enabled.setEnabled(not free_only)
        self.fallbacks.setEnabled(not free_only)
        for button in self._fallback_buttons:
            button.setEnabled(not free_only)
        self.advanced_enabled.setEnabled(not free_only)
        self.advanced_model.setEnabled(not free_only)
        self.model.setEditable(not free_only)
        self._load_models()

    @staticmethod
    def _model_order(provider: str, model: dict) -> tuple:
        model_id = str(model["id"]).casefold()
        if provider in {"gemini", "grok"}:
            preview = bool(
                re.search(r"(preview|experimental|exp|deprecated|legacy)", model_id)
            )
            version = tuple(-int(part) for part in re.findall(r"\d+", model_id))
            return preview, version, str(model.get("name", model_id)).casefold()
        return (not bool(model.get("free")), str(model.get("name", model_id)).casefold())

    def _load_models(
        self, *_args, reset_selection: bool = False, prefer_latest: bool = False
    ) -> None:
        provider = self.provider.currentData()
        previous = self.model.currentData() or self.model.currentText()
        self.model.clear()
        catalog = store.cached_model_catalog(provider)
        catalog_ids = {item["id"] for item in catalog}
        models = catalog
        if provider == "openrouter" and (
            self.free_only.isChecked() or self.free_chat_only.isChecked()
        ):
            models = [item for item in models if item.get("free")]
        models.sort(key=lambda item: self._model_order(provider, item))
        if not models and not self.free_chat_only.isChecked():
            default = next(
                (item[2] for item in self._provider_options if item[1] == provider),
                "",
            )
            configured = self._settings.get("ai_primary_model", "")
            if provider == self._settings.get("ai_primary_provider", "gemini"):
                default = configured or default
            models = [{"id": default, "name": default}] if default else []
        for item in models:
            self.model.addItem(item.get("name", item["id"]), item["id"])
        configured = ""
        if provider == self._settings.get("ai_primary_provider", "gemini"):
            configured = str(self._settings.get("ai_primary_model", ""))
        if prefer_latest and provider == "gemini":
            stable = [
                item for item in models
                if not re.search(
                    r"(preview|experimental|exp|deprecated|legacy)",
                    str(item.get("id", "")).casefold(),
                )
            ]
            if stable:
                selected = self.model.findData(stable[0]["id"])
                self.model.setCurrentIndex(selected)
            else:
                self.model.setCurrentIndex(-1)
                self.model.setEditText("")
        elif configured and self.model.findData(configured) >= 0:
            self.model.setCurrentIndex(self.model.findData(configured))
        elif reset_selection and provider in {"gemini", "grok"} and models:
            stable = [
                item for item in models
                if not re.search(
                    r"(preview|experimental|exp|deprecated|legacy)",
                    str(item.get("id", "")).casefold(),
                )
            ]
            if stable:
                self.model.setCurrentIndex(self.model.findData(stable[0]["id"]))
            else:
                self.model.setCurrentIndex(-1)
                self.model.setEditText("")
        elif (
            not reset_selection
            and previous in catalog_ids
            and self.model.findData(previous) >= 0
        ):
            self.model.setCurrentIndex(self.model.findData(previous))
        elif (
            not reset_selection
            and previous
            and previous not in catalog_ids
            and self.model.isEditable()
        ):
            self.model.setEditText(previous)

    def _load_credentials(self) -> None:
        provider = self.provider.currentData()
        previous = self.credential.currentData()
        self.credential.clear()
        self.credential.addItem("Environment variable", "__environment__")
        for item in self._settings.get("ai_credentials", []):
            if item.get("provider") == provider and item.get("enabled", True):
                self.credential.addItem(
                    str(item.get("label") or item.get("id")),
                    str(item.get("id", "")),
                )
        index = self.credential.findData(previous)
        if index >= 0:
            self.credential.setCurrentIndex(index)
        configured = str(self._settings.get("ai_primary_credential_id", ""))
        index = self.credential.findData(configured)
        if index >= 0:
            self.credential.setCurrentIndex(index)
        elif self.credential.count() > 1:
            self.credential.setCurrentIndex(1)

    def _refresh_models(self) -> None:
        provider = self.provider.currentData()
        try:
            models = self._gateway.discover_models(
                provider,
                force_refresh=True,
                credential_id=str(self.credential.currentData() or ""),
            )
            recommend_latest = (
                provider == "gemini"
                and self._settings.get("ai_primary_model", "gemini-2.5-flash")
                == "gemini-2.5-flash"
            )
            self._load_models(prefer_latest=recommend_latest)
            suffix = (
                " Selected the newest stable text model returned by the account."
                if recommend_latest else ""
            )
            self.status.setText(
                f"Loaded {len(models)} models from {provider}.{suffix}"
            )
        except Exception as exc:
            self.status.setText(f"Model discovery failed: {exc}")
            QMessageBox.warning(self, "Model discovery failed", str(exc))

    def _load_fallbacks(self) -> None:
        self.fallbacks.clear()
        for route in self._settings.get("ai_fallback_routes", []):
            label = f"{route.get('provider', '')} / {route.get('model', '')}"
            if not route.get("enabled", True):
                label += " (disabled)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dict(route))
            self.fallbacks.addItem(item)

    def _add_fallback(self) -> None:
        provider, ok = QInputDialog.getItem(
            self, "Add fallback", "Provider:",
            [item[0] for item in self._provider_options], 0, False,
        )
        if not ok:
            return
        provider_id = next(
            item[1] for item in self._provider_options if item[0] == provider
        )
        default = next(
            item[2] for item in self._provider_options if item[1] == provider_id
        )
        model, ok = QInputDialog.getText(
            self, "Add fallback", "Model ID:", text=default
        )
        if ok and model.strip():
            route = {"provider": provider_id, "model": model.strip(), "enabled": True}
            item = QListWidgetItem(f"{provider_id} / {model.strip()}")
            item.setData(Qt.ItemDataRole.UserRole, route)
            self.fallbacks.addItem(item)

    def _remove_fallback(self) -> None:
        row = self.fallbacks.currentRow()
        if row >= 0:
            self.fallbacks.takeItem(row)

    def _move_fallback(self, offset: int) -> None:
        row = self.fallbacks.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.fallbacks.count():
            return
        item = self.fallbacks.takeItem(row)
        self.fallbacks.insertItem(target, item)
        self.fallbacks.setCurrentRow(target)

    def _get_credential_store(self) -> CredentialStore:
        if self._credential_store is None:
            self._credential_store = CredentialStore()
        return self._credential_store

    def _manage_credentials(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Secure AI Credentials")
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for entry in self._settings.get("ai_credentials", []):
            try:
                masked = mask_secret(self._get_credential_store().get(entry["id"]))
            except Exception:
                masked = "Unavailable"
            label = (
                f"{entry.get('label', entry.get('id'))} — {entry.get('provider')} "
                f"— project: {entry.get('project') or 'unknown'} — {masked}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dict(entry))
            listing.addItem(item)
        layout.addWidget(listing)
        controls = QHBoxLayout()
        add = QPushButton("Add key")
        toggle = QPushButton("Enable / disable")
        test = QPushButton("Test selected")
        delete = QPushButton("Delete key")
        controls.addWidget(add)
        controls.addWidget(toggle)
        controls.addWidget(test)
        controls.addWidget(delete)
        layout.addLayout(controls)
        add.clicked.connect(lambda: self._add_credential(listing))
        toggle.clicked.connect(lambda: self._toggle_credential(listing))
        test.clicked.connect(lambda: self._test_listed_credential(listing))
        delete.clicked.connect(lambda: self._delete_credential(listing))
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        self._load_credentials()

    def _add_credential(self, listing: QListWidget) -> None:
        provider, ok = QInputDialog.getItem(
            self, "Add API key", "Provider:",
            [item[0] for item in self._provider_options], 0, False,
        )
        if not ok:
            return
        provider_id = next(
            item[1] for item in self._provider_options if item[0] == provider
        )
        label, ok = QInputDialog.getText(self, "Add API key", "Friendly label:")
        if not ok:
            return
        project = ""
        if provider_id == "gemini":
            project, ok = QInputDialog.getText(
                self, "Add Gemini key", "Google project ID (optional):"
            )
            if not ok:
                return
        secret, ok = QInputDialog.getText(
            self, "Add API key", "API key:", QLineEdit.EchoMode.Password
        )
        if not ok or not secret.strip():
            return
        credential_id = uuid.uuid4().hex
        try:
            self._get_credential_store().set(credential_id, secret)
        except Exception as exc:
            QMessageBox.critical(self, "Credential storage unavailable", str(exc))
            return
        entry = {
            "id": credential_id,
            "provider": provider_id,
            "label": label.strip() or provider,
            "project": project.strip(),
            "enabled": True,
        }
        entries = list(self._settings.get("ai_credentials", []))
        entries.append(entry)
        self._settings.set("ai_credentials", entries)
        self._settings.save()
        item = QListWidgetItem(
            f"{entry['label']} — {provider_id} — project: {entry['project'] or 'unknown'} "
            f"— {mask_secret(secret)}"
        )
        item.setData(Qt.ItemDataRole.UserRole, entry)
        listing.addItem(item)
        self.settings_changed.emit()

    def _toggle_credential(self, listing: QListWidget) -> None:
        item = listing.currentItem()
        if item is None:
            return
        selected = item.data(Qt.ItemDataRole.UserRole)
        entries = [dict(entry) for entry in self._settings.get("ai_credentials", [])]
        for entry in entries:
            if entry.get("id") == selected.get("id"):
                entry["enabled"] = not entry.get("enabled", True)
                selected = entry
                break
        self._settings.set("ai_credentials", entries)
        self._settings.save()
        item.setData(Qt.ItemDataRole.UserRole, selected)
        item.setText(f"{selected.get('label')} — {selected.get('provider')} — "
                     f"{'enabled' if selected.get('enabled') else 'disabled'}")
        self.settings_changed.emit()

    def _delete_credential(self, listing: QListWidget) -> None:
        item = listing.currentItem()
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        try:
            self._get_credential_store().delete(entry["id"])
        except Exception as exc:
            QMessageBox.warning(self, "Could not delete key", str(exc))
            return
        entries = [
            value for value in self._settings.get("ai_credentials", [])
            if value.get("id") != entry.get("id")
        ]
        self._settings.set("ai_credentials", entries)
        if self._settings.get("ai_primary_credential_id") == entry.get("id"):
            self._settings.set("ai_primary_credential_id", "")
        self._settings.save()
        listing.takeItem(listing.row(item))
        self.settings_changed.emit()

    def _test_listed_credential(self, listing: QListWidget) -> None:
        item = listing.currentItem()
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.status.setText(
                self._gateway.test_connection(
                    str(entry.get("provider", "")), str(entry.get("id", ""))
                )
            )
        except Exception as exc:
            self.status.setText(f"Connection failed: {exc}")
            QMessageBox.warning(self, "Connection failed", str(exc))

    def _test_connection(self) -> None:
        provider = self.provider.currentData()
        credential_id = str(self.credential.currentData() or "")
        try:
            result = self._gateway.test_connection(provider, credential_id)
            self.status.setText(result)
        except Exception as exc:
            self.status.setText(f"Connection failed: {exc}")
            QMessageBox.warning(self, "Connection failed", str(exc))

    def _manage_memories(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Saved User-Approved Memory")
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        self._reload_memories(listing)
        layout.addWidget(listing)
        controls = QHBoxLayout()
        for label, callback in (
            ("Add", lambda: self._edit_memory(listing)),
            ("Edit", lambda: self._edit_memory(listing, True)),
            ("Delete", lambda: self._delete_memory(listing)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    @staticmethod
    def _reload_memories(listing: QListWidget) -> None:
        listing.clear()
        for memory in store.list_memories():
            item = QListWidgetItem(memory["content"])
            item.setData(Qt.ItemDataRole.UserRole, memory["id"])
            listing.addItem(item)

    def _edit_memory(self, listing: QListWidget, editing: bool = False) -> None:
        item = listing.currentItem() if editing else None
        memory_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        text, ok = QInputDialog.getMultiLineText(
            self, "Saved memory", "Memory text:",
            item.text() if item else "",
        )
        if ok and text.strip():
            store.add_memory(text, memory_id)
            self._reload_memories(listing)

    def _delete_memory(self, listing: QListWidget) -> None:
        item = listing.currentItem()
        if item:
            store.delete_memory(item.data(Qt.ItemDataRole.UserRole))
            self._reload_memories(listing)

    def _clear_cache(self) -> None:
        count = store.clear_cache()
        self.status.setText(f"Cleared {count} cached response(s).")

    def _update_usage(self) -> None:
        stats = store.usage_stats()
        self.usage.setText(
            "Usage — requests: {requests}, provider attempts: {attempts}, "
            "estimated input/output tokens: "
            "{input_tokens}/{output_tokens}, cache hits: {cache_hits}, "
            "failed attempts: {failures}, estimated tokens saved by cache: "
            "{estimated_saved_tokens}".format(**stats)
        )

    def _save(self) -> None:
        provider = str(self.provider.currentData())
        free_chat_only = self.free_chat_only.isChecked()
        model = (
            str(self.model.currentData() or "")
            if free_chat_only
            else self.model.currentData() or self.model.currentText().strip()
        )
        if not model and not free_chat_only:
            QMessageBox.warning(self, "Model required", "Select or enter a model ID.")
            return
        if free_chat_only:
            provider = "openrouter"
        routes = []
        for index in range(self.fallbacks.count()):
            item = self.fallbacks.item(index)
            route = dict(item.data(Qt.ItemDataRole.UserRole))
            routes.append(route)
        self._settings.set("ai_primary_provider", provider)
        self._settings.set("ai_primary_model", str(model))
        self._settings.set("ai_provider", provider)
        self._settings.set("ai_model", str(model))
        self._settings.set(
            "ai_primary_credential_id",
            self.credential.currentData() or "__environment__",
        )
        self._settings.set("ai_api_key_env_var", self.environment_name.text().strip())
        self._settings.set(
            "ai_provider_enabled",
            {
                provider: checkbox.isChecked()
                for provider, checkbox in self.provider_enabled.items()
            },
        )
        self._settings.set("ai_fallback_enabled", self.fallback_enabled.isChecked())
        self._settings.set("ai_fallback_routes", routes)
        self._settings.set("ai_max_retries", self.retries.value())
        self._settings.set(
            "ai_max_fallback_attempts", self.max_fallback_attempts.value()
        )
        self._settings.set("ai_timeout", self.timeout.value())
        self._settings.set("ai_max_output_tokens", self.output_tokens.value())
        self._settings.set("ai_context_max_chars", self.context_chars.value())
        self._settings.set("ai_recent_message_count", self.recent_count.value())
        self._settings.set("ai_summary_threshold", self.summary_threshold.value())
        self._settings.set("ai_cache_enabled", self.cache_enabled.isChecked())
        self._settings.set("ai_cache_expiry_minutes", self.cache_expiry.value())
        self._settings.set("ai_free_models_only", self.free_only.isChecked())
        self._settings.set("ai_chat_free_only", free_chat_only)
        self._settings.set(
            "ai_advanced_route_enabled", self.advanced_enabled.isChecked()
        )
        self._settings.set("ai_advanced_model", self.advanced_model.text().strip())
        self._settings.save()
        self.settings_changed.emit()
        self.status.setText("Pipeline settings saved.")
        self._update_usage()
