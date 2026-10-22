"""
config/defaults.py — Canonical default settings for JARVIS Phase 2.
Extended with all new Phase 2 settings, all validated and documented.
"""
from __future__ import annotations
from typing import Any

DEFAULTS: dict[str, Any] = {
    # ── Window ──────────────────────────────────────────────────────────────
    "always_on_top":        True,
    "panels_always_on_top": True,        # chat panel + settings stay on top
    "opacity":              1.0,         # 0.3–1.0
    "robot_size":           120,         # 60–300 px
    "start_x":              -1,          # -1 = auto
    "start_y":              -1,

    # ── Movement ────────────────────────────────────────────────────────────
    "auto_movement":        True,
    "movement_speed":       1.2,         # px/frame  0.1–10.0
    "safe_margin":          20,          # px from edge  0–100

    # ── Animation ───────────────────────────────────────────────────────────
    "animation_enabled":    True,
    "animation_fps":        30,          # 10–60

    # ── Notifications ───────────────────────────────────────────────────────
    "notifications_enabled": True,
    "notification_duration": 5000,       # ms  1000–30000
    "notification_reminders": True,
    "notification_alarms": True,
    "notification_focus": True,
    "notification_wellness": True,
    "sound_enabled":         False,      # Phase 2+
    "sound_volume":          0.7,        # 0.0–1.0

    # ── Chest buttons ────────────────────────────────────────────────────────
    "chest_buttons": [
        {"id": 0, "name": "Voice",      "action": "toggle_voice",    "color": "#B84DFF", "enabled": True,  "shortcut": "", "confirm": False},
        {"id": 1, "name": "Focus",      "action": "toggle_focus",    "color": "#2878FF", "enabled": True,  "shortcut": "", "confirm": False},
        {"id": 2, "name": "Reminders",  "action": "open_reminders",  "color": "#FFB000", "enabled": True,  "shortcut": "", "confirm": False},
        {"id": 3, "name": "Actions",    "action": "open_quick_menu", "color": "#FF4FA3", "enabled": True,  "shortcut": "", "confirm": False},
    ],

    # ── Voice ────────────────────────────────────────────────────────────────
    "voice_enabled":        False,
    "voice_auto_listen":    True,
    "voice_silence_ms":     900,
    "voice_interrupt_tts":  True,
    "voice_wake_word":      "jarvis",
    "voice_model_id":       "base.en",
    "voice_language":       "en-US",
    "image_generation_model": "",
    "voice_model_path":     "",          # local faster-whisper model directory
    "voice_device":         "cpu",
    "voice_compute_type":   "int8",
    "voice_microphone_id":  -1,
    "tts_enabled":          False,
    "tts_voice":            "",          # empty = system default
    "tts_rate":             175,         # words per minute
    "tts_volume":           0.9,

    # ── Camera ───────────────────────────────────────────────────────────────
    "camera_enabled":       False,
    "camera_index":         0,

    # ── AI provider ──────────────────────────────────────────────────────────
    "ai_provider":          "none",      # "none"|"openai"|"anthropic"
    "ai_primary_provider":  "gemini",
    "ai_primary_model":     "gemini-2.5-flash",
    "ai_primary_credential_id": "",
    "ai_credentials":       [],
    "ai_provider_enabled":  {
        "gemini": True, "openrouter": True, "grok": True, "groq": True,
        "openai": True,
    },
    "ai_fallback_enabled":  True,
    "ai_fallback_routes":  [],
    "ai_max_fallback_attempts": 3,
    "ai_max_retries":       1,
    "ai_retry_wait_cap_seconds": 5,
    "ai_max_output_tokens": 512,
    "ai_recent_message_count": 8,
    "ai_context_max_chars": 12000,
    "ai_cache_enabled":     True,
    "ai_cache_expiry_minutes": 60,
    "ai_cache_policy_version": 1,
    "ai_summary_threshold": 30,
    "ai_summary_recent_messages": 12,
    "ai_advanced_route_enabled": False,
    "ai_advanced_model":    "",
    "ai_free_models_only":  False,
    "ai_chat_free_only":    True,
    "ai_model_catalog_ttl_seconds": 3600,
    "ai_model":             "",
    "ai_api_key_env_var":   "",
    "ai_timeout":           30,          # seconds
    "ai_trigger_enabled":   True,
    "ai_trigger_keyword":   "Friday",
    "ai_trigger_aliases":   [],
    "search_provider":      "brave",
    "search_openrouter_model": "",
    "search_result_limit":  5,
    "search_timeout_seconds": 12,
    "search_cache_ttl_minutes": 240,
    "search_news_cache_ttl_minutes": 15,
    "voice_actions_enabled": True,

    # ── Focus mode ───────────────────────────────────────────────────────────
    "focus_duration_minutes":       25,
    "focus_short_break_minutes":    5,
    "focus_long_break_minutes":     15,
    "focus_pomodoro_enabled":       True,
    "focus_distraction_nudge":      False,  # opt-in
    "focus_nudge_cooldown_minutes": 10,
    "focus_app_rules":      [],

    # ── Wellness ─────────────────────────────────────────────────────────────
    "wellness_enabled":              True,
    "wellness_hydration_enabled":    True,
    "wellness_hydration_interval":   60,     # minutes
    "wellness_stretch_enabled":      False,
    "wellness_stretch_interval":     60,
    "wellness_eyerest_enabled":      False,
    "wellness_eyerest_interval":     20,
    "wellness_hydration_interval_seconds": 0,  # 0 = use advanced-config minutes
    "wellness_stretch_interval_seconds":    0,
    "wellness_eyerest_interval_seconds":    0,
    "wellness_active_hour_start":    8,      # hour of day
    "wellness_active_hour_end":      22,

    # ── Quiet hours ──────────────────────────────────────────────────────────
    "quiet_hours_enabled":   False,
    "quiet_hour_start":      22,         # 10 PM
    "quiet_hour_end":        8,          # 8 AM

    # ── Custom apps ──────────────────────────────────────────────────────────
    "custom_apps":          [],          # [{name, path, args}]

    # ── System ───────────────────────────────────────────────────────────────
    "launch_on_startup":    False,
    "log_level":            "INFO",

    # ── Privacy ──────────────────────────────────────────────────────────────
    "telemetry_enabled":    False,
    "retain_conversation":  True,
}

# ── Validation rules ─────────────────────────────────────────────────────────
# (key, type, min, max)  — None means no bound
VALIDATORS: dict[str, tuple] = {
    "opacity":                    (float, 0.1, 1.0),
    "robot_size":                 (int,   60,  300),
    "movement_speed":             (float, 0.1, 10.0),
    "safe_margin":                (int,   0,   200),
    "animation_fps":              (int,   5,   60),
    "notification_duration":      (int,   500, 60000),
    "sound_volume":               (float, 0.0, 1.0),
    "tts_rate":                   (int,   50,  400),
    "tts_volume":                 (float, 0.0, 1.0),
    "ai_timeout":                 (int,   5,   300),
    "voice_microphone_id":        (int,   -1,   256),
    "focus_duration_minutes":     (int,   1,   240),
    "focus_short_break_minutes":  (int,   1,   60),
    "focus_long_break_minutes":   (int,   5,   120),
    "wellness_hydration_interval":(int,   10,  480),
    "wellness_stretch_interval":  (int,   10,  480),
    "wellness_eyerest_interval":  (int,   5,   120),
}
