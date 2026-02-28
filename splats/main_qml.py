"""QML-based application entry point for Video to Gaussian Splats Converter."""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtWebEngineQuick import QtWebEngineQuick
from PyQt6.QtCore import QUrl

from .qml_bridge import Backend


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

    # Create backend (Python ↔ QML bridge)
    backend = Backend()

    # Create QML engine
    engine = QQmlApplicationEngine()

    # QML import path — add the directory containing our QML files
    engine.addImportPath(str(qml_dir))

    # Expose backend to QML
    engine.rootContext().setContextProperty("backend", backend)

    # Load main QML
    main_qml = qml_dir / "main.qml"
    engine.load(QUrl.fromLocalFile(str(main_qml)))

    if not engine.rootObjects():
        print("ERROR: Failed to load QML. Check console for errors.", file=sys.stderr)
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
