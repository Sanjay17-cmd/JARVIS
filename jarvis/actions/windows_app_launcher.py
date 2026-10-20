"""
actions/windows_app_launcher.py — Safe Windows application launcher.

Rules:
  • Uses subprocess with an argument list — never shell=True with user text.
  • Validates paths before launching.
  • Falls back to known-app registry when no path is configured.
  • Returns a human-readable result string for the chat panel.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Known-app registry ────────────────────────────────────────────────────────
# Keys are lower-case aliases; values are lists of candidate exe names/paths
# tried in order. shutil.which() resolves PATH entries.
_KNOWN_APPS: dict[str, list[str]] = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "chrome",
    ],
    "google chrome": ["chrome"],  # alias
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "msedge",
    ],
    "microsoft edge": ["edge"],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        "firefox",
    ],
    "vscode": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        "code",
    ],
    "vs code": ["vscode"],
    "visual studio code": ["vscode"],
    "code": ["vscode"],
    "notepad": ["notepad.exe", "notepad"],
    "notepad++": [
        r"C:\Program Files\Notepad++\notepad++.exe",
        r"C:\Program Files (x86)\Notepad++\notepad++.exe",
    ],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "files": ["explorer.exe"],
    "taskmanager": ["taskmgr.exe"],
    "task manager": ["taskmgr.exe"],
    "taskmgr": ["taskmgr.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["wt.exe", "powershell.exe"],   # Windows Terminal → PS fallback
    "spotify": [
        r"%APPDATA%\Spotify\Spotify.exe",
        "spotify",
    ],
    "discord": [
        r"%LOCALAPPDATA%\Discord\Update.exe",
        "discord",
    ],
    "steam": [
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
        "steam",
    ],
    "vlc": [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        "vlc",
    ],
    "control panel": ["control.exe"],
    "settings": ["ms-settings:"],          # Windows Settings URI
    "snipping tool": ["SnippingTool.exe", "SnipSketch.exe"],
    "clock": ["ms-clock:"],
}


def _resolve(candidates: list[str]) -> str | None:
    """Return the first resolvable path from a candidates list."""
    for raw in candidates:
        expanded = os.path.expandvars(raw)
        if expanded.startswith("ms-"):        # URI scheme, not a file
            return expanded
        p = Path(expanded)
        if p.is_file():
            return str(p)
        found = shutil.which(expanded)
        if found:
            return found
    return None


class WindowsAppLauncher:
    """
    Launches registered or user-configured Windows applications safely.
    Custom apps are stored as dicts: {name, path, args: list[str]}.
    """

    def __init__(self, custom_apps: list[dict[str, Any]] | None = None) -> None:
        self._custom: dict[str, dict] = {}
        for app in (custom_apps or []):
            self._custom[app["name"].lower()] = app

    def update_custom_apps(self, custom_apps: list[dict[str, Any]]) -> None:
        self._custom = {a["name"].lower(): a for a in custom_apps}

    # ── Public API ────────────────────────────────────────────────────────────

    def launch(self, name: str) -> str:
        """Launch *name* and return a result string for the chat panel."""
        key = name.strip().lower()

        # 1. User-registered custom apps take priority
        if key in self._custom:
            return self._launch_custom(self._custom[key])

        # 2. Known-app registry with alias chaining
        visited: set[str] = set()
        target = key
        while target in _KNOWN_APPS and target not in visited:
            visited.add(target)
            candidates = _KNOWN_APPS[target]
            # If it's a single-alias entry pointing to another key, follow it
            if len(candidates) == 1 and candidates[0] in _KNOWN_APPS:
                target = candidates[0]
            else:
                exe = _resolve(candidates)
                if exe:
                    return self._run(exe, [], name)
                return f"❌ '{name}' is registered but could not be found. Is it installed?"

        return (
            f"❌ I don't know how to open '{name}'.\n"
            f"You can register it via Settings → Custom Apps."
        )

    def list_known(self) -> list[str]:
        """Return sorted unique display names."""
        seen: set[str] = set()
        out = []
        for k, v in _KNOWN_APPS.items():
            # Skip pure aliases
            if len(v) == 1 and v[0] in _KNOWN_APPS:
                continue
            out.append(k)
        return sorted(out)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _launch_custom(self, app: dict) -> str:
        path = os.path.expandvars(app.get("path", ""))
        if not path:
            return f"❌ No path configured for '{app['name']}'."
        if path.startswith("ms-"):
            return self._run(path, [], app["name"])
        if not Path(path).is_file():
            return f"❌ Path not found: {path}"
        args: list[str] = app.get("args") or []
        return self._run(path, args, app["name"])

    def _run(self, exe: str, args: list[str], display: str) -> str:
        try:
            if exe.startswith("ms-"):
                # URI — use os.startfile or ShellExecute
                os.startfile(exe)   # type: ignore[attr-defined]
            else:
                subprocess.Popen(
                    [exe] + args,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            log.info("Launched: %s (%s)", display, exe)
            return f"✅ Opening {display}…"
        except FileNotFoundError:
            return f"❌ Executable not found: {exe}"
        except PermissionError:
            return f"❌ Permission denied launching {display}."
        except Exception as exc:
            log.exception("Launch failed: %s", display)
            return f"❌ Failed to open {display}: {exc}"
