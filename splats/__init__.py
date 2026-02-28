"""Video to Gaussian Splats Converter"""

__version__ = "0.1.0"

# Video processing interfaces
from .video_processing_base import BaseVideoProcessor, ProcessingConfig
from .nerfstudio_video_processor import NerfstudioVideoProcessor

# Optional PyAV processor
try:
    from .pyav_video_processor import PyAVVideoProcessor
except ImportError:
    PyAVVideoProcessor = None

# Pipeline
from .nerfstudio_integration import NerfstudioPipeline

__all__ = [
    'BaseVideoProcessor',
    'ProcessingConfig',
    'NerfstudioVideoProcessor',
    'PyAVVideoProcessor',
    'NerfstudioPipeline',
]

