"""Typed, side-effecting tools for Jarvis AI integrations."""
from __future__ import annotations

import math
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from jarvis.ai import store
from jarvis.scheduling import database as db
from jarvis.scheduling import reminder_service, task_service


_FOCUS_SETTINGS = {
    "focus_duration_minutes": (int, 1, 240),
    "focus_short_break_minutes": (int, 1, 60),
    "focus_long_break_minutes": (int, 5, 120),
    "focus_pomodoro_enabled": (bool, None, None),
    "focus_distraction_nudge": (bool, None, None),
    "focus_nudge_cooldown_minutes": (int, 1, 120),
}
_RULE_CATEGORIES = ("distracting", "productive", "always_allow", "neutral")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _object(
    properties: dict[str, dict[str, Any]],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _string(description: str, **kwargs: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **kwargs}


def _integer(description: str, minimum: int | None = None,
             maximum: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer", "description": description}
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def _number(description: str) -> dict[str, Any]:
    return {"type": "number", "description": description}


def _boolean(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


def _tool(name: str, description: str, params: dict[str, Any]) -> Tool:
    return Tool(name, description, params)


def _build_tools() -> dict[str, Tool]:
    positive_id = _integer("Positive record ID.", 1)
    confirmed = _boolean("Must be true to permanently delete this record.")
    title = _string("A short, non-empty title.", minLength=1)
    text = _string("Text value.")
    timestamp = _number("Unix timestamp in seconds.")
    recurrence = _string(
        "Recurrence rule: empty, daily, weekly, weekdays, or interval:<seconds>.",
        pattern=r"^(|daily|weekly|weekdays|interval:[1-9][0-9]*)$",
    )
    enabled = _boolean("Whether this item is enabled.")
    tools = [
        _tool("task_create", "Create a task.", _object({
            "title": title, "description": text,
            "priority": _integer("Priority: 1 low, 2 medium, 3 high.", 1, 3),
            "deadline": timestamp,
            "estimated_min": _integer("Estimated minutes.", 0, 1440),
        }, ("title",))),
        _tool("task_list", "List tasks.", _object({
            "include_completed": _boolean("Include completed tasks."),
        })),
        _tool("task_get_details", "Get one task by stable ID.", _object({
            "task_id": positive_id,
        }, ("task_id",))),
        _tool("task_completed_list", "List completed tasks.", _object({})),
        _tool("task_update", "Update task fields.", _object({
            "task_id": positive_id, "title": title, "description": text,
            "priority": _integer("Priority: 1 low, 2 medium, 3 high.", 1, 3),
            "deadline": timestamp,
            "estimated_min": _integer("Estimated minutes.", 0, 1440),
        }, ("task_id",))),
        _tool("task_complete", "Mark a task complete.", _object({
            "task_id": positive_id,
        }, ("task_id",))),
        _tool("task_reopen", "Reopen a completed task.", _object({
            "task_id": positive_id,
        }, ("task_id",))),
        _tool("task_add_note", "Append a note to a task's description.", _object({
            "task_id": positive_id, "note": _string("Note text.", minLength=1),
        }, ("task_id", "note"))),
        _tool("task_delete", "Permanently delete a task; requires confirmation.", _object({
            "task_id": positive_id, "confirmed": confirmed,
        }, ("task_id", "confirmed"))),
        _tool("reminder_create", "Create a reminder.", _object({
            "title": title, "due_at": timestamp, "description": text,
            "recurrence": recurrence,
        }, ("title", "due_at"))),
        _tool("reminder_list", "List reminders.", _object({
            "include_completed": _boolean("Include completed or disabled reminders."),
        })),
        _tool("reminder_status", "Get a reminder's persisted status and schedule.", _object({
            "reminder_id": positive_id,
        }, ("reminder_id",))),
        _tool("reminder_update", "Update reminder fields.", _object({
            "reminder_id": positive_id, "title": title, "due_at": timestamp,
            "description": text, "recurrence": recurrence, "enabled": enabled,
        }, ("reminder_id",))),
        _tool("reminder_snooze", "Snooze a reminder.", _object({
            "reminder_id": positive_id,
            "minutes": _integer("Snooze duration in minutes.", 1, 10080),
        }, ("reminder_id",))),
        _tool("reminder_dismiss", "Dismiss a reminder.", _object({
            "reminder_id": positive_id,
        }, ("reminder_id",))),
        _tool("reminder_cancel", "Cancel a reminder without deleting it.", _object({
            "reminder_id": positive_id,
        }, ("reminder_id",))),
        _tool("reminder_delete", "Permanently delete a reminder; requires confirmation.", _object({
            "reminder_id": positive_id, "confirmed": confirmed,
        }, ("reminder_id", "confirmed"))),
        _tool("alarm_create", "Create an alarm.", _object({
            "title": title, "due_at": timestamp, "recurrence": recurrence,
            "sound": _boolean("Whether the alarm should play sound."),
            "snooze_min": _integer("Default snooze duration in minutes.", 1, 120),
        }, ("title", "due_at"))),
        _tool("alarm_list", "List alarms.", _object({
            "include_dismissed": _boolean("Include dismissed or disabled alarms."),
        })),
        _tool("alarm_update", "Update alarm fields.", _object({
            "alarm_id": positive_id, "title": title, "due_at": timestamp,
            "recurrence": recurrence, "sound": _boolean("Whether sound is enabled."),
            "enabled": enabled,
        }, ("alarm_id",))),
        _tool("alarm_snooze", "Snooze an alarm.", _object({
            "alarm_id": positive_id,
            "minutes": _integer("Snooze duration in minutes.", 1, 10080),
        }, ("alarm_id",))),
        _tool("alarm_dismiss", "Dismiss an alarm.", _object({
            "alarm_id": positive_id,
        }, ("alarm_id",))),
        _tool("alarm_cancel", "Cancel an alarm without deleting it.", _object({
            "alarm_id": positive_id,
        }, ("alarm_id",))),
        _tool("alarm_delete", "Permanently delete an alarm; requires confirmation.", _object({
            "alarm_id": positive_id, "confirmed": confirmed,
        }, ("alarm_id", "confirmed"))),
        _tool("focus_get", "Get current focus status and settings.", _object({})),
        _tool("focus_start", "Start a focus session.", _object({
            "duration_minutes": _integer("Session duration in minutes.", 1, 240),
        })),
        _tool("focus_stop", "Stop the current focus session.", _object({})),
        _tool("focus_settings", "Read or update focus settings.", _object({
            **{
                key: (
                    _boolean(f"Set {key}.") if kind is bool
                    else _integer(f"Set {key}.", low, high)
                )
                for key, (kind, low, high) in _FOCUS_SETTINGS.items()
            },
        })),
        _tool("focus_rule_list", "List focus-app rules.", _object({})),
        _tool("focus_rule_add", "Add a focus-app rule.", _object({
            "process": text, "path": text,
            "category": _string("Rule category.", enum=list(_RULE_CATEGORIES)),
            "enabled": enabled,
        }, ("category",))),
        _tool("focus_rule_update", "Update a focus-app rule.", _object({
            "rule_id": _string("Rule ID.", minLength=1),
            "process": text, "path": text,
            "category": _string("Rule category.", enum=list(_RULE_CATEGORIES)),
            "enabled": enabled,
        }, ("rule_id",))),
        _tool("focus_rule_remove", "Permanently remove a focus-app rule; requires confirmation.", _object({
            "rule_id": _string("Rule ID.", minLength=1), "confirmed": confirmed,
        }, ("rule_id", "confirmed"))),
        _tool("focus_rule_toggle", "Enable or disable a focus-app rule.", _object({
            "rule_id": _string("Rule ID.", minLength=1), "enabled": enabled,
        }, ("rule_id", "enabled"))),
        _tool("focus_rule_category", "Change a focus-app rule category.", _object({
            "rule_id": _string("Rule ID.", minLength=1),
            "category": _string("Rule category.", enum=list(_RULE_CATEGORIES)),
        }, ("rule_id", "category"))),
        _tool("saved_note_add", "Save a note to AI memory.", _object({
            "content": _string("Note content.", minLength=1),
        }, ("content",))),
        _tool("saved_note_list", "List saved notes.", _object({})),
        _tool("saved_note_search", "Search saved notes by text.", _object({
            "query": _string("Words to search for.", minLength=1),
        }, ("query",))),
        _tool("saved_note_delete", "Permanently delete a saved note; requires confirmation.", _object({
            "note_id": _string("Saved note ID.", minLength=1), "confirmed": confirmed,
        }, ("note_id", "confirmed"))),
        _tool("app_status", "Get application status.", _object({})),
        _tool("daily_briefing", "Summarize today's task and reminder counts.", _object({})),
        _tool("animation_play", "Play an animation using the injected app callback.", _object({
            "animation": _string("Animation name.", minLength=1),
        }, ("animation",))),
        _tool("app_open", "Open an application using the injected app callback.", _object({
            "application": _string("Application name or configured target.", minLength=1),
        }, ("application",))),
        _tool("clipboard_write", "Copy the exact supplied text to the system clipboard.", _object({
            "text": _string("Exact text to copy after user confirmation.", minLength=1, maxLength=20000),
            "confirmed": confirmed,
        }, ("text", "confirmed"))),
    ]
    return {tool.name: tool for tool in tools}


class ToolRegistry:
    """Validate tool calls, dispatch service operations, and record safe metadata.

    Action history intentionally stores only tool name, outcome, error code, and
    timestamp. Arguments and results (which may contain user data) are omitted.
    """

    def __init__(
        self,
        *,
        settings: Any = None,
        focus_service: Any = None,
        app_status: Callable[[], Any] | None = None,
        play_animation: Callable[[str], Any] | None = None,
        open_application: Callable[[str], Any] | None = None,
        write_clipboard: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.focus_service = focus_service
        self.callbacks = {
            "app_status": app_status,
            "animation_play": play_animation,
            "app_open": open_application,
            "clipboard_write": write_clipboard,
        }
        self._tools = _build_tools()
        self._handlers = self._make_handlers()

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools.values()]

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self.tools

    def validate_call(self, name: str, arguments: dict[str, Any]) -> None:
        if not isinstance(name, str) or name not in self._tools:
            raise ValueError("Unknown tool name.")
        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be a JSON object.")
        self._validate(self._tools[name].parameters, arguments)

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = {} if arguments is None else arguments
        if not isinstance(name, str) or name not in self._tools:
            self._record_action(name, "error", "unknown_tool")
            return {"ok": False, "error": "unknown_tool", "message": "Unknown tool name."}
        try:
            self.validate_call(name, args)
            result = self._handlers[name](args)
            if result is False or (
                isinstance(result, str) and result.startswith(("❌", "⚠"))
            ):
                self._record_action(
                    name, "error", "operation_failed",
                    affected_item_id=self._affected_id(args, result),
                )
                return {
                    "ok": False,
                    "error": "operation_failed",
                    "message": result if isinstance(result, str) else "The operation returned false.",
                }
            self._record_action(
                name, "success", "",
                affected_item_id=self._affected_id(args, result),
                result_summary=self._result_summary(result),
            )
            return {"ok": True, "result": result}
        except _ConfirmationRequired as exc:
            self._record_action(
                name, "error", "confirmation_required",
                affected_item_id=self._affected_id(args, None),
            )
            return {"ok": False, "error": "confirmation_required", "message": str(exc)}
        except (ValueError, TypeError, KeyError) as exc:
            self._record_action(
                name, "error", "invalid_arguments",
                affected_item_id=self._affected_id(args, None),
            )
            return {"ok": False, "error": "invalid_arguments", "message": str(exc)}
        except Exception:
            log.exception("AI application tool %s failed", name)
            self._record_action(
                name, "error", "operation_failed",
                affected_item_id=self._affected_id(args, None),
            )
            return {"ok": False, "error": "operation_failed", "message": "The requested operation failed."}

    @staticmethod
    def _validate(schema: dict[str, Any], value: Any, path: str = "arguments") -> None:
        if schema.get("type") == "object":
            if not isinstance(value, dict):
                raise ValueError(f"{path} must be an object.")
            missing = [key for key in schema.get("required", ()) if key not in value]
            if missing:
                raise ValueError(f"Missing required argument: {missing[0]}.")
            extra = set(value) - set(schema.get("properties", {}))
            if extra:
                raise ValueError(f"Unexpected argument: {sorted(extra)[0]}.")
            for key, item in value.items():
                ToolRegistry._validate(schema["properties"][key], item, f"{path}.{key}")
            return
        kind = schema.get("type")
        valid = {
            "string": lambda item: isinstance(item, str),
            "boolean": lambda item: isinstance(item, bool),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: (
                isinstance(item, (int, float)) and not isinstance(item, bool)
                and math.isfinite(float(item))
            ),
        }.get(kind)
        if valid is None or not valid(value):
            raise ValueError(f"{path} must be {kind or 'valid'}.")
        if kind == "string" and (
            len(value) < schema.get("minLength", 0)
            or (schema.get("minLength", 0) and not value.strip())
        ):
            raise ValueError(f"{path} must not be empty.")
        if kind == "string" and len(value) > schema.get("maxLength", float("inf")):
            raise ValueError(f"{path} must not exceed {schema['maxLength']} characters.")
        if kind == "string" and "pattern" in schema and not re.fullmatch(
            schema["pattern"], value
        ):
            raise ValueError(f"{path} does not match the required format.")
        if kind in ("integer", "number"):
            if "minimum" in schema and value < schema["minimum"]:
                raise ValueError(f"{path} must be at least {schema['minimum']}.")
            if "maximum" in schema and value > schema["maximum"]:
                raise ValueError(f"{path} must be at most {schema['maximum']}.")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of: {', '.join(schema['enum'])}.")

    @staticmethod
    def _record_action(
        name: str,
        outcome: str,
        error_code: str,
        affected_item_id: str = "",
        result_summary: str = "",
    ) -> None:
        ToolRegistry._record_action_table()
        safe_name = (
            name if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name)
            else "invalid_tool_name"
        )
        db.execute(
            "INSERT INTO ai_tool_action_history "
            "(tool_name,outcome,error_code,created_at,affected_item_id,result_summary) "
            "VALUES (?,?,?,?,?,?)",
            (
                safe_name, outcome, error_code, time.time(),
                str(affected_item_id)[:80], str(result_summary)[:80],
            ),
        )
        db.commit()

    @staticmethod
    def _affected_id(args: dict[str, Any], result: Any) -> str:
        for key in ("task_id", "reminder_id", "alarm_id", "rule_id", "note_id"):
            if key in args:
                return str(args[key])
        if isinstance(result, dict):
            for key in ("id", "task_id", "reminder_id", "alarm_id", "rule_id", "note_id"):
                if key in result:
                    return str(result[key])
        return ""

    @staticmethod
    def _result_summary(result: Any) -> str:
        if isinstance(result, dict):
            if result.get("deleted"):
                return "deleted"
            if result.get("removed"):
                return "removed"
            if "status" in result:
                return str(result["status"])
            if "state" in result:
                return str(result["state"])
            return "completed"
        if isinstance(result, list):
            return f"returned:{len(result)}"
        return "completed"

    @staticmethod
    def _record_action_table() -> None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS ai_tool_action_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, tool_name TEXT NOT NULL, "
            "outcome TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, "
            "affected_item_id TEXT NOT NULL DEFAULT '', "
            "result_summary TEXT NOT NULL DEFAULT '')"
        )
        columns = {
            row["name"] for row in db.execute(
                "PRAGMA table_info(ai_tool_action_history)"
            ).fetchall()
        }
        if "affected_item_id" not in columns:
            db.execute(
                "ALTER TABLE ai_tool_action_history ADD COLUMN "
                "affected_item_id TEXT NOT NULL DEFAULT ''"
            )
        if "result_summary" not in columns:
            db.execute(
                "ALTER TABLE ai_tool_action_history ADD COLUMN "
                "result_summary TEXT NOT NULL DEFAULT ''"
            )
        db.commit()

    @staticmethod
    def action_history(limit: int = 50) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer.")
        ToolRegistry._record_action_table()
        return [
            dict(row) for row in db.execute(
                "SELECT id,tool_name,outcome,error_code,created_at,"
                "affected_item_id,result_summary "
                "FROM ai_tool_action_history ORDER BY id DESC LIMIT ?", (min(limit, 500),)
            ).fetchall()
        ]

    def _make_handlers(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "task_create": self._task_create,
            "task_list": self._task_list,
            "task_get_details": lambda a: self._require_row("tasks", a["task_id"]),
            "task_completed_list": lambda _a: [
                task for task in task_service.get_all_tasks()
                if task.get("status") == "done"
            ],
            "task_update": self._task_update,
            "task_complete": self._task_complete,
            "task_reopen": self._task_reopen,
            "task_add_note": self._task_add_note,
            "task_delete": self._task_delete,
            "reminder_create": self._reminder_create,
            "reminder_list": lambda a: reminder_service.get_reminders(bool(a.get("include_completed", False))),
            "reminder_status": lambda a: self._require_row("reminders", a["reminder_id"]),
            "reminder_update": self._reminder_update,
            "reminder_snooze": self._reminder_snooze,
            "reminder_dismiss": self._reminder_dismiss,
            "reminder_cancel": self._reminder_cancel,
            "reminder_delete": self._reminder_delete,
            "alarm_create": self._alarm_create,
            "alarm_list": lambda a: reminder_service.get_alarms(bool(a.get("include_dismissed", False))),
            "alarm_update": self._alarm_update,
            "alarm_snooze": self._alarm_snooze,
            "alarm_dismiss": self._alarm_dismiss,
            "alarm_cancel": self._alarm_cancel,
            "alarm_delete": self._alarm_delete,
            "focus_get": self._focus_get,
            "focus_start": self._focus_start,
            "focus_stop": self._focus_stop,
            "focus_settings": self._focus_settings,
            "focus_rule_list": self._focus_rule_list,
            "focus_rule_add": self._focus_rule_add,
            "focus_rule_update": self._focus_rule_update,
            "focus_rule_remove": self._focus_rule_remove,
            "focus_rule_toggle": self._focus_rule_toggle,
            "focus_rule_category": self._focus_rule_category,
            "saved_note_add": lambda a: {"note_id": store.add_memory(a["content"])},
            "saved_note_list": lambda _a: store.list_memories(),
            "saved_note_search": lambda a: store.search_memories(a["query"]),
            "saved_note_delete": self._saved_note_delete,
            "clipboard_write": self._clipboard_write,
            "daily_briefing": self._daily_briefing,
        }
        for name, callback in self.callbacks.items():
            if name != "clipboard_write":
                handlers[name] = self._callback_handler(name, callback)
        return handlers

    @staticmethod
    def _callback_handler(name: str, callback: Callable[..., Any] | None) -> Callable[[dict[str, Any]], Any]:
        def invoke(args: dict[str, Any]) -> Any:
            if callback is None:
                raise ValueError(f"{name} callback is not configured.")
            if name == "animation_play":
                return callback(args["animation"])
            if name == "app_open":
                return callback(args["application"])
            if name == "clipboard_write":
                result = callback(args["text"])
                if result is False or (
                    isinstance(result, str)
                    and result.startswith(("❌", "⚠"))
                ):
                    return result
                return {"characters": len(args["text"])}
            return callback()
        return invoke

    @staticmethod
    def _require_row(table: str, row_id: int) -> dict[str, Any]:
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        if row is None:
            raise ValueError(f"{table.rstrip('s').title()} {row_id} does not exist.")
        return dict(row)

    def _task_create(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = task_service.add_task(
            args["title"], args.get("description", ""),
            args.get("priority", 1), args.get("deadline"),
            args.get("estimated_min", 0),
        )
        return self._require_row("tasks", task_id)

    @staticmethod
    def _daily_briefing(_args: dict[str, Any]) -> dict[str, Any]:
        from jarvis.scheduling.reminder_service import get_upcoming_reminders

        tasks = task_service.get_tasks()
        reminders = get_upcoming_reminders(5)
        return {
            "active_task_count": len(tasks),
            "upcoming_reminder_count": len(reminders),
            "tasks": tasks[:5],
            "reminders": reminders,
        }

    @staticmethod
    def _task_list(args: dict[str, Any]) -> list[dict[str, Any]]:
        return (
            task_service.get_all_tasks() if args.get("include_completed", False)
            else task_service.get_tasks()
        )

    def _task_update(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = args["task_id"]
        self._require_row("tasks", task_id)
        fields = {key: value for key, value in args.items() if key != "task_id"}
        if not fields:
            raise ValueError("At least one task field must be provided.")
        task_service.edit_task(task_id, **fields)
        row = self._require_row("tasks", task_id)
        self._verify(row, fields)
        return row

    def _task_complete(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = args["task_id"]
        self._require_row("tasks", task_id)
        task_service.complete_task(task_id)
        row = self._require_row("tasks", task_id)
        self._verify(row, {"status": "done"})
        return row

    def _task_reopen(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = args["task_id"]
        self._require_row("tasks", task_id)
        task_service.set_task_status(task_id, "todo")
        row = self._require_row("tasks", task_id)
        self._verify(row, {"status": "todo"})
        return row

    def _task_add_note(self, args: dict[str, Any]) -> dict[str, Any]:
        row = self._require_row("tasks", args["task_id"])
        previous = row.get("description") or ""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        description = f"{previous}\n[{timestamp}] {args['note']}".strip()
        task_service.edit_task(args["task_id"], description=description)
        updated = self._require_row("tasks", args["task_id"])
        self._verify(updated, {"description": description})
        return updated

    def _task_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = args["task_id"]
        task = self._require_row("tasks", task_id)
        self._confirm(args)
        task_service.delete_task(task_id)
        if db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise ValueError("Task deletion was not persisted.")
        return {"deleted": True, "id": task_id, "title": task["title"]}

    def _reminder_create(self, args: dict[str, Any]) -> dict[str, Any]:
        rid = reminder_service.add_reminder(
            args["title"], float(args["due_at"]), args.get("description", ""),
            args.get("recurrence", ""),
        )
        return self._require_row("reminders", rid)

    def _reminder_update(self, args: dict[str, Any]) -> dict[str, Any]:
        rid = args["reminder_id"]
        self._require_row("reminders", rid)
        fields = {key: value for key, value in args.items() if key != "reminder_id"}
        if not fields:
            raise ValueError("At least one reminder field must be provided.")
        reminder_service.edit_reminder(rid, **fields)
        row = self._require_row("reminders", rid)
        self._verify(row, fields)
        return row

    def _reminder_snooze(self, args: dict[str, Any]) -> dict[str, Any]:
        rid = args["reminder_id"]
        self._require_row("reminders", rid)
        reminder_service.snooze_reminder(rid, minutes=args.get("minutes", 10))
        row = self._require_row("reminders", rid)
        if row["status"] != "snoozed":
            raise ValueError("Reminder snooze was not persisted.")
        return row

    def _reminder_dismiss(self, args: dict[str, Any]) -> dict[str, Any]:
        rid = args["reminder_id"]
        self._require_row("reminders", rid)
        reminder_service.dismiss_reminder(rid)
        row = self._require_row("reminders", rid)
        self._verify(row, {"enabled": 0, "status": "dismissed"})
        return row

    def _reminder_cancel(self, args: dict[str, Any]) -> dict[str, Any]:
        rid = args["reminder_id"]
        self._require_row("reminders", rid)
        reminder_service.edit_reminder(rid, enabled=False)
        db.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (rid,))
        db.commit()
        row = self._require_row("reminders", rid)
        self._verify(row, {"enabled": 0, "status": "cancelled"})
        return row

    def _reminder_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        rid = args["reminder_id"]
        self._require_row("reminders", rid)
        self._confirm(args)
        reminder_service.delete_reminder(rid)
        if db.execute("SELECT 1 FROM reminders WHERE id=?", (rid,)).fetchone():
            raise ValueError("Reminder deletion was not persisted.")
        return {"deleted": True, "reminder_id": rid}

    def _alarm_create(self, args: dict[str, Any]) -> dict[str, Any]:
        aid = reminder_service.add_alarm(
            args["title"], float(args["due_at"]), args.get("recurrence", ""),
            args.get("sound", True), args.get("snooze_min", 5),
        )
        return self._require_row("alarms", aid)

    def _alarm_update(self, args: dict[str, Any]) -> dict[str, Any]:
        aid = args["alarm_id"]
        self._require_row("alarms", aid)
        fields = {key: value for key, value in args.items() if key != "alarm_id"}
        if not fields:
            raise ValueError("At least one alarm field must be provided.")
        reminder_service.edit_alarm(aid, **fields)
        row = self._require_row("alarms", aid)
        self._verify(row, fields)
        return row

    def _alarm_snooze(self, args: dict[str, Any]) -> dict[str, Any]:
        aid = args["alarm_id"]
        self._require_row("alarms", aid)
        reminder_service.snooze_alarm(aid, minutes=args.get("minutes", 5))
        row = self._require_row("alarms", aid)
        if row["status"] != "snoozed":
            raise ValueError("Alarm snooze was not persisted.")
        return row

    def _alarm_dismiss(self, args: dict[str, Any]) -> dict[str, Any]:
        aid = args["alarm_id"]
        before = self._require_row("alarms", aid)
        reminder_service.dismiss_alarm(aid)
        row = self._require_row("alarms", aid)
        if before.get("recurrence"):
            if row["due_at"] <= before["due_at"] or row["status"] != "scheduled":
                raise ValueError("Recurring alarm dismissal was not persisted.")
        else:
            self._verify(row, {"dismissed": 1, "status": "dismissed"})
        return row

    def _alarm_cancel(self, args: dict[str, Any]) -> dict[str, Any]:
        aid = args["alarm_id"]
        self._require_row("alarms", aid)
        reminder_service.edit_alarm(aid, enabled=False)
        db.execute("UPDATE alarms SET status='cancelled' WHERE id=?", (aid,))
        db.commit()
        row = self._require_row("alarms", aid)
        self._verify(row, {"enabled": 0, "status": "cancelled"})
        return row

    def _alarm_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        aid = args["alarm_id"]
        self._require_row("alarms", aid)
        self._confirm(args)
        reminder_service.delete_alarm(aid)
        if db.execute("SELECT 1 FROM alarms WHERE id=?", (aid,)).fetchone():
            raise ValueError("Alarm deletion was not persisted.")
        return {"deleted": True, "alarm_id": aid}

    def _focus_get(self, _args: dict[str, Any]) -> dict[str, Any]:
        if self.focus_service is None:
            raise ValueError("Focus service is not configured.")
        state = self.focus_service.state
        return {
            "state": getattr(state, "name", str(state)),
            "is_active": bool(self.focus_service.is_active),
            "remaining_seconds": int(getattr(self.focus_service, "_remaining", 0)),
            "status": self.focus_service.status(),
            "settings": self._focus_settings({}),
        }

    def _focus_start(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.focus_service is None:
            raise ValueError("Focus service is not configured.")
        message = self.focus_service.start_focus(args.get("duration_minutes"))
        return {"message": message, "state": getattr(self.focus_service.state, "name", str(self.focus_service.state))}

    def _focus_stop(self, _args: dict[str, Any]) -> dict[str, Any]:
        if self.focus_service is None:
            raise ValueError("Focus service is not configured.")
        return {"message": self.focus_service.stop(), "state": getattr(self.focus_service.state, "name", str(self.focus_service.state))}

    def _focus_settings(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.settings is None:
            raise ValueError("Settings are not configured.")
        if args:
            for key, value in args.items():
                kind, low, high = _FOCUS_SETTINGS[key]
                if kind is bool and not isinstance(value, bool):
                    raise ValueError(f"{key} must be boolean.")
                if kind is int and (
                    isinstance(value, bool) or not isinstance(value, int)
                    or value < low or value > high
                ):
                    raise ValueError(f"{key} must be between {low} and {high}.")
            for key, value in args.items():
                self.settings.set(key, value)
            self.settings.save()
            for key, value in args.items():
                if self.settings.get(key) != value:
                    raise ValueError(f"{key} update was not persisted.")
            if self.focus_service is not None and "focus_distraction_nudge" in args:
                self.focus_service.refresh_rules()
        return {key: self.settings.get(key) for key in _FOCUS_SETTINGS}

    def _focus_rule_list(self, _args: dict[str, Any]) -> list[dict[str, Any]]:
        return self._get_rules()

    def _focus_rule_add(self, args: dict[str, Any]) -> dict[str, Any]:
        rules = self._get_rules()
        process, path = args.get("process", "").strip(), args.get("path", "").strip()
        if not process and not path:
            raise ValueError("Provide at least a process name or application path.")
        rule = {
            "id": uuid.uuid4().hex,
            "process": process, "path": path,
            "category": args["category"], "enabled": args.get("enabled", True),
        }
        rules.append(rule)
        self._save_rules(rules)
        return rule

    def _focus_rule_update(self, args: dict[str, Any]) -> dict[str, Any]:
        fields = {key: value for key, value in args.items() if key != "rule_id"}
        if not fields:
            raise ValueError("At least one rule field must be provided.")
        return self._change_rule(args["rule_id"], fields)

    def _focus_rule_remove(self, args: dict[str, Any]) -> dict[str, Any]:
        rule_id = args["rule_id"]
        rules = self._get_rules()
        if not any(str(rule.get("id")) == rule_id for rule in rules):
            raise ValueError(f"Focus rule '{rule_id}' does not exist.")
        self._confirm(args)
        filtered = [rule for rule in rules if str(rule.get("id")) != rule_id]
        if len(filtered) == len(rules):
            raise ValueError(f"Focus rule '{rule_id}' does not exist.")
        self._save_rules(filtered)
        if any(str(rule.get("id")) == rule_id for rule in self._get_rules()):
            raise ValueError("Focus rule removal was not persisted.")
        return {"removed": True, "rule_id": rule_id}

    def _focus_rule_toggle(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._change_rule(args["rule_id"], {"enabled": args["enabled"]})

    def _focus_rule_category(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._change_rule(args["rule_id"], {"category": args["category"]})

    def _change_rule(self, rule_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        rules = self._get_rules()
        updated = None
        for rule in rules:
            if str(rule.get("id")) == rule_id:
                rule.update(fields)
                updated = dict(rule)
                break
        if updated is None:
            raise ValueError(f"Focus rule '{rule_id}' does not exist.")
        self._save_rules(rules)
        persisted = next(
            (rule for rule in self._get_rules() if str(rule.get("id")) == rule_id), None
        )
        if persisted is None:
            raise ValueError("Focus rule update was not persisted.")
        self._verify(persisted, fields)
        return persisted

    def _get_rules(self) -> list[dict[str, Any]]:
        if self.settings is None:
            raise ValueError("Settings are not configured.")
        rules = self.settings.get("focus_app_rules", [])
        if not isinstance(rules, list):
            raise ValueError("focus_app_rules setting must be a list.")
        return [dict(rule) for rule in rules if isinstance(rule, dict)]

    def _save_rules(self, rules: list[dict[str, Any]]) -> None:
        self.settings.set("focus_app_rules", rules)
        self.settings.save()
        if self.settings.get("focus_app_rules") != rules:
            raise ValueError("Focus rules were not persisted.")
        if self.focus_service is not None:
            self.focus_service.refresh_rules()

    def _saved_note_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        note_id = args["note_id"]
        if not any(note["id"] == note_id for note in store.list_memories()):
            raise ValueError(f"Saved note '{note_id}' does not exist.")
        self._confirm(args)
        store.delete_memory(note_id)
        if any(note["id"] == note_id for note in store.list_memories()):
            raise ValueError("Saved note deletion was not persisted.")
        return {"deleted": True, "note_id": note_id}

    def _clipboard_write(self, args: dict[str, Any]) -> dict[str, int]:
        self._confirm(args)
        callback = self.callbacks["clipboard_write"]
        if callback is None:
            raise ValueError("clipboard_write callback is not configured.")
        result = callback(args["text"])
        if result is False or (
            isinstance(result, str) and result.startswith(("❌", "⚠"))
        ):
            raise RuntimeError(
                result if isinstance(result, str) else "Clipboard write failed."
            )
        return {"characters": len(args["text"])}

    @staticmethod
    def _confirm(args: dict[str, Any]) -> None:
        if args.get("confirmed") is not True:
            raise _ConfirmationRequired(
                "Explicit confirmation is required. No changes were made."
            )

    @staticmethod
    def _verify(row: dict[str, Any], expected: dict[str, Any]) -> None:
        for key, value in expected.items():
            actual = row.get(key)
            if isinstance(value, bool):
                matches = bool(actual) is value
            else:
                matches = actual == value
            if not matches:
                raise ValueError(f"Update was not persisted for field '{key}'.")


class _ConfirmationRequired(ValueError):
    pass


def get_action_history(limit: int = 50) -> list[dict[str, Any]]:
    """Return safe tool-call metadata; never includes tool arguments or results."""
    return ToolRegistry.action_history(limit)


def get_tool_definitions() -> list[dict[str, Any]]:
    """Return stable provider-neutral function tool schemas."""
    return ToolRegistry().get_tool_definitions()
