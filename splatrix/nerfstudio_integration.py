"""Nerfstudio integration for Splatrix - Python API"""

from pathlib import Path
from typing import Optional, Callable, Literal
import json
import os
import shutil
import subprocess
import sys

# Import video processors
from .video_processing_base import ProcessingConfig
from .nerfstudio_video_processor import NerfstudioVideoProcessor
try:
    from .pyav_video_processor import PyAVVideoProcessor
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False

# Import nerfstudio Python API
try:
    from nerfstudio.scripts.process_data import VideoToNerfstudioDataset, ImagesToNerfstudioDataset
    from nerfstudio.configs.method_configs import method_configs
    from nerfstudio.engine.trainer import Trainer
    NERFSTUDIO_AVAILABLE = True
except ImportError:
    NERFSTUDIO_AVAILABLE = False


class NerfstudioPipeline:
    """
    Integration with nerfstudio for video processing and Gaussian Splatting
    Uses pluggable video processor implementations (nerfstudio or PyAV)
    """
    
    def __init__(
        self, 
        video_processor: Literal["nerfstudio", "pyav"] = "nerfstudio",
        processing_config: Optional[ProcessingConfig] = None
    ):
        self.workspace_dir: Optional[Path] = None
        self.data_dir: Optional[Path] = None
        self.output_dir: Optional[Path] = None
        
        if not NERFSTUDIO_AVAILABLE:
            raise ImportError("nerfstudio not installed. Install with: pip install nerfstudio")
        
        # Initialize video processor
        self.processing_config = processing_config or ProcessingConfig()
        
        if video_processor == "pyav":
            if not PYAV_AVAILABLE:
                raise ImportError("PyAV processor requested but not available. Install with: pip install av")
            self.video_processor = PyAVVideoProcessor(self.processing_config)
        else:
            self.video_processor = NerfstudioVideoProcessor(self.processing_config)
    
    def check_nerfstudio_installed(self) -> bool:
        """Check if nerfstudio is installed"""
        return NERFSTUDIO_AVAILABLE
    
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
        
        # Use nerfstudio's ImagesToNerfstudioDataset class
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
        """
        Train Gaussian Splatting model using nerfstudio Python API
        
        Args:
            data_dir: Directory with processed data
            max_num_iterations: Training iterations
            progress_callback: Callback(stage, progress)
        
        Returns:
            Dictionary with training results and config path
        """
        if progress_callback:
            progress_callback("Initializing splatfacto training", 0.01)
        
        # Verify transforms.json exists
        data_path = Path(data_dir)
        transforms_path = data_path / "transforms.json"
        
        if not transforms_path.exists():
            # Search recursively
            possible = list(data_path.rglob("transforms.json"))
            if possible:
                transforms_path = possible[0]
                # Use parent directory of transforms.json as data dir
                data_path = transforms_path.parent
                if progress_callback:
                    progress_callback(f"Found transforms.json at {transforms_path}", 0.02)
            else:
                # List what's actually in data_dir for debugging
                contents = list(data_path.iterdir()) if data_path.exists() else []
                raise RuntimeError(
                    f"transforms.json not found in {data_dir} or subdirectories.\n"
                    f"Directory contents: {[f.name for f in contents[:10]]}\n"
                    f"Data processing may have failed."
                )
        else:
            if progress_callback:
                progress_callback(f"Using data from {data_path}", 0.02)
        
        # Get splatfacto config (returns TrainerConfig)
        config = method_configs["splatfacto"]
        
        # Configure GPU/device
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            if progress_callback:
                progress_callback(f"Using GPU: {device_name}", 0.015)
            print(f"[Training] Using GPU: {device_name}")
            # Ensure machine config uses CUDA
            if hasattr(config, 'machine'):
                config.machine.device_type = "cuda"
                config.machine.num_devices = 1
        else:
            print("[Training] WARNING: CUDA not available, using CPU (will be slow)")
            if progress_callback:
                progress_callback("WARNING: Training on CPU", 0.015)
        
        # Override settings
        config.data = data_path.resolve()  # Use absolute path (for top-level config)
        config.output_dir = self.output_dir
        config.max_num_iterations = max_num_iterations
        config.viewer.quit_on_train_completion = True
        if hasattr(config, 'logging'):
            config.logging.steps_per_log = 100
        
        # CRITICAL: Set dataparser.data to absolute path (this is what export uses!)
        # Must do this BEFORE creating Trainer, so it gets saved in config.yml
        try:
            config.pipeline.datamanager.dataparser.data = data_path.resolve()
            print(f"[Training] Dataparser data path set to: {data_path.resolve()}")
        except AttributeError as e:
            print(f"[Training] WARNING: Could not set dataparser.data: {e}")
        
        # Ensure checkpoints saved for short training runs
        # Default is 2000 steps - reduce for shorter training
        if max_num_iterations < 2000:
            config.steps_per_save = max(100, max_num_iterations // 5)  # Save at least 5 times
        
        # Always save config and final checkpoint
        config.save_only_latest_checkpoint = False  # Keep all checkpoints for debugging
        
        # Set timestamp and experiment name directly (methods take no arguments)
        from datetime import datetime
        config.timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        config.experiment_name = "splatrix"
        
        # Pre-create output directory structure
        # Trainer expects parent directories to exist
        output_base = self.output_dir / config.experiment_name / "splatfacto"
        output_base.mkdir(parents=True, exist_ok=True)
        
        # Create trainer
        # Note: Some nerfstudio versions may look for transforms.json in cwd
        # Save current directory and change to data directory
        original_cwd = os.getcwd()
        checkpoint_dir_path = None  # Will be set after trainer creation
        
        try:
            # Change to data directory so relative paths work
            os.chdir(str(data_path))
            
            trainer = Trainer(config, local_rank=0, world_size=1)
            checkpoint_dir_path = trainer.checkpoint_dir  # Save for later use
            
            # Hook into training loop for progress
            original_train_iteration = trainer.train_iteration
            last_reported_step = [0]
            
            def tracked_train_iteration(step: int):
                """Track training progress"""
                result = original_train_iteration(step)
                
                if progress_callback and step != last_reported_step[0]:
                    # Report more frequently for continuous feedback:
                    # - Every 10 steps for first 100
                    # - Every 50 steps thereafter
                    # - Always report first/last 10 steps
                    should_report = (
                        step < 10 or  # First 10 steps
                        step > max_num_iterations - 10 or  # Last 10 steps
                        (step < 100 and step % 10 == 0) or  # Every 10 for first 100
                        (step >= 100 and step % 50 == 0)  # Every 50 after 100
                    )
                    
                    if should_report:
                        progress = min(step / max_num_iterations, 0.99)
                        progress_callback(f"Training: Step {step}/{max_num_iterations}", progress)
                        last_reported_step[0] = step
                
                return result
            
            trainer.train_iteration = tracked_train_iteration
            
            # Run training
            trainer.setup()
            if progress_callback:
                progress_callback("Training started", 0.02)
            
            # Verify model is on GPU after setup
            if torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated(0) / 1024**3  # GB
                reserved = torch.cuda.memory_reserved(0) / 1024**3  # GB
                print(f"[Training] GPU memory: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")
                
                # Check if model parameters are on GPU
                if hasattr(trainer, 'pipeline') and hasattr(trainer.pipeline, 'model'):
                    model_device = next(trainer.pipeline.model.parameters()).device
                    print(f"[Training] Model device: {model_device}")
                    if model_device.type != 'cuda':
                        print(f"[Training] ⚠ WARNING: Model on {model_device.type}, expected cuda")
            else:
                print("[Training] ⚠ WARNING: Training on CPU - this will be very slow!")
            
            trainer.train()
            
            if progress_callback:
                progress_callback("Training complete", 1.0)
            
            # Save final checkpoint and config explicitly
            config_yml_path = None
            try:
                # Config saved by Trainer during setup - verify it exists
                print(f"[Training] Checkpoint dir: {trainer.checkpoint_dir}")
                
                config_yml_path = trainer.checkpoint_dir.parent / "config.yml"
                
                # Verify it was actually created
                if config_yml_path.exists():
                    print(f"[Training] Config verified at: {config_yml_path}")
                else:
                    print(f"[Training] WARNING: Config not found after save at {config_yml_path}")
                
                # Save final checkpoint
                trainer.save_checkpoint(step=max_num_iterations)
                print(f"[Training] Final checkpoint saved at step {max_num_iterations}")
                
                # List checkpoint directory contents
                if trainer.checkpoint_dir.exists():
                    ckpts = list(trainer.checkpoint_dir.glob("*.ckpt"))
                    print(f"[Training] Found {len(ckpts)} checkpoint(s) in {trainer.checkpoint_dir}")
                    for ckpt in sorted(ckpts)[-3:]:  # Show last 3
                        print(f"  - {ckpt.name}")
            except Exception as e:
                print(f"[Training] Warning: Could not save final checkpoint: {e}")
                import traceback
                traceback.print_exc()
            
            # Restore original directory
            os.chdir(original_cwd)
            
        except Exception as e:
            # Restore directory even on error
            os.chdir(original_cwd)
            raise RuntimeError(
                f"Training failed: {str(e)}\n"
                f"Data directory: {data_path}\n"
                f"transforms.json: {transforms_path}\n"
                f"Original cwd: {original_cwd}"
            )
        
        # Use the config we just saved (don't search for old ones!)
        if config_yml_path and config_yml_path.exists():
            config_path = config_yml_path
            print(f"[Training] Using config from training: {config_path}")
        elif checkpoint_dir_path:
            # Fallback: check checkpoint parent directory
            potential_config = checkpoint_dir_path.parent / "config.yml"
            if potential_config.exists():
                config_path = potential_config
                print(f"[Training] Found config at checkpoint parent: {config_path}")
            else:
                # Last resort: search (might find old config)
                config_paths = list(self.output_dir.rglob("config.yml"))
                if config_paths:
                    # Take the NEWEST config (by modification time)
                    config_path = max(config_paths, key=lambda p: p.stat().st_mtime)
                    print(f"[Training] WARNING: Using newest config found: {config_path}")
                else:
                    config_path = None
                    print(f"[Training] ERROR: No config.yml found anywhere")
                    print(f"[Training] Checkpoint dir: {checkpoint_dir_path}")
        else:
            config_path = None
            print(f"[Training] ERROR: No checkpoint directory available")
        
        return {
            'output_dir': str(self.output_dir),
            'config_path': str(config_path) if config_path else None,
            'checkpoint_dir': str(checkpoint_dir_path) if checkpoint_dir_path else None
        }
    
    def export_gaussian_splat(
        self,
        checkpoint_path: str,
        output_ply_path: str,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Path:
        """
        Export Gaussian Splats to PLY using direct checkpoint loading
        
        Loads checkpoint with torch.load(), extracts Gaussian parameters,
        applies activations (exp/sigmoid/SH→RGB), writes PLY.
        No subprocess, no config path issues, <1s export time
        
        Args:
            checkpoint_path: Path to .ckpt file
            output_ply_path: Output PLY file path
            progress_callback: Callback(stage, progress)
        
        Returns:
            Path to exported PLY file
        """
        from .direct_ply_export import export_from_checkpoint
        
        return export_from_checkpoint(
            checkpoint_path,
            output_ply_path,
            progress_callback
        )
    
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
