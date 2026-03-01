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
    Export Gaussian Splats to PLY directly from checkpoint file.

    Writes raw (pre-activation) values so that standard viewers
    (GaussianSplats3D, SuperSplat, etc.) can apply their own
    activation functions correctly.

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
    scales = state['_model.gauss_params.scales']          # log-space (raw)
    quats = state['_model.gauss_params.quats']
    opacities = state['_model.gauss_params.opacities']    # logit-space (raw)
    features_dc = state['_model.gauss_params.features_dc']  # SH DC coefficients (raw)

    # Check for higher-order SH coefficients
    sh_rest_key = '_model.gauss_params.features_rest'
    features_rest = state.get(sh_rest_key, None)

    if progress_callback:
        progress_callback("Preparing raw parameters", 0.5)

    # Normalize quaternions (they should be normalized already, but ensure)
    quats_norm = torch.nn.functional.normalize(quats, dim=-1)

    if progress_callback:
        progress_callback("Converting to numpy arrays", 0.7)

    # Convert to numpy — keep all values in RAW space
    positions_np = means.detach().cpu().numpy()
    colors_sh_dc_np = features_dc.detach().cpu().numpy()    # raw SH DC
    scales_log_np = scales.detach().cpu().numpy()            # raw log-scale
    rotations_np = quats_norm.detach().cpu().numpy()
    opacities_logit_np = opacities.detach().cpu().numpy()   # raw logit

    # Handle SH rest coefficients
    sh_rest_np = None
    if features_rest is not None and features_rest.numel() > 0:
        # features_rest shape: [N, num_coeffs, 3]
        # INRIA PLY format groups by channel:
        #   f_rest_0..f_rest_{K-1} = all R coeffs,
        #   f_rest_K..f_rest_{2K-1} = all G coeffs,
        #   f_rest_2K..f_rest_{3K-1} = all B coeffs
        fr = features_rest.detach().cpu().numpy()  # [N, K, 3]
        # Transpose to [N, 3, K] then flatten to [N, 3*K]
        sh_rest_np = fr.transpose(0, 2, 1).reshape(fr.shape[0], -1)

    if progress_callback:
        progress_callback("Writing PLY file", 0.9)

    # Write PLY in INRIA-compatible format (raw values)
    output_path = PLYExporter.create_gaussian_splat_ply(
        positions=positions_np,
        colors_sh_dc=colors_sh_dc_np,
        scales_log=scales_log_np,
        rotations=rotations_np,
        opacities_logit=opacities_logit_np,
        output_path=output_ply_path,
        sh_rest=sh_rest_np,
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
