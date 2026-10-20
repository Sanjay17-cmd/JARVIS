from jarvis.scheduling.focus_service import FocusService
from jarvis.scheduling.wellness_service import WellnessService


class _Settings:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class _Advanced:
    def get(self, key, default=None):
        return {
            "wellness_hydration_interval": 60,
            "wellness_stretch_interval": 60,
            "wellness_eyerest_interval": 20,
            "focus_duration_minutes": 25,
            "focus_nudge_cooldown_minutes": 10,
        }.get(key, default)


def test_wellness_only_starts_enabled_reminder_types(qtbot):
    settings = _Settings({
        "wellness_enabled": True,
        "wellness_hydration_enabled": True,
        "wellness_stretch_enabled": False,
        "wellness_eyerest_enabled": False,
    })
    service = WellnessService(settings, _Advanced())
    service.start()
    try:
        assert set(service._timers) == {"hydration"}
    finally:
        service.stop()


def test_focus_duration_is_bounded(qtbot):
    service = FocusService(_Settings({}), _Advanced())
    assert "between 1 and 240" in service.start_focus(0)
    assert "between 1 and 240" in service.start_focus(241)
    assert not service.is_active
