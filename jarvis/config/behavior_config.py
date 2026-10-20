"""Validated, user-editable response and custom-command JSON configuration."""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from string import Formatter
from typing import Any

_FILES = {
    "responses": "assistant_responses.json",
    "commands": "custom_commands.json",
    "animations": "robot_animations.json",
}
_ACTIONS = {
    "open_app": {"app_name"},
    "open_website": {"url"},
    "show_tasks": set(),
    "show_completed_tasks": set(),
    "create_reminder": {"title", "seconds"},
    "create_alarm": {"title", "seconds"},
    "start_focus": {"minutes"},
    "stop_focus": set(),
    "open_settings": set(),
    "play_animation": {"name"},
    "new_chat": set(),
    "daily_briefing": set(),
}
_PLACEHOLDERS = {
    "app_name", "error", "title", "minutes", "task_title", "when", "name",
}


def config_directory() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return base / "JARVIS" / "config"


class BehaviorConfig:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or config_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        defaults = Path(__file__).parent / "default_configs"
        for filename in _FILES.values():
            destination = self.directory / filename
            if not destination.exists():
                shutil.copyfile(defaults / filename, destination)

    def path(self, kind: str) -> Path:
        try:
            return self.directory / _FILES[kind]
        except KeyError as exc:
            raise ValueError(f"Unknown behavior config: {kind}") from exc

    def load(self, kind: str) -> dict[str, Any]:
        path = self.path(kind)
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
        except OSError as exc:
            raise ValueError(f"Cannot read {path}: {exc}") from exc
        self.validate(kind, data)
        return data

    def save(self, kind: str, data: dict[str, Any]) -> None:
        self.validate(kind, data)
        path = self.path(kind)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with temporary.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def reset(self, kind: str) -> dict[str, Any]:
        defaults = Path(__file__).parent / "default_configs" / _FILES[kind]
        data = json.loads(defaults.read_text(encoding="utf-8"))
        self.save(kind, data)
        return data

    @staticmethod
    def validate(kind: str, data: Any) -> None:
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Configuration must be a JSON object with version: 1.")
        if kind == "responses":
            responses = data.get("responses")
            if not isinstance(responses, dict) or not responses:
                raise ValueError("'responses' must be a non-empty object.")
            formatter = Formatter()
            for key, alternatives in responses.items():
                if not isinstance(key, str) or not isinstance(alternatives, list) or not alternatives:
                    raise ValueError("Each response must be a non-empty list of strings.")
                for response in alternatives:
                    if not isinstance(response, str):
                        raise ValueError(f"Response '{key}' entries must be strings.")
                    for _, field, _, _ in formatter.parse(response):
                        if field and field not in _PLACEHOLDERS:
                            raise ValueError(f"Unsupported response placeholder '{{{field}}}'.")
        elif kind == "commands":
            commands = data.get("commands")
            if not isinstance(commands, list):
                raise ValueError("'commands' must be a list.")
            ids: set[str] = set()
            for command in commands:
                if not isinstance(command, dict):
                    raise ValueError("Each command must be an object.")
                required = {"id", "name", "triggers", "action", "arguments", "enabled"}
                if not required.issubset(command):
                    raise ValueError(f"Command missing fields: {', '.join(sorted(required - command.keys()))}")
                if not isinstance(command["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", command["id"]):
                    raise ValueError("Command IDs must use lowercase letters, digits, and hyphens.")
                if command["id"] in ids:
                    raise ValueError(f"Duplicate command ID '{command['id']}'.")
                ids.add(command["id"])
                if command["action"] not in _ACTIONS:
                    raise ValueError(f"Unknown or unsafe action '{command['action']}'.")
                if not isinstance(command["enabled"], bool):
                    raise ValueError(f"Command '{command['id']}' enabled must be boolean.")
                if not isinstance(command["arguments"], dict):
                    raise ValueError(f"Command '{command['id']}' arguments must be an object.")
                if set(command["arguments"]) - _ACTIONS[command["action"]]:
                    raise ValueError(f"Unsupported arguments for action '{command['action']}'.")
                phrases = command["triggers"] + command.get("aliases", [])
                if not phrases or any(not isinstance(item, str) or not item.strip() for item in phrases):
                    raise ValueError(f"Command '{command['id']}' needs non-empty trigger phrases.")
                reply = command.get("reply")
                if reply is not None:
                    if not isinstance(reply, str):
                        raise ValueError("Command reply must be a string.")
                    for _, field, _, _ in Formatter().parse(reply):
                        if field and field not in _PLACEHOLDERS:
                            raise ValueError(f"Unsupported response placeholder '{{{field}}}'.")
        elif kind == "animations":
            animations = data.get("animations")
            if not isinstance(animations, dict):
                raise ValueError("'animations' must be an object.")
            for name, config in animations.items():
                if not isinstance(config, dict) or not isinstance(config.get("enabled"), bool):
                    raise ValueError(f"Animation '{name}' must define boolean 'enabled'.")
