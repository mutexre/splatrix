"""Nerfstudio integration for Splatrix - Python API"""

from pathlib import Path
from typing import Optional, Callable, Literal
import os
import shutil

# Import video processors
from .video_processing_base import ProcessingConfig
from .nerfstudio_video_processor import NerfstudioVideoProcessor
try:
    from .pyav_video_processor import PyAVVideoProcessor
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False

from .training_backend import TrainingBackend

def _nerfstudio_available() -> bool:
    """Check at call time whether nerfstudio is importable."""
    try:
        import nerfstudio  # noqa: F401
        return True
    except ImportError:
        return False


class NerfstudioPipeline:
    """
    Integration with nerfstudio for video processing and Gaussian Splatting.
    Data processing always uses nerfstudio (COLMAP).
    Training/export delegate to the best available backend (nerfstudio or msplat).
    """
    
    def __init__(
        self, 
        video_processor: Literal["nerfstudio", "pyav", "auto"] = "auto",
        processing_config: Optional[ProcessingConfig] = None
    ):
        self.workspace_dir: Optional[Path] = None
        self.data_dir: Optional[Path] = None
        self.output_dir: Optional[Path] = None
        self._training_backend: Optional[TrainingBackend] = None
        
        self.processing_config = processing_config or ProcessingConfig()
        
        if video_processor == "auto":
            video_processor = "nerfstudio" if _nerfstudio_available() else "pyav"

        if video_processor == "pyav":
            if not PYAV_AVAILABLE:
                raise ImportError("PyAV processor requested but not available. Install with: pip install av")
            self.video_processor = PyAVVideoProcessor(self.processing_config)
        else:
            self.video_processor = NerfstudioVideoProcessor(self.processing_config)

    @property
    def training_backend(self) -> TrainingBackend:
        if self._training_backend is None:
            self._training_backend = TrainingBackend.auto_select()
            print(f"[Pipeline] Selected training backend: {self._training_backend.name}")
        return self._training_backend
    
    def check_nerfstudio_installed(self) -> bool:
        """Check if nerfstudio is installed"""
        return _nerfstudio_available()
    
    def setup_workspace(self, workspace_dir: str) -> dict:
        """Setup workspace directory structure"""
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        
        self.data_dir = self.workspace_dir / "nerfstudio_data"
        self.output_dir = self.workspace_dir / "outputs"
        
        self.data_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)
        
        return {
            'workspace': str(self.workspace_dir),
            'data': str(self.data_dir),
            'output': str(self.output_dir)
        }
    
    def process_video_data(
        self,
        video_path: str,
        num_frames_target: int = 300,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> dict:
        """
        Process video using selected video processor implementation
        
        Args:
            video_path: Path to input video
            num_frames_target: Target number of frames to extract
            progress_callback: Callback(stage, progress)
        
        Returns:
            Dictionary with processed data paths
        """
        if not self.data_dir:
            raise ValueError("Workspace not setup. Call setup_workspace() first.")
        
        # Delegate to video processor implementation
        return self.video_processor.process_video(
            video_path=video_path,
            output_dir=self.data_dir,
            num_frames_target=num_frames_target,
            progress_callback=progress_callback
        )
    
    def process_images_data(
        self,
        images_dir: str,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> dict:
        """
        Process pre-extracted images with nerfstudio
        
        Args:
            images_dir: Directory containing extracted frames
            progress_callback: Callback(stage, progress)
        
        Returns:
            Dictionary with processed data paths
        """
        if not self.workspace_dir:
            raise ValueError("Workspace not setup. Call setup_workspace() first.")
        
        # Clean COLMAP directory to prevent stale reconstruction data
        colmap_dir = self.data_dir / "colmap"
        if colmap_dir.exists():
            shutil.rmtree(colmap_dir)
        colmap_dir.mkdir(parents=True)
        
        if progress_callback:
            progress_callback("Processing images with COLMAP", 0.1)
        
        from nerfstudio.scripts.process_data import ImagesToNerfstudioDataset
        processor = ImagesToNerfstudioDataset(
            data=Path(images_dir),
            output_dir=self.data_dir,
            camera_type="perspective",
            matching_method="sequential",
            sfm_tool="any",  # Uses pycolmap
            skip_colmap=False,
            gpu=True,
            verbose=True
        )
        
        # Similar progress tracking as video processing
        original_print = print
        def progress_print(*args, **kwargs):
            msg = ' '.join(str(arg) for arg in args)
            if progress_callback:
                if "feature" in msg.lower() and "extract" in msg.lower():
                    progress_callback("COLMAP: Extracting features", 0.3)
                elif "match" in msg.lower():
                    progress_callback("COLMAP: Matching features", 0.5)
                elif "mapper" in msg.lower():
                    progress_callback("COLMAP: Sparse reconstruction", 0.7)
                elif "undistort" in msg.lower():
                    progress_callback("Finalizing", 0.9)
            original_print(*args, **kwargs)
        
        import builtins
        builtins.print = progress_print
        
        try:
            processor.main()
            if progress_callback:
                progress_callback("Image processing complete", 1.0)
        finally:
            builtins.print = original_print
        
        transforms_path = self.data_dir / "transforms.json"
        
        return {
            'data_dir': str(self.data_dir),
            'transforms_path': str(transforms_path) if transforms_path.exists() else None
        }
    
    def train_splatfacto(
        self,
        data_dir: str,
        max_num_iterations: int = 30000,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> dict:
        """Train Gaussian Splatting model via the auto-selected backend."""
        backend = self.training_backend
        output_dir = str(self.output_dir) if self.output_dir else str(Path(data_dir).parent / "outputs")

        result = backend.train(
            data_dir=data_dir,
            output_dir=output_dir,
            max_iterations=max_num_iterations,
            progress_callback=progress_callback,
        )

        self._last_training_result = result
        return {
            'output_dir': result.output_dir,
            'config_path': result.config_path,
            'checkpoint_dir': result.checkpoint_dir,
        }

    def export_gaussian_splat(
        self,
        checkpoint_path: str,
        output_ply_path: str,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Path:
        """Export trained model to PLY via the active backend."""
        backend = self.training_backend

        if hasattr(self, '_last_training_result') and self._last_training_result:
            return backend.export_ply(
                self._last_training_result, output_ply_path, progress_callback
            )

        # Fallback: build a minimal TrainingResult from the checkpoint path
        from .training_backend import TrainingResult
        result = TrainingResult(
            output_dir=str(Path(checkpoint_path).parent.parent),
            checkpoint_dir=str(Path(checkpoint_path).parent),
            checkpoint_path=checkpoint_path,
        )
        return backend.export_ply(result, output_ply_path, progress_callback)
    
    def get_method_info(self) -> dict:
        """Get information about available methods"""
        return {
            'splatfacto': {
                'name': 'Splatfacto (Gaussian Splatting)',
                'description': '3D Gaussian Splatting - fast training and rendering',
                'requires_gpu': True,
                'typical_time': '10-30 minutes',
                'output_format': 'PLY'
            },
            'nerfacto': {
                'name': 'Nerfacto (NeRF)',
                'description': 'Neural Radiance Fields - high quality',
                'requires_gpu': True,
                'typical_time': '30-60 minutes',
                'output_format': 'Various'
            }
        }
