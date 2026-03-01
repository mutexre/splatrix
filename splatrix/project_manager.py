
"""Project persistence manager - saves/restores pipeline state across app restarts.

A project is a DIRECTORY containing:
  project.yaml   — metadata, settings, stage statuses
  nerfstudio/     — workspace for nerfstudio pipeline
  output.ply      — exported Gaussian Splat
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


# Stage definitions in pipeline order
STAGE_ORDER = ['frames', 'feature_extract', 'feature_match', 'reconstruction', 'training', 'export']

SETTINGS_DIR = Path.home() / ".splatrix"
RECENT_PROJECTS_FILE = SETTINGS_DIR / "recent_projects.json"
MAX_RECENT = 10

PROJECT_FILENAME = "project.yaml"


class ProjectManager:
    """Manages project directories for pipeline state persistence.

    Each project is a folder containing project.yaml plus all generated data.
    """

    def __init__(self):
        self.project_dir: Optional[Path] = None   # The project folder
        self._data: dict = {}
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
    def project_path(self) -> Optional[Path]:
        """Path to project.yaml inside the project dir (for compat)."""
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

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def new_project(
        self,
        project_dir: Optional[str] = None,
        video_path: Optional[str] = None,
        settings: Optional[dict] = None
    ) -> dict:
        """Initialize a new project. If project_dir given, create the folder."""
        now = datetime.now().isoformat(timespec='seconds')
        self._data = {
            'project': {
                'version': '2.0',
                'created': now,
                'modified': now,
            },
            'input': {
                'video_path': video_path,
            },
            'settings': settings or {},
            'stages': {
                stage: {'status': 'pending'} for stage in STAGE_ORDER
            },
        }
        if project_dir:
            self.project_dir = Path(project_dir)
            self.project_dir.mkdir(parents=True, exist_ok=True)
            self._add_to_recent(self.project_dir)
        else:
            self.project_dir = None
        return self._data

    def load_project(self, path: str) -> dict:
        """Load project from a directory or a project.yaml file.
        Accepts either the project directory or the yaml file path.
        """
        p = Path(path)
        if p.is_dir():
            proj_dir = p
            proj_file = p / PROJECT_FILENAME
        elif p.name == PROJECT_FILENAME or p.suffix in ('.yaml', '.yml', '.splatproj'):
            proj_dir = p.parent
            proj_file = p
            # Legacy .splatproj files: treat parent as project dir
            if p.suffix == '.splatproj':
                proj_dir = p.parent
                proj_file = p
        else:
            raise FileNotFoundError(f"Not a valid project: {p}")

        if not proj_file.exists():
            # Check for legacy .splatproj
            legacy = list(proj_dir.glob("*.splatproj"))
            if legacy:
                proj_file = legacy[0]
            else:
                raise FileNotFoundError(f"Project file not found: {proj_file}")

        with open(proj_file, 'r') as f:
            data = yaml.safe_load(f)

        self._data = data or {}
        self.project_dir = proj_dir
        self._add_to_recent(proj_dir)
        return self._data

    def save_project(self, path: Optional[str] = None) -> bool:
        """Save project to disk. If path given, sets project dir.
        Returns True on success."""
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

        # Update modification timestamp
        if 'project' in self._data:
            self._data['project']['modified'] = datetime.now().isoformat(timespec='seconds')

        save_file = self.project_dir / PROJECT_FILENAME
        tmp_file = save_file.with_suffix('.yaml.tmp')
        with open(tmp_file, 'w') as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        tmp_file.replace(save_file)  # atomic on POSIX

        self._add_to_recent(self.project_dir)
        return True

    # ── Data Updates ──────────────────────────────────────────────────────────

    def update_input(self, video_path: str, video_info: Optional[dict] = None):
        """Update input video info"""
        self._ensure_open()
        self._data.setdefault('input', {})['video_path'] = video_path
        if video_info:
            self._data['input'].update(video_info)

    def update_settings(self, settings: dict):
        """Update processing settings"""
        self._ensure_open()
        self._data['settings'] = settings

    def update_stage(self, stage_key: str, status: str, **extra):
        """Update a pipeline stage's status and optional metadata."""
        self._ensure_open()
        stages = self._data.setdefault('stages', {})
        stage = stages.setdefault(stage_key, {})
        stage['status'] = status

        if status == 'completed' and 'completed_at' not in extra:
            extra['completed_at'] = datetime.now().isoformat(timespec='seconds')

        stage.update(extra)

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_stage(self, stage_key: str) -> dict:
        return self._data.get('stages', {}).get(stage_key, {'status': 'pending'})

    def is_stage_completed(self, stage_key: str) -> bool:
        return self.get_stage(stage_key).get('status') == 'completed'

    def get_resume_point(self) -> Optional[str]:
        """Return the first non-completed stage key, or None if all done."""
        for stage in STAGE_ORDER:
            if not self.is_stage_completed(stage):
                return stage
        return None

    def can_resume_from_training(self) -> bool:
        """True if training is complete and checkpoint exists"""
        stage = self.get_stage('training')
        if stage.get('status') != 'completed':
            return False
        ckpt = stage.get('latest_checkpoint')
        return bool(ckpt and Path(ckpt).exists())

    def can_resume_from_data(self) -> bool:
        """True if data processing (COLMAP) is complete"""
        return (
            self.is_stage_completed('frames') and
            self.is_stage_completed('feature_extract') and
            self.is_stage_completed('feature_match') and
            self.is_stage_completed('reconstruction')
        )

    def get_training_checkpoint(self) -> Optional[str]:
        """Get latest checkpoint path if available"""
        return self.get_stage('training').get('latest_checkpoint')

    def get_export_ply(self) -> Optional[str]:
        """Get exported PLY path if available"""
        return self.get_stage('export').get('ply_path')

    # ── Recent Projects ───────────────────────────────────────────────────────

    def get_recent_projects(self) -> list[str]:
        """Returns list of recent project directory paths (most recent first)"""
        if not RECENT_PROJECTS_FILE.exists():
            return []
        try:
            with open(RECENT_PROJECTS_FILE) as f:
                paths = json.load(f)
            return [p for p in paths if Path(p).exists()]
        except Exception:
            return []

    def _add_to_recent(self, path: Path):
        """Add a project to the recent projects list"""
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
