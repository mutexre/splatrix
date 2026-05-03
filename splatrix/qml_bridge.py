"""Python ↔ QML bridge: exposes backend state as QObject properties/slots for QML UI."""

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QObject, pyqtProperty, pyqtSignal, pyqtSlot, QUrl, QVariant, QTimer
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog, QApplication
from transitions import Machine, MachineError

from .video_processor import VideoProcessor
from .project_manager import ProjectManager, ProjectLockedError
from .protocol import Operation, StageState
from .stages import Stage, PipelineState

# ── Stage labels for QML UI ──────────────────────────────────────────────────

_STAGE_LABELS: dict[Stage, str] = {
    Stage.FRAMES:          "Frame Extraction",
    Stage.FEATURE_EXTRACT: "Feature Extraction",
    Stage.FEATURE_MATCH:   "Feature Matching",
    Stage.RECONSTRUCTION:  "Sparse Reconstruction",
    Stage.TRAINING:        "Training",
    Stage.EXPORT:          "Export PLY",
}

_DATA_STAGES = (Stage.FRAMES, Stage.FEATURE_EXTRACT, Stage.FEATURE_MATCH, Stage.RECONSTRUCTION)

_RESTARTABLE_STAGES = frozenset({Stage.FRAMES, Stage.TRAINING, Stage.EXPORT})

_STAGE_TO_OPERATION: dict[Stage, Operation] = {
    Stage.FRAMES: Operation.DATA,
    Stage.FEATURE_EXTRACT: Operation.DATA,
    Stage.FEATURE_MATCH: Operation.DATA,
    Stage.RECONSTRUCTION: Operation.DATA,
    Stage.TRAINING: Operation.TRAINING,
    Stage.EXPORT: Operation.EXPORT,
}


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
    pipelineStateChanged = pyqtSignal()
    isProcessingChanged = pyqtSignal()
    canExportPlyChanged = pyqtSignal()
    statusTextChanged = pyqtSignal()
    stagesChanged = pyqtSignal()
    logContentChanged = pyqtSignal()
    windowTitleChanged = pyqtSignal()
    projectNameChanged = pyqtSignal()
    viewerUrlChanged = pyqtSignal()
    frameImagesChanged = pyqtSignal()
    serverConnectedChanged = pyqtSignal()
    operationStatesChanged = pyqtSignal()

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

        # Pipeline state machine (idle → running → cancelling → idle)
        Machine(
            model=self,
            states=PipelineState,
            initial=PipelineState.IDLE,
            transitions=[
                {'trigger': 'pipeline_start',   'source': PipelineState.IDLE,       'dest': PipelineState.RUNNING},
                {'trigger': 'pipeline_cancel',  'source': PipelineState.RUNNING,    'dest': PipelineState.CANCELLING},
                {'trigger': 'pipeline_finish',  'source': PipelineState.RUNNING,    'dest': PipelineState.IDLE},
                {'trigger': 'pipeline_finish',  'source': PipelineState.CANCELLING, 'dest': PipelineState.IDLE},
                {'trigger': 'pipeline_timeout', 'source': PipelineState.CANCELLING, 'dest': PipelineState.IDLE},
            ],
            after_state_change='_on_pipeline_state_change',
        )
        self._cancel_timer: Optional[QTimer] = None

        # Stage state — with ETA tracking
        self._stage_start_times: dict[Stage, float] = {}
        self._stages: list[dict] = [
            {
                "key": s.value, "label": _STAGE_LABELS[s],
                "status": "pending", "progress": 0.0, "detail": "",
                "restartable": s in _RESTARTABLE_STAGES,
                "validity": StageState.NO_DATA.value,
            }
            for s in Stage
        ]
        self._stage_paths: dict[Stage, Optional[str]] = {s: None for s in Stage}

        # Workspace
        self._workspace = Path.home() / ".splatrix"
        self._workspace.mkdir(exist_ok=True)
        self._settings_file = self._workspace / "settings.json"

        # Last-used directories for file/folder dialogs (keyed by purpose)
        self._last_dirs: dict[str, str] = {}

        # Server bridge
        self._server_bridge = None
        self._server_connected = False
        self._active_request_id: Optional[str] = None
        self._active_stage: Optional[Stage] = None
        self._pending_input_dir: Optional[Path] = None
        self._pending_output_dir: Optional[Path] = None
        self._stage_queue: list[Stage] = []

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

    @pyqtProperty(str, notify=pipelineStateChanged)
    def pipelineState(self):
        return self.state.value

    @pyqtProperty(bool, notify=isProcessingChanged)
    def isProcessing(self):
        return self.state is not PipelineState.IDLE

    @pyqtProperty(bool, notify=canExportPlyChanged)
    def canExportPly(self):
        ply = self._project.output_ply_path
        return (
            self.state is PipelineState.IDLE and
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
            return f"Splatrix — {self._project.project_name}"
        return "Splatrix"

    @pyqtProperty(str, notify=projectNameChanged)
    def projectName(self):
        return self._project.project_name if self._project.is_open else ""

    @pyqtProperty(bool, constant=True)
    def webEngineAvailable(self):
        try:
            from PyQt6 import QtWebEngineQuick  # noqa: F401
            return True
        except ImportError:
            return False

    @pyqtProperty(QUrl, notify=viewerUrlChanged)
    def viewerUrl(self):
        if self._viewer_url:
            return QUrl(self._viewer_url)
        return QUrl.fromLocalFile(str(self._viewer_html))

    @pyqtProperty("QVariantList", notify=frameImagesChanged)
    def frameImages(self):
        return self._frame_images

    @pyqtProperty(bool, notify=serverConnectedChanged)
    def serverConnected(self):
        return self._server_connected

    @pyqtProperty("QVariantList", notify=operationStatesChanged)
    def operationStates(self):
        """Per-operation validity states for the QML UI."""
        if not self._project.is_open:
            return [{"operation": op.value, "state": StageState.NO_DATA.value} for op in Operation]
        return [
            {"operation": op.value, "state": self._project.operation_validity(op).value}
            for op in Operation
        ]

    # ══════════════════════════════════════════════════════════════════════════
    #  QML Slots (actions)
    # ══════════════════════════════════════════════════════════════════════════

    @pyqtSlot()
    def selectVideo(self):
        start_dir = self._get_last_dir(
            "video",
            str(Path(self._video_path).parent) if self._video_path else "",
        )

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
            self._set_last_dir("video", file_path)
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
    def openStageFolder(self, stage_key: str):
        """Open file browser for a stage's output directory."""
        try:
            stage = Stage(stage_key)
        except ValueError:
            self._log(f"Unknown stage: {stage_key}")
            return
        path = self._stage_paths.get(stage)
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self._log(f"Stage folder not available for: {stage_key}")

    @pyqtSlot()
    def startConversion(self):
        if not self._video_path:
            self._log("Error: No video selected")
            return
        try:
            self.pipeline_start()
        except MachineError:
            self._log("Pipeline is already running")
            return

        if not self._project.project_dir:
            self._ensure_project_dir()
            if not self._project.project_dir:
                self._log("Error: No project directory set")
                self.pipeline_finish()
                return

        self._log("=" * 50)
        self._log(f"Project: {self._project.project_dir}")
        self._set_status("Processing...")

        for s in Stage:
            self._set_stage(s, 'pending', 'Waiting...')

        self._stage_queue = list(Stage)
        self._run_next_stage()

    @pyqtSlot(str)
    def startFromStage(self, stage_key: str):
        """Start pipeline from a specific stage, reusing earlier results."""
        try:
            stage = Stage(stage_key)
        except ValueError:
            self._log(f"Unknown stage: {stage_key}")
            return

        if not self._video_path:
            self._log("Error: No video selected")
            return
        try:
            self.pipeline_start()
        except MachineError:
            self._log("Pipeline is already running")
            return

        if not self._project.project_dir:
            self._ensure_project_dir()
            if not self._project.project_dir:
                self._log("Error: No project directory set")
                self.pipeline_finish()
                return

        self._log("=" * 50)
        self._log(f"Starting pipeline from stage: {stage_key}")
        self._log(f"Project: {self._project.project_dir}")
        self._set_status("Processing...")

        all_stages = list(Stage)
        stage_idx = all_stages.index(stage)
        for s in all_stages[:stage_idx]:
            self._set_stage(s, 'completed', '')
        for s in all_stages[stage_idx:]:
            self._set_stage(s, 'pending', 'Waiting...')

        self._stage_queue = all_stages[stage_idx:]
        self._run_next_stage()

    @pyqtSlot()
    def exportPly(self):
        """Export the project's PLY to a user-chosen location."""
        src = self._project.output_ply_path
        if not src or not src.exists():
            self._log("No PLY file in project — run pipeline first")
            return

        start = str(Path(self._get_last_dir("export_ply")) / src.name)
        dst, _ = QFileDialog.getSaveFileName(
            None, "Export PLY", start, "PLY Files (*.ply)"
        )
        if not dst:
            return

        self._set_last_dir("export_ply", dst)
        try:
            shutil.copy2(str(src), dst)
            self._log(f"Exported PLY to {dst}")
        except Exception as e:
            self._log(f"Export failed: {e}")

    @pyqtSlot()
    def cancel(self):
        try:
            self.pipeline_cancel()
        except MachineError:
            return

        self._log("Cancelling operations...")
        self._stage_queue.clear()

        if self._active_request_id and self._server_bridge:
            self._server_bridge.request_cancel(self._active_request_id)

        self._set_status("Cancelling...")

        for stage in Stage:
            idx = self._stage_index(stage)
            st = self._stages[idx]
            if st["status"] in ("pending", "running"):
                self._set_stage(stage, "cancelled", "Cancelled")

    @pyqtSlot()
    def windowClosing(self):
        """Called by QML onClosing — auto-save, disconnect, and tell controller."""
        self._auto_save_project()
        self._save_settings()
        self.disconnect_from_server()
        self._project.close()
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
        default = str(self._controller.projects_root) if self._controller and self._controller.projects_root else ""
        start = self._get_last_dir("new_project", default)
        file_path, _ = QFileDialog.getSaveFileName(
            None, "Create New Project", start, "Splatrix Project Folder (*)"
        )
        if not file_path:
            return

        self._set_last_dir("new_project", file_path)

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
        default = str(self._controller.projects_root) if self._controller and self._controller.projects_root else ""
        start = self._get_last_dir("open_project", default)
        dir_path = QFileDialog.getExistingDirectory(
            None, "Open Project Folder", start
        )
        if not dir_path:
            return

        self._set_last_dir("open_project", dir_path)

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

    def _stage_index(self, stage: Stage) -> int:
        key = stage.value
        for i, s in enumerate(self._stages):
            if s["key"] == key:
                return i
        return -1

    def _set_stage(self, stage: Stage, status: str, detail: str = "", progress: float = -1):
        idx = self._stage_index(stage)
        if idx < 0:
            return
        entry = dict(self._stages[idx])

        if status == "running" and stage not in self._stage_start_times:
            self._stage_start_times[stage] = time.time()
        elif status in ("completed", "failed", "cancelled", "pending"):
            self._stage_start_times.pop(stage, None)

        entry["status"] = status
        if detail:
            entry["detail"] = detail
        if progress >= 0:
            entry["progress"] = progress
        elif status == "completed":
            entry["progress"] = 1.0
        elif status == "pending":
            entry["progress"] = 0.0

        if status == "running" and progress > 0.01:
            started = self._stage_start_times.get(stage)
            if started:
                elapsed = time.time() - started
                eta_s = (elapsed / progress) * (1.0 - progress)
                entry["eta"] = self._format_eta(eta_s)
            else:
                entry["eta"] = ""
        else:
            entry["eta"] = ""

        self._stages[idx] = entry
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
        self.pipelineStateChanged.emit()
        self.isProcessingChanged.emit()
        self.canExportPlyChanged.emit()

    # ── State machine callbacks (called by transitions lib) ──

    def _on_pipeline_state_change(self):
        """Dispatched by the transitions Machine after every state change."""
        self._update_button_states()

        if self.state is PipelineState.CANCELLING:
            self._cancel_timer = QTimer()
            self._cancel_timer.setSingleShot(True)
            self._cancel_timer.timeout.connect(self._on_cancel_timeout)
            self._cancel_timer.start(10_000)

        elif self.state is PipelineState.IDLE:
            if self._cancel_timer:
                self._cancel_timer.stop()
                self._cancel_timer = None

    def _on_cancel_timeout(self):
        """Safety net: force back to IDLE if server never responds."""
        self._log("Cancel timeout — forcing idle state")
        self._cleanup_pending_workspace()
        try:
            self.pipeline_timeout()
        except MachineError:
            pass

    def _scan_frame_images(self, frames_dir: str = None):
        """Scan extracted frames directory and populate frameImages list."""
        images = []
        search_dir = frames_dir or self._stage_paths.get(Stage.FRAMES)
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
        self._stage_paths[Stage.FRAMES] = str(ws_data / "images")
        self._stage_paths[Stage.FEATURE_EXTRACT] = str(ws_data / "colmap")
        self._stage_paths[Stage.FEATURE_MATCH] = str(ws_data / "colmap")
        self._stage_paths[Stage.RECONSTRUCTION] = str(ws_data)
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
            if 'last_dirs' in s and isinstance(s['last_dirs'], dict):
                self._last_dirs = s['last_dirs']
        except Exception as e:
            self._log(f"Could not load settings: {e}")

    def _save_settings(self):
        """Persist global default settings."""
        try:
            settings = {
                'training_iterations': self._training_iterations,
                'sample_rate': 5,
                'max_frames': self._max_frames,
                'last_dirs': self._last_dirs,
            }
            with open(self._settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"[WARN] Could not save settings: {e}")

    def _get_last_dir(self, key: str, fallback: str = "") -> str:
        """Get last-used directory for a dialog, with fallback."""
        d = self._last_dirs.get(key, "")
        if d and Path(d).is_dir():
            return d
        return fallback or str(Path.home())

    def _set_last_dir(self, key: str, path: str):
        """Remember the directory of a chosen file/folder for next time."""
        p = Path(path)
        self._last_dirs[key] = str(p.parent if p.is_file() else p)
        self._save_settings()

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
        for s in Stage:
            self._set_stage(s, "pending", "")
            self._stage_paths[s] = None

        self._log(f"New project: {proj_dir}")
        self.windowTitleChanged.emit()
        self.projectNameChanged.emit()
        self.projectDirChanged.emit()
        self._update_button_states()

    def _ensure_project_dir(self):
        """Auto-create a project dir from video name if not set."""
        if self._project.project_dir:
            return
        stem = Path(self._video_path).stem if self._video_path else "splatrix_project"
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
            self._update_validity_ui()
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
            for s in Stage:
                stage_data = self._project.get_stage(s)
                status = stage_data.get('status', 'pending')
                if status == 'completed':
                    self._set_stage(s, 'completed', 'Complete')
                    path_val = stage_data.get('path') or stage_data.get('ply_path') or stage_data.get('checkpoint_dir')
                    if path_val:
                        self._stage_paths[s] = path_val

            # Scan extracted frames — try stored path first, then discover from disk
            if not self._stage_paths.get(Stage.FRAMES):
                ws_base = self._project.workspace_dir or (self._workspace / "nerfstudio")
                candidate = Path(str(ws_base)) / "nerfstudio_data" / "images"
                if candidate.is_dir() and any(candidate.iterdir()):
                    self._stage_paths[Stage.FRAMES] = str(candidate)
                    self._log(f"Discovered frames at {candidate}")
            self._scan_frame_images()

            # Load PLY if available
            ply = self._project.get_export_ply()
            if ply and Path(ply).exists():
                self._load_ply_in_viewer(ply)
                self._log(f"Loaded existing PLY: {Path(ply).name}")

            self._update_button_states()

        except ProjectLockedError:
            self._log(f"Project is open in another instance: {path}")
            self._set_status("Project locked")
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
            recon_path = self._stage_paths.get(Stage.RECONSTRUCTION)
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
    #  Server bridge (client-server mode)
    # ══════════════════════════════════════════════════════════════════════════

    def connect_to_server(self):
        """Start the server bridge thread and connect to the processing server."""
        if self._server_bridge is not None:
            return

        from .server_bridge import ServerBridge
        self._server_bridge = ServerBridge(parent=self)
        self._server_bridge.connected.connect(self._on_server_connected)
        self._server_bridge.disconnected.connect(self._on_server_disconnected)
        self._server_bridge.connection_error.connect(self._on_server_error)
        self._server_bridge.accepted.connect(self._on_server_accepted)
        self._server_bridge.progress.connect(self._on_server_progress)
        self._server_bridge.completed.connect(self._on_server_completed)
        self._server_bridge.failed.connect(self._on_server_failed)
        self._server_bridge.cancelled.connect(self._on_server_cancelled)
        self._server_bridge.acknowledged.connect(self._on_server_acknowledged)
        self._server_bridge.status_received.connect(self._on_server_status)
        self._server_bridge.start()

    def disconnect_from_server(self):
        if self._server_bridge:
            self._server_bridge.stop()
            self._server_bridge = None
            self._server_connected = False
            self.serverConnectedChanged.emit()

    def _on_server_connected(self):
        self._server_connected = True
        self.serverConnectedChanged.emit()
        self._log("Connected to processing server")
        if self._project.is_open and self._project.project_uuid:
            self._server_bridge.request_status(self._project.project_uuid)
        if self._stage_queue and self.state is PipelineState.RUNNING:
            self._run_next_stage()

    def _on_server_disconnected(self):
        self._server_connected = False
        self.serverConnectedChanged.emit()
        self._log("Disconnected from processing server")

    def _on_server_error(self, error: str):
        self._log(f"Server connection error: {error}")
        self._server_connected = False
        self.serverConnectedChanged.emit()
        if self._stage_queue:
            self._stage_queue.clear()
            self._set_status("Server unavailable")
            try:
                self.pipeline_finish()
            except MachineError:
                pass

    def _on_server_accepted(self, request_id: str):
        self._active_request_id = request_id
        self._log(f"Server accepted request: {request_id[:12]}...")

    def _on_server_progress(self, request_id: str, stage_key: str, progress_val: float):
        if request_id != self._active_request_id:
            return
        if self.state is not PipelineState.RUNNING:
            return
        try:
            stage = Stage(stage_key)
        except ValueError:
            return
        self._set_stage(stage, 'running', progress=progress_val)
        self._set_status(_STAGE_LABELS.get(stage, "Processing..."))

    def _on_server_completed(self, request_id: str, output_dir: str):
        if request_id != self._active_request_id:
            return

        stage = self._active_stage
        if not stage:
            return

        from .atomic_swap import atomic_replace
        project_dir = self._project.project_dir

        _STAGE_TARGETS = {
            Stage.FRAMES:          "nerfstudio/frames",
            Stage.FEATURE_EXTRACT: "nerfstudio/feature_extract",
            Stage.FEATURE_MATCH:   "nerfstudio/feature_match",
            Stage.RECONSTRUCTION:  "nerfstudio/nerfstudio_data",
            Stage.TRAINING:        "nerfstudio/outputs",
            Stage.EXPORT:          "output.ply",
        }

        if project_dir:
            target = project_dir / _STAGE_TARGETS.get(stage, stage.value)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_replace(Path(output_dir), target)
            except Exception as exc:
                self._log(f"Swap failed, falling back to copy: {exc}")
                if target.exists():
                    shutil.rmtree(str(target), ignore_errors=True)
                shutil.move(str(output_dir), str(target))

        op = _STAGE_TO_OPERATION.get(stage)
        op_stages = [s for s, o in _STAGE_TO_OPERATION.items() if o == op] if op else []
        is_last_in_op = (not op_stages) or (stage == op_stages[-1])
        if is_last_in_op and op:
            self._project.bump_generation(op)
            self._project.save_project()

        self._server_bridge.request_acknowledge(request_id)

        self._set_stage(stage, 'completed', 'Complete')
        self._stage_paths[stage] = str(target) if project_dir else ""

        if stage == Stage.RECONSTRUCTION and project_dir:
            ws_data = project_dir / "nerfstudio" / "nerfstudio_data"
            if ws_data.exists():
                self._set_data_stage_paths(ws_data)

        if stage == Stage.EXPORT and project_dir:
            ply = project_dir / "output.ply"
            if ply.exists():
                self._load_ply_in_viewer(str(ply))

        self._update_validity_ui()
        self._cleanup_pending_workspace()

        if self._stage_queue:
            self._log(f"Stage {stage.value} complete, continuing pipeline...")
            self._run_next_stage()
        else:
            self._set_status("Pipeline complete")
            self._log("Pipeline complete!")
            self._auto_save_project()
            try:
                self.pipeline_finish()
            except MachineError:
                pass

    def _on_server_failed(self, request_id: str, error: str):
        if request_id != self._active_request_id:
            return
        self._log(f"Server stage failed: {error}")
        self._set_status("Pipeline failed")
        self._stage_queue.clear()
        self._cleanup_pending_workspace()
        for s in Stage:
            idx = self._stage_index(s)
            if self._stages[idx]["status"] in ("pending", "running"):
                self._set_stage(s, 'failed', 'Failed')
                break
        try:
            self.pipeline_finish()
        except MachineError:
            pass

    def _on_server_cancelled(self, request_id: str):
        if request_id != self._active_request_id:
            return
        self._log("Operation cancelled")
        self._stage_queue.clear()
        self._cleanup_pending_workspace()
        self._set_status("Cancelled")
        try:
            self.pipeline_finish()
        except MachineError:
            pass

    def _on_server_acknowledged(self, request_id: str):
        self._log(f"Server acknowledged: {request_id[:12]}...")

    def _on_server_status(self, active_requests: list):
        """Handle status response — process any completed requests from previous session."""
        for req in active_requests:
            status = req.get("status")
            request_id = req.get("request_id", "")
            op_str = req.get("operation", "")
            depends_on = req.get("depends_on", {})

            try:
                op = Operation(op_str)
            except ValueError:
                continue

            current_deps = self._project.current_depends_on(op)
            deps_valid = all(
                current_deps.get(k) == v for k, v in depends_on.items()
            )

            if status == "completed" and deps_valid:
                output_dir = req.get("output_dir", "")
                self._on_server_completed(request_id, output_dir)
            elif status == "completed" and not deps_valid:
                self._server_bridge.request_reject(request_id)
                self._log(f"Rejected stale result for {op_str}")
            elif status == "running" and deps_valid:
                self._active_request_id = request_id
                self._active_stage = op
                try:
                    self.pipeline_start()
                except MachineError:
                    pass
                self._set_status(f"Resuming {op_str}...")
            elif status == "running" and not deps_valid:
                self._server_bridge.request_cancel(request_id)

    def _cleanup_pending_workspace(self):
        from .workspace import WorkspaceManager
        wm = WorkspaceManager()
        if self._pending_input_dir:
            wm.delete(self._pending_input_dir)
            self._pending_input_dir = None
        if self._pending_output_dir:
            wm.delete(self._pending_output_dir)
            self._pending_output_dir = None
        self._active_request_id = None
        self._active_stage = None

    def _update_validity_ui(self):
        """Recompute operation validity and update stage entries."""
        if not self._project.is_open:
            return
        states = self._project.all_operation_states()
        for stage in Stage:
            op = _STAGE_TO_OPERATION.get(stage)
            if op:
                idx = self._stage_index(stage)
                if idx >= 0:
                    self._stages[idx]["validity"] = states[op].value
        self.stagesChanged.emit()
        self.operationStatesChanged.emit()

    def _start_server_stage(self, stage: Stage):
        """Start a single pipeline stage via the server bridge."""
        if not self._server_bridge or not self._server_connected:
            self._log("Error: Not connected to processing server")
            try:
                self.pipeline_finish()
            except MachineError:
                pass
            return

        from .workspace import WorkspaceManager
        wm = WorkspaceManager()
        input_dir, output_dir = wm.create_input_output()
        self._pending_input_dir = input_dir
        self._pending_output_dir = output_dir
        self._active_stage = stage

        project_dir = self._project.project_dir
        _STAGE_INPUT_SOURCES = {
            Stage.FRAMES:          lambda pd: Path(self._video_path) if self._video_path else None,
            Stage.FEATURE_EXTRACT: lambda pd: pd / "nerfstudio" / "frames" if pd else None,
            Stage.FEATURE_MATCH:   lambda pd: pd / "nerfstudio" / "feature_extract" if pd else None,
            Stage.RECONSTRUCTION:  lambda pd: pd / "nerfstudio" / "feature_match" if pd else None,
            Stage.TRAINING:        lambda pd: pd / "nerfstudio" / "nerfstudio_data" if pd else None,
            Stage.EXPORT:          lambda pd: pd / "nerfstudio" / "outputs" if pd else None,
        }
        source_fn = _STAGE_INPUT_SOURCES.get(stage)
        source = source_fn(project_dir) if source_fn else None
        if source and source.exists():
            wm.clone_into(input_dir, source)

        params = {}
        if stage == Stage.FRAMES:
            params["num_frames_target"] = self._max_frames if self._max_frames > 0 else 300
        elif stage == Stage.TRAINING:
            params["max_iterations"] = self._training_iterations

        op = _STAGE_TO_OPERATION.get(stage)
        depends_on = self._project.current_depends_on(op) if op else {}

        self._server_bridge.request_run_stage(
            project_id=self._project.project_uuid or "",
            stage=stage.value,
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            depends_on=depends_on,
            params=params,
        )

    def _run_next_stage(self):
        """Pop the next stage from the queue and execute it via the server."""
        if not self._stage_queue:
            return

        if not self._server_connected:
            self._log("Connecting to server...")
            self.connect_to_server()
            return

        if not self._project.is_open:
            self._project.new_project(
                project_dir=str(self._project.project_dir) if self._project.project_dir else None,
                video_path=self._video_path,
                settings=self._current_settings(),
            )

        stage = self._stage_queue.pop(0)
        self._log(f"Starting {stage.value}...")
        self._start_server_stage(stage)

    @pyqtSlot()
    def connectToServer(self):
        """QML-callable: initiate server connection."""
        self.connect_to_server()

    @pyqtSlot()
    def disconnectFromServer(self):
        """QML-callable: disconnect from server."""
        self.disconnect_from_server()
