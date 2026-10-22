# JARVIS Initial Windows Release Checklist

## Release status

- [x] Source audit and current functionality reviewed.
- [x] Existing automated test suite run before packaging changes.
- [x] Missing PyInstaller icon reference removed; no icon file exists in source.
- [x] Required default behavior configuration files bundled.
- [x] NumPy and optional speech modules included in the embedded Python archive.
- [x] Unnecessary development packages excluded from the build.
- [x] Corrected packaged EXE launched on Windows using isolated temporary
      `%APPDATA%`; startup log and animation frame loading verified.
- [x] Full regression suite rerun after final packaging/doc changes: 277 passed.
- [x] Final onedir package launched from a different working directory with
      isolated `%APPDATA%`; app window, database/log creation, and all 16 bundled
      animation frame sets verified.
- [ ] Final distributable ZIP generated and inspected.
- [ ] Manual GUI, provider, microphone, credential-store, and clean-account
      acceptance complete.
- [ ] Source changes committed and pushed to GitHub.

## Changelog

- Added the missing application default-config resources to the PyInstaller
  bundle and removed the spec's stale reference to a nonexistent icon.
- Bundled lazy-loaded NumPy, faster-whisper, sounddevice, and pyttsx3 imports
  for the optional voice workflow.
- Excluded unrelated heavyweight development packages from the packaged build.
- Documented the Windows installation, user-data locations, credential setup,
  updating, known limitations, and manual acceptance steps.
- Added release archives and local SQLite files to `.gitignore`.

## Manual acceptance checklist

On the target Windows PC, using test data or after backing up
`%APPDATA%\JARVIS`:

1. Extract the complete release ZIP and run `JARVIS\JARVIS.exe` from the
   extracted folder.
2. Confirm the robot is visible, transparent, correctly scaled, and stays
   within screen bounds while moving; drag it and test resize/opacity settings.
3. Open and close the interaction panel, Settings, task manager, reminders, and
   animation gallery. Confirm the system tray Show/Hide/Pause/Exit actions.
4. Test all four chest buttons: Voice, Focus, Reminders, and Actions; verify
   status indicators after moving and resizing the robot.
5. Change one harmless setting, exit via the tray, restart, and verify that the
   setting persisted.
6. Test local task, reminder, alarm, and focus workflows. Confirm exact-time
   reminders fire at the selected local time.
7. With no API credentials configured, confirm AI requests show a useful setup
   error and do not crash. If desired, configure a personal key and verify the
   selected provider/model with one safe request.
8. If voice is needed, initialize a model, confirm the intended microphone is
   selected, test transcription, stop listening, and test TTS. Confirm useful
   messages with unavailable devices or permissions.
9. Inspect `%APPDATA%\JARVIS\logs\jarvis.log` for startup/shutdown errors and
   confirm settings/database files remain outside the install directory.
10. Update by extracting a newer package over the app files and confirm settings,
    tasks, reminders, and chat history remain present.

Do not treat this manual list as passed until each item has been performed on
the target machine.
