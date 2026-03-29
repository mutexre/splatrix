"""QML-based application entry point for Splatrix.

Startup sequence:
1. Check if ML pipeline dependencies are installed
2. If not, show bootstrap dialog to download and install them
3. Ensure "SplatrixProjects" folder exists in ~/Documents
4. Restore last session (reopen previously open projects)
5. If no session to restore, open one empty window
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont, QIcon
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtWebEngineQuick import QtWebEngineQuick

from .bootstrapper import is_bootstrap_needed, reset_bootstrap, BootstrapController


def main():
    if "--reset-bootstrap" in sys.argv:
        reset_bootstrap()
        sys.argv.remove("--reset-bootstrap")

    force_bootstrap = "--force-bootstrap" in sys.argv
    if force_bootstrap:
        sys.argv.remove("--force-bootstrap")

    try:
        import setproctitle
        setproctitle.setproctitle("Splatrix")
    except ImportError:
        pass

    QtWebEngineQuick.initialize()

    app = QApplication(sys.argv)
    app.setApplicationName("Splatrix")
    app.setApplicationDisplayName("Splatrix")
    app.setOrganizationName("mutexre")
    app.setOrganizationDomain("mutexre.github.io")
    app.setQuitOnLastWindowClosed(False)

    _setup_icon(app)
    qml_dir = _setup_fonts(app)

    if force_bootstrap or is_bootstrap_needed():
        _run_bootstrap(app, qml_dir)
    else:
        _start_app(app)

    sys.exit(app.exec())


def _run_bootstrap(app: QApplication, qml_dir: Path):
    """Show the bootstrap dialog; start the main app when done."""
    controller = BootstrapController()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bootstrapController", controller)
    engine.addImportPath(str(qml_dir))
    engine.load(QUrl.fromLocalFile(str(qml_dir / "BootstrapDialog.qml")))

    if not engine.rootObjects():
        print("ERROR: Failed to load bootstrap dialog", file=sys.stderr)
        sys.exit(1)

    # prevent GC — Python would otherwise destroy these locals when this
    # function returns, even though Qt still references them via the context
    app._bootstrap_engine = engine
    app._bootstrap_controller = controller

    def on_proceed():
        for obj in engine.rootObjects():
            obj.close()
        engine.deleteLater()
        del app._bootstrap_engine
        del app._bootstrap_controller
        _reload_modules()
        # Defer app startup to the next event-loop tick so the bootstrap
        # dialog actually closes before heavy module imports block the thread.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: _start_app(app))

    controller.finished.connect(on_proceed)


def _reload_modules():
    """After bootstrap installs new packages, ensure Python's import
    machinery can find them.  The nerfstudio/torch checks are now lazy
    (done at use-time in each class), so we only need to clear the
    finder caches so newly-installed packages are discoverable."""
    import importlib
    importlib.invalidate_caches()
    sys.path_importer_cache.clear()


def _start_app(app: QApplication):
    """Normal app startup — open project windows."""
    from .app_controller import AppController

    controller = AppController()

    if not controller.ensure_projects_root():
        print("No projects folder configured — exiting.", file=sys.stderr)
        app.quit()
        return

    if not controller.restore_session():
        controller.create_window()

    # prevent GC — when called from a signal handler the local would
    # be collected on return, destroying all windows
    app._app_controller = controller


def _setup_icon(app: QApplication):
    icon_dir = Path(__file__).parent / "qml" / "icons"
    for icon_file in ["app-icon.png", "app-icon.svg"]:
        icon_path = icon_dir / icon_file
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    res_dir = Path(__file__).parent.parent / "resources"
    if (res_dir / "icon-256.png").exists():
        icon = QIcon()
        for sz in [16, 32, 48, 64, 128, 256, 512, 1024]:
            p = res_dir / f"icon-{sz}.png"
            if p.exists():
                icon.addFile(str(p))
        if not icon.isNull():
            app.setWindowIcon(icon)


def _setup_fonts(app: QApplication) -> Path:
    """Load Inter font family.  Returns the qml directory path."""
    qml_dir = Path(__file__).parent / "qml"
    font_dir = qml_dir / "fonts"

    for ttf in font_dir.glob("Inter*.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            print(f"[Font] Loaded: {ttf.name} → {families}")

    font = QFont("Inter Variable")
    font.setPixelSize(13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    return qml_dir


if __name__ == "__main__":
    main()
