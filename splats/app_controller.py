"""Application controller — manages multiple project windows."""

import json
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtQml import QQmlApplicationEngine


# Where we persist the list of open windows across sessions
SETTINGS_DIR = Path.home() / ".splats_workspace"
SESSION_FILE = SETTINGS_DIR / "session.json"


class AppController(QObject):
    """Creates / destroys project windows.  Each window is an independent
    (QQmlApplicationEngine, Backend) pair."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._windows: list[tuple[QQmlApplicationEngine, "Backend"]] = []
        self._qml_dir = Path(__file__).parent / "qml"
        SETTINGS_DIR.mkdir(exist_ok=True)

    # ── Window lifecycle ──────────────────────────────────────────────────

    def create_window(
        self,
        project_dir: Optional[str] = None,
        new_project_dir: Optional[str] = None,
    ) -> Optional["Backend"]:
        """Spawn a new project window.

        * project_dir     — open an existing project folder
        * new_project_dir — create a new empty project in this folder
        * neither         — open an empty (unsaved) window
        """
        from .qml_bridge import Backend  # deferred to avoid circular import

        backend = Backend(controller=self)

        engine = QQmlApplicationEngine()
        engine.addImportPath(str(self._qml_dir))
        engine.rootContext().setContextProperty("backend", backend)

        main_qml = self._qml_dir / "main.qml"
        engine.load(QUrl.fromLocalFile(str(main_qml)))

        if not engine.rootObjects():
            print("ERROR: Failed to create project window", file=sys.stderr)
            return None

        self._windows.append((engine, backend))

        # Initialize project state
        if project_dir:
            backend._load_project_file(project_dir)
        elif new_project_dir:
            backend._init_new_project(new_project_dir)

        self._save_session()
        return backend

    def close_window(self, backend: "Backend"):
        """Remove a window and clean up."""
        for i, (engine, b) in enumerate(self._windows):
            if b is backend:
                self._windows.pop(i)
                # Schedule deletion — engine owns the QML window
                engine.deleteLater()
                break

        self._save_session()

        # Quit app when last window closes
        if not self._windows:
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().quit()

    @property
    def window_count(self) -> int:
        return len(self._windows)

    # ── Session persistence ───────────────────────────────────────────────

    def _save_session(self):
        """Persist list of open project dirs so they reopen next launch."""
        dirs = []
        for _, backend in self._windows:
            d = backend._project.project_dir
            if d and d.exists():
                dirs.append(str(d))
        try:
            with open(SESSION_FILE, "w") as f:
                json.dump(dirs, f, indent=2)
        except Exception:
            pass

    def restore_session(self):
        """Reopen windows from last session.  Returns True if at least one
        window was created."""
        if not SESSION_FILE.exists():
            return False
        try:
            with open(SESSION_FILE) as f:
                dirs = json.load(f)
        except Exception:
            return False

        opened = False
        for d in dirs:
            p = Path(d)
            if p.is_dir() and (p / "project.yaml").exists():
                if self.create_window(project_dir=d):
                    opened = True
        return opened
