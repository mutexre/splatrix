"""Direct PLY export from nerfstudio checkpoint without subprocess"""

from pathlib import Path
from typing import Optional, Callable
import torch
import numpy as np

from .ply_exporter import PLYExporter


def export_from_checkpoint(
    checkpoint_path: str,
    output_ply_path: str,
    progress_callback: Optional[Callable[[str, float], None]] = None
) -> Path:
    """
    Export Gaussian Splats to PLY directly from checkpoint file
    
    This bypasses ns-export CLI and pymeshlab conflicts by:
    1. Loading checkpoint directly with torch.load()
    2. Extracting Gaussian parameters from state dict
    3. Applying activation functions (exp, sigmoid, SH→RGB)
    4. Writing PLY using our ply_exporter
    
    Args:
        checkpoint_path: Path to .ckpt file
        output_ply_path: Output PLY file path
        progress_callback: Optional callback(message, progress_0_to_1)
    
    Returns:
        Path to created PLY file
    """
    if progress_callback:
        progress_callback("Loading checkpoint", 0.1)
    
    checkpoint_path = Path(checkpoint_path)
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
    
    # Load checkpoint (weights_only=False needed for nerfstudio checkpoints)
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=False)
    
    if progress_callback:
        progress_callback("Extracting Gaussian parameters", 0.3)
    
    # Extract Gaussian parameters from state dict
    state = checkpoint['pipeline']
    
    means = state['_model.gauss_params.means']
    scales = state['_model.gauss_params.scales']
    quats = state['_model.gauss_params.quats']
    opacities = state['_model.gauss_params.opacities']
    features_dc = state['_model.gauss_params.features_dc']
    
    if progress_callback:
        progress_callback("Applying activation functions", 0.5)
    
    # Apply activation functions
    # 1. Scales: log space → linear space
    scales_linear = torch.exp(scales)
    
    # 2. Opacities: logit space → probability (0-1)
    opacities_prob = torch.sigmoid(opacities)
    
    # 3. Quaternions: normalize (should already be normalized, but ensure)
    quats_norm = torch.nn.functional.normalize(quats, dim=-1)
    
    # 4. Colors: Spherical Harmonics DC term → RGB
    # SH DC coefficient (0th order): C0 = 0.28209479177387814 (sqrt(1/(4*pi)))
    C0 = 0.28209479177387814
    colors_01 = features_dc * C0 + 0.5  # SH to RGB (0-1 range)
    colors_01 = torch.clamp(colors_01, 0.0, 1.0)
    colors_255 = (colors_01 * 255.0)
    
    if progress_callback:
        progress_callback("Converting to numpy arrays", 0.7)
    
    # Convert to numpy
    positions_np = means.detach().cpu().numpy()
    colors_np = colors_255.detach().cpu().numpy()
    scales_np = scales_linear.detach().cpu().numpy()
    rotations_np = quats_norm.detach().cpu().numpy()
    opacities_np = opacities_prob.detach().cpu().numpy()
    
    if progress_callback:
        progress_callback("Writing PLY file", 0.9)
    
    # Write PLY using our exporter
    output_path = PLYExporter.create_gaussian_splat_ply(
        positions=positions_np,
        colors=colors_np,
        scales=scales_np,
        rotations=rotations_np,
        opacities=opacities_np,
        output_path=output_ply_path
    )
    
    if progress_callback:
        progress_callback("Export complete", 1.0)
    
    print(f"✓ Exported {len(positions_np)} Gaussians to {output_path}")
    
    return output_path


def find_latest_checkpoint(output_dir: Path) -> Optional[Path]:
    """
    Find the latest checkpoint in nerfstudio output directory
    
    Args:
        output_dir: Base output directory (e.g., ~/.splats_workspace/nerfstudio/outputs)
    
    Returns:
        Path to latest checkpoint .ckpt file, or None if not found
    """
    # Search for checkpoint files
    checkpoint_files = list(output_dir.rglob("nerfstudio_models/step-*.ckpt"))
    
    if not checkpoint_files:
        return None
    
    # Return most recently modified
    latest = max(checkpoint_files, key=lambda p: p.stat().st_mtime)
    return latest

