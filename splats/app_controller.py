"""Application controller — manages multiple project windows."""

import json
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QUrl, QStandardPaths
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtWidgets import QFileDialog, QMessageBox


# Where we persist session state
SETTINGS_DIR = Path.home() / ".splats_workspace"
SESSION_FILE = SETTINGS_DIR / "session.json"
PROJECTS_FOLDER_NAME = "Splats Projects"


class AppController(QObject):
    """Creates / destroys project windows.  Each window is an independent
    (QQmlApplicationEngine, Backend) pair."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._windows: list[tuple[QQmlApplicationEngine, "Backend"]] = []
        self._qml_dir = Path(__file__).parent / "qml"
        self._projects_root: Optional[Path] = None
        SETTINGS_DIR.mkdir(exist_ok=True)

    # ── Projects root directory ───────────────────────────────────────────

    @property
    def projects_root(self) -> Optional[Path]:
        return self._projects_root

    def ensure_projects_root(self) -> bool:
        """Ensure the default 'Splats Projects' folder exists in ~/Documents.

        Returns True if a valid projects root is available.  If a non-folder
        entity blocks the default path, prompts the user to pick an
        alternative location.
        """
        # Check for a previously saved custom location
        saved = self._load_projects_root()
        if saved and saved.is_dir():
            self._projects_root = saved
            return True

        docs = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        ))
        default_path = docs / PROJECTS_FOLDER_NAME

        if default_path.is_dir():
            # Already exists as a folder — use it
            self._projects_root = default_path
            self._save_projects_root()
            return True

        if not default_path.exists():
            # Nothing there — create it
            try:
                default_path.mkdir(parents=True, exist_ok=True)
                self._projects_root = default_path
                self._save_projects_root()
                return True
            except OSError as e:
                print(f"[WARN] Cannot create {default_path}: {e}", file=sys.stderr)

        # Something non-folder exists at that path, or creation failed
        QMessageBox.information(
            None,
            "Projects Folder",
            f"Cannot use default location:\n{default_path}\n\n"
            "Please choose where to store Splats projects.",
        )
        chosen = QFileDialog.getExistingDirectory(
            None, "Choose Projects Root Folder", str(docs)
        )
        if chosen:
            self._projects_root = Path(chosen)
            self._save_projects_root()
            return True

        return False

    def _load_projects_root(self) -> Optional[Path]:
        try:
            with open(SESSION_FILE) as f:
                data = json.load(f)
            root = data.get("projects_root")
            return Path(root) if root else None
        except Exception:
            return None

    def _save_projects_root(self):
        data = self._load_session_data()
        data["projects_root"] = str(self._projects_root) if self._projects_root else None
        self._write_session(data)

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

    def _load_session_data(self) -> dict:
        if not SESSION_FILE.exists():
            return {}
        try:
            with open(SESSION_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_session(self, data: dict):
        try:
            with open(SESSION_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _save_session(self):
        """Persist list of open project dirs so they reopen next launch."""
        data = self._load_session_data()
        dirs = []
        for _, backend in self._windows:
            d = backend._project.project_dir
            if d and d.exists():
                dirs.append(str(d))
        data["open_projects"] = dirs
        self._write_session(data)

    def restore_session(self) -> bool:
        """Reopen windows from last session.  Returns True if at least one
        window was created."""
        data = self._load_session_data()
        dirs = data.get("open_projects", [])

        opened = False
        for d in dirs:
            p = Path(d)
            if p.is_dir() and (p / "project.yaml").exists():
                if self.create_window(project_dir=d):
                    opened = True
        return opened
