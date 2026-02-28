"""Project persistence manager - saves/restores pipeline state across app restarts"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


# Stage definitions in pipeline order
STAGE_ORDER = ['frames', 'feature_extract', 'feature_match', 'reconstruction', 'training', 'export']

SETTINGS_DIR = Path.home() / ".splats_workspace"
RECENT_PROJECTS_FILE = SETTINGS_DIR / "recent_projects.json"
MAX_RECENT = 10


class ProjectManager:
    """Manages .splatproj project files (YAML format) for pipeline state persistence"""

    def __init__(self):
        self.project_path: Optional[Path] = None
        self._data: dict = {}
        SETTINGS_DIR.mkdir(exist_ok=True)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return bool(self._data)

    @property
    def project_name(self) -> str:
        if self.project_path:
            return self.project_path.stem
        return "Unsaved Project"

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
        video_path: Optional[str] = None,
        settings: Optional[dict] = None
    ) -> dict:
        """Initialize a new in-memory project"""
        now = datetime.now().isoformat(timespec='seconds')
        self._data = {
            'project': {
                'version': '1.0',
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
        self.project_path = None
        return self._data

    def load_project(self, path: str) -> dict:
        """Load project from .splatproj YAML file. Returns project data dict."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Project file not found: {p}")

        with open(p, 'r') as f:
            data = yaml.safe_load(f)

        self._data = data or {}
        self.project_path = p
        self._add_to_recent(p)
        return self._data

    def save_project(self, path: Optional[str] = None) -> bool:
        """Save project to disk. Uses existing path if no path provided.
        Returns True on success."""
        if not self._data:
            return False

        save_path = Path(path) if path else self.project_path
        if not save_path:
            return False  # No path set - caller must use save_as

        # Update modification timestamp
        if 'project' in self._data:
            self._data['project']['modified'] = datetime.now().isoformat(timespec='seconds')

        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, 'w') as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        if path:
            self.project_path = save_path
            self._add_to_recent(save_path)

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
        """Update a pipeline stage's status and optional metadata.

        Args:
            stage_key: One of STAGE_ORDER values
            status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
            **extra: Additional fields to store (path, count, checkpoint_dir, etc.)
        """
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
        return None  # All complete

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
        """Returns list of recent project paths (most recent first)"""
        if not RECENT_PROJECTS_FILE.exists():
            return []
        try:
            with open(RECENT_PROJECTS_FILE) as f:
                paths = json.load(f)
            # Filter to existing files only
            return [p for p in paths if Path(p).exists()]
        except Exception:
            return []

    def _add_to_recent(self, path: Path):
        """Add a project to the recent projects list"""
        recent = self.get_recent_projects()
        path_str = str(path)
        # Remove if already present
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
