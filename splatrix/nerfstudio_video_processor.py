"""Nerfstudio-based video processor implementation"""

from pathlib import Path
from typing import Optional, Callable, Dict
import shutil
import threading
import time
import sys
import re
import builtins

from .video_processing_base import BaseVideoProcessor, ProcessingConfig

class NerfstudioVideoProcessor(BaseVideoProcessor):
    """
    Video processor using nerfstudio's integrated pipeline.
    Uses nerfstudio's VideoToNerfstudioDataset + pycolmap for SfM.
    """
    
    def __init__(self, config: Optional[ProcessingConfig] = None):
        super().__init__()
        try:
            from nerfstudio.scripts.process_data import VideoToNerfstudioDataset  # noqa: F401
        except ImportError:
            raise ImportError("nerfstudio not installed. Install with: pip install nerfstudio")
        
        self.config = config or ProcessingConfig()
        self._monitor_active = [False]
        self._monitor_thread = None
    
    def cancel(self) -> None:
        """Request cancellation"""
        self._is_cancelled = True
        if self._monitor_thread:
            self._monitor_active[0] = False
    
    def get_video_info(self, video_path: str) -> Dict[str, any]:
        """Get video metadata using PyAV (ffmpeg Python bindings)"""
        try:
            import av
        except ImportError:
            raise ImportError("PyAV not installed. Install with: pip install av")
        
        video_path = Path(video_path)
        
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        
        try:
            with av.open(str(video_path)) as container:
                video_stream = container.streams.video[0]
                
                width = video_stream.width
                height = video_stream.height
                
                # FPS calculation
                fps = float(video_stream.average_rate)
                
                # Frame count
                frame_count = video_stream.frames
                if frame_count == 0:
                    # Estimate from duration if frames not available
                    duration = float(video_stream.duration * video_stream.time_base)
                    frame_count = int(duration * fps)
                
                duration = float(video_stream.duration * video_stream.time_base) if video_stream.duration else frame_count / fps
                
                codec = video_stream.codec_context.name
                
                return {
                    'width': width,
                    'height': height,
                    'fps': fps,
                    'frame_count': frame_count,
                    'duration': duration,
                    'codec': codec,
                    'path': str(video_path)
                }
        except Exception as e:
            raise RuntimeError(f"Failed to get video info using PyAV: {e}")
    
    def process_video(
        self,
        video_path: str,
        output_dir: Path,
        num_frames_target: int = 300,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict[str, any]:
        """Process video using nerfstudio pipeline"""
        
        # Clean workspace to prevent stale data
        images_dir = output_dir / "images"
        colmap_dir = output_dir / "colmap"
        
        if images_dir.exists():
            shutil.rmtree(images_dir)
        images_dir.mkdir(parents=True)
        
        if colmap_dir.exists():
            shutil.rmtree(colmap_dir)
        colmap_dir.mkdir(parents=True)
        
        if progress_callback:
            progress_callback("Preparing for frame extraction", 0.02)
        
        # Start frame count monitoring thread
        self._monitor_active[0] = True
        last_reported = {'frame': 0, 'feature_extract': 0, 'matching': 0}
        
        def monitor_frames():
            """Monitor images directory for frame count"""
            last_count = 0
            while self._monitor_active[0]:
                try:
                    if self._is_cancelled:
                        return
                    
                    if images_dir.exists():
                        frame_files = list(images_dir.glob("frame_*.png"))
                        count = len(frame_files)
                        if count > last_count and progress_callback:
                            progress_callback(f"Extracting frames: {count}", 0.05 + (count / 500) * 0.10)
                            last_count = count
                    time.sleep(0.5)  # Check every 500ms
                except Exception:
                    pass
        
        self._monitor_thread = threading.Thread(target=monitor_frames, daemon=True)
        self._monitor_thread.start()
        
        from nerfstudio.scripts.process_data import VideoToNerfstudioDataset
        processor = VideoToNerfstudioDataset(
            data=Path(video_path),
            output_dir=output_dir,
            num_frames_target=num_frames_target,
            camera_type=self.config.camera_type,
            matching_method=self.config.matching_method,
            sfm_tool="any",  # Uses pycolmap
            skip_colmap=False,
            gpu=self.config.gpu,
            verbose=True
        )

        original_print = print

        def _parse_progress(msg: str):
            """Extract progress from nerfstudio print output."""
            if not progress_callback:
                return
            if "Processed file" in msg:
                m = re.search(r'\[(\d+)/(\d+)\]', msg)
                if m:
                    cur, tot = int(m.group(1)), int(m.group(2))
                    if last_reported['feature_extract'] != cur:
                        progress_callback(f"COLMAP: Extracting features [{cur}/{tot}]",
                                          0.15 + (cur / tot) * 0.15)
                        last_reported['feature_extract'] = cur
            elif "Processing image" in msg and "[" in msg:
                m = re.search(r'\[(\d+)/(\d+)\]', msg)
                if m:
                    cur, tot = int(m.group(1)), int(m.group(2))
                    if last_reported['matching'] != cur:
                        progress_callback(f"COLMAP: Matching features [{cur}/{tot}]",
                                          0.30 + (cur / tot) * 0.20)
                        last_reported['matching'] = cur
            elif "Registering image" in msg:
                m = re.search(r'num_reg_frames=(\d+)', msg)
                if m:
                    progress_callback(f"COLMAP: Reconstruction [{m.group(1)} images]",
                                      0.50 + (int(m.group(1)) / 350) * 0.30)
            elif "All DONE" in msg or "CONGRATS" in msg:
                progress_callback("COLMAP processing complete", 0.95)

        def progress_print(*args, **kwargs):
            if self._is_cancelled:
                raise InterruptedError("Processing cancelled")
            msg = ' '.join(str(a) for a in args)
            _parse_progress(msg)
            original_print(*args, **kwargs)

        builtins.print = progress_print

        try:
            processor.main()
            if progress_callback:
                progress_callback("Video processing complete", 1.0)
        finally:
            self._monitor_active[0] = False
            if self._monitor_thread:
                self._monitor_thread.join(timeout=2)
            builtins.print = original_print
        
        # Find transforms.json
        transforms_path = output_dir / "transforms.json"
        if not transforms_path.exists():
            possible = list(output_dir.rglob("transforms.json"))
            if possible:
                transforms_path = possible[0]
        
        # Count extracted frames
        frame_files = list(images_dir.glob("frame_*.png")) if images_dir.exists() else []
        
        return {
            'data_dir': str(output_dir),
            'transforms_path': str(transforms_path) if transforms_path.exists() else None,
            'images_dir': str(images_dir),
            'frame_count': len(frame_files)
        }

