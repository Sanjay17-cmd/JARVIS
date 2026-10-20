"""
app.py — Application entry point and lifecycle manager — JARVIS v2.0.0

Phase 2 changes:
  • panels_always_on_top: read from settings and passed to both
    InteractionPanel and SettingsDialog at construction + every time
    settings change (live apply, no restart needed).
  • All overlay settings applied on settings_changed (opacity, movement,
    always-on-top, animation).
  • version bump to 2.0.0.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QApplication

# ── logging setup (must run before importing jarvis modules) ────────────────

def _setup_logging(level: str = "INFO") -> None:
    log_dir = Path(os.environ.get("APPDATA", Path.home())) / "JARVIS" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "jarvis.log"

    root = logging.getLogger()
    # Avoid adding duplicate handlers on repeated calls
    if not root.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
        )
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(sh)
        root.addHandler(fh)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))


_setup_logging()
log = logging.getLogger(__name__)

from jarvis.config import Settings
from jarvis.core import StateManager, RobotState, EventBus, CommandRouter
from jarvis.ui.overlay import RobotOverlay
from jarvis.ui.interaction_panel import InteractionPanel
from jarvis.ui.tray import TrayManager
from jarvis.ui.settings_dialog import SettingsDialog
from jarvis.actions.windows_app_launcher import WindowsAppLauncher
from jarvis.config.behavior_config import BehaviorConfig


class JarvisApp:
    """Top-level application controller — JARVIS v2.0.0."""

    def __init__(self) -> None:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        self._qt_app = QApplication.instance() or QApplication(sys.argv)
        self._qt_app.setApplicationName("JARVIS")
        self._qt_app.setApplicationVersion("2.0.0")
        self._qt_app.setOrganizationName("JARVISProject")
        self._qt_app.setQuitOnLastWindowClosed(False)

        # ── Core services ─────────────────────────────────────────────────
        self._settings      = Settings()
        self._state_manager = StateManager()
        self._event_bus     = EventBus()
        self._router        = CommandRouter()
        self._behavior = BehaviorConfig()
        self._behavior_error = ""
        try:
            self._router.set_responses(
                self._behavior.load("responses").get("responses", {})
            )
        except Exception as exc:
            self._behavior_error = str(exc)
            log.error("Behavior responses could not be loaded: %s", exc)
        self._router.set_ai_keywords(self._ai_keywords())

        # Advanced config (INI — user-editable)
        from jarvis.config.advanced_config import AdvancedConfig
        self._adv = AdvancedConfig()
        # Merge advanced values that the overlay/services need
        self._settings.set("movement_speed", self._adv.get("movement_speed", 1.2))
        self._settings.set("safe_margin",    self._adv.get("safe_margin",    20))
        self._settings.set("animation_fps",  self._adv.get("animation_fps",  30))
        self._settings.set("tts_rate",       self._adv.get("tts_rate",       175))
        legacy_model_path = self._adv.get("voice_model_path", "")
        if legacy_model_path and not self._settings.get("voice_model_path", ""):
            self._settings.set("voice_model_path", legacy_model_path)
            self._settings.save()

        _setup_logging(self._settings.get("log_level", "INFO"))
        log.info("JARVIS v2.0.0 starting up…")

        # ── App launcher ──────────────────────────────────────────────────
        self._launcher = WindowsAppLauncher(
            custom_apps=self._settings.get("custom_apps", [])
        )
        self._router.set_launcher(self._launcher)

        # ── Scheduling service ────────────────────────────────────────────
        from jarvis.scheduling import database as sched_db
        sched_db.get_conn()
        self._sched_timer = None

        # ── Part K — mic/camera state tracking ───────────────────────────
        self._mic_active    = False
        self._camera_active = False

        # ── Part J — AI provider ──────────────────────────────────────────
        from jarvis.ai.provider import get_provider
        self._ai_provider_factory = get_provider
        self._configure_ai_provider()

        # ── UI ────────────────────────────────────────────────────────────
        panels_top = self._settings.get("panels_always_on_top", True)

        self._overlay = RobotOverlay(
            self._settings, self._state_manager, self._event_bus
        )
        # InteractionPanel receives the panels_always_on_top flag at init
        self._panel = InteractionPanel(
            self._state_manager,
            self._event_bus,
            self._router,
            panels_always_on_top=panels_top,
            settings=self._settings,
        )
        self._tray = TrayManager(
            self._state_manager, self._event_bus
        )

        # ── Signal wiring ─────────────────────────────────────────────────
        self._overlay.robot_clicked.connect(self._toggle_panel)
        self._panel.open_tasks_requested.connect(self._open_tasks)
        self._panel.voice_active_changed.connect(self.set_mic_active)

        self._tray.show_requested.connect(self._overlay.show)
        self._tray.hide_requested.connect(self._overlay.hide)
        self._tray.hide_requested.connect(self._panel.hide)
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.pause_requested.connect(self._toggle_pause)
        self._tray.exit_requested.connect(self._exit)

        # Panel close button
        self._panel.close_requested.connect(self._panel.hide)

        # ── Event bus subscriptions ────────────────────────────────────────
        self._event_bus.subscribe("open_settings",  lambda **_: self._open_settings())
        self._event_bus.subscribe("toggle_pause",   lambda **_: self._toggle_pause())
        self._event_bus.subscribe("exit_requested", lambda **_: self._exit())

        # ── Chest button actions ───────────────────────────────────────────
        self._event_bus.subscribe("toggle_voice",    lambda **_: self._chest_voice())
        self._event_bus.subscribe("toggle_focus",    lambda **_: self._chest_focus())
        self._event_bus.subscribe("open_reminders",  lambda **_: self._chest_reminders())
        self._event_bus.subscribe("open_quick_menu", lambda **_: self._chest_quick_menu())

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> int:
        self._tray.show()
        self._overlay.start()

        # ── Notification queue (Part I) ───────────────────────────────────
        from jarvis.ui.notification import NotificationQueue
        self._notif_queue = NotificationQueue.instance()

        # ── Wellness service (Part F) ─────────────────────────────────────
        from jarvis.scheduling.wellness_service import WellnessService
        self._wellness = WellnessService(self._settings, self._adv)
        self._wellness.start()

        # ── Focus service (Part H) ────────────────────────────────────────
        from jarvis.scheduling.focus_service import FocusService
        self._focus = FocusService(
            self._settings, self._adv,
            on_indicator=lambda active: self._overlay.set_chest_indicator(
                1, "#00ff60" if active else None
            ),
        )
        # Wire focus commands to router
        self._router._commands["focus"]      = self._focus_command
        self._router._commands["focusstop"]  = lambda t: self._focus.stop()
        self._router._commands["focusskip"]  = lambda t: self._focus.skip_break()
        self._router._commands["focusstatus"]= lambda t: self._focus.status()
        self._register_custom_actions()
        self._reload_behavior_config()

        # ── Scheduler tick (Part E) ───────────────────────────────────────
        from PySide6.QtCore import QTimer as _QTimer
        self._sched_timer = _QTimer()
        # Overdue entries found after startup are delivered once on the first tick.
        self._sched_timer.setInterval(1_000)
        self._sched_timer.timeout.connect(self._on_scheduler_tick)
        self._sched_timer.start()

        log.info("JARVIS overlay started.")
        return self._qt_app.exec()

    @Slot()
    def _on_scheduler_tick(self) -> None:
        from jarvis.scheduling.reminder_service import tick as _sched_tick
        try:
            events = _sched_tick()
            for ev in events:
                title   = ev.get("title", "Reminder")
                ev_type = ev.get("type", "reminder")
                source_key = str(ev.get("source_key", ""))
                if str(ev.get("source_key", "")).startswith("wellness:"):
                    if hasattr(self, "_wellness") and not self._wellness.can_deliver():
                        continue
                icon = (
                    "💧" if source_key == "wellness:hydration"
                    else "⏰" if ev_type == "alarm"
                    else "🔔"
                )
                if (
                    ev_type == "alarm"
                    and ev.get("sound", True)
                    and self._settings.get("sound_enabled", False)
                ):
                    try:
                        import winsound
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    except (ImportError, OSError):
                        log.warning("Alarm sound unavailable; using in-app notification.")
                from jarvis.ui.notification import notify
                item_id = int(ev["id"])
                if ev_type == "alarm":
                    done = lambda i=item_id: self._dismiss_due_item("alarm", i)
                    snooze = lambda i=item_id: self._snooze_due_item("alarm", i)
                    animation = "alarm"
                else:
                    recurring = str(ev.get("recurrence", "")).startswith("interval:")
                    if recurring:
                        done = lambda i=item_id: self._ack_recurring_reminder(i)
                    else:
                        done = lambda i=item_id: self._dismiss_due_item(
                            "reminder", i, complete=True
                        )
                    snooze = lambda i=item_id: self._snooze_due_item("reminder", i)
                    animation = (
                        "thirsty"
                        if source_key == "wellness:hydration"
                        or "water" in title.casefold()
                        or "drink" in title.casefold()
                        else "success"
                    )
                notify(
                    icon, title, ev.get("description", ""),
                    duration_ms=30000,
                    actions=[
                        ("Done", done),
                        ("Snooze 5 minutes", snooze),
                        ("Dismiss", lambda i=item_id, t=ev_type: self._dismiss_due_item(t, i)),
                    ],
                )
                self._overlay.play_animation(animation, duration_ms=6000)
                # Overlay status bar
                self._overlay.show_status(f"{icon} {title}", 6000)
                # Chest indicator (Part K)
                self.set_reminder_due(True)
                from PySide6.QtCore import QTimer as _T
                _T.singleShot(10000, lambda: self.set_reminder_due(False))
                log.info("Due %s: %s", ev_type, title)
        except Exception as exc:
            log.warning("Scheduler tick error: %s", exc)

    def _exit(self) -> None:
        log.info("JARVIS shutting down…")
        pos = self._overlay.pos()
        self._settings.set("start_x", pos.x())
        self._settings.set("start_y", pos.y())
        self._settings.save()
        if self._sched_timer:
            self._sched_timer.stop()
        if hasattr(self, "_wellness"):
            self._wellness.stop()
        if hasattr(self, "_focus"):
            self._focus.stop()
        if hasattr(self, "_panel") and self._panel._voice is not None:
            self._panel._voice.stop()
        from jarvis.scheduling import database as sched_db
        sched_db.close()
        self._overlay.stop()
        self._tray.hide()
        self._qt_app.quit()

    # ── Panel toggle ──────────────────────────────────────────────────────

    def _toggle_panel(self) -> None:
        if self._panel.isVisible():
            self._panel.hide()
            return

        # Position panel next to overlay, respecting screen edge
        ov_geo = self._overlay.geometry()
        px = ov_geo.right() + 10
        py = ov_geo.top()

        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().availableGeometry()
        panel_w = self._panel.sizeHint().width() or 360
        if px + panel_w > screen.right():
            px = ov_geo.left() - panel_w - 10
        # Clamp vertically
        py = max(screen.top(), min(py, screen.bottom() - 400))

        self._panel.move(px, py)
        self._panel.adjustSize()
        self._panel.show()
        self._panel.raise_()
        self._panel._input.setFocus()

    # ── Settings ──────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        panels_top = self._settings.get("panels_always_on_top", True)
        dlg = SettingsDialog(
            self._settings,
            panels_always_on_top=panels_top,
            behavior=self._behavior,
            router=self._router,
            voice_controller=self._panel._voice,
            overlay=self._overlay,
            parent=None,
        )
        dlg.settings_changed.connect(self._apply_settings)
        # Centre near the overlay
        ov_geo = self._overlay.geometry()
        dlg.adjustSize()
        dlg.move(
            ov_geo.center().x() - dlg.width() // 2,
            ov_geo.center().y() - dlg.height() // 2,
        )
        dlg.exec()

    def _open_tasks(self) -> None:
        from jarvis.ui.task_dialog import TaskDialog

        dlg = TaskDialog(
            panels_always_on_top=self._settings.get("panels_always_on_top", True),
            parent=self._panel,
        )
        dlg.exec()

    def _open_reminders(self) -> None:
        from jarvis.ui.reminders_dialog import RemindersDialog

        RemindersDialog(
            panels_always_on_top=self._settings.get("panels_always_on_top", True),
            parent=self._panel,
        ).exec()

    def _dismiss_due_item(
        self, kind: str, item_id: int, complete: bool = False
    ) -> None:
        from jarvis.scheduling import reminder_service
        if kind == "reminder":
            if complete:
                reminder_service.complete_reminder(item_id)
            else:
                reminder_service.dismiss_reminder(item_id)
        else:
            reminder_service.dismiss_alarm(item_id)

    def _snooze_due_item(self, kind: str, item_id: int) -> None:
        from jarvis.scheduling import reminder_service
        if kind == "reminder":
            reminder_service.snooze_reminder(item_id, seconds=300)
        else:
            reminder_service.snooze_alarm(item_id, seconds=300)

    @staticmethod
    def _ack_recurring_reminder(item_id: int) -> None:
        from jarvis.scheduling.reminder_service import acknowledge_recurring_reminder
        acknowledge_recurring_reminder(item_id)

    def _ai_keywords(self) -> list[str]:
        if not self._settings.get("ai_trigger_enabled", True):
            return []
        keyword = str(self._settings.get("ai_trigger_keyword", "Friday")).strip()
        aliases = self._settings.get("ai_trigger_aliases", [])
        return ([keyword] if keyword else []) + [
            str(alias).strip() for alias in aliases if str(alias).strip()
        ]

    def _configure_ai_provider(self) -> None:
        self._ai_provider = self._ai_provider_factory(self._settings)
        stream_handler = getattr(self._ai_provider, "ask_stream", None)
        self._router.register_ai_fallback(self._ai_provider.ask, stream_handler)
        log.info("AI provider: %s", self._ai_provider.name)

    def _register_custom_actions(self) -> None:
        import time
        import webbrowser
        from urllib.parse import urlparse

        def open_app(args: dict) -> str:
            name = str(args.get("app_name", "")).strip()
            return self._launcher.launch(name) if name else "❌ app_name is required."

        def open_website(args: dict) -> str:
            url = str(args.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return "❌ Website URL must use http:// or https://."
            if not webbrowser.open(url):
                return f"❌ Could not open {url}."
            return f"Opening {url}."

        def create_scheduled(kind: str, args: dict) -> str:
            try:
                seconds = int(args.get("seconds", 0))
                title = str(args.get("title", "")).strip()
                if seconds <= 0 or not title:
                    return "❌ A title and positive seconds duration are required."
                from jarvis.scheduling import reminder_service
                due = time.time() + seconds
                item_id = (
                    reminder_service.add_reminder(title, due)
                    if kind == "reminder"
                    else reminder_service.add_alarm(title, due)
                )
                return f"Scheduled {kind} #{item_id}: {title}."
            except (TypeError, ValueError, OSError) as exc:
                log.exception("Could not create custom %s", kind)
                return f"❌ Could not create {kind}: {exc}"

        self._custom_actions = {
            "open_app": open_app,
            "open_website": open_website,
            "show_tasks": lambda _args: self._show_tasks_action(False),
            "show_completed_tasks": lambda _args: self._show_tasks_action(True),
            "create_reminder": lambda args: create_scheduled("reminder", args),
            "create_alarm": lambda args: create_scheduled("alarm", args),
            "start_focus": lambda args: self._focus.start_focus(int(args.get("minutes", 25))),
            "stop_focus": lambda _args: self._focus.stop(),
            "open_settings": lambda _args: self._open_settings() or "Opened Settings.",
            "play_animation": lambda args: self._play_animation_action(args),
            "new_chat": lambda _args: self._new_chat_action(),
            "daily_briefing": lambda _args: self._daily_briefing(),
        }

    def _reload_behavior_config(self) -> None:
        try:
            responses = self._behavior.load("responses").get("responses", {})
            commands = self._behavior.load("commands").get("commands", [])
            self._router.set_responses(responses)
            self._router.set_custom_commands(
                commands, getattr(self, "_custom_actions", {})
            )
            self._behavior_error = ""
        except Exception as exc:
            self._behavior_error = str(exc)
            log.error("Behavior configuration reload failed: %s", exc)

    def _show_tasks_action(self, completed: bool) -> str:
        from jarvis.ui.task_dialog import TaskDialog
        TaskDialog(
            self._settings.get("panels_always_on_top", True),
            self._panel,
            show_completed=completed,
        ).show()
        return "Opened Completed Tasks." if completed else "Opened Active Tasks."

    def _new_chat_action(self) -> str:
        self._panel.new_chat()
        if not self._panel.isVisible():
            self._toggle_panel()
        return "Started a new chat."

    def _play_animation_action(self, args: dict) -> str:
        name = str(args.get("name", "")).strip().casefold()
        name = {"fly": "flying", "repair": "tools", "scan": "scanning"}.get(name, name)
        if not self._overlay.play_animation(name):
            return f"❌ Animation '{name}' is not available."
        return f"Playing {name} animation."

    @staticmethod
    def _daily_briefing() -> str:
        from jarvis.scheduling.task_service import get_tasks
        from jarvis.scheduling.reminder_service import get_upcoming_reminders
        return (
            f"You have {len(get_tasks())} active task(s) and "
            f"{len(get_upcoming_reminders(5))} upcoming reminder(s)."
        )

    def _focus_command(self, text: str) -> str:
        action = text.lower().split()[1:] or ["start"]
        if action[0] in {"stop", "end"}:
            return self._focus.stop()
        if action[0] == "resume":
            return self._focus.resume()
        if action[0] == "pause":
            return self._focus.pause()
        if action[0] == "status":
            return self._focus.status()
        if action[0] in {"skip", "next"}:
            return self._focus.skip_break()
        if action[0] in {"start", "begin"}:
            return self._focus.start_focus()
        if action[0].isdigit():
            return self._focus.start_focus(int(action[0]))
        return "Usage: focus [minutes|start|stop|status|skip]"

    def _apply_settings(self) -> None:
        """Apply every changed setting to the live runtime immediately."""
        s = self._settings

        # 1. Opacity
        self._overlay.setWindowOpacity(s.get("opacity", 0.9))

        # 2. Robot always-on-top
        self._overlay.set_always_on_top(s.get("always_on_top", True))

        # 3. Robot size (live resize — regenerates frames on QThread)
        self._overlay.set_robot_size(s.get("robot_size", 120))

        # 4. Movement
        self._overlay.set_auto_movement(s.get("auto_movement", True))
        self._overlay._speed = s.get("movement_speed", 1.2)

        # Animation is gated inside the shared timer so movement remains active.

        # 6. panels_always_on_top
        panels_top = s.get("panels_always_on_top", True)
        self._panel.apply_topmost(panels_top)

        # 7. Startup registry
        try:
            from jarvis.core.settings_service import set_startup
            set_startup(s.get("launch_on_startup", False))
        except Exception as exc:
            log.warning("Startup registry: %s", exc)

        # 8. Custom apps
        self._launcher.update_custom_apps(s.get("custom_apps", []))
        self._router.set_ai_keywords(self._ai_keywords())
        self._configure_ai_provider()
        if hasattr(self, "_focus"):
            self._focus.refresh_rules()
        if hasattr(self, "_wellness"):
            self._wellness.refresh()

        log.info(
            "Settings applied — opacity=%.2f size=%d aot=%s move=%s panels_top=%s",
            s.get("opacity", 0.9), s.get("robot_size", 120),
            s.get("always_on_top", True), s.get("auto_movement", True), panels_top,
        )

    # ── Pause / resume ────────────────────────────────────────────────────

    def _toggle_pause(self) -> None:
        if self._state_manager.is_paused():
            self._state_manager.resume()
            self._overlay.set_auto_movement(
                self._settings.get("auto_movement", True)
            )
        else:
            self._state_manager.pause()
            self._overlay.set_auto_movement(False)

    # ── Part K — Mic / Camera chest indicators ────────────────────────────

    def set_mic_active(self, active: bool) -> None:
        """Called by voice service. Button 0 = cyan idle, green active, red muted."""
        self._mic_active = active
        color = "#00ff60" if active else None   # green=on, reset=idle-cyan
        self._overlay.set_chest_indicator(0, color)

    def set_mic_muted(self, muted: bool) -> None:
        color = "#ff3030" if muted else None
        self._overlay.set_chest_indicator(0, color)

    def set_camera_active(self, active: bool) -> None:
        """Future: called by camera/vision service. Button 1 indicator."""
        self._camera_active = active
        color = "#00ff60" if active else None
        self._overlay.set_chest_indicator(1, color)

    def set_reminder_due(self, has_due: bool) -> None:
        """Button 2 flashes amber when a reminder is due."""
        color = "#ff9900" if has_due else None
        self._overlay.set_chest_indicator(2, color)

    # ── Chest button handlers ─────────────────────────────────────────────

    def _chest_voice(self) -> None:
        """Open the panel and toggle push-to-talk capture."""
        self._panel.show()
        self._panel.raise_()
        self._panel.toggle_voice()

    def _chest_focus(self) -> None:
        """Start or stop the Pomodoro focus session."""
        if self._focus.is_active:
            self._focus.stop()
        else:
            self._focus.start_focus()

    def _chest_reminders(self) -> None:
        """Open the persistent reminder and alarm manager."""
        self._open_reminders()

    def _chest_quick_menu(self) -> None:
        """Open the panel's task manager and quick commands."""
        self._panel.show()
        self._panel.raise_()
        self._open_tasks()


def main() -> None:
    app = JarvisApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
