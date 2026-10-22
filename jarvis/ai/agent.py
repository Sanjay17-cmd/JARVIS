"""Shared structured action layer for typed and transcribed chat requests."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from threading import Event
from typing import Any, Callable

from jarvis.ai.tools import ToolRegistry

log = logging.getLogger(__name__)

_DESTRUCTIVE_TOOLS = {
    "task_delete", "reminder_delete", "alarm_delete", "focus_rule_remove",
    "saved_note_delete",
}
_CONFIRMATION_REQUIRED_TOOLS = {
    "task_create", "task_update", "task_complete", "task_reopen",
    "task_add_note", "task_delete",
    "reminder_create", "reminder_update", "reminder_snooze",
    "reminder_dismiss", "reminder_cancel", "reminder_delete",
    "alarm_create", "alarm_update", "alarm_snooze", "alarm_dismiss",
    "alarm_cancel", "alarm_delete",
    "focus_start", "focus_stop", "focus_settings", "focus_rule_add",
    "focus_rule_update", "focus_rule_remove", "focus_rule_toggle",
    "focus_rule_category",
    "saved_note_add", "saved_note_delete", "app_open", "animation_play",
    "clipboard_write",
}
_CONFIRM_YES = {
    "yes", "yes confirm", "confirm", "confirm delete", "do it",
    "yeah", "yep", "approve", "approved", "go ahead", "proceed",
    "yes proceed", "yes do it",
}
_CONFIRM_NO = {
    "no", "no cancel", "cancel", "cancel it", "never mind",
    "no thanks", "no do not", "dont", "decline",
}


class AIAgent:
    """Extract one validated action or a normal response through the AI gateway."""

    def __init__(
        self,
        gateway: Any,
        registry: ToolRegistry,
        tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.gateway = gateway
        self.registry = registry
        self.tool_executor = tool_executor or registry.execute
        self._pending_confirmations: dict[
            str, tuple[str, dict[str, Any], str]
        ] = {}

    def generate(
        self,
        prompt: str,
        on_chunk: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
        on_reset: Callable[[], None] | None = None,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            return "Request cancelled."
        conversation_id = self._conversation_id(prompt)
        confirmation = self._pending_confirmations.get(conversation_id)
        normalized = re.sub(r"[^a-z ]", "", prompt.casefold()).strip()
        if confirmation and normalized in _CONFIRM_YES:
            name, arguments, _description = confirmation
            confirmed_arguments = dict(arguments)
            if name in _DESTRUCTIVE_TOOLS or name == "clipboard_write":
                confirmed_arguments["confirmed"] = True
            self._pending_confirmations.pop(conversation_id, None)
            outcome = self.tool_executor(name, confirmed_arguments)
            result = self._format_outcome(name, outcome, confirmed_arguments)
            if on_chunk and result:
                on_chunk(result)
            return result
        if confirmation and normalized in _CONFIRM_NO:
            self._pending_confirmations.pop(conversation_id, None)
            result = "Cancelled. No changes were made."
            if on_chunk:
                on_chunk(result)
            return result
        if confirmation:
            result = (
                f"Please answer yes or no to this pending request: "
                f"{confirmation[2]}"
            )
            if on_chunk:
                on_chunk(result)
            return result
        definitions = self._select_tools(prompt)
        if not definitions:
            return self.gateway.generate(
                prompt, on_chunk, cancel_event, on_reset
            )
        records = self._relevant_records(prompt)
        extraction_prompt = (
            "You are Jarvis's application-action planner. Interpret the user's request, "
            "then return exactly one JSON object and no markdown. Use only the registered "
            "tools listed below. Never claim an action succeeded. For normal conversation "
            "return {\"action\":null,\"response\":\"...\"}. For a clear request return "
            "{\"action\":{\"name\":\"tool_name\",\"arguments\":{}},\"response\":\"\"}. "
            "For ambiguity or missing information return "
            "{\"action\":null,\"response\":\"a concise clarification question\"}. "
            "Do not invent record IDs: choose IDs only from the provided records. For "
            "deletion requests, propose the matching delete tool with confirmed=false; "
            "confirmation is handled separately by the application. For clipboard_write, "
            "put the exact final requested content in the text argument; if the user "
            "asked you to compose content and copy it, compose it now. Use local time "
            f"{datetime.now().astimezone().isoformat()} when resolving relative dates. "
            "Return the actual date/time in arguments as Unix seconds.\n\n"
            "Registered tools:\n"
            + json.dumps(definitions, ensure_ascii=False, separators=(",", ":"))
            + "\n\nRelevant records:\n"
            + json.dumps(records, ensure_ascii=False, default=str)
            + "\n\nUser request:\n"
            + prompt
        )
        raw = self.gateway.generate(
            extraction_prompt, None, cancel_event, on_reset, use_cache=False
        )
        if cancel_event is not None and cancel_event.is_set():
            return "Request cancelled."
        plan = self._parse_plan(raw)
        action = plan.get("action")
        if action is None:
            response = plan.get("response")
            if not isinstance(response, str) or not response.strip():
                raise ValueError("AI returned neither a valid action nor a response.")
            result = response.strip()
        else:
            if not isinstance(action, dict):
                raise ValueError("AI returned an invalid action.")
            name = action.get("name")
            arguments = action.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("AI returned an invalid tool call.")
            if name in _DESTRUCTIVE_TOOLS or name == "clipboard_write":
                arguments = dict(arguments)
                arguments["confirmed"] = False
            self.registry.validate_call(name, arguments)
            duplicate_question = self._duplicate_target_question(
                name, arguments, records
            )
            target_error = self._target_validation_message(
                name, arguments, records
            )
            if duplicate_question or target_error:
                clarification = duplicate_question or target_error
                if on_chunk:
                    on_chunk(clarification)
                return clarification
            if name in _CONFIRMATION_REQUIRED_TOOLS:
                description = self._confirmation_description(
                    name, arguments, records
                )
                self._pending_confirmations[conversation_id] = (
                    name, arguments, description,
                )
                result = (
                    f"Please confirm: {description} "
                    "Say or type yes to proceed, or no to cancel."
                )
                if on_chunk:
                    on_chunk(result)
                return result
            outcome = self.tool_executor(name, arguments)
            result = self._format_outcome(name, outcome, arguments)
        if on_chunk and result:
            on_chunk(result)
        return result

    def has_pending_confirmation(self, prompt: str) -> bool:
        return self._conversation_id(prompt) in self._pending_confirmations

    @staticmethod
    def _parse_plan(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        try:
            plan = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("AI action planner returned malformed JSON: %s", exc)
            raise ValueError("AI returned an invalid action plan. Please try again.") from exc
        if (
            not isinstance(plan, dict)
            or set(plan) != {"action", "response"}
            or (plan["action"] is not None and not isinstance(plan["action"], dict))
            or not isinstance(plan["response"], str)
        ):
            raise ValueError("AI returned an invalid action plan. Please try again.")
        return plan

    def _select_tools(self, prompt: str) -> list[dict[str, Any]]:
        text = prompt.casefold()
        groups: set[str] = set()
        if (
            re.search(r"\b(it|that|this)\b", text)
            and re.search(r"\b(move|change|update|delete|complete|mark|reopen|"
                          r"snooze|cancel|dismiss|add)\b", text)
        ):
            groups.update(("task_", "reminder_", "alarm_", "focus_", "saved_note_"))
        if any(term in text for term in (
            "task", "assignment", "project", "deadline", "todo", "to-do",
        )) or re.match(r"^(task|done)\b", text):
            groups.add("task_")
        if any(term in text for term in ("reminder", "water reminder", "remind me")):
            groups.add("reminder_")
        if "alarm" in text or re.match(r"^set\s+alarm\b", text):
            groups.add("alarm_")
        if any(term in text for term in (
            "focus", "distracting", "productive app", "always allow",
        )):
            groups.add("focus_")
        if "note" in text:
            groups.add("saved_note_")
            if "task" in text or "assignment" in text or "project" in text:
                groups.add("task_")
        if any(term in text for term in ("open ", "launch ")):
            groups.add("app_open")
        if any(term in text for term in (
            "clipboard", "copy this", "copy it", "copy that", "put this",
        )):
            groups.add("clipboard_write")
        if re.match(r"^start\s+\S", text) and not text.startswith("start focus"):
            groups.add("app_open")
        if "animation" in text or "robot" in text:
            groups.add("animation_play")
        if "application status" in text or text.strip() in {"status", "app status"}:
            groups.add("app_status")
        if "briefing" in text or "daily summary" in text:
            groups.add("daily_briefing")
        return [
            item for item in self.registry.get_tool_definitions()
            if any(
                item["function"]["name"].startswith(group)
                if group.endswith("_") else item["function"]["name"] == group
                for group in groups
            )
        ]

    def _conversation_id(self, prompt: str) -> str:
        fingerprint = getattr(self.gateway, "context_fingerprint", None)
        if callable(fingerprint):
            _context, conversation_id = fingerprint(prompt)
            return str(conversation_id)
        return "default"

    @staticmethod
    def _confirmation_description(
        name: str,
        arguments: dict[str, Any],
        records: dict[str, Any],
    ) -> str:
        item_types = {
            "task": ("tasks", "task_id"),
            "reminder": ("reminders", "reminder_id"),
            "alarm": ("alarms", "alarm_id"),
            "focus_rule": ("focus_apps", "rule_id"),
        }
        prefix = next(
            (
                candidate for candidate in ("focus_rule", "task", "reminder", "alarm")
                if name.startswith(candidate + "_")
            ),
            "",
        )
        if name in {"app_open", "animation_play"}:
            value = arguments.get(
                "application" if name == "app_open" else "animation", ""
            )
            verb = "open application" if name == "app_open" else "play animation"
            return f"{verb} '{value}'?"
        if name == "clipboard_write":
            content = arguments.get("text", "")
            return (
                "copy this exact text to the clipboard:\n"
                f"“{content}”?"
            )
        if name == "saved_note_add":
            return f"save this note: “{arguments.get('content', '')}”?"
        if name == "saved_note_delete":
            return f"permanently delete saved note #{arguments.get('note_id')}?"
        if name == "focus_start":
            return (
                "start a Focus session for "
                f"{arguments.get('duration_minutes', 'the configured')} minutes?"
            )
        if name == "focus_stop":
            return "stop the current Focus session?"
        if name == "focus_settings":
            changes = ", ".join(
                f"{key.removeprefix('focus_').replace('_', ' ')} to {value}"
                for key, value in arguments.items()
            )
            return f"change Focus settings ({changes})?"
        if name == "focus_rule_add":
            application = arguments.get("process") or arguments.get("path") or "application"
            return (
                f"add {application} to the {arguments.get('category')} Focus category?"
            )
        if name.startswith("focus_rule_"):
            rule_id = arguments.get("rule_id", "")
            rule = next(
                (
                    item for item in records.get("focus_apps", [])
                    if str(item.get("id")) == str(rule_id)
                ),
                {},
            )
            application = rule.get("process") or rule.get("path") or f"rule #{rule_id}"
            changes = {
                "focus_rule_update": "update",
                "focus_rule_remove": "remove",
                "focus_rule_toggle": (
                    "enable" if arguments.get("enabled") else "disable"
                ),
                "focus_rule_category": f"move to {arguments.get('category')}",
            }
            return f"{changes.get(name, 'change')} Focus rule for {application}?"
        if prefix in item_types:
            record_key, id_key = item_types[prefix]
            item_id = arguments.get(id_key)
            record = next(
                (
                    item for item in records.get(record_key, [])
                    if str(item.get("id")) == str(item_id)
                ),
                {},
            )
            title = record.get("title") or f"{prefix} #{item_id}"
            if name.endswith("_create"):
                title = arguments.get("title") or title
                due_key = "deadline" if prefix == "task" else "due_at"
                due = arguments.get(due_key)
                due_text = (
                    datetime.fromtimestamp(due).astimezone().strftime("%Y-%m-%d %H:%M")
                    if isinstance(due, (int, float)) else ""
                )
                details = f" for {due_text}" if due_text else ""
                return f"create {prefix} '{title}'{details}?"
            if name.endswith("_delete"):
                return f"permanently delete {prefix} '{title}'?"
            if name.endswith("_complete"):
                return f"mark task '{title}' complete?"
            if name.endswith("_reopen"):
                return f"reopen task '{title}'?"
            if name.endswith("_add_note"):
                return f"add the note to task '{title}': “{arguments.get('note', '')}”?"
            changes = []
            field_names = {
                "deadline": "deadline",
                "due_at": "due time",
                "snooze_min": "snooze duration",
                "estimated_min": "estimate",
            }
            for key, value in arguments.items():
                if key in {"task_id", "reminder_id", "alarm_id", "confirmed"}:
                    continue
                if key in {"deadline", "due_at"} and isinstance(value, (int, float)):
                    value = datetime.fromtimestamp(value).astimezone().strftime(
                        "%Y-%m-%d %H:%M"
                    )
                elif key == "minutes":
                    value = f"{value} minutes"
                changes.append(f"{field_names.get(key, key)} to {value}")
            if name.endswith("_cancel"):
                return f"cancel {prefix} '{title}'?"
            if name.endswith("_dismiss"):
                return f"dismiss {prefix} '{title}'?"
            if name.endswith("_snooze"):
                return f"snooze {prefix} '{title}' for {arguments.get('minutes')} minutes?"
            return (
                f"update {prefix} '{title}'"
                + (f" ({', '.join(changes)})?" if changes else "?")
            )
        return f"perform {name.replace('_', ' ')}?"

    @staticmethod
    def _duplicate_target_question(
        name: str, arguments: dict[str, Any], records: dict[str, Any]
    ) -> str:
        record_key, id_key, label_key = {
            "task_id": ("tasks", "task_id", "title"),
            "reminder_id": ("reminders", "reminder_id", "title"),
            "alarm_id": ("alarms", "alarm_id", "title"),
            "rule_id": ("focus_apps", "rule_id", "process"),
        }.get(
            next(
                (key for key in ("task_id", "reminder_id", "alarm_id", "rule_id")
                 if key in arguments),
                "",
            ),
            ("", "", ""),
        )
        if not record_key:
            return ""
        selected_id = str(arguments.get(id_key, ""))
        candidates = [
            item for item in records.get(record_key, [])
            if str(item.get("id", "")) == selected_id
        ]
        if not candidates:
            return ""
        label = str(candidates[0].get(label_key, "")).strip().casefold()
        if not label:
            return ""
        duplicates = [
            item for item in records.get(record_key, [])
            if str(item.get(label_key, "")).strip().casefold() == label
        ]
        if len(duplicates) > 1:
            ids = ", ".join(str(item.get("id")) for item in duplicates)
            kind = record_key.rstrip("s")
            return (
                f"I found multiple {kind} records named '{candidates[0][label_key]}' "
                f"(IDs {ids}). Which one do you mean?"
            )
        return ""

    @staticmethod
    def _target_validation_message(
        name: str,
        arguments: dict[str, Any],
        records: dict[str, Any],
    ) -> str:
        key_map = {
            "task_id": ("tasks", "task"),
            "reminder_id": ("reminders", "reminder"),
            "alarm_id": ("alarms", "alarm"),
            "rule_id": ("focus_apps", "Focus app rule"),
            "note_id": ("saved_notes", "saved note"),
        }
        for argument, (record_key, label) in key_map.items():
            if argument not in arguments:
                continue
            if record_key not in records:
                return f"I couldn't verify that {label}; please list it and try again."
            if not any(
                str(item.get("id", "")) == str(arguments[argument])
                for item in records[record_key]
            ):
                return (
                    f"I couldn't find {label} #{arguments[argument]}. "
                    "No change was made."
                )
        return ""

    def _relevant_records(self, prompt: str) -> dict[str, Any]:
        text = prompt.casefold()
        records: dict[str, Any] = {}
        has_reference = bool(re.search(r"\b(it|that|this)\b", text))
        try:
            from jarvis.scheduling import task_service, reminder_service

            if any(word in text for word in (
                "task", "assignment", "project", "deadline", "completed",
                "todo", "to-do",
            )) or has_reference or re.match(r"^(task|done)\b", text):
                records["tasks"] = task_service.get_all_tasks()
            if has_reference or any(word in text for word in ("reminder", "alarm", "water", "meeting")):
                records["reminders"] = reminder_service.get_reminders(True)
                records["alarms"] = reminder_service.get_alarms(True)
            if has_reference or any(word in text for word in (
                "focus", "distracting", "productive", "always allow",
            )):
                settings = self.registry.settings
                if settings is not None:
                    records["focus_apps"] = settings.get("focus_app_rules", [])
            if "note" in text and any(word in text for word in ("delete", "remove")):
                from jarvis.ai import store

                records["saved_notes"] = store.list_memories()
        except Exception:
            log.exception("Could not load records for AI action resolution")
            raise
        return records

    @staticmethod
    def _format_outcome(
        name: str,
        outcome: dict[str, Any],
        arguments: dict[str, Any] | None = None,
    ) -> str:
        arguments = arguments or {}
        if outcome.get("error") == "confirmation_required":
            return (
                f"{outcome.get('message', 'This action needs confirmation')} "
                "I have not changed anything."
            )
        if not outcome.get("ok"):
            return f"⚠ I couldn't complete {name.replace('_', ' ')}: {outcome.get('message', outcome.get('error', 'operation failed'))}"
        result = outcome.get("result")
        if isinstance(result, dict):
            if result.get("deleted"):
                identifier = (
                    result.get("id") or result.get("task_id")
                    or result.get("reminder_id") or result.get("alarm_id")
                    or result.get("rule_id") or result.get("note_id")
                )
                suffix = f" #{identifier}" if identifier is not None else ""
                return f"Deleted {name.split('_')[0]}{suffix}."
            if name == "task_get_details":
                return AIAgent._format_record_details("Task", result)
            if name == "reminder_status":
                return AIAgent._format_record_details("Reminder", result)
            title = result.get("title")
            record_id = result.get("id")
            if name in {"task_create", "reminder_create", "alarm_create"}:
                created = "task" if name == "task_create" else (
                    "reminder" if name == "reminder_create" else "alarm"
                )
                message = f"Created {created}: {title or '(untitled)'}."
                due = AIAgent._format_timestamp(
                    result.get("deadline") or result.get("due_at")
                )
                return message + (f" Due {due}." if due else "")
            if name in {"task_update", "reminder_update", "alarm_update"}:
                kind = name.split("_")[0]
                fields = {
                    key: value for key, value in arguments.items()
                    if key not in {
                        "task_id", "reminder_id", "alarm_id", "confirmed",
                    }
                }
                changed = []
                for key, value in fields.items():
                    if key in {"deadline", "due_at"}:
                        value = AIAgent._format_timestamp(value)
                        label = "deadline" if key == "deadline" else "due"
                    else:
                        label = key.replace("_", " ")
                    changed.append(f"{label}: {value}")
                return (
                    f"Updated {kind} {title or f'#{record_id}'}"
                    + (f" — {', '.join(changed)}." if changed else ".")
                )
            if name == "task_complete":
                return f"Marked task {title or f'#{record_id}'} complete."
            if name == "task_reopen":
                return f"Reopened task {title or f'#{record_id}'}."
            if name == "task_add_note":
                return f"Added a timestamped note to task {title or f'#{record_id}'}."
            if name in {"reminder_snooze", "alarm_snooze"}:
                kind = name.split("_")[0]
                due = AIAgent._format_timestamp(result.get("due_at"))
                return (
                    f"Snoozed {kind} {title or f'#{record_id}'} for "
                    f"{arguments.get('minutes')} minute(s)"
                    + (f" until {due}." if due else ".")
                )
            if name == "focus_settings":
                values = ", ".join(
                    f"{key.replace('focus_', '').replace('_', ' ')}: {value}"
                    for key, value in (
                        arguments.items() if arguments else result.items()
                    )
                )
                action = "Updated" if arguments else "Focus"
                return f"{action} settings — {values}."
            if name == "focus_rule_remove":
                return f"Removed Focus app rule #{result.get('rule_id')}."
            if name.startswith("focus_rule_"):
                process = result.get("process") or result.get("path") or result.get("id")
                details = []
                if result.get("category"):
                    details.append(str(result["category"]))
                if "enabled" in result:
                    details.append("enabled" if result["enabled"] else "disabled")
                suffix = f" ({', '.join(details)})" if details else ""
                return f"Updated Focus app rule for {process}{suffix}."
            if name in {"focus_start", "focus_stop"} and result.get("message"):
                return str(result["message"])
            if name == "focus_get" and result.get("status"):
                return str(result["status"])
            if name == "app_status":
                return "Application status: " + json.dumps(result, ensure_ascii=False)
            if name == "clipboard_write":
                return f"Copied {result.get('characters', 0)} characters to the clipboard."
            if title is not None:
                suffix = f" (#{record_id})" if record_id is not None else ""
                return f"Done: {title}{suffix}."
            if "state" in result:
                return f"Done. Focus is now {result['state']}."
            if "active_task_count" in result:
                return (
                    f"Today's briefing: {result['active_task_count']} active task(s) "
                    f"and {result['upcoming_reminder_count']} upcoming reminder(s)."
                )
            return f"Done: {name.replace('_', ' ')}."
        if isinstance(result, list):
            if not result:
                return "There are no matching records."
            lines = []
            for item in result[:20]:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("process") or item.get("id")
                    status = item.get("status")
                    due = AIAgent._format_timestamp(item.get("deadline") or item.get("due_at"))
                    lines.append(
                        f"- {title}"
                        + (f" ({status})" if status else "")
                        + (f" — {item['category']}" if item.get("category") else "")
                        + (
                            f" — {'enabled' if item['enabled'] else 'disabled'}"
                            if "enabled" in item else ""
                        )
                        + (f" — {due}" if due else "")
                    )
                else:
                    lines.append(f"- {item}")
            return "\n".join(lines)
        if isinstance(result, str):
            return result
        return f"Done: {name.replace('_', ' ')}."

    @staticmethod
    def _format_record_details(label: str, record: dict[str, Any]) -> str:
        title = record.get("title") or f"#{record.get('id', '')}"
        details = [f"{label}: {title}"]
        if record.get("status"):
            details.append(f"Status: {record['status']}")
        if record.get("priority") is not None:
            details.append(f"Priority: {record['priority']}")
        if record.get("description"):
            details.append(f"Description: {record['description']}")
        due = AIAgent._format_timestamp(record.get("deadline") or record.get("due_at"))
        if due:
            details.append(f"Due: {due}")
        return "\n".join(details)

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            return ""
        return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M")
