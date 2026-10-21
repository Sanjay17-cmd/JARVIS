from jarvis.ui.notification import NotificationQueue


class Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_notification_preferences_filter_master_and_category(qtbot, monkeypatch):
    queue = NotificationQueue()
    queued = []
    monkeypatch.setattr(queue, "_push_payload", queued.append)
    queue.configure(
        Settings(
            notifications_enabled=True,
            notification_reminders=False,
            notification_focus=True,
        )
    )

    queue.push("🔔", "Reminder", category="reminders")
    queue.push("🎯", "Focus", category="focus")

    assert len(queued) == 1
    assert queued[0][1] == "Focus"
    assert queued[0][-1] == "focus"

    queue.configure(Settings(notifications_enabled=False))
    queue.push("🔔", "Master disabled", category="reminders")
    assert len(queued) == 1


def test_unconfigured_notification_queue_keeps_existing_behavior(qtbot, monkeypatch):
    queue = NotificationQueue()
    queued = []
    monkeypatch.setattr(queue, "_push_payload", queued.append)

    queue.push("🔔", "Test notification")

    assert len(queued) == 1
    assert queued[0][1] == "Test notification"


def test_reminder_toast_stays_at_screen_bottom_even_with_robot_anchor(qtbot):
    from PySide6.QtGui import QGuiApplication
    from jarvis.ui.notification import _ToastWidget

    queue = NotificationQueue()
    queue.configure(Settings(), anchor=object())
    toast = _ToastWidget("🔔", "Reminder", "Task due")
    bounds = QGuiApplication.primaryScreen().availableGeometry()

    queue._place_toast(toast, 0)

    assert toast.geometry().right() == bounds.right() - 15
    assert toast.geometry().bottom() == bounds.bottom() - 15
    toast.close()
