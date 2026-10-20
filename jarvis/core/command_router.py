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
from datetime import datetime
from typing import Callable

log = logging.getLogger(__name__)

CommandHandler = Callable[[str], str]


class CommandRouter:
    def __init__(self) -> None:
        self._commands: dict[str, CommandHandler] = {}
        self._ai_fallback: CommandHandler | None = None
        # Launcher injected after construction via set_launcher()
        self._launcher = None
        self._register_builtins()

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, name: str) -> Callable[[CommandHandler], CommandHandler]:
        def decorator(fn: CommandHandler) -> CommandHandler:
            self._commands[name.lower()] = fn
            return fn
        return decorator

    def register_ai_fallback(self, handler: CommandHandler) -> None:
        self._ai_fallback = handler

    def set_launcher(self, launcher) -> None:
        """Inject the WindowsAppLauncher after construction."""
        self._launcher = launcher

    # ── Routing ──────────────────────────────────────────────────────────────

    def route(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        key = text.lower().split()[0]
        handler = self._commands.get(key)
        if handler:
            try:
                return handler(text)
            except Exception as exc:
                log.exception("Command '%s' failed", key)
                return f"⚠ Error running '{key}': {exc}"

        if self._ai_fallback:
            return self._ai_fallback(text)

        return (
            f"I don't recognise '{key}'. "
            f"Try: {', '.join(sorted(self._commands.keys()))}"
        )

    # ── Built-in commands ─────────────────────────────────────────────────────

    def _register_builtins(self) -> None:

        @self.register("hello")
        def _(text): return "👋 Hello! I'm JARVIS v2, your desktop AI companion!"

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
                "State cycle: THINKING → SUCCESS → IDLE.\n"
                "Phase 2 adds voice, reminders, focus mode and app launching."
            )

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
                return self._launcher.launch(app_name)
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
            # "remind me in 30 minutes to check code"
            # "remind me tomorrow at 7pm to submit assignment"
            from jarvis.scheduling.reminder_service import (
                add_reminder, parse_time_expression
            )
            lower = text.lower()
            # Strip the "remind me" prefix
            body = re.sub(r"^remind\s+(me\s+)?", "", lower, flags=re.I).strip()

            # Split on "to " — left side is time, right is title
            to_match = re.search(r"\bto\b(.+)$", body, re.I)
            title = to_match.group(1).strip().capitalize() if to_match else body
            time_part = body[:to_match.start()].strip() if to_match else body

            due = parse_time_expression(time_part or body)
            if due is None:
                return (
                    "⚠ I couldn't understand the time.\n"
                    "Try: remind me in 30 minutes to check code\n"
                    "     remind me tomorrow at 9am to submit assignment"
                )
            add_reminder(title or "Reminder", due)
            from jarvis.scheduling.reminder_service import format_due
            return f"✅ Reminder set: '{title}' — {format_due(due)}"

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
            return f"📋 Task added: '{body.capitalize()}'"

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
            from jarvis.scheduling.task_service import complete_task
            complete_task(int(parts[1]))
            return f"✅ Task {parts[1]} marked done!"

        # ── Focus stub ────────────────────────────────────────────────────────

        @self.register("focus")
        def _(text):
            return "🎯 Focus mode coming in Phase 2! (Pomodoro timer + distraction nudges)"

        # ── Wellness stub ─────────────────────────────────────────────────────
        @self.register("hydration")
        def _(text): return "💧 Hydration reminders coming in Phase 2!"

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
