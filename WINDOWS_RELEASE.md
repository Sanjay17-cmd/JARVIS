# JARVIS Windows Release Guide

## Requirements

- Windows 10 or 11, 64-bit.
- No separately installed Python is required to run the packaged distribution.
- Internet access is needed for provider APIs and for the optional first download
  of a local speech model.
- Microphone and a compatible Windows speech voice are needed for voice input
  and text-to-speech respectively.

## Rebuild the release

On a 64-bit Windows build machine with Python installed:

```powershell
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm JARVIS.spec
New-Item -ItemType Directory -Force release | Out-Null
Compress-Archive -Path dist\JARVIS,INSTALL.txt `
  -DestinationPath release\JARVIS-Windows-x64.zip -CompressionLevel Optimal
```

The build output is `dist\JARVIS\JARVIS.exe`. Do not include `.env`, local
databases, logs, or the `%APPDATA%\JARVIS` user-data directory in the ZIP.

## Install and launch

1. Download `JARVIS-Windows-x64.zip` from the release handoff.
2. Extract the complete ZIP to a user-writable folder, for example
   `%LOCALAPPDATA%\Programs\JARVIS`. Keep the `JARVIS` folder structure intact.
3. Launch `JARVIS\JARVIS.exe`. The app appears as a transparent desktop robot
   and in the system tray. It is a one-folder application; do not move the EXE
   away from its accompanying `_internal` folder.
4. On first launch, allow Windows to run the application if SmartScreen displays
   an unsigned-app warning. This build is not code-signed.

## API credentials

Open Settings → AI Pipeline Settings / Credentials and add your own provider
keys. On Windows, saved secrets are stored via Windows Credential Manager.
Credentials do not come in the ZIP and are not shared between PCs. Provider
keys may incur charges according to provider terms; free-only routing does not
guarantee provider availability or account eligibility.

Do not place live keys in the installation folder, release ZIP, source tree, or
example configuration. The local `.env` approach is for source/developer runs;
it is not part of the packaged application.

## Data, configuration, and logs

The executable keeps user data separate from the install directory:

- Settings and application data: `%APPDATA%\JARVIS`
- SQLite task/reminder/chat data: `%APPDATA%\JARVIS\jarvis.db`
- Logs: `%APPDATA%\JARVIS\logs\jarvis.log`
- Generated images: `%APPDATA%\JARVIS\generated_images`
- Editable behavior configuration: `%APPDATA%\JARVIS\config`
- Advanced settings: `%APPDATA%\JARVIS\advanced_settings.ini`

Back up `%APPDATA%\JARVIS` before manually editing or migrating data. Do not
delete this directory when updating the application.

## Voice setup

Open Settings → Voice Setup to enable local speech recognition, select the
microphone/model, and initialize the model. The first initialization can require
internet access and disk space to download the model. A usable microphone,
audio drivers, and Windows permissions are required. Text-to-speech depends on
an installed compatible Windows voice. Voice hardware and model initialization
were not validated on other PCs.

## Update without losing data

1. Exit JARVIS from its system-tray menu.
2. Keep a backup of `%APPDATA%\JARVIS`.
3. Extract the new release to the same installation folder, replacing the
   application files.
4. Do not delete or replace `%APPDATA%\JARVIS`; launch the new `JARVIS.exe`.

## Logs and startup troubleshooting

If startup fails, inspect `%APPDATA%\JARVIS\logs\jarvis.log`. Confirm the
extracted `_internal` folder is beside `JARVIS.exe`, then retry after extracting
the ZIP completely. Do not launch the executable from inside the ZIP preview.
If the log does not exist or remains empty, capture the Windows error dialog
text and include the Windows version and the release build when reporting the
problem. Keep a backup of user data before attempting repairs.

## Verification and limitations

Automated project tests use mocks for provider/network calls. A packaged smoke
launch was performed on Windows using a temporary, isolated `%APPDATA%`; startup
logs confirmed the app initialized its database, configured the gateway,
started the overlay, and loaded all bundled robot animation frames. A second
build error caused by an omitted default-config resource was fixed and the
corrected build was smoke-launched. This does not verify every dialog or
interaction, provider credentials, actual speech devices, or operation on a
clean account without Python.

See [RELEASE_CHECKLIST.md](./RELEASE_CHECKLIST.md) for what was actually tested
and the remaining manual acceptance steps. Features depending on live provider
credentials, account quota, microphone, audio devices, and Windows Credential
Manager require verification on the target PC.
