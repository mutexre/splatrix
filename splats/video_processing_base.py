"""Base classes for video processing implementations"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Callable, Dict


class BaseVideoProcessor(ABC):
    """
    Abstract base for video-to-frames-to-SfM processing.
    Implementations can use different approaches (nerfstudio, PyAV, etc.)
    """
    
    def __init__(self):
        self._is_cancelled = False
    
    @abstractmethod
    def process_video(
        self,
        video_path: str,
        output_dir: Path,
        num_frames_target: int = 300,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict[str, any]:
        """
        Process video: extract frames and run Structure from Motion
        
        Args:
            video_path: Path to input video
            output_dir: Directory for output (images/, colmap/, transforms.json)
            num_frames_target: Target number of frames to extract
            progress_callback: Callback(stage_description, progress_0_to_1)
        
        Returns:
            Dictionary with:
                - data_dir: str - output directory
                - transforms_path: str - path to transforms.json
                - images_dir: str - directory with extracted frames
                - frame_count: int - number of frames extracted
        
        Raises:
            InterruptedError: If cancel() was called during processing
            RuntimeError: On processing errors
        """
        pass
    
    @abstractmethod
    def cancel(self) -> None:
        """
        Request cancellation of current processing.
        Implementation should check _is_cancelled flag and raise InterruptedError.
        """
        pass
    
    @abstractmethod
    def get_video_info(self, video_path: str) -> Dict[str, any]:
        """
        Get video metadata without processing
        
        Args:
            video_path: Path to video file
        
        Returns:
            Dictionary with:
                - width: int
                - height: int
                - fps: float
                - frame_count: int
                - duration: float (seconds)
        """
        pass


class ProcessingConfig:
    """Configuration for video processing"""
    
    def __init__(
        self,
        num_frames_target: int = 300,
        camera_type: str = "perspective",
        matching_method: str = "sequential",
        gpu: bool = True,
        feature_type: str = "sift",  # For COLMAP
        matcher_type: str = "sequential"  # exhaustive, sequential, vocab_tree
    ):
        self.num_frames_target = num_frames_target
        self.camera_type = camera_type
        self.matching_method = matching_method
        self.gpu = gpu
        self.feature_type = feature_type
        self.matcher_type = matcher_type

