# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Splatrix macOS .app bundle.

Bundles the UI layer only (Python + PyQt6, no WebEngine, no ML stack).
Heavy dependencies are downloaded on first launch via the bootstrap dialog.

Build:  pyinstaller splatrix.spec
Output: dist/Splatrix.app
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Paths ────────────────────────────────────────────────────────────────────

SRC_DIR = Path(SPECPATH)
SPLATRIX_PKG = SRC_DIR / "splatrix"
RESOURCES = SRC_DIR / "resources"

# ── Data files ───────────────────────────────────────────────────────────────

datas = []

# QML files
for qml in SPLATRIX_PKG.glob("qml/*.qml"):
    datas.append((str(qml), "splatrix/qml"))
qmldir = SPLATRIX_PKG / "qml" / "qmldir"
if qmldir.exists():
    datas.append((str(qmldir), "splatrix/qml"))

# Icons
for icon in SPLATRIX_PKG.glob("qml/icons/*"):
    datas.append((str(icon), "splatrix/qml/icons"))

# Fonts
for font in SPLATRIX_PKG.glob("qml/fonts/*.ttf"):
    datas.append((str(font), "splatrix/qml/fonts"))

# Viewer HTML
viewer_dir = SPLATRIX_PKG / "viewer"
if viewer_dir.is_dir():
    for f in viewer_dir.iterdir():
        datas.append((str(f), "splatrix/viewer"))

# Themes
themes_dir = SPLATRIX_PKG / "themes"
if themes_dir.is_dir():
    for f in themes_dir.glob("*.yml"):
        datas.append((str(f), "splatrix/themes"))

# Bootstrap config
bootstrap_config = SPLATRIX_PKG / "bootstrap_config.json"
if bootstrap_config.exists():
    datas.append((str(bootstrap_config), "splatrix"))

# PyQt6 QML modules (QtQuick, QtQuick.Controls, etc.)
datas += collect_data_files("PyQt6", subdir="Qt6/qml", includes=["**/*"])
datas += collect_data_files("PyQt6", subdir="Qt6/plugins", includes=["**/*"])

# ── Excluded modules ─────────────────────────────────────────────────────────

excludes = [
    # ML stack (installed by bootstrap)
    "torch", "torchvision", "torchaudio",
    "nerfstudio",
    "gsplat",
    "msplat",
    "tinycudann",
    "tensorboard", "tensorboardX",
    "scipy",
    "cv2", "opencv",
    # Pillow — bundled copy is incomplete (missing ImageDraw etc.);
    # the full Pillow from the bootstrapped env is used instead.
    "PIL", "Pillow",
    # WebEngine / Chromium (installed by bootstrap)
    "PyQt6.QtWebEngine",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineQuick",
    "PyQt6.QtWebEngineWidgets",
    # Unused Qt modules
    "PyQt6.QtBluetooth",
    "PyQt6.QtDBus",
    "PyQt6.QtDesigner",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtNfc",
    "PyQt6.QtPositioning",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtSensors",
    "PyQt6.QtSerialPort",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
    "PyQt6.QtTextToSpeech",
    "PyQt6.Qt3DCore",
    "PyQt6.Qt3DAnimation",
    "PyQt6.Qt3DExtras",
    "PyQt6.Qt3DInput",
    "PyQt6.Qt3DLogic",
    "PyQt6.Qt3DRender",
    # Test / dev
    "pytest", "ruff",
    "IPython", "jupyter", "notebook",
    "matplotlib",
    "tkinter", "_tkinter",
]

# ── Hidden imports ───────────────────────────────────────────────────────────

hiddenimports = [
    "splatrix",
    "splatrix.main_qml",
    "splatrix.bootstrapper",
    "splatrix.app_controller",
    "splatrix.qml_bridge",
    "splatrix.stages",
    "splatrix.worker_threads",
    "splatrix.training_backend",
    "splatrix.backend_nerfstudio",
    "splatrix.backend_msplat",
    "splatrix.nerfstudio_integration",
    "splatrix.nerfstudio_video_processor",
    *collect_submodules("transitions"),
]

# ── Analysis ─────────────────────────────────────────────────────────────────

a = Analysis(
    [str(SRC_DIR / "run.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Strip Qt WebEngine frameworks that may have been pulled in despite excludes.
# Careful not to strip our own ViewerWebEngine.qml.
def _is_qt_webengine(name):
    return ("QtWebEngine" in name or "WebEngine" in name) and "ViewerWebEngine.qml" not in name

a.binaries = [b for b in a.binaries if not _is_qt_webengine(b[0])]
a.datas = [d for d in a.datas if not _is_qt_webengine(d[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── Executable ───────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Splatrix",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=False,
    target_arch="arm64",
)

# ── Collect ──────────────────────────────────────────────────────────────────

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    name="Splatrix",
)

# ── macOS .app bundle ────────────────────────────────────────────────────────

app = BUNDLE(
    coll,
    name="Splatrix.app",
    icon=str(RESOURCES / "icon.icns"),
    bundle_identifier="io.github.mutexre.splatrix",
    info_plist={
        "CFBundleName": "Splatrix",
        "CFBundleDisplayName": "Splatrix",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSRequiresAquaSystemAppearance": False,
    },
)
