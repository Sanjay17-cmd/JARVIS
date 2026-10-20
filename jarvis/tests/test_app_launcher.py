"""
tests/test_app_launcher.py — Unit tests for WindowsAppLauncher.
Hardware/filesystem is mocked; no real processes launched.
"""
import pytest
from unittest.mock import patch, MagicMock
from jarvis.actions.windows_app_launcher import WindowsAppLauncher, _resolve


# ── _resolve helper ───────────────────────────────────────────────────────────

def test_resolve_returns_none_for_unknown():
    result = _resolve(["no_such_binary_xyzzy_12345"])
    assert result is None


def test_resolve_finds_notepad(tmp_path):
    # Create a fake exe so Path.is_file() passes
    fake = tmp_path / "notepad.exe"
    fake.write_bytes(b"")
    result = _resolve([str(fake)])
    assert result == str(fake)


def test_resolve_uri_passthrough():
    # ms- URIs should pass straight through without file checks
    result = _resolve(["ms-settings:"])
    assert result == "ms-settings:"


# ── WindowsAppLauncher ────────────────────────────────────────────────────────

@pytest.fixture
def launcher():
    return WindowsAppLauncher()


def test_unknown_app_returns_helpful_message(launcher):
    result = launcher.launch("xyzzy_unknown_app_99")
    assert "don't know" in result.lower() or "❌" in result


def test_known_app_not_installed_returns_error(launcher):
    # Patch _resolve to always return None (app not found)
    with patch("jarvis.actions.windows_app_launcher._resolve", return_value=None):
        result = launcher.launch("chrome")
    assert "❌" in result or "not found" in result.lower()


def test_known_app_launches_when_found(launcher):
    with patch("jarvis.actions.windows_app_launcher._resolve", return_value="C:\\fake\\chrome.exe"), \
         patch("subprocess.Popen") as mock_popen:
        result = launcher.launch("chrome")
    assert "✅" in result
    mock_popen.assert_called_once()


def test_popen_uses_no_shell(launcher):
    """subprocess.Popen must never be called with shell=True."""
    with patch("jarvis.actions.windows_app_launcher._resolve", return_value="C:\\fake\\notepad.exe"), \
         patch("subprocess.Popen") as mock_popen:
        launcher.launch("notepad")
    call_kwargs = mock_popen.call_args[1]
    assert call_kwargs.get("shell") is not True


def test_custom_app_path_not_found(launcher):
    launcher.update_custom_apps([{"name": "myapp", "path": "C:\\nonexistent\\app.exe", "args": []}])
    result = launcher.launch("myapp")
    assert "❌" in result


def test_custom_app_launches_when_path_exists(tmp_path, launcher):
    fake = tmp_path / "myapp.exe"
    fake.write_bytes(b"")
    launcher.update_custom_apps([{"name": "myapp", "path": str(fake), "args": []}])
    with patch("subprocess.Popen") as mock_popen:
        result = launcher.launch("myapp")
    assert "✅" in result


def test_list_known_returns_non_empty(launcher):
    names = launcher.list_known()
    assert len(names) > 5
    assert "chrome" in names or "notepad" in names


def test_alias_resolution_edge_to_msedge(launcher):
    """'edge' alias should resolve to msedge candidates."""
    with patch("jarvis.actions.windows_app_launcher._resolve", return_value="C:\\fake\\msedge.exe"), \
         patch("subprocess.Popen"):
        result = launcher.launch("edge")
    assert "✅" in result


def test_permission_error_handled(launcher):
    with patch("jarvis.actions.windows_app_launcher._resolve", return_value="C:\\fake\\app.exe"), \
         patch("subprocess.Popen", side_effect=PermissionError):
        result = launcher.launch("chrome")
    assert "❌" in result


# ── Command router open command ────────────────────────────────────────────────

def test_router_open_command_calls_launcher():
    from jarvis.core.command_router import CommandRouter
    router = CommandRouter()
    mock_launcher = MagicMock()
    mock_launcher.launch.return_value = "✅ Opening Chrome…"
    router.set_launcher(mock_launcher)

    result = router.route("open chrome")
    mock_launcher.launch.assert_called_once_with("chrome")
    assert "✅" in result


def test_router_open_no_app_name():
    from jarvis.core.command_router import CommandRouter
    router = CommandRouter()
    result = router.route("open")
    assert "open" in result.lower() or "?" in result or "example" in result.lower()


def test_router_time_command():
    from jarvis.core.command_router import CommandRouter
    result = CommandRouter().route("time")
    assert ":" in result   # HH:MM format


def test_router_date_command():
    from jarvis.core.command_router import CommandRouter
    result = CommandRouter().route("date")
    assert "2026" in result or "20" in result   # year present
