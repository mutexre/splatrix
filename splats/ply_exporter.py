"""PLY file export functionality"""

from pathlib import Path
from typing import Optional
import numpy as np
from plyfile import PlyData, PlyElement


class PLYExporter:
    """Export Gaussian Splats to PLY format"""
    
    @staticmethod
    def create_gaussian_splat_ply(
        positions: np.ndarray,
        colors: np.ndarray,
        scales: Optional[np.ndarray] = None,
        rotations: Optional[np.ndarray] = None,
        opacities: Optional[np.ndarray] = None,
        output_path: str = "output.ply"
    ) -> Path:
        """
        Create PLY file with Gaussian Splat data
        
        Args:
            positions: Nx3 array of 3D positions
            colors: Nx3 array of RGB colors (0-255)
            scales: Nx3 array of scale parameters
            rotations: Nx4 array of quaternion rotations
            opacities: Nx1 array of opacity values
            output_path: Output PLY file path
        
        Returns:
            Path to created PLY file
        """
        num_points = len(positions)
        
        # Default values if not provided
        if scales is None:
            scales = np.ones((num_points, 3)) * 0.01
        if rotations is None:
            rotations = np.zeros((num_points, 4))
            rotations[:, 0] = 1.0  # Identity quaternion
        if opacities is None:
            opacities = np.ones((num_points, 1))
        
        # Create structured array for PLY
        dtype = [
            ('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
            ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),  # Normals (dummy)
            ('red', 'u1'), ('green', 'u1'), ('blue', 'u1'),
            ('scale_0', 'f4'), ('scale_1', 'f4'), ('scale_2', 'f4'),
            ('rot_0', 'f4'), ('rot_1', 'f4'), ('rot_2', 'f4'), ('rot_3', 'f4'),
            ('opacity', 'f4')
        ]
        
        vertex_data = np.zeros(num_points, dtype=dtype)
        vertex_data['x'] = positions[:, 0]
        vertex_data['y'] = positions[:, 1]
        vertex_data['z'] = positions[:, 2]
        vertex_data['nx'] = 0.0
        vertex_data['ny'] = 0.0
        vertex_data['nz'] = 1.0
        vertex_data['red'] = colors[:, 0].astype(np.uint8)
        vertex_data['green'] = colors[:, 1].astype(np.uint8)
        vertex_data['blue'] = colors[:, 2].astype(np.uint8)
        vertex_data['scale_0'] = scales[:, 0]
        vertex_data['scale_1'] = scales[:, 1]
        vertex_data['scale_2'] = scales[:, 2]
        vertex_data['rot_0'] = rotations[:, 0]
        vertex_data['rot_1'] = rotations[:, 1]
        vertex_data['rot_2'] = rotations[:, 2]
        vertex_data['rot_3'] = rotations[:, 3]
        vertex_data['opacity'] = opacities.flatten()
        
        # Create PLY element and write
        vertex_element = PlyElement.describe(vertex_data, 'vertex')
        ply_data = PlyData([vertex_element])
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        ply_data.write(str(output_file))
        
        return output_file
    
    @staticmethod
    def create_point_cloud_ply(
        positions: np.ndarray,
        colors: np.ndarray,
        output_path: str = "pointcloud.ply"
    ) -> Path:
        """
        Create simple point cloud PLY file
        
        Args:
            positions: Nx3 array of 3D positions
            colors: Nx3 array of RGB colors (0-255)
            output_path: Output PLY file path
        
        Returns:
            Path to created PLY file
        """
        num_points = len(positions)
        
        dtype = [
            ('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
            ('red', 'u1'), ('green', 'u1'), ('blue', 'u1')
        ]
        
        vertex_data = np.zeros(num_points, dtype=dtype)
        vertex_data['x'] = positions[:, 0]
        vertex_data['y'] = positions[:, 1]
        vertex_data['z'] = positions[:, 2]
        vertex_data['red'] = colors[:, 0].astype(np.uint8)
        vertex_data['green'] = colors[:, 1].astype(np.uint8)
        vertex_data['blue'] = colors[:, 2].astype(np.uint8)
        
        vertex_element = PlyElement.describe(vertex_data, 'vertex')
        ply_data = PlyData([vertex_element])
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        ply_data.write(str(output_file))
        
        return output_file

