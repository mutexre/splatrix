"""Project persistence manager — saves/restores pipeline state across app restarts.

A project is a DIRECTORY containing:
  project.yaml   — metadata, settings, stage generations
  nerfstudio/     — workspace for nerfstudio pipeline
  output.ply      — exported Gaussian Splat
  .lock           — advisory lock held while the project is open
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .protocol import Operation, StageState, OPERATION_DEPENDENCIES
from .stages import Stage

SETTINGS_DIR = Path.home() / ".splatrix"
RECENT_PROJECTS_FILE = SETTINGS_DIR / "recent_projects.json"
MAX_RECENT = 10

PROJECT_FILENAME = "project.yaml"


class ProjectLockedError(Exception):
    """Raised when trying to open a project that is locked by another instance."""


class ProjectManager:
    """Manages project directories for pipeline state persistence.

    Each project is a folder containing project.yaml plus all generated data.
    """

    def __init__(self):
        self.project_dir: Optional[Path] = None
        self._data: dict = {}
        self._lock_fd = None
        SETTINGS_DIR.mkdir(exist_ok=True)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return bool(self._data)

    @property
    def project_name(self) -> str:
        if self.project_dir:
            return self.project_dir.name
        return "Unsaved Project"

    @property
    def project_uuid(self) -> Optional[str]:
        return self._data.get('project', {}).get('uuid')

    @property
    def project_path(self) -> Optional[Path]:
        """Path to project.yaml inside the project dir."""
        if self.project_dir:
            return self.project_dir / PROJECT_FILENAME
        return None

    @property
    def workspace_dir(self) -> Optional[Path]:
        """Nerfstudio workspace inside the project dir."""
        if self.project_dir:
            return self.project_dir / "nerfstudio"
        return None

    @property
    def output_ply_path(self) -> Optional[Path]:
        """Default PLY output inside the project dir."""
        if self.project_dir:
            return self.project_dir / "output.ply"
        return None

    @property
    def video_path(self) -> Optional[str]:
        return self._data.get('input', {}).get('video_path')

    @property
    def settings(self) -> dict:
        return self._data.get('settings', {})

    @property
    def stages(self) -> dict:
        return self._data.get('stages', {})

    # ── Locking ───────────────────────────────────────────────────────────────

    def _acquire_lock(self) -> None:
        """Acquire an exclusive advisory lock on the project directory.

        Uses ``fcntl.flock`` on a ``.lock`` file.  The lock is released
        automatically when the file descriptor is closed (including on crash).
        """
        if not self.project_dir:
            return
        lock_path = self.project_dir / ".lock"
        self._lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            self._lock_fd.close()
            self._lock_fd = None
            raise ProjectLockedError(
                f"Project is open in another instance: {self.project_dir}"
            )

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
            except OSError:
                pass
            self._lock_fd = None

    def close(self) -> None:
        """Close the project and release the lock."""
        self._release_lock()
        self._data = {}
        self.project_dir = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def new_project(
        self,
        project_dir: Optional[str] = None,
        video_path: Optional[str] = None,
        settings: Optional[dict] = None,
    ) -> dict:
        """Initialize a new project.  If *project_dir* given, create the folder
        and acquire a lock."""
        self._release_lock()
        now = datetime.now().isoformat(timespec='seconds')
        self._data = {
            'project': {
                'uuid': str(_uuid.uuid4()),
                'version': '2.0',
                'created': now,
                'modified': now,
            },
            'input': {
                'video_path': video_path,
            },
            'settings': settings or {},
            'stages': {},
        }
        if project_dir:
            self.project_dir = Path(project_dir)
            self.project_dir.mkdir(parents=True, exist_ok=True)
            self._acquire_lock()
            self._add_to_recent(self.project_dir)
        else:
            self.project_dir = None
        return self._data

    def load_project(self, path: str) -> dict:
        """Load project from a directory or a project.yaml file.

        Acquires an exclusive lock; raises ``ProjectLockedError`` if the
        project is already open in another instance.
        """
        self._release_lock()
        p = Path(path)
        if p.is_dir():
            proj_dir = p
            proj_file = p / PROJECT_FILENAME
        elif p.name == PROJECT_FILENAME or p.suffix in ('.yaml', '.yml', '.splatproj'):
            proj_dir = p.parent
            proj_file = p
        else:
            raise FileNotFoundError(f"Not a valid project: {p}")

        if not proj_file.exists():
            legacy = list(proj_dir.glob("*.splatproj"))
            if legacy:
                proj_file = legacy[0]
            else:
                raise FileNotFoundError(f"Project file not found: {proj_file}")

        with open(proj_file, 'r') as f:
            data = yaml.safe_load(f)

        self._data = data or {}
        self.project_dir = proj_dir

        # Ensure project has a UUID (back-fill older projects)
        if 'uuid' not in self._data.get('project', {}):
            self._data.setdefault('project', {})['uuid'] = str(_uuid.uuid4())

        self._acquire_lock()
        self._add_to_recent(proj_dir)
        return self._data

    def save_project(self, path: Optional[str] = None) -> bool:
        """Save project to disk.  Returns True on success."""
        if not self._data:
            return False

        if path:
            p = Path(path)
            if p.suffix in ('.yaml', '.yml', '.splatproj'):
                self.project_dir = p.parent
            else:
                self.project_dir = p
                self.project_dir.mkdir(parents=True, exist_ok=True)

        if not self.project_dir:
            return False

        self.project_dir.mkdir(parents=True, exist_ok=True)

        if 'project' in self._data:
            self._data['project']['modified'] = datetime.now().isoformat(timespec='seconds')

        save_file = self.project_dir / PROJECT_FILENAME
        tmp_file = save_file.with_suffix('.yaml.tmp')
        with open(tmp_file, 'w') as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        tmp_file.replace(save_file)

        self._add_to_recent(self.project_dir)
        return True

    # ── Data Updates ──────────────────────────────────────────────────────────

    def update_input(self, video_path: str, video_info: Optional[dict] = None):
        self._ensure_open()
        self._data.setdefault('input', {})['video_path'] = video_path
        if video_info:
            self._data['input'].update(video_info)

    def update_settings(self, settings: dict):
        self._ensure_open()
        self._data['settings'] = settings

    def update_stage(self, stage: Stage, status: str, **extra):
        """Update a pipeline stage's status and optional metadata.

        .. deprecated:: Use :meth:`bump_generation` for the new generation model.
        """
        self._ensure_open()
        stages = self._data.setdefault('stages', {})
        entry = stages.setdefault(stage.value, {})
        entry['status'] = status
        if status == 'completed' and 'completed_at' not in extra:
            extra['completed_at'] = datetime.now().isoformat(timespec='seconds')
        entry.update(extra)

    # ── Generation tracking ───────────────────────────────────────────────────

    def get_generation(self, op: Operation) -> int:
        """Return the current generation for *op*, or 0 if never completed."""
        stage = self._data.get('stages', {}).get(op.value, {})
        return stage.get('generation', 0)

    def get_input_gen(self, op: Operation) -> dict[str, int]:
        """Return the ``input_gen`` dict for *op* (which dep generations
        were used as input the last time this operation completed)."""
        stage = self._data.get('stages', {}).get(op.value, {})
        return dict(stage.get('input_gen', {}))

    def bump_generation(self, op: Operation) -> int:
        """Increment the generation counter for *op* and record ``input_gen``
        from the current generations of its dependencies.

        Called **before** atomic-swapping output into the project dir
        (bump-before-swap ordering).  Returns the new generation value.
        """
        self._ensure_open()
        stages = self._data.setdefault('stages', {})
        entry = stages.setdefault(op.value, {})

        old_gen = entry.get('generation', 0)
        new_gen = old_gen + 1
        entry['generation'] = new_gen

        deps = OPERATION_DEPENDENCIES.get(op, [])
        if deps:
            entry['input_gen'] = {
                dep.value: self.get_generation(dep) for dep in deps
            }
        elif 'input_gen' in entry:
            del entry['input_gen']

        entry['bumped_at'] = datetime.now().isoformat(timespec='seconds')
        return new_gen

    def operation_validity(self, op: Operation) -> StageState:
        """Compute the validity state of *op* (NO_DATA, VALID, or OUTDATED).

        Checks both direct and transitive dependencies.
        """
        stage = self._data.get('stages', {}).get(op.value, {})
        if 'generation' not in stage:
            return StageState.NO_DATA

        for dep in OPERATION_DEPENDENCIES.get(op, []):
            dep_gen_used = stage.get('input_gen', {}).get(dep.value, 0)
            current_dep_gen = self.get_generation(dep)
            if current_dep_gen != dep_gen_used:
                return StageState.OUTDATED
            if self.operation_validity(dep) == StageState.OUTDATED:
                return StageState.OUTDATED

        return StageState.VALID

    def all_operation_states(self) -> dict[Operation, StageState]:
        """Return the validity state for every operation."""
        return {op: self.operation_validity(op) for op in Operation}

    def current_depends_on(self, op: Operation) -> dict[str, int]:
        """Build a ``depends_on`` dict for a new server request for *op*.

        Maps each dependency operation name to its current generation.
        """
        return {
            dep.value: self.get_generation(dep)
            for dep in OPERATION_DEPENDENCIES.get(op, [])
        }

    # ── Legacy query helpers (backward compat) ────────────────────────────────

    def get_stage(self, stage: Stage) -> dict:
        return self._data.get('stages', {}).get(stage.value, {'status': 'pending'})

    def is_stage_completed(self, stage: Stage) -> bool:
        s = self.get_stage(stage)
        if s.get('status') == 'completed':
            return True
        return 'generation' in s

    def get_resume_point(self) -> Optional[Stage]:
        for stage in Stage:
            if not self.is_stage_completed(stage):
                return stage
        return None

    def can_resume_from_training(self) -> bool:
        data = self.get_stage(Stage.TRAINING)
        if data.get('status') != 'completed' and 'generation' not in data:
            return False
        ckpt = data.get('latest_checkpoint')
        return bool(ckpt and Path(ckpt).exists())

    def can_resume_from_data(self) -> bool:
        return all(
            self.is_stage_completed(s)
            for s in (Stage.FRAMES, Stage.FEATURE_EXTRACT, Stage.FEATURE_MATCH, Stage.RECONSTRUCTION)
        )

    def get_training_checkpoint(self) -> Optional[str]:
        return self.get_stage(Stage.TRAINING).get('latest_checkpoint')

    def get_export_ply(self) -> Optional[str]:
        return self.get_stage(Stage.EXPORT).get('ply_path')

    # ── Recent Projects ───────────────────────────────────────────────────────

    def get_recent_projects(self) -> list[str]:
        if not RECENT_PROJECTS_FILE.exists():
            return []
        try:
            with open(RECENT_PROJECTS_FILE) as f:
                paths = json.load(f)
            return [p for p in paths if Path(p).exists()]
        except Exception:
            return []

    def _add_to_recent(self, path: Path):
        recent = self.get_recent_projects()
        path_str = str(path)
        recent = [p for p in recent if p != path_str]
        recent.insert(0, path_str)
        recent = recent[:MAX_RECENT]
        try:
            with open(RECENT_PROJECTS_FILE, 'w') as f:
                json.dump(recent, f, indent=2)
        except Exception:
            pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_open(self):
        if not self._data:
            self.new_project()
