"""Python ↔ QML bridge: exposes backend state as QObject properties/slots for QML UI."""

import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QObject, pyqtProperty, pyqtSignal, pyqtSlot, QUrl, QVariant
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog, QApplication

from .worker_threads import (
    VideoProcessingWorker, ReconstructionWorker, PLYExportWorker, NerfstudioWorker
)
from .video_processor import VideoProcessor
from .project_manager import ProjectManager, STAGE_ORDER


# ── Stage model exposed to QML ──────────────────────────────────────────────

STAGE_DEFS = [
    ("frames",          "1. Frame Extraction"),
    ("feature_extract", "2. Feature Extraction"),
    ("feature_match",   "3. Feature Matching"),
    ("reconstruction",  "4. Sparse Reconstruction"),
    ("training",        "5. Training (Splatfacto)"),
    ("export",          "6. Export PLY"),
]


class Backend(QObject):
    """Per-window QObject that QML binds to via 'backend' context property.

    Each project window gets its own Backend instance.  The optional
    *controller* reference is used to spawn / close windows.
    """

    # ── Signals for property change notifications ──
    videoNameChanged = pyqtSignal()
    videoInfoChanged = pyqtSignal()
    videoUrlChanged = pyqtSignal()
    hasVideoChanged = pyqtSignal()
    maxFramesChanged = pyqtSignal()
    trainingIterationsChanged = pyqtSignal()
    projectDirChanged = pyqtSignal()
    isProcessingChanged = pyqtSignal()
    canExportPlyChanged = pyqtSignal()
    statusTextChanged = pyqtSignal()
    stagesChanged = pyqtSignal()
    logContentChanged = pyqtSignal()
    windowTitleChanged = pyqtSignal()
    projectNameChanged = pyqtSignal()
    viewerUrlChanged = pyqtSignal()
    frameImagesChanged = pyqtSignal()

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._controller = controller   # AppController (may be None for legacy)

        # Internal state
        self._video_path: Optional[str] = None
        self._video_info = ""
        self._max_frames = 300
        self._training_iterations = 30000
        self._status_text = "Ready"
        self._log_lines: list[str] = []
        self._viewer_url = ""
        self._camera_hint: Optional[dict] = None
        self._frame_images: list[str] = []  # list of file:// URLs for extracted frames

        # Stage state — with ETA tracking
        self._stage_start_times: dict[str, float] = {}  # key → time.time()
        self._stages: list[dict] = [
            {"key": key, "label": label, "status": "pending", "progress": 0.0, "detail": ""}
            for key, label in STAGE_DEFS
        ]
        self._stage_paths: dict[str, Optional[str]] = {k: None for k, _ in STAGE_DEFS}

        # Workspace
        self._workspace = Path.home() / ".splats_workspace"
        self._workspace.mkdir(exist_ok=True)
        self._settings_file = self._workspace / "settings.json"

        # Workers
        self._nerfstudio_worker: Optional[NerfstudioWorker] = None
        self._video_worker: Optional[VideoProcessingWorker] = None
        self._reconstruction_worker: Optional[ReconstructionWorker] = None
        self._export_worker: Optional[PLYExportWorker] = None

        # Project manager
        self._project = ProjectManager()

        # Viewer HTML path
        self._viewer_html = Path(__file__).parent / "viewer" / "viewer.html"

        # Load persisted default settings (not project — that's loaded separately)
        self._load_settings()

    # ══════════════════════════════════════════════════════════════════════════
    #  QML Properties
    # ══════════════════════════════════════════════════════════════════════════

    @pyqtProperty(str, notify=videoNameChanged)
    def videoName(self):
        return Path(self._video_path).name if self._video_path else ""

    @pyqtProperty(str, notify=videoInfoChanged)
    def videoInfo(self):
        return self._video_info

    @pyqtProperty(QUrl, notify=videoUrlChanged)
    def videoUrl(self):
        if self._video_path:
            return QUrl.fromLocalFile(self._video_path)
        return QUrl()

    @pyqtProperty(bool, notify=hasVideoChanged)
    def hasVideo(self):
        return self._video_path is not None

    @pyqtProperty(int, notify=maxFramesChanged)
    def maxFrames(self):
        return self._max_frames

    @maxFrames.setter
    def maxFrames(self, v):
        if self._max_frames != v:
            self._max_frames = v
            self.maxFramesChanged.emit()
            self._save_settings()
            self._auto_save_project()

    @pyqtProperty(int, notify=trainingIterationsChanged)
    def trainingIterations(self):
        return self._training_iterations

    @trainingIterations.setter
    def trainingIterations(self, v):
        if self._training_iterations != v:
            self._training_iterations = v
            self.trainingIterationsChanged.emit()
            self._save_settings()
            self._auto_save_project()

    @pyqtProperty(str, notify=projectDirChanged)
    def projectDir(self):
        return str(self._project.project_dir) if self._project.project_dir else ""

    @pyqtProperty(bool, notify=isProcessingChanged)
    def isProcessing(self):
        return any([
            self._nerfstudio_worker and self._nerfstudio_worker.isRunning(),
            self._video_worker and self._video_worker.isRunning(),
            self._reconstruction_worker and self._reconstruction_worker.isRunning(),
            self._export_worker and self._export_worker.isRunning(),
        ])

    @pyqtProperty(bool, notify=canExportPlyChanged)
    def canExportPly(self):
        ply = self._project.output_ply_path
        return (
            not self.isProcessing and
            ply is not None and ply.exists()
        )

    @pyqtProperty(str, notify=statusTextChanged)
    def statusText(self):
        return self._status_text

    @pyqtProperty("QVariantList", notify=stagesChanged)
    def stages(self):
        return self._stages

    @pyqtProperty(str, notify=logContentChanged)
    def logContent(self):
        return "\n".join(self._log_lines)

    @pyqtProperty(str, notify=windowTitleChanged)
    def windowTitle(self):
        if self._project.project_path:
            return f"Video to Gaussian Splats — {self._project.project_name}"
        return "Video to Gaussian Splats Converter"

    @pyqtProperty(str, notify=projectNameChanged)
    def projectName(self):
        return self._project.project_name if self._project.is_open else ""

    @pyqtProperty(QUrl, notify=viewerUrlChanged)
    def viewerUrl(self):
        if self._viewer_url:
            return QUrl(self._viewer_url)
        return QUrl.fromLocalFile(str(self._viewer_html))

    @pyqtProperty("QVariantList", notify=frameImagesChanged)
    def frameImages(self):
        return self._frame_images

    # ══════════════════════════════════════════════════════════════════════════
    #  QML Slots (actions)
    # ══════════════════════════════════════════════════════════════════════════

    @pyqtSlot()
    def selectVideo(self):
        start_dir = str(Path(self._video_path).parent) if self._video_path else str(Path.home())

        VIDEO_EXTS = [
            "mp4", "mov", "avi", "mkv", "webm", "flv", "wmv", "m4v", "mts", "ts",
            "mpg", "mpeg", "3gp", "3g2", "mxf", "dv", "braw", "r3d",
            "vob", "ogv", "gif", "asf", "rm", "swf", "divx", "f4v",
        ]
        patterns = []
        for ext in VIDEO_EXTS:
            patterns.append(f"*.{ext}")
            upper = ext.upper()
            if upper != ext:
                patterns.append(f"*.{upper}")

        filter_str = "Video Files (" + " ".join(patterns) + ");;All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(None, "Select Video File", start_dir, filter_str)

        if file_path:
            self._video_path = file_path
            self.videoNameChanged.emit()
            self.videoUrlChanged.emit()
            self.hasVideoChanged.emit()
            self._log(f"Selected video: {file_path}")

            # Load metadata
            try:
                processor = VideoProcessor()
                info = processor.get_video_info(file_path)
                self._video_info = (
                    f"Resolution: {info['width']}x{info['height']} | "
                    f"FPS: {info['fps']:.2f} | "
                    f"Frames: {info['frame_count']} | "
                    f"Duration: {info['duration']:.2f}s"
                )
                self.videoInfoChanged.emit()
            except Exception as e:
                self._log(f"Error loading video metadata: {e}")

            self._save_settings()
            self._auto_save_project()
            self._update_button_states()

    @pyqtSlot(str)
    def openStageFolder(self, stage_key):
        """Open file browser for a stage's output directory."""
        path = self._stage_paths.get(stage_key)
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self._log(f"Stage folder not available for: {stage_key}")

    @pyqtSlot()
    def startConversion(self):
        if not self._video_path:
            self._log("Error: No video selected")
            return

        # Ensure project folder exists
        if not self._project.project_dir:
            self._ensure_project_dir()
            if not self._project.project_dir:
                self._log("Error: No project directory set")
                return

        self._log("=" * 50)
        self._log("Starting conversion pipeline...")
        self._log(f"Project: {self._project.project_dir}")
        self._set_status("Processing...")

        self._start_nerfstudio_pipeline()

    @pyqtSlot(str)
    def startFromStage(self, stage_key: str):
        """Start pipeline from a specific stage, reusing earlier results."""
        if not self._video_path:
            self._log("Error: No video selected")
            return
        if self.isProcessing:
            return

        if not self._project.project_dir:
            self._ensure_project_dir()
            if not self._project.project_dir:
                self._log("Error: No project directory set")
                return

        self._log("=" * 50)
        self._log(f"Starting pipeline from stage: {stage_key}")
        self._log(f"Project: {self._project.project_dir}")
        self._set_status("Processing...")

        # Determine what to skip based on requested start stage
        stage_keys = [k for k, _ in STAGE_DEFS]
        start_idx = stage_keys.index(stage_key) if stage_key in stage_keys else 0

        if start_idx >= 5:  # export
            # Need a checkpoint to export from
            checkpoint = self._project.get_training_checkpoint()
            if not checkpoint or not Path(checkpoint).exists():
                self._log("Error: No training checkpoint found — run training first")
                return
            for k in stage_keys[:5]:
                self._set_stage(k, 'completed', '')
            self._set_stage('export', 'pending', 'Waiting...')
            workspace = str(self._project.workspace_dir or self._workspace / "nerfstudio")
            output_ply = str(self._project.output_ply_path or self._workspace / "output.ply")
            max_frames = self._max_frames if self._max_frames > 0 else 300
            self._nerfstudio_worker = NerfstudioWorker(
                video_path=self._video_path,
                workspace_dir=workspace,
                output_ply_path=output_ply,
                max_iterations=self._training_iterations,
                use_video_directly=True,
                num_frames_target=max_frames,
                skip_data_processing=True,
                skip_training=True,
                existing_checkpoint=checkpoint,
                existing_data_dir=self._project.get_stage('reconstruction').get('path'),
            )
        elif start_idx >= 4:  # training
            data_dir = self._project.get_stage('reconstruction').get('path')
            if not data_dir or not Path(data_dir).exists():
                self._log("Error: No reconstruction data found — run earlier stages first")
                return
            for k in stage_keys[:4]:
                self._set_stage(k, 'completed', '')
            for k in stage_keys[4:]:
                self._set_stage(k, 'pending', 'Waiting...')
            workspace = str(self._project.workspace_dir or self._workspace / "nerfstudio")
            output_ply = str(self._project.output_ply_path or self._workspace / "output.ply")
            max_frames = self._max_frames if self._max_frames > 0 else 300
            self._nerfstudio_worker = NerfstudioWorker(
                video_path=self._video_path,
                workspace_dir=workspace,
                output_ply_path=output_ply,
                max_iterations=self._training_iterations,
                use_video_directly=True,
                num_frames_target=max_frames,
                skip_data_processing=True,
                existing_data_dir=data_dir,
            )
        else:
            # Start from beginning (stages 0-3 are COLMAP — atomic unit)
            self._start_nerfstudio_pipeline()
            return

        self._connect_nerfstudio_worker()
        self._nerfstudio_worker.start()
        self._update_button_states()

    @pyqtSlot()
    def exportPly(self):
        """Export the project's PLY to a user-chosen location."""
        src = self._project.output_ply_path
        if not src or not src.exists():
            self._log("No PLY file in project — run pipeline first")
            return

        dst, _ = QFileDialog.getSaveFileName(
            None, "Export PLY",
            str(Path.home() / src.name),
            "PLY Files (*.ply)"
        )
        if not dst:
            return

        import shutil
        try:
            shutil.copy2(str(src), dst)
            self._log(f"Exported PLY to {dst}")
        except Exception as e:
            self._log(f"Export failed: {e}")

    @pyqtSlot()
    def cancel(self):
        self._log("Cancelling operations...")

        if self._nerfstudio_worker and self._nerfstudio_worker.isRunning():
            self._nerfstudio_worker.cancel()
            self._nerfstudio_worker.wait(2000)
            if self._nerfstudio_worker.isRunning():
                self._nerfstudio_worker.terminate()
                self._nerfstudio_worker.wait(1000)

        if self._video_worker and self._video_worker.isRunning():
            self._video_worker.cancel()
            self._video_worker.wait(1000)
            if self._video_worker.isRunning():
                self._video_worker.terminate()

        if self._reconstruction_worker and self._reconstruction_worker.isRunning():
            self._reconstruction_worker.cancel()
            self._reconstruction_worker.wait(1000)
            if self._reconstruction_worker.isRunning():
                self._reconstruction_worker.terminate()

        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.wait(1000)
            if self._export_worker.isRunning():
                self._export_worker.terminate()

        self._log("Operations cancelled")
        self._set_status("Cancelled")

        for key, _ in STAGE_DEFS:
            idx = self._stage_index(key)
            st = self._stages[idx]
            if st["status"] in ("pending", "running"):
                self._set_stage(key, "cancelled", "Cancelled")

        self._update_button_states()

    @pyqtSlot()
    def windowClosing(self):
        """Called by QML onClosing — auto-save and tell controller."""
        self._auto_save_project()
        self._save_settings()
        if self._controller:
            self._controller.close_window(self)

    @pyqtSlot()
    def clearLog(self):
        self._log_lines.clear()
        self.logContentChanged.emit()

    @pyqtSlot()
    def pauseVideo(self):
        # No-op from Python side — video is handled in QML MediaPlayer
        pass

    # ── Project management slots ──

    @pyqtSlot()
    def newProject(self):
        """Create a new project.  Uses save-file dialog so user can pick
        parent folder *and* type a project name.  If the current window
        already has a project, a new window is spawned instead."""
        start = str(self._controller.projects_root) if self._controller and self._controller.projects_root else str(Path.home())
        file_path, _ = QFileDialog.getSaveFileName(
            None, "Create New Project", start, "Splats Project Folder (*)"
        )
        if not file_path:
            return

        proj_dir = Path(file_path)
        # Sanitize: spaces in paths break nerfstudio/COLMAP shell commands
        safe_name = proj_dir.name.replace(" ", "_")
        if safe_name != proj_dir.name:
            proj_dir = proj_dir.parent / safe_name
        # getSaveFileName returns a file-like path; we treat it as a dir
        proj_dir.mkdir(parents=True, exist_ok=True)

        if self._project.is_open and self._controller:
            # Current window has a project → spawn new window
            self._controller.create_window(new_project_dir=str(proj_dir))
        else:
            # Current window is empty → use it
            self._init_new_project(str(proj_dir))

    @pyqtSlot()
    def openProject(self):
        """Open an existing project folder.  Spawns a new window if this
        window already has a project loaded."""
        start = str(self._controller.projects_root) if self._controller and self._controller.projects_root else str(Path.home())
        dir_path = QFileDialog.getExistingDirectory(
            None, "Open Project Folder", start
        )
        if not dir_path:
            return

        if self._project.is_open and self._controller:
            # Current window has a project → spawn new window
            self._controller.create_window(project_dir=dir_path)
        else:
            # Current window is empty → use it
            self._load_project_file(dir_path)
            self._save_settings()

    @pyqtSlot()
    def saveProject(self):
        if not self._project.is_open:
            self._project.new_project(video_path=self._video_path, settings=self._current_settings())
        if not self._project.project_dir:
            # No dir yet — prompt via New
            self.newProject()
        else:
            self._project.update_settings(self._current_settings())
            if self._video_path:
                self._project.update_input(self._video_path)
            self._project.save_project()
            self._save_settings()
            self._log(f"Project saved: {self._project.project_name}")
            self.windowTitleChanged.emit()

    # ══════════════════════════════════════════════════════════════════════════
    #  Internal helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _log(self, msg: str):
        self._log_lines.append(msg)
        self.logContentChanged.emit()
        print(f"[LOG] {msg}")

    def _set_status(self, text: str):
        self._status_text = text
        self.statusTextChanged.emit()

    def _stage_index(self, key: str) -> int:
        for i, s in enumerate(self._stages):
            if s["key"] == key:
                return i
        return -1

    def _set_stage(self, key: str, status: str, detail: str = "", progress: float = -1):
        idx = self._stage_index(key)
        if idx < 0:
            return
        stage = self._stages[idx]

        # ETA tracking
        if status == "running" and key not in self._stage_start_times:
            self._stage_start_times[key] = time.time()
        elif status in ("completed", "failed", "cancelled", "pending"):
            self._stage_start_times.pop(key, None)

        stage["status"] = status
        if detail:
            stage["detail"] = detail
        if progress >= 0:
            stage["progress"] = progress
        elif status == "completed":
            stage["progress"] = 1.0
        elif status == "pending":
            stage["progress"] = 0.0

        # Compute ETA for running stages
        if status == "running" and progress > 0.01:
            started = self._stage_start_times.get(key)
            if started:
                elapsed = time.time() - started
                eta_s = (elapsed / progress) * (1.0 - progress)
                stage["eta"] = self._format_eta(eta_s)
            else:
                stage["eta"] = ""
        else:
            stage["eta"] = ""

        self.stagesChanged.emit()

    @staticmethod
    def _format_eta(seconds: float) -> str:
        if seconds < 0 or seconds > 86400:
            return ""
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"~{h}h {m}m left"
        elif m > 0:
            return f"~{m}m {s}s left"
        else:
            return f"~{s}s left"

    def _update_button_states(self):
        self.isProcessingChanged.emit()
        self.canExportPlyChanged.emit()

    def _scan_frame_images(self, frames_dir: str = None):
        """Scan extracted frames directory and populate frameImages list."""
        images = []
        search_dir = frames_dir or self._stage_paths.get('frames')
        if search_dir:
            d = Path(search_dir)
            if d.is_dir():
                exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
                files = sorted(
                    [f for f in d.iterdir() if f.suffix.lower() in exts],
                    key=lambda f: f.name
                )
                images = [QUrl.fromLocalFile(str(f)).toString() for f in files]
        if images != self._frame_images:
            self._frame_images = images
            self.frameImagesChanged.emit()

    def _set_data_stage_paths(self, ws_data: Path):
        """Set all data-stage folder paths from the nerfstudio data directory."""
        self._stage_paths['frames'] = str(ws_data / "images")
        self._stage_paths['feature_extract'] = str(ws_data / "colmap")
        self._stage_paths['feature_match'] = str(ws_data / "colmap")
        self._stage_paths['reconstruction'] = str(ws_data)
        self._scan_frame_images()

    def _current_settings(self) -> dict:
        return {
            'training_iterations': self._training_iterations,
            'sample_rate': 5,
            'max_frames': self._max_frames,
        }

    # ── Settings persistence ──

    def _load_settings(self):
        """Load global default settings (not project state — that's separate)."""
        if not self._settings_file.exists():
            return
        try:
            with open(self._settings_file) as f:
                s = json.load(f)
            if 'training_iterations' in s:
                self._training_iterations = s['training_iterations']
            if 'max_frames' in s:
                self._max_frames = s['max_frames']
        except Exception as e:
            self._log(f"Could not load settings: {e}")

    def _save_settings(self):
        """Persist global default settings."""
        try:
            settings = {
                'training_iterations': self._training_iterations,
                'sample_rate': 5,
                'max_frames': self._max_frames,
            }
            with open(self._settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"[WARN] Could not save settings: {e}")

    # ── Project helpers ──

    def _init_new_project(self, proj_dir: str):
        """Set up this Backend for a brand-new project at *proj_dir*."""
        self._project.new_project(
            project_dir=proj_dir,
            video_path=self._video_path,
            settings=self._current_settings(),
        )
        self._project.save_project()
        self._save_settings()

        # Reset stage UI
        for key, _ in STAGE_DEFS:
            self._set_stage(key, "pending", "")
            self._stage_paths[key] = None

        self._log(f"New project: {proj_dir}")
        self.windowTitleChanged.emit()
        self.projectNameChanged.emit()
        self.projectDirChanged.emit()
        self._update_button_states()

    def _ensure_project_dir(self):
        """Auto-create a project dir from video name if not set."""
        if self._project.project_dir:
            return
        stem = Path(self._video_path).stem if self._video_path else "splats_project"
        proj_dir = self._workspace / stem
        proj_dir.mkdir(parents=True, exist_ok=True)
        if not self._project.is_open:
            self._project.new_project(
                project_dir=str(proj_dir),
                video_path=self._video_path,
                settings=self._current_settings(),
            )
        else:
            self._project.project_dir = proj_dir
        self._project.save_project()
        self._log(f"Auto-created project: {proj_dir}")
        self.windowTitleChanged.emit()
        self.projectNameChanged.emit()
        self.projectDirChanged.emit()

    def _load_project_file(self, path: str):
        try:
            self._project.load_project(path)
            self._log(f"Project loaded: {self._project.project_name}")
            self.windowTitleChanged.emit()
            self.projectNameChanged.emit()
            self.projectDirChanged.emit()

            # Restore video
            vid = self._project.video_path
            if vid and Path(vid).exists():
                self._video_path = vid
                self.videoNameChanged.emit()
                self.videoUrlChanged.emit()
                self.hasVideoChanged.emit()
                try:
                    processor = VideoProcessor()
                    info = processor.get_video_info(vid)
                    self._video_info = (
                        f"Resolution: {info['width']}x{info['height']} | "
                        f"FPS: {info['fps']:.2f} | "
                        f"Frames: {info['frame_count']} | "
                        f"Duration: {info['duration']:.2f}s"
                    )
                    self.videoInfoChanged.emit()
                except Exception:
                    pass

            # Restore settings
            s = self._project.settings
            if s.get('training_iterations'):
                self._training_iterations = s['training_iterations']
                self.trainingIterationsChanged.emit()
            if s.get('max_frames'):
                self._max_frames = s['max_frames']
                self.maxFramesChanged.emit()

            # Restore stage indicators
            for key, _ in STAGE_DEFS:
                stage = self._project.get_stage(key)
                status = stage.get('status', 'pending')
                if status == 'completed':
                    self._set_stage(key, 'completed', 'Complete')
                    path_val = stage.get('path') or stage.get('ply_path') or stage.get('checkpoint_dir')
                    if path_val:
                        self._stage_paths[key] = path_val

            # Scan extracted frames
            self._scan_frame_images()

            # Load PLY if available
            ply = self._project.get_export_ply()
            if ply and Path(ply).exists():
                self._load_ply_in_viewer(ply)
                self._log(f"Loaded existing PLY: {Path(ply).name}")

            self._update_button_states()

        except Exception as e:
            self._log(f"Failed to load project: {e}")

    def _auto_save_project(self):
        if self._project.is_open:
            self._project.update_settings(self._current_settings())
            if self._video_path:
                self._project.update_input(self._video_path)
            self._project.save_project()
            self._save_settings()  # persist last_project_dir

    def _compute_camera_hint(self) -> dict:
        """Compute optimal camera position from COLMAP transforms.json."""
        try:
            import numpy as np
            # Find transforms.json from reconstruction stage
            recon_path = self._stage_paths.get('reconstruction')
            if not recon_path:
                return {}
            transforms_file = Path(recon_path) / "transforms.json"
            if not transforms_file.exists():
                return {}

            with open(transforms_file) as f:
                data = json.load(f)

            frames = data.get('frames', [])
            if not frames:
                return {}

            # Extract camera positions from 4x4 transform matrices
            cam_positions = []
            for frame in frames:
                m = frame.get('transform_matrix')
                if m and len(m) >= 3:
                    cam_positions.append([m[0][3], m[1][3], m[2][3]])

            if not cam_positions:
                return {}

            positions = np.array(cam_positions)
            centroid = positions.mean(axis=0)

            # Scene center is at origin (nerfstudio normalizes)
            scene_center = [0.0, 0.0, 0.0]

            # Pick a representative camera: closest to median distance from centroid
            dists = np.linalg.norm(positions - centroid, axis=1)
            median_idx = np.argsort(dists)[len(dists) // 2]
            representative_cam = positions[median_idx]

            # Camera orbit radius (median distance from scene center)
            orbit_radius = float(np.median(np.linalg.norm(positions, axis=1)))

            return {
                "centroid": scene_center,
                "radius": orbit_radius,
                "camera_pos": representative_cam.tolist(),
            }
        except Exception as e:
            self._log(f"Camera hint computation failed: {e}")
            return {}

    def _load_ply_in_viewer(self, ply_path: str, camera_hint: dict = None):
        try:
            ply = Path(ply_path).resolve()
            if not ply.exists():
                self._log(f"PLY file not found: {ply}")
                return

            # Auto-compute camera from COLMAP data if not provided
            if not camera_hint:
                camera_hint = self._compute_camera_hint()

            url = QUrl.fromLocalFile(str(self._viewer_html))
            query = f"ply=file://{ply}"
            if camera_hint:
                c = camera_hint.get("centroid", [0, 0, 0])
                r = camera_hint.get("radius", 5)
                query += f"&cx={c[0]:.3f}&cy={c[1]:.3f}&cz={c[2]:.3f}&r={r:.3f}"
                cam = camera_hint.get("camera_pos")
                if cam:
                    query += f"&px={cam[0]:.3f}&py={cam[1]:.3f}&pz={cam[2]:.3f}"
            url.setQuery(query)
            self._viewer_url = url.toString()
            self._camera_hint = camera_hint
            self.viewerUrlChanged.emit()
            self._log(f"Loaded PLY in viewer: {ply.name}")
        except Exception as e:
            self._log(f"Error loading PLY in viewer: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    #  Pipeline execution (Nerfstudio)
    # ══════════════════════════════════════════════════════════════════════════

    def _start_nerfstudio_pipeline(self):
        self._log("Starting Nerfstudio pipeline...")
        self._log("This will take 10-30 minutes depending on GPU and settings")

        if not self._project.is_open:
            self._project.new_project(
                project_dir=str(self._project.project_dir) if self._project.project_dir else None,
                video_path=self._video_path,
                settings=self._current_settings(),
            )
        else:
            self._project.update_settings(self._current_settings())
            if self._video_path:
                self._project.update_input(self._video_path)
            for s in STAGE_ORDER:
                self._project.update_stage(s, 'pending')

        for key, _ in STAGE_DEFS:
            self._set_stage(key, 'pending', 'Waiting...')

        max_frames = self._max_frames if self._max_frames > 0 else 300
        workspace = str(self._project.workspace_dir or self._workspace / "nerfstudio")
        output_ply = str(self._project.output_ply_path or self._workspace / "output.ply")

        self._nerfstudio_worker = NerfstudioWorker(
            video_path=self._video_path,
            workspace_dir=workspace,
            output_ply_path=output_ply,
            max_iterations=self._training_iterations,
            use_video_directly=True,
            num_frames_target=max_frames
        )
        self._connect_nerfstudio_worker()
        self._nerfstudio_worker.start()
        self._update_button_states()

    def _connect_nerfstudio_worker(self):
        w = self._nerfstudio_worker
        w.progress.connect(self._on_nerfstudio_progress)
        w.finished.connect(self._on_nerfstudio_finished)
        w.error.connect(lambda msg: (self._log(f"Error: {msg}"), self._set_status("Error"), self._update_button_states()))
        w.log.connect(self._log)
        w.stage_data_completed.connect(self._on_stage_data_completed)
        w.stage_training_completed.connect(self._on_stage_training_completed)

    def _on_nerfstudio_progress(self, data: dict):
        stage = data['stage']
        progress = data.get('progress', 0.0)
        substage = data.get('substage', '')
        progress_pct = int(progress * 100)

        # Status text
        if "Data" in stage:
            if progress < 0.15:
                self._set_status("Extracting frames...")
            elif progress < 0.30:
                self._set_status("Extracting features...")
            elif progress < 0.50:
                self._set_status("Matching features...")
            elif progress < 1.0:
                self._set_status("Building reconstruction...")
            else:
                self._set_status("Data processing complete")
        elif "Training" in stage:
            self._set_status("Training Gaussian Splatting model...")
        elif "Export" in stage:
            self._set_status("Exporting PLY...")

        # Map to stages (same logic as main_window.py)
        if "Data" in stage:
            ws_base = self._project.workspace_dir or (self._workspace / "nerfstudio")
            ws_data = ws_base / "nerfstudio_data"

            if any(x in substage.lower() for x in ["extracting frames", "converting video"]) or (progress < 0.15 and "colmap" not in substage.lower()):
                target = self._max_frames or 300
                self._set_stage('frames', 'running', f"Extracting (target: {target})", progress=min(progress / 0.15, 0.99))

            elif "frame extraction complete" in substage.lower() or ("done converting" in substage.lower() and "feature" not in substage.lower()):
                self._set_stage('frames', 'completed', 'Complete')
                self._stage_paths['frames'] = str(ws_data / "images")

            elif "extracting features" in substage.lower():
                self._set_stage('frames', 'completed', 'Complete')
                self._stage_paths['frames'] = str(ws_data / "images")
                count_match = re.search(r'\[(\d+)/(\d+)\]', substage)
                if count_match:
                    detail = f"{count_match.group(1)}/{count_match.group(2)}"
                    pct = int(count_match.group(1)) / int(count_match.group(2))
                else:
                    detail = "Starting"
                    pct = 0
                self._set_stage('feature_extract', 'running', detail, progress=pct)

            elif "matching features" in substage.lower():
                self._set_stage('frames', 'completed', 'Complete')
                self._set_stage('feature_extract', 'completed', 'Complete')
                self._stage_paths['frames'] = str(ws_data / "images")
                self._stage_paths['feature_extract'] = str(ws_data / "colmap")
                count_match = re.search(r'\[(\d+)/(\d+)\]', substage)
                if count_match:
                    detail = f"{count_match.group(1)}/{count_match.group(2)}"
                    pct = int(count_match.group(1)) / int(count_match.group(2))
                else:
                    detail = "Starting"
                    pct = 0
                self._set_stage('feature_match', 'running', detail, progress=pct)

            elif any(x in substage.lower() for x in ["reconstruction", "bundle adjustment", "refining", "registering"]):
                self._set_stage('frames', 'completed', 'Complete')
                self._set_stage('feature_extract', 'completed', 'Complete')
                self._set_stage('feature_match', 'completed', 'Complete')
                self._stage_paths['frames'] = str(ws_data / "images")
                self._stage_paths['feature_extract'] = str(ws_data / "colmap")
                self._stage_paths['feature_match'] = str(ws_data / "colmap")
                if "bundle" in substage.lower():
                    detail = "Optimizing"
                elif "refining" in substage.lower():
                    detail = "Refining"
                else:
                    count_match = re.search(r'\[(\d+)\s+images?\]', substage)
                    detail = f"{count_match.group(1)} registered" if count_match else "Running"
                self._set_stage('reconstruction', 'running', detail, progress=0.5)

            elif "feature extraction complete" in substage.lower():
                self._set_stage('feature_extract', 'completed', 'Complete')

            elif "feature matching complete" in substage.lower():
                self._set_stage('feature_match', 'completed', 'Complete')

            elif "colmap" in substage.lower() and "complete" in substage.lower():
                for k in ['frames', 'feature_extract', 'feature_match', 'reconstruction']:
                    self._set_stage(k, 'completed', 'Complete')
                self._set_data_stage_paths(ws_data)

            elif progress >= 1.0 or "all done" in substage.lower() or "congrats" in substage.lower():
                for k in ['frames', 'feature_extract', 'feature_match', 'reconstruction']:
                    self._set_stage(k, 'completed', 'Complete')
                self._set_data_stage_paths(ws_data)

        elif "Training" in stage:
            step_match = re.search(r'Step (\d+)/(\d+)', substage)
            if step_match:
                detail = f"{step_match.group(1)}/{step_match.group(2)}"
            else:
                detail = substage[:50] if substage else "Running"

            status = 'running' if progress < 1.0 else 'completed'
            self._set_stage('training', status, detail, progress=progress)

            if progress > 0:
                for k in ['frames', 'feature_extract', 'feature_match', 'reconstruction']:
                    self._set_stage(k, 'completed', 'Complete')

        elif "Export" in stage:
            detail = substage[:50] if substage else f"{progress_pct}%"
            status = 'running' if progress < 1.0 else 'completed'
            self._set_stage('export', status, detail, progress=progress)

            if progress > 0:
                self._set_stage('training', 'completed', 'Complete')

    def _on_nerfstudio_finished(self, result: dict):
        self._nerfstudio_worker = None

        if result['success']:
            output_path = result['output_path']
            self._log("=" * 50)
            self._log("Pipeline complete!")
            self._log(f"Output PLY: {output_path}")
            self._set_status("Pipeline complete")

            for key, _ in STAGE_DEFS:
                self._set_stage(key, 'completed', 'Complete')

            # Save project
            if not self._project.is_open:
                self._project.new_project(video_path=self._video_path, settings=self._current_settings())
            self._project.update_stage('export', 'completed', ply_path=output_path)
            self._stage_paths['export'] = str(Path(output_path).parent)
            self._auto_save_project()
            self.windowTitleChanged.emit()
            self.projectNameChanged.emit()
            self.projectDirChanged.emit()

            self._load_ply_in_viewer(output_path)
        else:
            self._log(f"Pipeline failed: {result['error']}")
            self._set_status("Pipeline failed")

            # Mark first non-done stage as failed
            for key, _ in STAGE_DEFS:
                idx = self._stage_index(key)
                if self._stages[idx]["status"] in ("pending", "running"):
                    self._set_stage(key, 'failed', 'Failed')
                    break

        self._update_button_states()

    def _on_stage_data_completed(self, data_dir: str):
        if not self._project.is_open:
            self._project.new_project(video_path=self._video_path, settings=self._current_settings())
        images_path = str(Path(data_dir) / "images")
        colmap_path = str(Path(data_dir) / "colmap")
        self._project.update_stage('frames', 'completed', path=images_path)
        self._project.update_stage('feature_extract', 'completed')
        self._project.update_stage('feature_match', 'completed')
        self._project.update_stage('reconstruction', 'completed', path=colmap_path)

        # Track paths for "Open Folder" buttons
        self._stage_paths['frames'] = images_path
        self._stage_paths['feature_extract'] = colmap_path
        self._stage_paths['feature_match'] = colmap_path
        self._stage_paths['reconstruction'] = data_dir
        self._auto_save_project()

    def _on_stage_training_completed(self, checkpoint_dir: str, latest_checkpoint: str):
        if not self._project.is_open:
            self._project.new_project(video_path=self._video_path, settings=self._current_settings())
        self._project.update_stage(
            'training', 'completed',
            checkpoint_dir=checkpoint_dir,
            latest_checkpoint=latest_checkpoint,
        )
        # Track path for "Open Folder" button
        self._stage_paths['training'] = checkpoint_dir
        self._auto_save_project()
        self._update_button_states()

    # ── Mock/COLMAP pipeline (non-nerfstudio) ──

    def _start_video_processing(self):
        self._log("Stage 1/3: Extracting frames from video...")
        base_dir = self._project.project_dir or self._workspace
        frames_dir = base_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        for f in frames_dir.glob("*.png"):
            f.unlink()

        max_frames = self._max_frames if self._max_frames > 0 else None

        self._video_worker = VideoProcessingWorker(
            self._video_path, str(frames_dir), sample_rate=5, max_frames=max_frames
        )
        self._video_worker.progress.connect(lambda d: self._set_status("Processing video frames..."))
        self._video_worker.finished.connect(self._on_video_finished)
        self._video_worker.error.connect(lambda msg: (self._log(f"Error: {msg}"), self._set_status("Error")))
        self._video_worker.start()
        self._update_button_states()

    def _on_video_finished(self, result: dict):
        self._video_worker = None
        if result['success']:
            self._log(f"Extracted {len(result['frame_paths'])} frames")
            self._start_reconstruction(result['frame_paths'])
        else:
            self._log(f"Error: {result['error']}")
            self._set_status("Failed")
            self._update_button_states()

    def _start_reconstruction(self, frame_paths: list):
        self._log("Stage 2/3: Performing 3D reconstruction...")
        base_dir = self._project.project_dir or self._workspace
        method = "colmap"
        self._reconstruction_worker = ReconstructionWorker(
            frame_paths, str(base_dir / "reconstruction"), method=method
        )
        self._reconstruction_worker.progress.connect(lambda d: self._set_status(f"Running {d['stage']}..."))
        self._reconstruction_worker.finished.connect(self._on_reconstruction_finished)
        self._reconstruction_worker.error.connect(lambda msg: (self._log(f"Error: {msg}"), self._set_status("Error")))
        self._reconstruction_worker.start()

    def _on_reconstruction_finished(self, result: dict):
        self._reconstruction_worker = None
        if result['success']:
            self._log(f"Generated {result['data'].get('num_points', 0)} Gaussian splats")
            self._start_ply_export(result['data'])
        else:
            self._log(f"Error: {result['error']}")
            self._set_status("Failed")
            self._update_button_states()

    def _start_ply_export(self, splat_data: dict):
        self._log("Stage 3/3: Exporting to PLY format...")
        output_ply = str(self._project.output_ply_path) if self._project.output_ply_path else str(self._workspace / "output.ply")
        self._export_worker = PLYExportWorker(splat_data, output_ply)
        self._export_worker.progress.connect(lambda d: self._set_status("Exporting PLY..."))
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(lambda msg: (self._log(f"Error: {msg}"), self._set_status("Error")))
        self._export_worker.start()

    def _on_export_finished(self, result: dict):
        self._export_worker = None
        if result['success']:
            self._log(f"Conversion complete! Output: {result['output_path']}")
            self._set_status("Complete")
            self._load_ply_in_viewer(result['output_path'])
        else:
            self._log(f"Error: {result['error']}")
            self._set_status("Failed")
        self._update_button_states()
