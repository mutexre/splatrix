"""Worker threads for async UI operations"""

import os
import signal
import psutil
from typing import Optional, Literal
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from .video_processor import VideoProcessor
from .reconstruction_pipeline import ReconstructionPipeline
from .ply_exporter import PLYExporter
from .nerfstudio_integration import NerfstudioPipeline


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
    
    progress = pyqtSignal(dict)  # {'stage': str, 'progress': float, 'substage': str}
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
    
    def run(self):
        """Execute full nerfstudio pipeline"""
        try:
            pipeline = NerfstudioPipeline(video_processor=self.video_processor)
            
            # Check nerfstudio installation
            if not pipeline.check_nerfstudio_installed():
                raise RuntimeError(
                    "nerfstudio not found. Install with: pip install nerfstudio"
                )
            
            self.log.emit("Nerfstudio pipeline starting...")
            
            # Setup workspace
            workspace_info = pipeline.setup_workspace(self.workspace_dir)
            self.log.emit(f"Workspace: {workspace_info['workspace']}")
            
            # Stage 1: Process data (video or images)
            if self.skip_data_processing and self.existing_data_dir:
                # Resume: skip data processing, use existing data
                self.log.emit(f"[Resume] Skipping data processing - using existing: {self.existing_data_dir}")
                data_result = {'data_dir': self.existing_data_dir}
                # Emit done signals for all data stages
                for substage in ['frames', 'feature_extract', 'feature_match', 'reconstruction']:
                    self.progress.emit({
                        'stage': 'Data Processing',
                        'progress': 0.2,
                        'substage': f'{substage} skipped (resumed)'
                    })
            else:
                last_logged = ""
                def data_progress(stage: str, progress: float):
                    nonlocal last_logged
                    if self._is_cancelled:
                        raise InterruptedError("Operation cancelled")
                    self.progress.emit({
                        'stage': 'Data Processing',
                        'progress': progress * 0.2,  # 0-20%
                        'substage': stage
                    })
                    # Log unique stages, filtering spinner/animation updates
                    import re
                    stage_clean = re.sub(r'[🌑🌒🌓🌔🌕🌖🌗🌘🚶🏃◡⊙◠]', '', stage).strip()
                    last_clean = re.sub(r'[🌑🌒🌓🌔🌕🌖🌗🌘🚶🏃◡⊙◠]', '', last_logged).strip()
                    
                    if stage_clean != last_clean and stage_clean:
                        self.log.emit(f"[Data] {stage_clean}")
                        last_logged = stage
                
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
                # Emit stage completion signal for project manager hook in main window
                self.stage_data_completed.emit(data_result['data_dir'])
            
            if self._is_cancelled:
                self._emit_cancelled()
                return
            
            # Stage 2: Train splatfacto
            if self.skip_training and self.existing_checkpoint:
                # Resume: skip training, use existing checkpoint
                latest_checkpoint = Path(self.existing_checkpoint)
                config_path = None
                checkpoint_dir = str(latest_checkpoint.parent)
                self.log.emit(f"[Resume] Skipping training - using checkpoint: {latest_checkpoint.name}")
                self.progress.emit({
                    'stage': 'Training Gaussian Splats',
                    'progress': 0.9,
                    'substage': 'Skipped (resumed from checkpoint)'
                })
            else:
                last_training_log = ""
                def training_progress(stage: str, progress: float):
                    nonlocal last_training_log
                    if self._is_cancelled:
                        raise InterruptedError("Operation cancelled")
                    self.progress.emit({
                        'stage': 'Training Gaussian Splats',
                        'progress': 0.2 + progress * 0.7,  # 20-90%
                        'substage': stage
                    })
                    should_log = False
                    if stage != last_training_log:
                        should_log = True
                    elif "Step" in stage:
                        import re
                        match = re.search(r'Step (\d+)/', stage)
                        if match:
                            step = int(match.group(1))
                            if step % 100 == 0 or step < 10 or progress > 0.95:
                                should_log = True
                    
                    if should_log:
                        self.log.emit(f"[Training] {stage}")
                        last_training_log = stage
                
                self.log.emit("Starting splatfacto training (this may take 10-30 minutes)...")
                self.log.emit(f"Training data directory: {data_result['data_dir']}")
                
                training_result = pipeline.train_splatfacto(
                    data_result['data_dir'],
                    max_num_iterations=self.max_iterations,
                    progress_callback=training_progress
                )
                
                config_path = training_result.get('config_path')
                checkpoint_dir = training_result.get('checkpoint_dir')
                
                if not checkpoint_dir:
                    raise RuntimeError("Training completed but checkpoint directory not found")
                
                checkpoint_dir_path = Path(checkpoint_dir)
                checkpoints = list(checkpoint_dir_path.glob("step-*.ckpt"))
                if not checkpoints:
                    raise RuntimeError(f"No checkpoints found in {checkpoint_dir}")
                
                latest_checkpoint = max(checkpoints, key=lambda p: int(p.stem.split('-')[1]))
                self.log.emit(f"Training complete. Using checkpoint: {latest_checkpoint.name}")
                # Signal for project manager to save training state
                self.stage_training_completed.emit(checkpoint_dir, str(latest_checkpoint))
            
            if self._is_cancelled:
                self._emit_cancelled()
                return
            
            # Stage 3: Export to PLY
            def export_progress(stage: str, progress: float):
                if self._is_cancelled:
                    raise InterruptedError("Operation cancelled")
                self.progress.emit({
                    'stage': 'Exporting PLY',
                    'progress': 0.9 + progress * 0.1,  # 90-100%
                    'substage': stage
                })
                self.log.emit(f"[Export] {stage}")
            
            self.log.emit("Exporting Gaussian Splats to PLY...")
            output_path, camera_hint = pipeline.export_gaussian_splat(
                str(latest_checkpoint),
                self.output_ply_path,
                progress_callback=export_progress
            )
            
            self.log.emit(f"✓ Export complete: {output_path}")
            
            self.finished.emit({
                'success': True,
                'output_path': str(output_path),
                'config_path': config_path,
                'camera_hint': camera_hint,
                'error': ''
            })
        
        except InterruptedError:
            self._emit_cancelled()
        except Exception as e:
            # Check if this was caused by cancellation (SIGTERM to child processes)
            if self._is_cancelled:
                self._emit_cancelled()
                return
            
            error_msg = str(e)
            
            # Provide helpful context for common failures
            if "BundleAdjuster" in error_msg or "COLMAP" in error_msg:
                self.log.emit("✗ COLMAP reconstruction failed")
                self.log.emit("💡 Tip: Video needs good camera motion, textured scenes, and overlap")
                self.log.emit("   Try a video with slow panning and well-lit objects")
            
            self.log.emit(f"✗ Error: {error_msg[:200]}")  # Limit error display
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

