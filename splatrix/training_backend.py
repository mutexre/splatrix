"""Abstract training backend for Gaussian Splatting.

Defines the interface that concrete backends (nerfstudio/gsplat, msplat, etc.)
must implement so the rest of the app stays backend-agnostic.
"""

from __future__ import annotations

import platform
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class TrainingResult:
    """Returned by TrainingBackend.train()."""
    output_dir: str
    checkpoint_path: Optional[str] = None
    config_path: Optional[str] = None
    checkpoint_dir: Optional[str] = None
    extra: dict = field(default_factory=dict)


ProgressCallback = Callable[[str, float], None]


class TrainingBackend(ABC):
    """Train a Gaussian Splat model and export it to PLY."""

    name: str = "base"

    @abstractmethod
    def train(
        self,
        data_dir: str,
        output_dir: str,
        max_iterations: int = 30000,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TrainingResult:
        """Run training on processed COLMAP / nerfstudio data.

        Args:
            data_dir: Directory containing transforms.json + images/.
            output_dir: Where to write checkpoints / outputs.
            max_iterations: Number of optimisation steps.
            progress_callback: ``(message, progress_0_to_1)`` updates.

        Returns:
            A TrainingResult with paths to outputs.
        """

    @abstractmethod
    def export_ply(
        self,
        result: TrainingResult,
        output_ply_path: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        """Export trained model to a Gaussian-Splat PLY file.

        Args:
            result: The TrainingResult returned by :meth:`train`.
            output_ply_path: Destination PLY path.
            progress_callback: ``(message, progress_0_to_1)`` updates.

        Returns:
            Resolved path to the written PLY file.
        """

    @staticmethod
    def available_backends() -> list[str]:
        """Return names of backends that can run on this machine."""
        names: list[str] = []
        if _cuda_available():
            names.append("nerfstudio")
        if _msplat_usable():
            names.append("msplat")
        if not names and _nerfstudio_importable():
            names.append("nerfstudio")
        return names

    @staticmethod
    def auto_select() -> TrainingBackend:
        """Pick the best backend for this machine."""
        if _cuda_available():
            from .backend_nerfstudio import NerfstudioBackend
            return NerfstudioBackend()

        if _msplat_usable():
            from .backend_msplat import MsplatBackend
            return MsplatBackend()

        is_mac_arm = (
            platform.system() == "Darwin"
            and platform.machine() in ("arm64", "aarch64")
        )
        if is_mac_arm:
            py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            raise RuntimeError(
                "Gaussian Splatting training requires either CUDA (not available on macOS) "
                "or the msplat Metal backend.\n\n"
                "To fix this, install msplat:\n"
                "  pip install msplat\n\n"
                f"Note: msplat requires Python >= 3.12 (you have {py_ver}).\n"
                "Recreate your conda environment with:\n"
                "  conda create -n splatrix python=3.12 && conda activate splatrix"
            )

        if _nerfstudio_importable():
            from .backend_nerfstudio import NerfstudioBackend
            return NerfstudioBackend()

        raise RuntimeError(
            "No training backend available.\n"
            "Install nerfstudio (requires CUDA) or msplat (macOS Apple Silicon)."
        )


# ── helpers ────────────────────────────────────────────────────────────────

def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _nerfstudio_importable() -> bool:
    try:
        import nerfstudio  # noqa: F401
        return True
    except ImportError:
        return False


def _msplat_usable() -> bool:
    if platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64"):
        return False
    try:
        import msplat  # noqa: F401
        return True
    except ImportError:
        return False
