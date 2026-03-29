"""Nerfstudio / gsplat training backend (requires CUDA for splatfacto)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .training_backend import ProgressCallback, TrainingBackend, TrainingResult


class NerfstudioBackend(TrainingBackend):
    name = "nerfstudio"

    def train(
        self,
        data_dir: str,
        output_dir: str,
        max_iterations: int = 30000,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TrainingResult:
        if progress_callback:
            progress_callback("Initializing splatfacto training", 0.01)

        data_path = Path(data_dir)
        transforms_path = self._resolve_transforms(data_path, progress_callback)
        data_path = transforms_path.parent
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        from nerfstudio.configs.method_configs import method_configs
        config = method_configs["splatfacto"]

        import torch
        device_type = self._configure_device(config, torch, progress_callback)

        config.data = data_path.resolve()
        config.output_dir = output_dir_path
        config.max_num_iterations = max_iterations
        config.vis = None
        config.viewer.quit_on_train_completion = True
        if hasattr(config, "logging"):
            config.logging.steps_per_log = 100

        try:
            config.pipeline.datamanager.dataparser.data = data_path.resolve()
        except AttributeError:
            pass

        if max_iterations < 2000:
            config.steps_per_save = max(100, max_iterations // 5)
        config.save_only_latest_checkpoint = False
        config.timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        config.experiment_name = "splatrix"

        output_base = output_dir_path / config.experiment_name / "splatfacto"
        output_base.mkdir(parents=True, exist_ok=True)

        original_cwd = os.getcwd()
        checkpoint_dir_path: Optional[Path] = None
        config_yml_path: Optional[Path] = None

        try:
            os.chdir(str(data_path))

            from nerfstudio.engine.trainer import Trainer
            trainer = Trainer(config, local_rank=0, world_size=1)
            checkpoint_dir_path = trainer.checkpoint_dir

            original_train_iteration = trainer.train_iteration
            last_reported_step = [0]

            def tracked_train_iteration(step: int):
                result = original_train_iteration(step)
                if progress_callback and step != last_reported_step[0]:
                    should_report = (
                        step < 10
                        or step > max_iterations - 10
                        or (step < 100 and step % 10 == 0)
                        or (step >= 100 and step % 50 == 0)
                    )
                    if should_report:
                        progress = min(step / max_iterations, 0.99)
                        progress_callback(
                            f"Training: Step {step}/{max_iterations}", progress
                        )
                        last_reported_step[0] = step
                return result

            trainer.train_iteration = tracked_train_iteration

            trainer.setup()
            if progress_callback:
                progress_callback("Training started", 0.02)

            if hasattr(trainer, "pipeline") and hasattr(trainer.pipeline, "model"):
                try:
                    dev = next(trainer.pipeline.model.parameters()).device
                    print(f"[Training] Model device: {dev}")
                except StopIteration:
                    pass
            if device_type == "cuda":
                alloc = torch.cuda.memory_allocated(0) / 1024**3
                res = torch.cuda.memory_reserved(0) / 1024**3
                print(f"[Training] GPU memory: {alloc:.2f}GB allocated, {res:.2f}GB reserved")

            trainer.train()

            if progress_callback:
                progress_callback("Training complete", 1.0)

            try:
                config_yml_path = trainer.checkpoint_dir.parent / "config.yml"
                trainer.save_checkpoint(step=max_iterations)
            except Exception as exc:
                print(f"[Training] Warning: could not save final checkpoint: {exc}")

            os.chdir(original_cwd)
        except Exception:
            os.chdir(original_cwd)
            raise

        config_path = self._find_config(config_yml_path, checkpoint_dir_path, output_dir_path)

        return TrainingResult(
            output_dir=str(output_dir_path),
            config_path=str(config_path) if config_path else None,
            checkpoint_dir=str(checkpoint_dir_path) if checkpoint_dir_path else None,
        )

    def export_ply(
        self,
        result: TrainingResult,
        output_ply_path: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        if not result.checkpoint_dir:
            raise RuntimeError("No checkpoint directory in TrainingResult")
        ckpt_dir = Path(result.checkpoint_dir)
        checkpoints = sorted(ckpt_dir.glob("step-*.ckpt"))
        if not checkpoints:
            raise RuntimeError(f"No checkpoints found in {ckpt_dir}")
        latest = max(checkpoints, key=lambda p: int(p.stem.split("-")[1]))

        from .direct_ply_export import export_from_checkpoint
        return export_from_checkpoint(str(latest), output_ply_path, progress_callback)

    # ── internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _resolve_transforms(data_path: Path, cb: Optional[ProgressCallback]) -> Path:
        transforms = data_path / "transforms.json"
        if transforms.exists():
            if cb:
                cb(f"Using data from {data_path}", 0.02)
            return transforms
        found = list(data_path.rglob("transforms.json"))
        if found:
            if cb:
                cb(f"Found transforms.json at {found[0]}", 0.02)
            return found[0]
        contents = [f.name for f in data_path.iterdir()][:10] if data_path.exists() else []
        raise RuntimeError(
            f"transforms.json not found in {data_path} or subdirectories.\n"
            f"Directory contents: {contents}\n"
            f"Data processing may have failed."
        )

    @staticmethod
    def _configure_device(config, torch_mod, cb: Optional[ProgressCallback]) -> str:
        device_type = "cpu"
        if torch_mod.cuda.is_available():
            device_type = "cuda"
            name = torch_mod.cuda.get_device_name(0)
            if cb:
                cb(f"Using GPU: {name}", 0.015)
            print(f"[Training] Using GPU (CUDA): {name}")
        elif hasattr(torch_mod.backends, "mps") and torch_mod.backends.mps.is_available():
            device_type = "mps"
            if cb:
                cb("Using Apple GPU (MPS)", 0.015)
            print("[Training] Using Apple GPU (MPS)")
            def _cuda_to_mps(self, *a, **kw):
                return self.to("mps")
            torch_mod.Tensor.cuda = _cuda_to_mps
        else:
            print("[Training] WARNING: No GPU available, using CPU (will be very slow)")
            if cb:
                cb("WARNING: Training on CPU (slow)", 0.015)
            def _cuda_to_cpu(self, *a, **kw):
                return self.to("cpu")
            torch_mod.Tensor.cuda = _cuda_to_cpu

        if hasattr(config, "machine"):
            config.machine.device_type = device_type
            config.machine.num_devices = 1
        return device_type

    @staticmethod
    def _find_config(
        config_yml: Optional[Path],
        ckpt_dir: Optional[Path],
        output_dir: Path,
    ) -> Optional[Path]:
        if config_yml and config_yml.exists():
            return config_yml
        if ckpt_dir:
            alt = ckpt_dir.parent / "config.yml"
            if alt.exists():
                return alt
        found = list(output_dir.rglob("config.yml"))
        if found:
            return max(found, key=lambda p: p.stat().st_mtime)
        return None
