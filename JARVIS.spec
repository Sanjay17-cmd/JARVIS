# JARVIS.spec — PyInstaller spec for Windows EXE packaging
# Build with: pyinstaller JARVIS.spec

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
voice_hiddenimports = (
    collect_submodules('faster_whisper')
    + collect_submodules('sounddevice')
    + collect_submodules('pyttsx3')
)

a = Analysis(
    ['main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('jarvis/assets/images', 'jarvis/assets/images'),
        ('jarvis/assets/icons',  'jarvis/assets/icons'),
        ('jarvis/assets/sounds', 'jarvis/assets/sounds'),
        ('jarvis/config/default_configs', 'jarvis/config/default_configs'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFilter',
        'numpy',
        'sounddevice',
        'faster_whisper',
        'pyttsx3',
    ] + voice_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'mediapipe', 'cv2', 'sherpa_onnx', 'openai', 'anthropic',
        'tkinter', 'matplotlib', 'IPython', 'jupyter', 'nbformat',
        'pandas', 'pyarrow', 'scipy', 'sqlalchemy', 'zmq',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JARVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                 # no console window
    disable_windowed_traceback=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JARVIS',
)
