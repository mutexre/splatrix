"""QML-based application entry point for Splatrix.

Startup sequence:
1. Ensure "SplatrixProjects" folder exists in ~/Documents
2. Restore last session (reopen previously open projects)
3. If no session to restore, open one empty window
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont, QIcon
from PyQt6.QtWebEngineQuick import QtWebEngineQuick

from .app_controller import AppController


def main():
    # Set process title so it appears as "Splatrix" in Activity Monitor / task manager
    try:
        import setproctitle
        setproctitle.setproctitle("Splatrix")
    except ImportError:
        pass

    # Must be called before QApplication
    QtWebEngineQuick.initialize()

    app = QApplication(sys.argv)
    app.setApplicationName("Splatrix")
    app.setApplicationDisplayName("Splatrix")
    app.setOrganizationName("mutexre")
    app.setOrganizationDomain("mutexre.github.io")

    # Set application icon (used in Dock, taskbar, window decorations)
    icon_dir = Path(__file__).parent / "qml" / "icons"
    for icon_file in ["app-icon.png", "app-icon.svg"]:
        icon_path = icon_dir / icon_file
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    # Also check resources dir (for higher-res icons)
    res_dir = Path(__file__).parent.parent / "resources"
    if (res_dir / "icon-256.png").exists():
        icon = QIcon()
        for sz in [16, 32, 48, 64, 128, 256, 512, 1024]:
            p = res_dir / f"icon-{sz}.png"
            if p.exists():
                icon.addFile(str(p))
        if not icon.isNull():
            app.setWindowIcon(icon)

    # Load bundled Inter variable font
    qml_dir = Path(__file__).parent / "qml"
    font_dir = qml_dir / "fonts"
    for ttf in font_dir.glob("Inter*.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            print(f"[Font] Loaded: {ttf.name} → {families}")

    # Set Inter as default application font
    font = QFont("Inter Variable")
    font.setPixelSize(13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    # ── Window management ─────────────────────────────────────────────────
    controller = AppController()

    # 1. Ensure projects root folder exists
    if not controller.ensure_projects_root():
        print("No projects folder configured — exiting.", file=sys.stderr)
        sys.exit(1)

    # 2. Try to restore previous session
    if not controller.restore_session():
        # 3. No previous session → open one empty window
        controller.create_window()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
