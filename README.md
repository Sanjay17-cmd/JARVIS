# JARVIS — Windows Desktop AI Companion

<div align="center">

```
  ⚡ JARVIS — Your Friendly Desktop Robot
  Futuristic • Animated • Transparent • Always On Top
```

</div>

---

## Quick Start

### 1. Prerequisites
- Windows 10 or 11 (64-bit)
- Python 3.11+ (64-bit) — tested on Python 3.14.6

### 2. Install dependencies
```powershell
pip install -r requirements.txt
```

### Optional local voice
The app stays lightweight and works without speech packages. Open Settings → Voice
Setup, enable voice, choose a microphone and model, then explicitly initialize the
model. The first model initialization may download it to the faster-whisper cache.
You can also browse to a local model directory. Audio recognition remains local;
the optional `pyttsx3` TTS backend is enabled from Voice Setup.

### 3. Run JARVIS
```powershell
python main.py
```

That's it! JARVIS will appear as an animated robot on your desktop.

---

## What you'll see

| Feature | Status |
|---|---|
| Animated cyan/blue robot | ✅ Working |
| Transparent background | ✅ No rectangular window |
| Always on top | ✅ Floats above all windows |
| Smooth floating movement | ✅ Boundary-safe |
| Drag to reposition | ✅ Click-and-drag |
| Right-click context menu | ✅ Full menu |
| System tray icon | ✅ Show/Hide/Pause/Exit |
| Interaction panel | ✅ Click robot to open |
| Demo command | ✅ Type "demo" in panel |
| Settings dialog | ✅ Persistent JSON |
| State animations | ✅ State and special-effect animations |
| Task manager | ✅ Separate active/completed views and persisted deadlines |
| Chat history | ✅ Separate SQLite-backed conversations |
| Push-to-talk | ✅ Optional local Whisper setup and transcription |
| Reminders and alarms | ✅ Persistent scheduling with visible in-app notifications |
| Editable behavior | ✅ User JSON configs for replies and allowlisted custom actions |

---

## Interaction

### Left-click the robot
Opens the interaction panel. Type commands:

| Command | Description |
|---|---|
| `hello` | Greeting |
| `demo` | Triggers THINKING → SUCCESS state cycle |
| `status` | System status |
| `help` | List all commands |
| `version` | Version info |
| `task <title>` | Add a task |
| `tasks` / `done <id>` | List or complete tasks |
| `focus start/stop/status/skip` | Control a Pomodoro session |
| `remind me in 30 minutes to ...` | Add a reminder |

### Right-click the robot
Opens the context menu with: Open Panel, Pause, Reset Position, Settings, Hide, Exit.
The chest microphone button opens a separate voice-chat window and starts/stops
push-to-talk without opening the main interaction panel. Use **New Chat** or the
conversation selector to start a conversation or return to an older one. The
other chest buttons control focus, open reminders, and open the task manager.

### System Tray
Look for the **J** icon in the system tray (bottom-right). 
Right-click for: Show, Hide, Pause/Resume, Settings, Exit.

---

## Settings

Open via: Right-click → Settings, or tray → Settings.

Settings are grouped under the top section bar. **AI & Voice** includes the
trigger words, AI provider controls, voice output enablement, and installed
speech-voice selection. The chat panel can speak assistant replies from either
typed or voice input, including local command responses, when voice output is
enabled.

**Notifications** provides a master toggle and category switches for reminders,
alarms, focus, wellness, and other notifications. Due reminders can also appear
in the chat. Desktop notification toasts appear in the bottom-right; the robot
shows a reminder bubble with a matching animation.

The settings window's bottom scrolling legend explains chest-button colors:
purple for Voice, blue for Focus, amber for Reminders, and pink for Actions.
Status colors are cyan while listening, red while muted or when a reminder is
due, and green while Focus is active.

| Setting | Description |
|---|---|
| Robot size | Pixel size of the robot (60–300) |
| Opacity | Window transparency (30–100%) |
| Animation FPS | Smoothness (10–60) |
| Auto movement | Toggle floating movement |
| Movement speed | Pixels per frame |
| Safe margin | Distance from screen edge |
| Always on top | Keep above other windows |
| Start position | X/Y or -1 for auto |

Settings are saved to: `%APPDATA%\JARVIS\settings.json`

### Behavior, AI routing, and reminder notes

- Behavior & Responses in Settings opens the editable JSON files in
  `%APPDATA%\JARVIS\config`. The application copies defaults there once and does
  not overwrite customized files during updates.
- The configurable AI Trigger Keyword (initially `Friday`) invokes the configured
  AI provider for the remainder of the request. Unprefixed registered local
  commands such as `Open Chrome` and `Remind me in 5 seconds` remain local actions.
- Open **AI Pipeline Settings** to configure Gemini, OpenRouter, and xAI Grok.
  Refresh the provider's model catalogue to see account-available models; OpenRouter
  models can be filtered to free entries. Configure ordered fallbacks, retry/timeout
  limits, context size, cache retention, summaries, and saved user-approved memory.
- Existing OpenAI settings are migrated through the same gateway for compatibility;
  OpenAI is shown in the provider list only for a migrated legacy configuration.
- Add API keys in **Credentials**. Stored keys use Windows Credential Manager;
  only labels, provider/project metadata, and credential IDs are saved in Settings.
  Alternatively, copy `.env.example` to `.env` and set `GEMINI_API_KEY`,
  `OPENROUTER_API_KEY`, or `XAI_API_KEY`. The local `.env` is ignored by Git.
- AI results and summaries are stored in the local SQLite database. Eligible exact
  responses are cached with context-aware keys; time-sensitive/current-information
  prompts are excluded. Cached answers are not live provider checks.
- All model-generated text is kept separate from local application actions. AI
  output does not execute shell commands. Search is not claimed unless the provider
  integration actually performs a configured search.
- Manual provider integration checklist: add a key for each provider; use **Test
  Connection**; refresh models and select an available model; send one ordinary
  prompt and verify provider/model status; configure a fallback and test with a
  deliberately unavailable model; verify rate-limit/quota behavior with an account
  where safe. Mocked tests cannot validate real credentials, project quota policy,
  billing, or current catalogue availability.
- The settings window is split into General, Notifications, AI & Voice, and
  Focus & Tools sections. Installed TTS voices are listed by the local Windows
  speech backend; availability depends on voices installed on that PC.
- Reminder/alarm definitions and wellness intervals persist in the local SQLite
  store. Due notifications are delivered while JARVIS is running; reminders cannot
  fire when the process is closed or the computer is powered off.
- Utility dialogs use the robot's opacity and can be dragged from non-control
  areas; buttons, text fields, lists, and other interactive controls keep their
  normal click/edit behavior. The chat panel is unchanged.

---

## Project Structure

```
v1/
├── main.py                    # Entry point
├── requirements.txt
├── JARVIS.spec                # PyInstaller config (future)
└── jarvis/
    ├── app.py                 # Application lifecycle
    ├── core/
    │   ├── state.py           # State machine (7 states)
    │   ├── event_bus.py       # Pub/sub event bus
    │   └── command_router.py  # Command dispatcher
    ├── ui/
    │   ├── overlay.py         # Transparent robot window
    │   ├── interaction_panel.py  # Chat/command panel
    │   ├── settings_dialog.py # Settings UI
    │   └── tray.py            # System tray
    ├── assets/
    │   └── robot_painter.py   # Programmatic robot art
    ├── config/
    │   ├── defaults.py        # Default settings
    │   └── settings.py        # JSON persistence
    ├── voice/                 # Optional local speech recognition and TTS
    ├── vision/                # Phase 3 stub
    ├── ai/                    # Unified provider gateway, adapters, cache and memory
    ├── actions/               # Action registry
    ├── plugins/               # Phase 5 stub
    ├── memory/                # SQLite stub
    └── tests/
        ├── test_state.py      (9 tests)
        ├── test_settings.py   (8 tests)
        ├── test_command_router.py (10 tests)
        └── test_event_bus.py  (6 tests)
```

---

## Running Tests

```powershell
python -m pytest jarvis/tests/ -v
```

The suite includes unit and mocked integration tests for providers, routing,
persistence, and user interface behavior.

---

## Logs

Log files: `%APPDATA%\JARVIS\logs\jarvis.log`

## Packaging and portability

The current `JARVIS.spec` uses PyInstaller's `COLLECT` mode and produces an
**onedir distribution**, not a single portable EXE. It has not been built or
validated as a distributable package. A build also needs the referenced asset
folders and icon to exist, and optional speech recognition/model resources may
need separate setup. API credentials are stored in the Windows Credential
Manager and do not automatically transfer to another PC; configure credentials
there after installation. Do not package API keys in the executable.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `ModuleNotFoundError: PySide6` | Run `pip install PySide6` |
| Robot not visible | Check system tray → Show JARVIS |
| Window behind other apps | Right-click → Settings → Always on top ✓ |
| Transparent background not working | Requires Windows 10+ with DWM enabled |
| Robot disappears off screen | Right-click → Reset Position |
| Settings not saving | Check `%APPDATA%\JARVIS\` is writable |

---

## Future Roadmap

### Later phases
- Wake-word detection and broader local speech-engine support
- Computer vision
- OpenCV webcam capture
- MediaPipe hand landmark tracking
- Static + dynamic gesture recognition
- Gesture-to-command mappings

### Phase 5 — Plugins & Memory
- Plugin discovery system
- Custom gesture plugins

---

## Future EXE Packaging

> ⚠ Build and test first. Only package once the app is verified.

```powershell
pip install pyinstaller
pyinstaller JARVIS.spec
# Output: dist/JARVIS/JARVIS.exe
```

---

## License & Attribution

JARVIS Phase 1 — Original project.  
Dependencies: PySide6 (LGPL), Pillow (HPND), pytest (MIT), PyInstaller (GPL+exception).

See `docs/LICENSES.md` for full third-party license inventory.
