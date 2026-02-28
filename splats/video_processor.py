"""Video frame extraction module"""

from pathlib import Path
from typing import Optional, Callable, Dict
import cv2
import numpy as np

try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False


class VideoProcessor:
    """Extract frames from video files"""
    
    def __init__(self):
        self.video_path: Optional[Path] = None
        self.frame_count: int = 0
        self.fps: float = 0.0
        self.duration: float = 0.0
        self.resolution: tuple[int, int] = (0, 0)
    
    def get_video_info(self, video_path: str) -> Dict[str, any]:
        """
        Get video metadata using PyAV (preferred) or OpenCV fallback
        
        Returns:
            Dictionary with: width, height, fps, frame_count, duration, codec
        """
        video_path = Path(video_path)
        
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        
        # Try PyAV first (more accurate)
        if PYAV_AVAILABLE:
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
                # Fall through to OpenCV if PyAV fails
                print(f"PyAV failed, using OpenCV fallback: {e}")
        
        # OpenCV fallback
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = frame_count / fps if fps > 0 else 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        cap.release()
        
        return {
            'width': width,
            'height': height,
            'fps': fps,
            'frame_count': frame_count,
            'duration': duration,
            'codec': 'unknown',
            'path': str(video_path)
        }
    
    def load_video(self, video_path: str) -> dict:
        """Load video and extract metadata (legacy interface)"""
        info = self.get_video_info(video_path)
        
        # Update instance variables
        self.video_path = Path(video_path)
        self.frame_count = info['frame_count']
        self.fps = info['fps']
        self.duration = info['duration']
        self.resolution = (info['width'], info['height'])
        
        # Return legacy format
        return {
            'frame_count': self.frame_count,
            'fps': self.fps,
            'duration': self.duration,
            'resolution': self.resolution,
            'path': str(self.video_path)
        }
    
    def extract_frames(
        self,
        output_dir: str,
        sample_rate: int = 1,
        max_frames: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> list[Path]:
        """
        Extract frames from video
        
        Args:
            output_dir: Output directory for frames
            sample_rate: Extract every Nth frame (1 = all frames)
            max_frames: Maximum number of frames to extract
            progress_callback: Callback function(current, total)
        
        Returns:
            List of extracted frame paths
        """
        if not self.video_path:
            raise ValueError("No video loaded. Call load_video() first.")
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        cap = cv2.VideoCapture(str(self.video_path))
        frame_paths: list[Path] = []
        frame_idx = 0
        extracted_count = 0
        
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Sample frames based on sample_rate
                if frame_idx % sample_rate == 0:
                    frame_filename = output_path / f"frame_{extracted_count:06d}.png"
                    cv2.imwrite(str(frame_filename), frame)
                    frame_paths.append(frame_filename)
                    extracted_count += 1
                    
                    if progress_callback:
                        progress_callback(extracted_count, 
                                        min(max_frames or self.frame_count, 
                                            self.frame_count // sample_rate))
                    
                    if max_frames and extracted_count >= max_frames:
                        break
                
                frame_idx += 1
        
        finally:
            cap.release()
        
        return frame_paths
    
    def get_frame_at(self, frame_number: int) -> Optional[np.ndarray]:
        """Get specific frame from video"""
        if not self.video_path:
            return None
        
        cap = cv2.VideoCapture(str(self.video_path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        cap.release()
        
        return frame if ret else None

