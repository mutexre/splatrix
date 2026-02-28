"""Python ↔ QML bridge: exposes backend state as QObject properties/slots for QML UI."""

import json
import re
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QObject, pyqtProperty, pyqtSignal, pyqtSlot, QUrl, QVariant
)
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
    """Single QObject that QML binds to via 'backend' context property."""

    # ── Signals for property change notifications ──
    videoNameChanged = pyqtSignal()
    videoInfoChanged = pyqtSignal()
    videoUrlChanged = pyqtSignal()
    hasVideoChanged = pyqtSignal()
    maxFramesChanged = pyqtSignal()
    trainingIterationsChanged = pyqtSignal()
    reconstructionMethodChanged = pyqtSignal()
    outputPathChanged = pyqtSignal()
    isProcessingChanged = pyqtSignal()
    canResumeTrainingChanged = pyqtSignal()
    statusTextChanged = pyqtSignal()
    stagesChanged = pyqtSignal()
    logContentChanged = pyqtSignal()
    windowTitleChanged = pyqtSignal()
    projectNameChanged = pyqtSignal()
    viewerUrlChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Internal state
        self._video_path: Optional[str] = None
        self._video_info = ""
        self._max_frames = 300
        self._training_iterations = 30000
        self._reconstruction_method = 1  # Nerfstudio
        self._output_path = str(Path.home() / ".splats_workspace" / "output.ply")
        self._status_text = "Ready"
        self._log_lines: list[str] = []
        self._viewer_url = ""

        # Stage state
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

        # Load persisted settings
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

    @pyqtProperty(int, notify=trainingIterationsChanged)
    def trainingIterations(self):
        return self._training_iterations

    @trainingIterations.setter
    def trainingIterations(self, v):
        if self._training_iterations != v:
            self._training_iterations = v
            self.trainingIterationsChanged.emit()
            self._save_settings()

    @pyqtProperty(int, notify=reconstructionMethodChanged)
    def reconstructionMethod(self):
        return self._reconstruction_method

    @reconstructionMethod.setter
    def reconstructionMethod(self, v):
        if self._reconstruction_method != v:
            self._reconstruction_method = v
            self.reconstructionMethodChanged.emit()
            self._save_settings()

    @pyqtProperty(str, notify=outputPathChanged)
    def outputPath(self):
        return self._output_path

    @outputPath.setter
    def outputPath(self, v):
        if self._output_path != v:
            self._output_path = v
            self.outputPathChanged.emit()

    @pyqtProperty(bool, notify=isProcessingChanged)
    def isProcessing(self):
        return any([
            self._nerfstudio_worker and self._nerfstudio_worker.isRunning(),
            self._video_worker and self._video_worker.isRunning(),
            self._reconstruction_worker and self._reconstruction_worker.isRunning(),
            self._export_worker and self._export_worker.isRunning(),
        ])

    @pyqtProperty(bool, notify=canResumeTrainingChanged)
    def canResumeTraining(self):
        return (
            not self.isProcessing and
            self._project.is_open and
            self._project.can_resume_from_training()
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
            self._update_button_states()

    @pyqtSlot()
    def browseOutput(self):
        file_path, _ = QFileDialog.getSaveFileName(
            None, "Save PLY File", self._output_path, "PLY Files (*.ply);;All Files (*)"
        )
        if file_path:
            self.outputPath = file_path

    @pyqtSlot()
    def startConversion(self):
        if not self._video_path:
            self._log("Error: No video selected")
            return

        self._log("=" * 50)
        self._log("Starting conversion pipeline...")
        self._set_status("Processing...")

        if self._reconstruction_method == 1:
            self._start_nerfstudio_pipeline()
        else:
            self._start_video_processing()

    @pyqtSlot()
    def resumeFromTraining(self):
        checkpoint = self._project.get_training_checkpoint()
        if not checkpoint or not Path(checkpoint).exists():
            self._log("No valid checkpoint found in project")
            return

        self._log(f"[Resume] Starting from checkpoint: {Path(checkpoint).name}")
        self._log("Skipping data processing and training")

        for key in ['frames', 'feature_extract', 'feature_match', 'reconstruction', 'training']:
            self._set_stage(key, 'completed', 'Skipped')
        self._set_stage('export', 'pending', 'Waiting...')

        workspace = self._workspace / "nerfstudio"
        max_frames = self._max_frames if self._max_frames > 0 else 300

        self._nerfstudio_worker = NerfstudioWorker(
            video_path=self._video_path or "",
            workspace_dir=str(workspace),
            output_ply_path=self._output_path,
            max_iterations=self._training_iterations,
            use_video_directly=True,
            num_frames_target=max_frames,
            skip_data_processing=True,
            skip_training=True,
            existing_checkpoint=checkpoint,
            existing_data_dir=self._project.get_stage('reconstruction').get('path'),
        )
        self._connect_nerfstudio_worker()
        self._nerfstudio_worker.start()
        self._update_button_states()

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
    def clear(self):
        self._video_path = None
        self._video_info = ""
        self._set_status("Ready")
        self._log_lines.clear()
        self.logContentChanged.emit()
        self.videoNameChanged.emit()
        self.videoUrlChanged.emit()
        self.videoInfoChanged.emit()
        self.hasVideoChanged.emit()

        for key, _ in STAGE_DEFS:
            self._set_stage(key, "pending", "")
            self._stage_paths[key] = None

        self._log("Cleared all data")
        self._update_button_states()

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
        self._project.new_project(video_path=self._video_path, settings=self._current_settings())
        self._on_save_project_as()

    @pyqtSlot()
    def openProject(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Open Project", str(Path.home()),
            "Splat Projects (*.splatproj);;All Files (*)"
        )
        if path:
            self._load_project_file(path)

    @pyqtSlot()
    def saveProject(self):
        if not self._project.is_open:
            self._project.new_project(video_path=self._video_path, settings=self._current_settings())
        if not self._project.project_path:
            self._on_save_project_as()
        else:
            self._project.update_settings(self._current_settings())
            if self._video_path:
                self._project.update_input(self._video_path)
            self._project.save_project()
            self._log(f"Project saved: {self._project.project_path.name}")
            self.windowTitleChanged.emit()

    @pyqtSlot()
    def saveProjectAs(self):
        self._on_save_project_as()

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
        stage["status"] = status
        if detail:
            stage["detail"] = detail
        if progress >= 0:
            stage["progress"] = progress
        elif status == "completed":
            stage["progress"] = 1.0
        elif status == "pending":
            stage["progress"] = 0.0
        self.stagesChanged.emit()

    def _update_button_states(self):
        self.isProcessingChanged.emit()
        self.canResumeTrainingChanged.emit()

    def _current_settings(self) -> dict:
        return {
            'reconstruction_method': self._reconstruction_method,
            'training_iterations': self._training_iterations,
            'sample_rate': 5,
            'max_frames': self._max_frames,
        }

    # ── Settings persistence ──

    def _load_settings(self):
        if not self._settings_file.exists():
            return
        try:
            with open(self._settings_file) as f:
                s = json.load(f)
            if 'reconstruction_method' in s:
                self._reconstruction_method = s['reconstruction_method']
            if 'training_iterations' in s:
                self._training_iterations = s['training_iterations']
            if 'max_frames' in s:
                self._max_frames = s['max_frames']
            last_video = s.get('last_video_path')
            if last_video and Path(last_video).exists():
                self._video_path = last_video
                try:
                    processor = VideoProcessor()
                    info = processor.get_video_info(last_video)
                    self._video_info = (
                        f"Resolution: {info['width']}x{info['height']} | "
                        f"FPS: {info['fps']:.2f} | "
                        f"Frames: {info['frame_count']} | "
                        f"Duration: {info['duration']:.2f}s"
                    )
                except Exception:
                    pass
            self._log("Settings loaded")
        except Exception as e:
            self._log(f"Could not load settings: {e}")

    def _save_settings(self):
        try:
            settings = {
                'last_video_path': self._video_path,
                'reconstruction_method': self._reconstruction_method,
                'training_iterations': self._training_iterations,
                'sample_rate': 5,
                'max_frames': self._max_frames,
            }
            with open(self._settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"[WARN] Could not save settings: {e}")

    # ── Project helpers ──

    def _on_save_project_as(self):
        suggested = str(Path.home() / "splats_project.splatproj")
        if self._video_path:
            stem = Path(self._video_path).stem
            suggested = str(Path.home() / f"{stem}.splatproj")

        path, _ = QFileDialog.getSaveFileName(
            None, "Save Project As", suggested,
            "Splat Projects (*.splatproj);;All Files (*)"
        )
        if path:
            if not path.endswith('.splatproj'):
                path += '.splatproj'
            if not self._project.is_open:
                self._project.new_project(video_path=self._video_path, settings=self._current_settings())
            self._project.update_settings(self._current_settings())
            if self._video_path:
                self._project.update_input(self._video_path)
            self._project.save_project(path)
            self._log(f"Project saved: {path}")
            self.windowTitleChanged.emit()
            self.projectNameChanged.emit()

    def _load_project_file(self, path: str):
        try:
            self._project.load_project(path)
            self._log(f"Project loaded: {Path(path).name}")
            self.windowTitleChanged.emit()
            self.projectNameChanged.emit()

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
            if s.get('reconstruction_method') is not None:
                self._reconstruction_method = s['reconstruction_method']
                self.reconstructionMethodChanged.emit()
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

    def _load_ply_in_viewer(self, ply_path: str):
        try:
            ply = Path(ply_path).resolve()
            if not ply.exists():
                self._log(f"PLY file not found: {ply}")
                return
            url = QUrl.fromLocalFile(str(self._viewer_html))
            url.setQuery(f"ply=file://{ply}")
            self._viewer_url = url.toString()
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
            self._project.new_project(video_path=self._video_path, settings=self._current_settings())
        else:
            self._project.update_settings(self._current_settings())
            if self._video_path:
                self._project.update_input(self._video_path)
            for s in STAGE_ORDER:
                self._project.update_stage(s, 'pending')

        for key, _ in STAGE_DEFS:
            self._set_stage(key, 'pending', 'Waiting...')

        max_frames = self._max_frames if self._max_frames > 0 else 300
        workspace = self._workspace / "nerfstudio"

        self._nerfstudio_worker = NerfstudioWorker(
            video_path=self._video_path,
            workspace_dir=str(workspace),
            output_ply_path=self._output_path,
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
            ws_data = str(self._workspace / "nerfstudio" / "nerfstudio_data")

            if any(x in substage.lower() for x in ["extracting frames", "converting video"]) or (progress < 0.15 and "colmap" not in substage.lower()):
                target = self._max_frames or 300
                self._set_stage('frames', 'running', f"Extracting (target: {target})", progress=min(progress / 0.15, 0.99))

            elif "frame extraction complete" in substage.lower() or ("done converting" in substage.lower() and "feature" not in substage.lower()):
                self._set_stage('frames', 'completed', 'Complete')

            elif "extracting features" in substage.lower():
                self._set_stage('frames', 'completed', 'Complete')
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

            elif progress >= 1.0 or "all done" in substage.lower() or "congrats" in substage.lower():
                for k in ['frames', 'feature_extract', 'feature_match', 'reconstruction']:
                    self._set_stage(k, 'completed', 'Complete')

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
            if not self._project.project_path:
                stem = Path(self._video_path).stem if self._video_path else "splats"
                auto_path = self._workspace / f"{stem}.splatproj"
                self._project.save_project(str(auto_path))
                self._log(f"Project auto-saved: {auto_path.name}")
                self.windowTitleChanged.emit()
                self.projectNameChanged.emit()
            else:
                self._auto_save_project()

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
        self._auto_save_project()

    def _on_stage_training_completed(self, checkpoint_dir: str, latest_checkpoint: str):
        if not self._project.is_open:
            self._project.new_project(video_path=self._video_path, settings=self._current_settings())
        self._project.update_stage(
            'training', 'completed',
            checkpoint_dir=checkpoint_dir,
            latest_checkpoint=latest_checkpoint,
        )
        self._auto_save_project()
        self._update_button_states()

    # ── Mock/COLMAP pipeline (non-nerfstudio) ──

    def _start_video_processing(self):
        self._log("Stage 1/3: Extracting frames from video...")
        frames_dir = self._workspace / "frames"
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
        method = "mock" if self._reconstruction_method == 0 else "colmap"
        self._reconstruction_worker = ReconstructionWorker(
            frame_paths, str(self._workspace / "reconstruction"), method=method
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
        self._export_worker = PLYExportWorker(splat_data, self._output_path)
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
