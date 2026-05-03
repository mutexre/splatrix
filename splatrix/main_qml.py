"""QML-based application entry point for Splatrix.

Startup sequence:
1. If frozen (.app), prepend ~/.splatrix env site-packages to sys.path
2. Check if ML pipeline dependencies are installed
3. If not, show bootstrap dialog to download and install them
4. Ensure "SplatrixProjects" folder exists in ~/Documents
5. Restore last session (reopen previously open projects)
6. If no session to restore, open one empty window
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont, QIcon
from PyQt6.QtQml import QQmlApplicationEngine

try:
    from PyQt6.QtWebEngineQuick import QtWebEngineQuick
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

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

    if _HAS_WEBENGINE:
        QtWebEngineQuick.initialize()

    _prepend_env_site_packages()

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


def _resource_dir() -> Path:
    """Root of the splatrix package resources.
    In frozen mode, PyInstaller extracts data into sys._MEIPASS."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "splatrix"
    return Path(__file__).parent


class _EnvFallbackFinder:
    """Meta-path finder that resolves submodule imports from the bootstrapped
    env's stdlib/site-packages when PyInstaller's FrozenImporter owns the
    parent package but doesn't bundle the submodule.

    Appended to the END of sys.meta_path so it only activates after all
    default finders have given up."""

    def __init__(self, env_lib: Path):
        self._roots = []
        if env_lib.is_dir():
            for pydir in sorted(env_lib.glob("python3.*")):
                self._roots.append(pydir)
                sp = pydir / "site-packages"
                if sp.is_dir():
                    self._roots.append(sp)

    def find_spec(self, fullname, path, target=None):
        import importlib.util
        import importlib.machinery
        parts = fullname.replace(".", "/")
        for root in self._roots:
            pkg_init = root / parts / "__init__.py"
            if pkg_init.is_file():
                return importlib.util.spec_from_file_location(
                    fullname, str(pkg_init),
                    submodule_search_locations=[str(root / parts)],
                )
            for suffix in importlib.machinery.SOURCE_SUFFIXES:
                candidate = root / (parts + suffix)
                if candidate.is_file():
                    return importlib.util.spec_from_file_location(
                        fullname, str(candidate))
            for suffix in importlib.machinery.EXTENSION_SUFFIXES:
                candidate = root / (parts + suffix)
                if candidate.is_file():
                    return importlib.util.spec_from_file_location(
                        fullname, str(candidate))
        return None


def _prepend_env_site_packages():
    """When running from a frozen .app, ML deps live in ~/.splatrix/envs.
    Add that env's site-packages to sys.path so they become importable.

    Also installs a fallback meta-path finder so that submodules of
    packages already loaded by PyInstaller's FrozenImporter (e.g.
    ctypes.util, xml.etree) can be resolved from the env's complete
    stdlib."""
    splatrix_env = Path.home() / ".splatrix" / "envs" / "splatrix"
    if not splatrix_env.is_dir():
        return

    lib_dir = splatrix_env / "lib"
    if lib_dir.is_dir():
        for pydir in sorted(lib_dir.glob("python3.*")):
            sp = pydir / "site-packages"
            if sp.is_dir():
                sp_str = str(sp)
                if sp_str not in sys.path:
                    sys.path.insert(0, sp_str)

    # Install fallback finder for frozen-bundle submodule gaps
    if getattr(sys, "frozen", False) and lib_dir.is_dir():
        finder = _EnvFallbackFinder(lib_dir)
        if finder._roots:
            sys.meta_path.append(finder)

    bin_dir = splatrix_env / "bin"
    if bin_dir.is_dir():
        path = os.environ.get("PATH", "")
        if str(bin_dir) not in path:
            os.environ["PATH"] = f"{bin_dir}:{path}"


def _reload_modules():
    """After bootstrap installs new packages, ensure Python's import
    machinery can find them.  The nerfstudio/torch checks are now lazy
    (done at use-time in each class), so we only need to clear the
    finder caches so newly-installed packages are discoverable."""
    import importlib
    _prepend_env_site_packages()
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
    pkg = _resource_dir()
    icon_dir = pkg / "qml" / "icons"
    for icon_file in ["app-icon.png", "app-icon.svg"]:
        icon_path = icon_dir / icon_file
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    res_dir = pkg.parent / "resources"
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
    qml_dir = _resource_dir() / "qml"
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
