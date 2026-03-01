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

try:
    from nerfstudio.scripts.process_data import VideoToNerfstudioDataset
    NERFSTUDIO_AVAILABLE = True
except ImportError:
    NERFSTUDIO_AVAILABLE = False


class NerfstudioVideoProcessor(BaseVideoProcessor):
    """
    Video processor using nerfstudio's integrated pipeline.
    Uses nerfstudio's VideoToNerfstudioDataset + pycolmap for SfM.
    """
    
    def __init__(self, config: Optional[ProcessingConfig] = None):
        super().__init__()
        if not NERFSTUDIO_AVAILABLE:
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
        
        # Setup nerfstudio VideoToNerfstudioDataset
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
        
        # Hook print and stderr for progress tracking
        # COLMAP C++ extension writes to stderr FD directly, need to capture at OS level
        import os
        import select
        
        original_print = print
        original_stderr_fd = os.dup(2)  # Duplicate stderr FD
        
        # Create pipe for stderr capture
        stderr_pipe_read, stderr_pipe_write = os.pipe()
        os.dup2(stderr_pipe_write, 2)  # Redirect stderr FD to pipe
        
        # Make read end non-blocking
        import fcntl
        flags = fcntl.fcntl(stderr_pipe_read, fcntl.F_GETFL)
        fcntl.fcntl(stderr_pipe_read, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        stderr_buffer = []
        
        def process_stderr_line(line: str):
            """Process captured stderr line for progress"""
            if self._is_cancelled:
                raise InterruptedError("Processing cancelled")
            
            # Write to original stderr
            os.write(original_stderr_fd, (line + '\n').encode())
            
            if not progress_callback:
                return
            
            # Parse for progress
            # Feature extraction: "Processed file [N/M]"
            if "Processed file" in line:
                # Debug: log that we caught this message
                try:
                    os.write(original_stderr_fd, f"[DEBUG] Caught feature extraction: {line}\n".encode())
                except:
                    pass
                
                match = re.search(r'\[(\d+)/(\d+)\]', line)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    if last_reported['feature_extract'] != current:
                        progress = 0.15 + (current / total) * 0.15
                        progress_callback(f"COLMAP: Extracting features [{current}/{total}]", progress)
                        last_reported['feature_extract'] = current
            
            # Feature matching: "Processing image [N/M]"
            elif "Processing image" in line and "[" in line:
                match = re.search(r'\[(\d+)/(\d+)\]', line)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    if last_reported['matching'] != current:
                        progress = 0.30 + (current / total) * 0.20
                        progress_callback(f"COLMAP: Matching features [{current}/{total}]", progress)
                        last_reported['matching'] = current
            
            # Reconstruction phases
            elif "Registering image" in line:
                match = re.search(r'num_reg_frames=(\d+)', line)
                if match:
                    num_reg = int(match.group(1))
                    progress = 0.50 + (num_reg / 350) * 0.30
                    progress_callback(f"COLMAP: Reconstruction [{num_reg} images]", progress)
            
            # Completion stages
            elif "Done extracting" in line and "features" not in line.lower():
                progress_callback("Frame extraction complete", 0.15)
            elif "Done extracting" in line and "features" in line.lower():
                progress_callback("Feature extraction complete", 0.30)
            elif "Done matching" in line and "feature" in line.lower():
                progress_callback("Feature matching complete", 0.50)
            elif "Done" in line and "bundle adjustment" in line:
                progress_callback("Bundle adjustment complete", 0.80)
            elif "Done refining" in line:
                progress_callback("Refining intrinsics complete", 0.90)
            elif "All DONE" in line or "CONGRATS" in line:
                progress_callback("COLMAP processing complete", 0.95)
        
        def progress_print(*args, **kwargs):
            """Capture print statements for progress"""
            if self._is_cancelled:
                raise InterruptedError("Processing cancelled")
            
            msg = ' '.join(str(arg) for arg in args)
            process_stderr_line(msg)
            original_print(*args, **kwargs)
        
        builtins.print = progress_print
        
        # Start stderr reader thread
        def read_stderr():
            """Read from stderr pipe and process lines"""
            # Debug: Signal that stderr reader is active
            try:
                os.write(original_stderr_fd, b"[DEBUG] stderr reader thread started\n")
            except:
                pass
            
            while self._monitor_active[0]:
                try:
                    # Check if data available (with timeout)
                    ready, _, _ = select.select([stderr_pipe_read], [], [], 0.1)
                    if ready:
                        data = os.read(stderr_pipe_read, 4096)
                        if data:
                            text = data.decode('utf-8', errors='replace')
                            # Accumulate in buffer and process complete lines
                            stderr_buffer.append(text)
                            full_text = ''.join(stderr_buffer)
                            
                            # Split by newlines
                            lines = full_text.split('\n')
                            # Keep last incomplete line in buffer
                            stderr_buffer.clear()
                            if not full_text.endswith('\n'):
                                stderr_buffer.append(lines[-1])
                                lines = lines[:-1]
                            
                            # Process complete lines
                            for line in lines:
                                line = line.strip()
                                if line:
                                    process_stderr_line(line)
                except Exception as e:
                    # Log errors but don't crash - stderr capture is non-critical
                    import traceback
                    error_msg = f"stderr reader error: {e}\n{traceback.format_exc()}"
                    # Write to original stderr FD to avoid recursion
                    try:
                        os.write(original_stderr_fd, error_msg.encode())
                    except:
                        pass
        
        stderr_reader = threading.Thread(target=read_stderr, daemon=True)
        stderr_reader.start()
        
        try:
            # Run nerfstudio processing
            processor.main()
            
            if progress_callback:
                progress_callback("Video processing complete", 1.0)
        
        finally:
            # Stop monitoring threads
            self._monitor_active[0] = False
            if self._monitor_thread:
                self._monitor_thread.join(timeout=2)
            stderr_reader.join(timeout=2)
            
            # Restore stderr file descriptor
            os.dup2(original_stderr_fd, 2)
            os.close(original_stderr_fd)
            os.close(stderr_pipe_read)
            os.close(stderr_pipe_write)
            
            # Restore original functions
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

