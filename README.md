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
| State animations | ✅ 7 visual states |

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

### Right-click the robot
Opens the context menu with: Open Panel, Pause, Reset Position, Settings, Hide, Exit.

### System Tray
Look for the **J** icon in the system tray (bottom-right). 
Right-click for: Show, Hide, Pause/Resume, Settings, Exit.

---

## Settings

Open via: Right-click → Settings, or tray → Settings.

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
    ├── voice/                 # Phase 2 stub
    ├── vision/                # Phase 3 stub
    ├── ai/                    # Phase 4 stub
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

Expected: **33 passed** ✅

---

## Logs

Log files: `%APPDATA%\JARVIS\logs\jarvis.log`

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

### Phase 2 — Voice First
- Wake-word detection via sherpa-onnx
- Speech recognition (local, no cloud)
- Text-to-speech response
- Live microphone indicator

### Phase 3 — Computer Vision
- OpenCV webcam capture
- MediaPipe hand landmark tracking
- Static + dynamic gesture recognition
- Gesture-to-command mappings

### Phase 4 — AI Integration
- OpenAI / Anthropic provider
- Streaming responses
- Local LLM support
- AI output sandboxing (action registry)

### Phase 5 — Plugins & Memory
- Plugin discovery system
- SQLite command history
- User-defined memories
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
