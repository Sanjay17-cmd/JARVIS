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
Voice Setup supports English plus Tamil, Telugu, Kannada, and Malayalam
recognition with multilingual Whisper models. For South Indian languages, use
`tiny`, `base`, or `small` rather than an English-only `.en` model. Spoken
responses need a compatible Windows TTS voice installed on that PC. Keep
“Keep listening after each reply” enabled for hands-free follow-up commands.

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
The chest microphone button toggles hands-free listening without opening a chat
window. JARVIS records one phrase at a time and submits it after the configured
silence interval, then listens again while the session remains active. Use
Settings → AI & Voice → Voice Setup to enable voice, choose a model/microphone,
set the silence interval, and decide whether talking interrupts spoken replies.
The other chest buttons control focus, open reminders, and open the task manager.

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
shows a cyan outlined speech bubble beside itself with an **ALERT!** label and
the reminder title, alongside the matching robot animation.

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
- Open **AI Pipeline Settings** to configure Gemini, OpenRouter, xAI Grok, and Groq.
  Refresh the provider's model catalogue to see account-available models; OpenRouter
  models can be filtered to free entries. Configure ordered fallbacks, retry/timeout
  limits, context size, cache retention, summaries, and saved user-approved memory.
- **Free-only AI chat** is enabled by default. It routes chat only to OpenRouter
  models whose IDs end in `:free`, whose text output is listed in the model catalog,
  and whose published prices are all zero. It checks the catalog before every
  request and never falls back to Gemini, Grok, Groq, or a paid model. If no verified
  free model or OpenRouter key is available, it reports an error instead. Groq is
  supported as a provider using `GROQ_API_KEY`, but the Groq model catalog does not
  publish the zero-price metadata required by this strict mode; disable free-only
  mode in AI Pipeline Settings to use Groq. Groq's account-level free tier/rate
  limits depend on the account and are not a proof of zero billing.
- Existing OpenAI settings are migrated through the same gateway for compatibility;
  OpenAI is shown in the provider list only for a migrated legacy configuration.
- Add API keys in **Credentials**. Stored keys use Windows Credential Manager;
  only labels, provider/project metadata, and credential IDs are saved in Settings.
  Alternatively, copy `.env.example` to `.env` and set `GEMINI_API_KEY`,
  `OPENROUTER_API_KEY`, `XAI_API_KEY`, or `GROQ_API_KEY`. The local `.env` is
  ignored by Git.
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
- Configure live search in Settings → **Web Search**. Choose Brave Search,
  Tavily, or OpenRouter Web Search, set its API key using the secure-key button,
  and test the connection. Search keys are stored in Windows Credential Manager
  under separate IDs from model-provider credentials. The chat **Search** toggle
  forces a query; requests asking for recent/current information are searched
  automatically. Returned sources are linked in chat. Search results and stable
  summaries use separate configurable caches; news defaults to a shorter cache.
  Search-backed answers with returned source links are marked with a 🌐 prefix;
  local predefined responses keep their ◆ marker.
- **When search runs:** turn on the chat's **Search** button to force web search
  for that message, or ask for current/recent information (for example, latest
  releases, current news, research, comparisons, or verification) for automatic
  search. Starting with the configured AI trigger word (such as “Friday”) uses
  the AI pipeline; if that request is also search-related, it searches the web.
- **When normal AI runs:** ordinary questions without the Search toggle, search
  intent, or a local built-in command use the configured AI provider directly.
  Common greetings and registered local commands are handled locally first,
  unless the Search toggle or AI trigger explicitly requests the AI path. If web
  search is unavailable or fails, JARVIS reports the failure rather than
  presenting an unsourced answer as searched.
- The settings window is split into General, Notifications, AI & Voice, and
  Focus & Tools sections. Installed TTS voices are listed by the local Windows
  speech backend; availability depends on voices installed on that PC.
- **AI Action History** shows recent tool names, outcomes, and error codes without
  recording arguments, API keys, or returned task content. It records affected
  record IDs and a concise status/result category where available.
- In **AI & Voice**, “Allow spoken commands to perform application actions” can
  disable voice-triggered actions while leaving spoken chat replies available.
- **Built-in Responses** is a settings section for adding local replies by key or
  importing CSV rows with `key,response` columns. Greetings such as “hi” and
  “how are you” have local replies; unmatched requests continue to the configured
  AI fallback. A small diamond marks local predefined replies in chat, including
  alarm command replies.
- Reminder/alarm definitions and wellness intervals persist in the local SQLite
  store. Due notifications are delivered while JARVIS is running; reminders cannot
  fire when the process is closed or the computer is powered off.
- Utility dialogs use the robot's opacity and can be dragged from non-control
  areas; buttons, text fields, lists, and other interactive controls keep their
  normal click/edit behavior. The chat panel is unchanged.

### Phase 3: web search and application actions

- Web search uses independently configured Brave, Tavily, or OpenRouter Search
  credentials. The Search button forces a search; current-information requests
  may also be routed automatically. Sources are linked in chat only when the
  configured service returned them. Search has separate result and summary
  caches from the AI response cache.
- Typed requests and recognized speech use the same command router and AI
  gateway. Tool-capable requests are converted to a strict JSON plan, validated
  against registered schemas, and executed through the existing task,
  reminder/alarm, Focus, saved-memory, and app services. Ordinary chat without
  an action-intent keyword goes directly through the existing gateway to avoid
  the extra planning prompt.
- The registry verifies persisted task, reminder, alarm, and Focus-rule changes.
  Relative dates use the machine's local timezone. Repeated records with the
  same displayed title trigger a clarification rather than selecting by list
  order. Before creating, updating, completing, reopening, snoozing, dismissing,
  cancelling, deleting, changing Focus, saving notes, opening apps, or playing
  animations, or copying text to the clipboard, JARVIS shows the proposed change
  with **Yes** and **No** buttons. Clipboard approval displays the exact text to
  be copied. The operation is not executed until approved. You can also say or
  type “yes” or “no” in the same conversation. Saying “no” leaves stored data
  and the clipboard unchanged.
- Voice action permission is configurable in Settings. Transcribed requests
  still appear in chat, and enabled TTS reads the final response. When speech
  interruption is enabled, speaking stops the current TTS output; the microphone
  stays/reopens for the next request, and the new request receives its own
  response. This relies on the optional local microphone/recognition/TTS setup
  described above.
- The action planner currently performs at most one registered tool per turn.
  It does not execute generated code or shell commands. Windows microphone,
  TTS voice availability, provider credentials, billing/quota, and live search
  results require validation on the target machine; mocked tests do not prove
  those external integrations.
- The chat panel's **Image** button opens an OpenRouter image-generation window.
  Add an OpenRouter key in AI Pipeline Settings and enter a prompt. The model
  selector lists only image models whose OpenRouter catalog ID ends in `:free`
  and whose published prices are all zero; the catalog is checked again before
  every generation. If no model passes those checks, generation is disabled and
  no paid fallback is attempted. Generated images are saved under
  `%APPDATA%\JARVIS\generated_images`; use **Save As…** for another location.
  **Copy Image** asks for confirmation before putting the image on the Windows
  clipboard. Free model availability may change. Nano Banana is not treated as
  free unless OpenRouter lists that exact image model as a zero-priced `:free`
  endpoint.
  OpenRouter documents the image API at
  [Image Generation](https://openrouter.ai/docs/guides/overview/multimodal/image-generation).
- Each assistant reply shows its provider/model in a small caption below the
  response; the caption is saved with chat history. Built-in/local replies are
  labelled accordingly. The chat window is wider, and Settings has been widened
  to make the section controls and text easier to read.

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
