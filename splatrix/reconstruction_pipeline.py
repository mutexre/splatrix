"""3D reconstruction and Gaussian Splatting pipeline"""

from pathlib import Path
from typing import Optional, Callable, Literal
import subprocess
import json
import numpy as np


class ReconstructionPipeline:
    """
    Pipeline for 3D reconstruction from video frames.
    Supports COLMAP and future integration with nerfstudio.
    """
    
    def __init__(self):
        self.workspace_dir: Optional[Path] = None
        self.method: Literal["colmap", "instant-ngp", "mock"] = "mock"
    
    def setup_workspace(self, workspace_dir: str) -> Path:
        """Setup workspace directory for reconstruction"""
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (self.workspace_dir / "images").mkdir(exist_ok=True)
        (self.workspace_dir / "sparse").mkdir(exist_ok=True)
        (self.workspace_dir / "dense").mkdir(exist_ok=True)
        (self.workspace_dir / "output").mkdir(exist_ok=True)
        
        return self.workspace_dir
    
    def check_colmap_installed(self) -> bool:
        """Check if COLMAP is installed and accessible"""
        try:
            result = subprocess.run(
                ["colmap", "-h"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def run_colmap_sfm(
        self,
        image_dir: str,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> dict:
        """
        Run COLMAP Structure from Motion
        
        Args:
            image_dir: Directory containing input images
            progress_callback: Callback function(stage, progress)
        
        Returns:
            Dictionary with reconstruction results
        """
        if not self.workspace_dir:
            raise ValueError("Workspace not setup. Call setup_workspace() first.")
        
        if not self.check_colmap_installed():
            raise RuntimeError("COLMAP not found. Please install COLMAP.")
        
        database_path = self.workspace_dir / "database.db"
        sparse_path = self.workspace_dir / "sparse"
        
        stages = [
            ("Feature extraction", ["colmap", "feature_extractor",
                                   "--database_path", str(database_path),
                                   "--image_path", image_dir]),
            ("Feature matching", ["colmap", "exhaustive_matcher",
                                 "--database_path", str(database_path)]),
            ("Sparse reconstruction", ["colmap", "mapper",
                                      "--database_path", str(database_path),
                                      "--image_path", image_dir,
                                      "--output_path", str(sparse_path)])
        ]
        
        for i, (stage_name, cmd) in enumerate(stages):
            if progress_callback:
                progress_callback(stage_name, i / len(stages))
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"COLMAP {stage_name} failed: {result.stderr}")
        
        if progress_callback:
            progress_callback("Complete", 1.0)
        
        return {
            'sparse_path': str(sparse_path),
            'database_path': str(database_path)
        }
    
    def create_mock_gaussian_splats(
        self,
        frame_paths: list[Path],
        num_points: int = 10000,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> dict:
        """
        Create mock Gaussian Splats for testing (no external dependencies)
        
        Args:
            frame_paths: List of frame image paths
            num_points: Number of splat points to generate
            progress_callback: Callback function(stage, progress)
        
        Returns:
            Dictionary with splat data arrays
        """
        if progress_callback:
            progress_callback("Generating mock splats", 0.0)
        
        # Create random 3D points in a reasonable space
        np.random.seed(42)
        positions = np.random.randn(num_points, 3) * 2.0
        
        if progress_callback:
            progress_callback("Generating colors", 0.3)
        
        # Random colors
        colors = np.random.randint(0, 255, size=(num_points, 3), dtype=np.uint8)
        
        if progress_callback:
            progress_callback("Generating parameters", 0.6)
        
        # Scales, rotations, opacities
        scales = np.random.rand(num_points, 3) * 0.05 + 0.01
        rotations = np.zeros((num_points, 4))
        rotations[:, 0] = 1.0  # Identity quaternion
        opacities = np.random.rand(num_points, 1) * 0.5 + 0.5
        
        if progress_callback:
            progress_callback("Complete", 1.0)
        
        return {
            'positions': positions,
            'colors': colors,
            'scales': scales,
            'rotations': rotations,
            'opacities': opacities,
            'num_points': num_points
        }
    
    def export_transforms_json(self, output_path: str) -> Path:
        """Export camera transforms for nerfstudio (future implementation)"""
        transforms = {
            "camera_model": "OPENCV",
            "frames": []
        }
        
        output_file = Path(output_path)
        with open(output_file, 'w') as f:
            json.dump(transforms, f, indent=2)
        
        return output_file

