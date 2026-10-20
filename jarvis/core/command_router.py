"""
core/command_router.py — Routes text commands to built-in handlers
or, in future phases, to the configured AI provider.

Phase 2 additions:
  • open / launch  — Windows app launcher integration
  • time           — current time
  • apps           — list launchable apps
  • reminder (stub)
  • focus (stub)
"""
from __future__ import annotations

import logging
import re
import random
from datetime import datetime
from typing import Callable

log = logging.getLogger(__name__)

CommandHandler = Callable[[str], str]


class CommandRouter:
    def __init__(self) -> None:
        self._commands: dict[str, CommandHandler] = {}
        self._ai_fallback: CommandHandler | None = None
        self._ai_stream_fallback: Callable[[str, Callable[[str], None]], str] | None = None
        self._ai_keywords: list[str] = []
        self._custom_commands: list[dict] = []
        self._custom_actions: dict[str, Callable[[dict], str]] = {}
        self._responses: dict[str, list[str]] = {}
        # Launcher injected after construction via set_launcher()
        self._launcher = None
        self._register_builtins()

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, name: str) -> Callable[[CommandHandler], CommandHandler]:
        def decorator(fn: CommandHandler) -> CommandHandler:
            self._commands[name.lower()] = fn
            return fn
        return decorator

    def register_ai_fallback(
        self,
        handler: CommandHandler,
        stream_handler: Callable[[str, Callable[[str], None]], str] | None = None,
    ) -> None:
        self._ai_fallback = handler
        self._ai_stream_fallback = stream_handler

    def has_builtin(self, text: str) -> bool:
        """Return whether this input resolves to a registered local command."""
        try:
            matches_custom = self._match_custom(text) is not None
        except ValueError:
            # Route ambiguous matches locally so the user receives an actionable error.
            matches_custom = True
        return (
            bool(text.strip())
            and not self._strip_ai_keyword(text)[1]
            and (
                text.strip().lower().split()[0] in self._commands
                or matches_custom
            )
        )

    def set_ai_keywords(self, keywords: list[str]) -> None:
        self._ai_keywords = [self._normalize(item) for item in keywords if self._normalize(item)]

    def set_responses(self, responses: dict[str, list[str]]) -> None:
        self._responses = dict(responses)

    def response(self, key: str, fallback: str, **values: str) -> str:
        templates = self._responses.get(key)
        if not templates:
            return fallback.format(**values)
        try:
            return random.choice(templates).format(**values)
        except (KeyError, ValueError) as exc:
            log.error("Invalid response template '%s': %s", key, exc)
            return fallback.format(**values)

    def set_custom_commands(
        self,
        commands: list[dict],
        actions: dict[str, Callable[[dict], str]],
    ) -> None:
        for command in commands:
            if command.get("enabled", True):
                action = command.get("action")
                if action not in actions:
                    raise ValueError(f"No registered action handler for '{action}'.")
        self._custom_commands = list(commands)
        self._custom_actions = actions

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.casefold().strip()
        text = re.sub(r"[^\w\s]", " ", text)
        return " ".join(text.split())

    def _strip_ai_keyword(self, text: str) -> tuple[str, bool]:
        normalized = text.strip()
        for keyword in sorted(self._ai_keywords, key=len, reverse=True):
            if re.match(rf"^{re.escape(keyword)}(?:\b|[,!:])", normalized, re.I):
                query = re.sub(
                    rf"^{re.escape(keyword)}\s*[,!:]?\s*",
                    "",
                    normalized,
                    count=1,
                    flags=re.I,
                ).strip()
                return query, True
        return normalized, False

    def _match_custom(self, text: str) -> dict | None:
        normalized = self._normalize(text)
        matches = [
            command for command in self._custom_commands
            if command.get("enabled", True)
            and normalized in {
                self._normalize(phrase)
                for phrase in command.get("triggers", []) + command.get("aliases", [])
            }
        ]
        if len(matches) > 1:
            raise ValueError(
                "This phrase matches multiple custom commands. "
                "Give each command a distinct trigger."
            )
        return matches[0] if matches else None

    def _route_local_or_custom(self, text: str) -> str | None:
        custom = self._match_custom(text)
        if custom is not None:
            handler = self._custom_actions[custom["action"]]
            result = handler(dict(custom.get("arguments", {})))
            if result.startswith(("❌", "⚠")):
                return result
            reply = custom.get("reply")
            if reply:
                try:
                    return reply.format(**custom.get("arguments", {}))
                except (KeyError, ValueError) as exc:
                    log.error("Invalid reply template for %s: %s", custom["id"], exc)
            return result
        key = text.strip().lower().split()[0] if text.strip() else ""
        handler = self._commands.get(key)
        if handler is None:
            return None
        try:
            return handler(text)
        except Exception as exc:
            log.exception("Command '%s' failed", key)
            return f"⚠ Error running '{key}': {exc}"

    def route_stream(self, text: str, on_chunk: Callable[[str], None]) -> str:
        """Route one command and forward response chunks as they become available."""
        text = text.strip()
        if not text:
            return ""
        query, forced_ai = self._strip_ai_keyword(text)
        if forced_ai:
            if not query:
                response = "Please add a question after the AI keyword."
                on_chunk(response)
                return response
            if not self._ai_stream_fallback and not self._ai_fallback:
                response = self.response(
                    "ai_unavailable",
                    "⚠ AI provider is unavailable. Local commands still work.",
                )
                on_chunk(response)
                return response
            try:
                if self._ai_stream_fallback:
                    return self._ai_stream_fallback(query, on_chunk)
                response = self._ai_fallback(query)
                on_chunk(response)
                return response
            except Exception as exc:
                log.exception("AI request failed")
                response = f"⚠ AI request failed: {exc}"
                on_chunk(response)
                return response
        key = text.lower().split()[0]
        try:
            try:
                response = self._route_local_or_custom(text)
            except ValueError as exc:
                return f"⚠ {exc}"
            if response is not None:
                if response:
                    on_chunk(response)
                return response
            if self._ai_stream_fallback:
                return self._ai_stream_fallback(text, on_chunk)
            response = self._ai_fallback(text) if self._ai_fallback else self.route(text)
            if response:
                on_chunk(response)
            return response
        except Exception as exc:
            log.exception("Streaming command '%s' failed", key)
            response = f"⚠ Error running '{key}': {exc}"
            on_chunk(response)
            return response

    def set_launcher(self, launcher) -> None:
        """Inject the WindowsAppLauncher after construction."""
        self._launcher = launcher

    # ── Routing ──────────────────────────────────────────────────────────────

    def route(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        query, forced_ai = self._strip_ai_keyword(text)
        if forced_ai:
            if not query:
                return "Please add a question after the AI keyword."
            if self._ai_fallback:
                return self._ai_fallback(query)
            return self.response(
                "ai_unavailable",
                "⚠ AI provider is unavailable. Local commands still work.",
            )
        key = text.lower().split()[0]
        try:
            response = self._route_local_or_custom(text)
        except ValueError as exc:
            return f"⚠ {exc}"
        if response is not None:
            return response

        if self._ai_fallback:
            return self._ai_fallback(text)

        return self.response(
            "unsupported_command",
            f"I don't recognise '{key}'. Try: {', '.join(sorted(self._commands.keys()))}",
        )

    # ── Built-in commands ─────────────────────────────────────────────────────

    def _register_builtins(self) -> None:

        @self.register("hello")
        def _(text):
            return self.response(
                "greeting", "👋 Hello! I'm JARVIS v2, your desktop AI companion!"
            )

        @self.register("help")
        def _(text):
            cmds = sorted(self._commands.keys())
            return "Available commands:\n" + "  ".join(cmds)

        @self.register("status")
        def _(text): return "✅ JARVIS v2.0.0 is fully operational."

        @self.register("demo")
        def _(text):
            return (
                "🤖 Demo mode!\n"
                "State cycle: THINKING → SUCCESS → IDLE."
            )

        @self.register("goodbye")
        def _(text):
            return self.response("goodbye", "Goodbye! I'll be here when you need me.")

        @self.register("version")
        def _(text):
            from jarvis import __version__
            return f"JARVIS v{__version__}"

        @self.register("time")
        def _(text):
            now = datetime.now().strftime("%I:%M %p, %A %d %B %Y")
            return f"🕐 It's {now}"

        @self.register("date")
        def _(text):
            now = datetime.now().strftime("%A, %d %B %Y")
            return f"📅 Today is {now}"

        # ── App launcher ──────────────────────────────────────────────────────
        # Handles: "open chrome", "launch vscode", "open file explorer"

        def _open_handler(text: str) -> str:
            parts = text.split(None, 1)
            if len(parts) < 2:
                return (
                    "What would you like me to open?\n"
                    "Example: open chrome, open vscode, open file explorer"
                )
            app_name = parts[1].strip()
            if self._launcher:
                result = self._launcher.launch(app_name)
                if result.startswith(("❌", "⚠")):
                    return self.response(
                        "app_open_failed", result,
                        app_name=app_name, error=result,
                    )
                return self.response(
                    "app_opened", result, app_name=app_name
                )
            return f"🚀 Would open '{app_name}' (launcher not configured)."

        self._commands["open"]   = _open_handler
        self._commands["launch"] = _open_handler
        self._commands["start"]  = _open_handler

        @self.register("apps")
        def _(text):
            if self._launcher:
                names = self._launcher.list_known()
                return "🖥 I can open:\n" + ", ".join(names)
            return "App launcher not configured."

        # ── Reminders (live, SQLite-backed) ───────────────────────────────
        @self.register("remind")
        def _(text):
            from jarvis.scheduling.reminder_service import (
                add_reminder, parse_time_expression
            )
            body = re.sub(r"^remind(?:\s+me)?\s+", "", text, flags=re.I).strip()
            to_match = re.search(r"\bto\b(.+)$", body, re.I)
            title = to_match.group(1).strip().rstrip(".!?") if to_match else "Reminder"
            time_part = body[:to_match.start()].strip() if to_match else body
            due = parse_time_expression(time_part)
            if due is None:
                return (
                    "⚠ I couldn't understand the time.\n"
                    "Try: remind me in 5 seconds to test the notification."
                )
            try:
                rid = add_reminder(title or "Reminder", due)
            except Exception as exc:
                log.exception("Reminder creation failed")
                return f"⚠ Reminder was not saved: {exc}"
            from jarvis.scheduling.reminder_service import format_due
            return self.response(
                "reminder_created",
                f"✅ Reminder #{rid} set: '{title}' — {format_due(due)}",
                title=title,
            )

        @self.register("reminder")
        def _(text): return self._commands["remind"](text)

        @self.register("reminders")
        def _(text):
            from jarvis.scheduling.reminder_service import get_upcoming_reminders, format_due
            items = get_upcoming_reminders(limit=8)
            if not items:
                return "📋 No upcoming reminders."
            lines = [f"📋 Upcoming reminders ({len(items)}):"]
            for r in items:
                lines.append(f"  • {r['title']} — {format_due(r['due_at'])}")
            return "\n".join(lines)

        @self.register("alarm")
        def _(text):
            from jarvis.scheduling.reminder_service import add_alarm, parse_time_expression, format_due
            lower = text.lower()
            body = re.sub(r"^alarm\s+(for\s+|at\s+)?", "", lower, flags=re.I).strip()
            due = parse_time_expression(body)
            if due is None:
                return (
                    "⚠ I couldn't parse the alarm time.\n"
                    "Try: alarm at 7:00 AM\n"
                    "     alarm in 2 hours"
                )
            title = f"Alarm at {__import__('datetime').datetime.fromtimestamp(due).strftime('%I:%M %p')}"
            add_alarm(title, due)
            return f"⏰ Alarm set: {format_due(due)}"

        @self.register("set")
        def _(text):
            if re.match(r"^set\s+(?:an?\s+)?alarm\b", text, re.I):
                body = re.sub(r"^set\s+(?:an?\s+)?alarm\s*", "", text, flags=re.I)
                body = re.sub(r"^(?:in|for|at)\s+", "", body, flags=re.I)
                return self._commands["alarm"](f"alarm {body}")
            if re.match(r"^set\s+(?:a\s+)?reminder\b", text, re.I):
                body = re.sub(r"^set\s+(?:a\s+)?reminder\s*", "", text, flags=re.I)
                body = re.sub(r"^(?:in|for)\s+", "in ", body, flags=re.I)
                return self._commands["remind"](f"remind me {body}")
            return "Try: set a reminder for 1 minute to stretch, or set an alarm in 10 seconds."

        @self.register("alarms")
        def _(text):
            from jarvis.scheduling.reminder_service import get_alarms, format_due
            items = get_alarms()
            if not items:
                return "⏰ No alarms set."
            lines = [f"⏰ Alarms ({len(items)}):"]
            for a in items:
                lines.append(f"  • {a['title']} — {format_due(a['due_at'])}")
            return "\n".join(lines)

        # ── Task manager (Part G) ─────────────────────────────────────────────
        @self.register("task")
        def _(text):
            body = re.sub(r"^task\s*", "", text, flags=re.I).strip()
            if not body:
                return "Usage: task <title>  (e.g. task finish the report)"
            from jarvis.scheduling.task_service import add_task
            add_task(body.capitalize())
            return self.response(
                "task_created",
                f"📋 Task added: '{body.capitalize()}'",
                task_title=body.capitalize(),
            )

        @self.register("tasks")
        def _(text):
            from jarvis.scheduling.task_service import get_tasks, format_task
            items = get_tasks()
            if not items:
                return "📋 No open tasks. Type 'task <title>' to add one."
            lines = [f"📋 Open tasks ({len(items)}):"]
            for t in items:
                lines.append(f"  {format_task(t)}")
            return "\n".join(lines)

        @self.register("done")
        def _(text):
            # "done 1" → complete task by id
            parts = text.split()
            if len(parts) < 2 or not parts[1].isdigit():
                return "Usage: done <task_id>  (see 'tasks' for IDs)"
            from jarvis.scheduling.task_service import complete_task, get_all_tasks
            task_id = int(parts[1])
            task = next((item for item in get_all_tasks() if item["id"] == task_id), None)
            complete_task(task_id)
            title = task["title"] if task else parts[1]
            return self.response(
                "task_completed",
                f"✅ Task {parts[1]} marked done!",
                task_title=title,
            )

        # ── Focus stub ────────────────────────────────────────────────────────

        @self.register("focus")
        def _(text):
            return "🎯 Focus controls: focus start, focus stop, focus status, focus skip."

        # ── Wellness stub ─────────────────────────────────────────────────────
        @self.register("hydration")
        def _(text): return "💧 Hydration reminders run automatically when Wellness is enabled in Settings."

        # ── System ────────────────────────────────────────────────────────────
        @self.register("pause")
        def _(text): return "⏸ Use the tray icon or right-click to pause JARVIS."

        @self.register("exit")
        def _(text): return "To exit, right-click the robot → Exit JARVIS."

        @self.register("settings")
        def _(text): return "⚙ Right-click the robot → Settings (or tray icon → Settings)."

        @self.register("opacity")
        def _(text):
            parts = text.split()
            return (
                "Set opacity in Settings → Appearance tab."
                if len(parts) < 2 else
                f"Set opacity in Settings → Appearance tab (value: {parts[1]}%)"
            )
