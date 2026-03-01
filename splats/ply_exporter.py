"""PLY file export functionality"""

from pathlib import Path
from typing import Optional
import numpy as np
from plyfile import PlyData, PlyElement


class PLYExporter:
    """Export Gaussian Splats to PLY format (INRIA-compatible)"""

    @staticmethod
    def create_gaussian_splat_ply(
        positions: np.ndarray,
        colors_sh_dc: np.ndarray,
        scales_log: np.ndarray,
        rotations: np.ndarray,
        opacities_logit: np.ndarray,
        output_path: str = "output.ply",
        sh_rest: Optional[np.ndarray] = None,
    ) -> Path:
        """
        Create PLY file with Gaussian Splat data in INRIA-compatible format.

        All values should be in RAW (pre-activation) space:
        - scales_log: log-space scales (viewer applies exp())
        - opacities_logit: logit-space opacities (viewer applies sigmoid())
        - colors_sh_dc: SH DC coefficients (viewer converts to RGB)

        Args:
            positions: Nx3 array of 3D positions
            colors_sh_dc: Nx3 array of SH DC color coefficients (raw, NOT RGB)
            scales_log: Nx3 array of log-scale parameters (raw, NOT exp'd)
            rotations: Nx4 array of quaternion rotations (normalized)
            opacities_logit: Nx1 array of logit opacity (raw, NOT sigmoid'd)
            output_path: Output PLY file path
            sh_rest: Optional Nx(K*3) array of higher-order SH coefficients

        Returns:
            Path to created PLY file
        """
        num_points = len(positions)

        # Number of higher-order SH coefficients (0, 9, or 24 per channel)
        n_sh_rest = sh_rest.shape[1] if sh_rest is not None else 0

        # Build dtype: INRIA standard property names
        props = [
            ('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
            ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
            ('f_dc_0', 'f4'), ('f_dc_1', 'f4'), ('f_dc_2', 'f4'),
        ]

        # Add SH rest coefficients
        for i in range(n_sh_rest):
            props.append((f'f_rest_{i}', 'f4'))

        props += [
            ('opacity', 'f4'),
            ('scale_0', 'f4'), ('scale_1', 'f4'), ('scale_2', 'f4'),
            ('rot_0', 'f4'), ('rot_1', 'f4'), ('rot_2', 'f4'), ('rot_3', 'f4'),
        ]

        vertex_data = np.zeros(num_points, dtype=props)
        vertex_data['x'] = positions[:, 0]
        vertex_data['y'] = positions[:, 1]
        vertex_data['z'] = positions[:, 2]
        vertex_data['nx'] = 0.0
        vertex_data['ny'] = 0.0
        vertex_data['nz'] = 0.0

        # SH DC coefficients (raw)
        vertex_data['f_dc_0'] = colors_sh_dc[:, 0]
        vertex_data['f_dc_1'] = colors_sh_dc[:, 1]
        vertex_data['f_dc_2'] = colors_sh_dc[:, 2]

        # SH rest coefficients
        if sh_rest is not None:
            for i in range(n_sh_rest):
                vertex_data[f'f_rest_{i}'] = sh_rest[:, i]

        # Raw logit opacity
        vertex_data['opacity'] = opacities_logit.flatten()

        # Raw log-space scales
        vertex_data['scale_0'] = scales_log[:, 0]
        vertex_data['scale_1'] = scales_log[:, 1]
        vertex_data['scale_2'] = scales_log[:, 2]

        # Quaternion rotations
        vertex_data['rot_0'] = rotations[:, 0]
        vertex_data['rot_1'] = rotations[:, 1]
        vertex_data['rot_2'] = rotations[:, 2]
        vertex_data['rot_3'] = rotations[:, 3]

        # Write PLY
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
