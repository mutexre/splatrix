"""Worker threads for async UI operations"""

import os
import re
import signal
import sys
import psutil
from typing import Optional, Literal
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from .video_processor import VideoProcessor
from .reconstruction_pipeline import ReconstructionPipeline
from .ply_exporter import PLYExporter
from .nerfstudio_integration import NerfstudioPipeline
from .stages import Stage

_SPINNER_RE = re.compile(r'[🌑🌒🌓🌔🌕🌖🌗🌘🚶🏃◡⊙◠]')
_COUNT_RE = re.compile(r'\[(\d+)/(\d+)\]')
_FRAME_COUNT_RE = re.compile(r'Extracting frames: (\d+)')


def _classify_data_substage(text: str, raw_progress: float) -> list[dict]:
    """Parse nerfstudio data-processing output and return stage signals to emit.

    Each signal is a dict with keys: stage_key (Stage enum), status, progress.
    Includes explicit completion signals for prior stages when a later stage starts.
    """
    lower = text.lower()
    signals: list[dict] = []

    if any(x in lower for x in ("extracting frames", "converting video", "preparing for frame")):
        m = _FRAME_COUNT_RE.search(text)
        pct = min(int(m.group(1)) / 300, 0.99) if m else min(raw_progress / 0.15, 0.99) if raw_progress < 0.15 else 0.01
        signals.append({'stage_key': Stage.FRAMES, 'status': 'running', 'progress': pct})

    elif "frame extraction complete" in lower or ("done converting" in lower and "feature" not in lower):
        signals.append({'stage_key': Stage.FRAMES, 'status': 'completed', 'progress': 1.0})

    elif "extracting features" in lower or "processed file" in lower:
        signals.append({'stage_key': Stage.FRAMES, 'status': 'completed', 'progress': 1.0})
        m = _COUNT_RE.search(text)
        pct = int(m.group(1)) / int(m.group(2)) if m else 0.01
        signals.append({'stage_key': Stage.FEATURE_EXTRACT, 'status': 'running', 'progress': pct})

    elif "feature extraction complete" in lower:
        signals.append({'stage_key': Stage.FRAMES, 'status': 'completed', 'progress': 1.0})
        signals.append({'stage_key': Stage.FEATURE_EXTRACT, 'status': 'completed', 'progress': 1.0})

    elif "matching features" in lower or "processing image" in lower:
        signals.append({'stage_key': Stage.FRAMES, 'status': 'completed', 'progress': 1.0})
        signals.append({'stage_key': Stage.FEATURE_EXTRACT, 'status': 'completed', 'progress': 1.0})
        m = _COUNT_RE.search(text)
        pct = int(m.group(1)) / int(m.group(2)) if m else 0.01
        signals.append({'stage_key': Stage.FEATURE_MATCH, 'status': 'running', 'progress': pct})

    elif "feature matching complete" in lower:
        for s in (Stage.FRAMES, Stage.FEATURE_EXTRACT, Stage.FEATURE_MATCH):
            signals.append({'stage_key': s, 'status': 'completed', 'progress': 1.0})

    elif any(x in lower for x in ("reconstruction", "bundle adjustment", "refining", "registering")):
        for s in (Stage.FRAMES, Stage.FEATURE_EXTRACT, Stage.FEATURE_MATCH):
            signals.append({'stage_key': s, 'status': 'completed', 'progress': 1.0})
        pct = 0.5
        if "bundle" in lower:
            pct = 0.6
        elif "refining" in lower:
            pct = 0.8
        signals.append({'stage_key': Stage.RECONSTRUCTION, 'status': 'running', 'progress': pct})

    elif ("colmap" in lower and "complete" in lower) or "all done" in lower or "congrats" in lower or raw_progress >= 1.0:
        for s in (Stage.FRAMES, Stage.FEATURE_EXTRACT, Stage.FEATURE_MATCH, Stage.RECONSTRUCTION):
            signals.append({'stage_key': s, 'status': 'completed', 'progress': 1.0})

    elif raw_progress < 0.15 and "colmap" not in lower:
        pct = min(raw_progress / 0.15, 0.99) if raw_progress > 0 else 0.01
        signals.append({'stage_key': Stage.FRAMES, 'status': 'running', 'progress': pct})

    return signals


class VideoProcessingWorker(QThread):
    """Worker thread for video frame extraction"""
    
    progress = pyqtSignal(dict)  # {'stage': str, 'current': int, 'total': int}
    finished = pyqtSignal(dict)  # {'success': bool, 'frame_paths': list, 'error': str}
    error = pyqtSignal(str)
    
    def __init__(
        self,
        video_path: str,
        output_dir: str,
        sample_rate: int = 1,
        max_frames: Optional[int] = None
    ):
        super().__init__()
        self.setTerminationEnabled(True)  # Allow thread termination
        self.video_path = video_path
        self.output_dir = output_dir
        self.sample_rate = sample_rate
        self.max_frames = max_frames
        self._is_cancelled = False
    
    def cancel(self):
        """Cancel the operation"""
        self._is_cancelled = True
    
    def run(self):
        """Execute video processing"""
        try:
            processor = VideoProcessor()
            
            # Load video
            self.progress.emit({
                'stage': 'Loading video',
                'current': 0,
                'total': 100
            })
            
            metadata = processor.load_video(self.video_path)
            
            # Extract frames
            def progress_callback(current: int, total: int):
                if self._is_cancelled:
                    raise InterruptedError("Operation cancelled")
                
                self.progress.emit({
                    'stage': 'Extracting frames',
                    'current': current,
                    'total': total
                })
            
            frame_paths = processor.extract_frames(
                self.output_dir,
                sample_rate=self.sample_rate,
                max_frames=self.max_frames,
                progress_callback=progress_callback
            )
            
            if self._is_cancelled:
                self.finished.emit({
                    'success': False,
                    'frame_paths': [],
                    'error': 'Operation cancelled'
                })
                return
            
            self.finished.emit({
                'success': True,
                'frame_paths': [str(p) for p in frame_paths],
                'metadata': metadata,
                'error': ''
            })
        
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit({
                'success': False,
                'frame_paths': [],
                'error': str(e)
            })


class ReconstructionWorker(QThread):
    """Worker thread for 3D reconstruction and Gaussian Splatting"""
    
    progress = pyqtSignal(dict)  # {'stage': str, 'progress': float}
    finished = pyqtSignal(dict)  # {'success': bool, 'data': dict, 'error': str}
    error = pyqtSignal(str)
    
    def __init__(
        self,
        frame_paths: list[str],
        workspace_dir: str,
        method: Literal["colmap", "instant-ngp", "mock"] = "mock"
    ):
        super().__init__()
        self.setTerminationEnabled(True)
        self.frame_paths = [Path(p) for p in frame_paths]
        self.workspace_dir = workspace_dir
        self.method = method
        self._is_cancelled = False
    
    def cancel(self):
        """Cancel the operation"""
        self._is_cancelled = True
    
    def run(self):
        """Execute reconstruction"""
        try:
            pipeline = ReconstructionPipeline()
            pipeline.setup_workspace(self.workspace_dir)
            
            def progress_callback(stage: str, progress: float):
                if self._is_cancelled:
                    raise InterruptedError("Operation cancelled")
                
                self.progress.emit({
                    'stage': stage,
                    'progress': progress
                })
            
            if self.method == "mock":
                # Use mock reconstruction for testing
                splat_data = pipeline.create_mock_gaussian_splats(
                    self.frame_paths,
                    num_points=10000,
                    progress_callback=progress_callback
                )
            elif self.method == "colmap":
                # Use COLMAP for real reconstruction
                image_dir = self.frame_paths[0].parent
                colmap_result = pipeline.run_colmap_sfm(
                    str(image_dir),
                    progress_callback=progress_callback
                )
                # Would need to convert COLMAP output to Gaussian Splats
                # For now, fall back to mock data
                splat_data = pipeline.create_mock_gaussian_splats(
                    self.frame_paths,
                    num_points=10000,
                    progress_callback=progress_callback
                )
            else:
                raise ValueError(f"Unsupported method: {self.method}")
            
            if self._is_cancelled:
                self.finished.emit({
                    'success': False,
                    'data': {},
                    'error': 'Operation cancelled'
                })
                return
            
            self.finished.emit({
                'success': True,
                'data': splat_data,
                'error': ''
            })
        
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit({
                'success': False,
                'data': {},
                'error': str(e)
            })


class PLYExportWorker(QThread):
    """Worker thread for PLY export"""
    
    progress = pyqtSignal(dict)  # {'stage': str, 'progress': float}
    finished = pyqtSignal(dict)  # {'success': bool, 'output_path': str, 'error': str}
    error = pyqtSignal(str)
    
    def __init__(self, splat_data: dict, output_path: str):
        super().__init__()
        self.setTerminationEnabled(True)
        self.splat_data = splat_data
        self.output_path = output_path
    
    def run(self):
        """Execute PLY export"""
        try:
            self.progress.emit({
                'stage': 'Exporting to PLY',
                'progress': 0.5
            })
            
            exporter = PLYExporter()
            output_file = exporter.create_gaussian_splat_ply(
                positions=self.splat_data['positions'],
                colors=self.splat_data['colors'],
                scales=self.splat_data.get('scales'),
                rotations=self.splat_data.get('rotations'),
                opacities=self.splat_data.get('opacities'),
                output_path=self.output_path
            )
            
            self.progress.emit({
                'stage': 'Export complete',
                'progress': 1.0
            })
            
            self.finished.emit({
                'success': True,
                'output_path': str(output_file),
                'error': ''
            })
        
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit({
                'success': False,
                'output_path': '',
                'error': str(e)
            })


class NerfstudioWorker(QThread):
    """Worker thread for full nerfstudio pipeline"""
    
    progress = pyqtSignal(dict)  # {'stage_key': Stage, 'status': str, 'progress': float}
    finished = pyqtSignal(dict)  # {'success': bool, 'output_path': str, 'error': str}
    error = pyqtSignal(str)
    log = pyqtSignal(str)  # Log messages
    stage_data_completed = pyqtSignal(str)       # data_dir - for project save
    stage_training_completed = pyqtSignal(str, str)  # checkpoint_dir, latest_ckpt - for project save
    
    def __init__(
        self,
        video_path: str,
        workspace_dir: str,
        output_ply_path: str,
        max_iterations: int = 30000,
        use_video_directly: bool = True,
        video_processor: str = "nerfstudio",  # "nerfstudio" or "pyav"
        num_frames_target: int = 300,  # Max frames to extract from video
        # Resume support
        skip_data_processing: bool = False,  # Skip frames/COLMAP stages
        skip_training: bool = False,          # Skip training stage
        existing_checkpoint: Optional[str] = None,  # Resume export from checkpoint
        existing_data_dir: Optional[str] = None,    # Resume training from existing data
    ):
        super().__init__()
        self.setTerminationEnabled(True)  # Allow thread termination
        self.video_path = video_path
        self.workspace_dir = workspace_dir
        self.output_ply_path = output_ply_path
        self.video_processor = video_processor
        self.max_iterations = max_iterations
        self.use_video_directly = use_video_directly
        self.num_frames_target = num_frames_target
        self.skip_data_processing = skip_data_processing
        self.skip_training = skip_training
        self.existing_checkpoint = existing_checkpoint
        self.existing_data_dir = existing_data_dir
        self._is_cancelled = False
    
    def cancel(self):
        """Cancel the operation"""
        self._is_cancelled = True
    
    def terminate(self):
        """Override terminate to kill child processes (ffmpeg, colmap, etc)"""
        self._is_cancelled = True
        try:
            import subprocess
            current_process = psutil.Process(os.getpid())
            children = current_process.children(recursive=True)
            
            # Send SIGTERM to children (graceful shutdown)
            for child in children:
                try:
                    # Redirect stderr to suppress pycolmap stack traces during termination
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Wait briefly then force kill if still alive
            gone, alive = psutil.wait_procs(children, timeout=1)
            for proc in alive:
                try:
                    # SIGKILL - no cleanup, immediate termination
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Suppress the worker's own stderr to hide pycolmap abort messages
            # (This won't fully suppress them since they're in child processes,
            #  but documents the behavior)
        except Exception:
            pass  # Best effort cleanup
        
        super().terminate()
    
    def _emit_stage(self, stage: Stage, status: str, progress: float):
        self.progress.emit({'stage_key': stage, 'status': status, 'progress': progress})

    def run(self):
        """Execute full nerfstudio pipeline"""
        try:
            self.log.emit("Loading ML libraries...")
            init_stage = Stage.TRAINING if self.skip_data_processing else Stage.FRAMES
            self._emit_stage(init_stage, 'running', 0.01)

            pipeline = NerfstudioPipeline(video_processor=self.video_processor)

            if not pipeline.check_nerfstudio_installed():
                raise RuntimeError(
                    "nerfstudio not found. Install with: pip install nerfstudio"
                )

            self.log.emit("Nerfstudio pipeline starting...")

            workspace_info = pipeline.setup_workspace(self.workspace_dir)
            self.log.emit(f"Workspace: {workspace_info['workspace']}")

            # ── Stage 1: Process data (video or images) ──
            if self.skip_data_processing and self.existing_data_dir:
                self.log.emit(f"[Resume] Skipping data processing - using existing: {self.existing_data_dir}")
                for s in (Stage.FRAMES, Stage.FEATURE_EXTRACT, Stage.FEATURE_MATCH, Stage.RECONSTRUCTION):
                    self._emit_stage(s, 'completed', 1.0)
                data_result = {'data_dir': self.existing_data_dir}
            else:
                last_logged = ""
                def data_progress(text: str, raw_progress: float):
                    nonlocal last_logged
                    if self._is_cancelled:
                        raise InterruptedError("Operation cancelled")
                    for signal in _classify_data_substage(text, raw_progress):
                        self.progress.emit(signal)
                    text_clean = _SPINNER_RE.sub('', text).strip()
                    last_clean = _SPINNER_RE.sub('', last_logged).strip()
                    if text_clean != last_clean and text_clean:
                        self.log.emit(f"[Data] {text_clean}")
                        last_logged = text

                if self.use_video_directly:
                    self.log.emit("Processing video with nerfstudio...")
                    self.log.emit(f"Target frames: {self.num_frames_target}")
                    data_result = pipeline.process_video_data(
                        self.video_path,
                        num_frames_target=self.num_frames_target,
                        progress_callback=data_progress
                    )
                else:
                    frames_dir = Path(self.workspace_dir) / "frames"
                    self.log.emit(f"Processing images from {frames_dir}...")
                    data_result = pipeline.process_images_data(
                        str(frames_dir),
                        progress_callback=data_progress
                    )

                self.log.emit(f"Data processing complete: {data_result['data_dir']}")
                for s in (Stage.FRAMES, Stage.FEATURE_EXTRACT, Stage.FEATURE_MATCH, Stage.RECONSTRUCTION):
                    self._emit_stage(s, 'completed', 1.0)
                self.stage_data_completed.emit(data_result['data_dir'])

            if self._is_cancelled:
                self._emit_cancelled()
                return

            # ── Stage 2: Train splatfacto ──
            if self.skip_training and self.existing_checkpoint:
                latest_checkpoint = Path(self.existing_checkpoint)
                config_path = None
                checkpoint_dir = str(latest_checkpoint.parent)
                self.log.emit(f"[Resume] Skipping training - using checkpoint: {latest_checkpoint.name}")
                self._emit_stage(Stage.TRAINING, 'completed', 1.0)
            else:
                last_training_log = ""
                def training_progress(text: str, progress: float):
                    nonlocal last_training_log
                    if self._is_cancelled:
                        raise InterruptedError("Operation cancelled")
                    status = 'running' if progress < 1.0 else 'completed'
                    self._emit_stage(Stage.TRAINING, status, progress)
                    should_log = False
                    if text != last_training_log:
                        should_log = True
                    elif "Step" in text:
                        match = re.search(r'Step (\d+)/', text)
                        if match:
                            step = int(match.group(1))
                            if step % 100 == 0 or step < 10 or progress > 0.95:
                                should_log = True
                    if should_log:
                        self.log.emit(f"[Training] {text}")
                        last_training_log = text

                backend_name = pipeline.training_backend.name
                self.log.emit(f"Starting training via {backend_name} backend...")
                self.log.emit(f"Training data directory: {data_result['data_dir']}")

                training_result = pipeline.train_splatfacto(
                    data_result['data_dir'],
                    max_num_iterations=self.max_iterations,
                    progress_callback=training_progress
                )

                config_path = training_result.get('config_path')
                checkpoint_dir = training_result.get('checkpoint_dir')

                if checkpoint_dir:
                    checkpoint_dir_path = Path(checkpoint_dir)
                    checkpoints = list(checkpoint_dir_path.glob("step-*.ckpt"))
                    if checkpoints:
                        latest_checkpoint = max(checkpoints, key=lambda p: int(p.stem.split('-')[1]))
                    else:
                        latest_checkpoint = next(checkpoint_dir_path.iterdir(), None)
                else:
                    latest_checkpoint = None

                ckpt_label = latest_checkpoint.name if latest_checkpoint else "N/A"
                self.log.emit(f"Training complete. Checkpoint: {ckpt_label}")
                self._emit_stage(Stage.TRAINING, 'completed', 1.0)
                if checkpoint_dir and latest_checkpoint:
                    self.stage_training_completed.emit(checkpoint_dir, str(latest_checkpoint))

            if self._is_cancelled:
                self._emit_cancelled()
                return

            # ── Stage 3: Export to PLY ──
            def export_progress(text: str, progress: float):
                if self._is_cancelled:
                    raise InterruptedError("Operation cancelled")
                status = 'running' if progress < 1.0 else 'completed'
                self._emit_stage(Stage.EXPORT, status, progress)
                self.log.emit(f"[Export] {text}")

            self.log.emit("Exporting Gaussian Splats to PLY...")
            output_path = pipeline.export_gaussian_splat(
                str(latest_checkpoint) if latest_checkpoint else "",
                self.output_ply_path,
                progress_callback=export_progress
            )

            self.log.emit(f"Export complete: {output_path}")
            self._emit_stage(Stage.EXPORT, 'completed', 1.0)

            self.finished.emit({
                'success': True,
                'output_path': str(output_path),
                'config_path': config_path,
                'error': ''
            })

        except InterruptedError:
            self._emit_cancelled()
        except Exception as e:
            if self._is_cancelled:
                self._emit_cancelled()
                return

            import traceback
            error_msg = str(e)
            tb = traceback.format_exc()
            print(f"[Pipeline] Full traceback:\n{tb}", file=sys.stderr)

            if "BundleAdjuster" in error_msg or "COLMAP" in error_msg:
                self.log.emit("✗ COLMAP reconstruction failed")
                self.log.emit("💡 Tip: Video needs good camera motion, textured scenes, and overlap")
                self.log.emit("   Try a video with slow panning and well-lit objects")

            self.log.emit(f"✗ Error: {error_msg[:200]}")
            self.error.emit(error_msg)
            self.finished.emit({
                'success': False,
                'output_path': '',
                'error': error_msg
            })
    
    def _emit_cancelled(self):
        """Emit cancellation result"""
        self.log.emit("Operation cancelled by user")
        self.log.emit("ℹ Note: ERROR messages above are expected when cancelling (ffmpeg/COLMAP received SIGTERM)")
        self.finished.emit({
            'success': False,
            'output_path': '',
            'error': 'Operation cancelled'
        })

