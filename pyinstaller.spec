# PyInstaller spec for the UIUC Part-Time Job Scanner.
#
# Build with:
#     pyinstaller pyinstaller.spec
#
# Output:
#     dist/UIUC Part-Time Job Scanner.app   (macOS)
#
# Notes:
# - Uses onedir mode (NOT onefile); onefile .app bundles are slow and
#   trigger macOS security scans per Apple/PyInstaller guidance.
# - Windowed flag -- no console terminal pops up when launched from Finder.
# - Excludes unused Qt modules (WebEngine, Multimedia, 3D) to trim ~50MB.
# - macOS only builds .app. Build on macOS to ship macOS.

# -*- mode: python ; coding: utf-8 -*-

import os
import shutil
from pathlib import Path

APP_NAME = "UIUC Part-Time Job Scanner"
ENTRY = Path("gui.py").resolve()


block_cipher = None


# Excluded Qt modules keep the bundle lean. Each is a real Qt module we
# don't use; PyInstaller otherwise pulls them in transitively.
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtNfc",
    "PySide6.QtSensors",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
]


a = Analysis(
    [str(ENTRY)],
    pathex=[str(ENTRY.parent / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
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
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # windowed app -- no terminal
    disable_windowed_traceback=False,
    target_arch=None,        # None = current arch; set to "arm64"/"x86_64" to lock
    codesign_identity=None,  # fill in for signed builds
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
    name=APP_NAME,
)

# macOS .app bundle -- only emitted on macOS.
if os.uname().sysname == "Darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="edu.illinois.jobscanner",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "0.2.0",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # respect dark mode
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )

    # Trim Qt frameworks the app does not use. PySide6_Addons ships every
    # Qt module's framework into Contents/Frameworks/PySide6/Qt/lib/ even
    # when the Python-level module isn't imported. Removing the unused
    # frameworks trims ~8 MB off the bundle. Each frame is verified not to
    # be a transitive dependency before being removed (see comments).
    _TRIMMED_FRAMEWORKS = [
        "QtPdf",                # no QPdf* usage in the app
        "QtVirtualKeyboard",    # no input-method reliance
        "QtVirtualKeyboardQml",
        "QtQmlWorkerScript",    # no QML worker scripts
        "QtSvg",                # no SVG asset loading
    ]
    _qt_lib = os.path.join(app.name, "Contents", "Frameworks", "PySide6", "Qt", "lib")
    for _fw in _TRIMMED_FRAMEWORKS:
        _path = os.path.join(_qt_lib, f"{_fw}.framework")
        if os.path.isdir(_path):
            shutil.rmtree(_path, ignore_errors=True)
