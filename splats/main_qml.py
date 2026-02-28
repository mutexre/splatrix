"""QML-based application entry point for Video to Gaussian Splats Converter.

Uses AppController to manage multiple project windows (one Backend per window).
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWebEngineQuick import QtWebEngineQuick

from .app_controller import AppController


def main():
    # Must be called before QApplication
    QtWebEngineQuick.initialize()

    app = QApplication(sys.argv)

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

    # Try to restore previous session (reopens all windows from last run)
    if not controller.restore_session():
        # No previous session → open one empty window
        controller.create_window()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
