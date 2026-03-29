"""msplat training backend — Metal-native Gaussian Splatting for Apple Silicon.

Training runs in a subprocess to avoid holding the GIL and freezing the UI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional

from .training_backend import ProgressCallback, TrainingBackend, TrainingResult

# Script executed in a child process — avoids GIL contention with the Qt UI.
_TRAIN_SCRIPT = textwrap.dedent("""\
    import json, sys, msplat
    from pathlib import Path

    data_dir, output_dir, max_iters = sys.argv[1], sys.argv[2], int(sys.argv[3])

    dataset = msplat.load_dataset(data_dir, eval_mode=False)
    config = msplat.TrainingConfig(iterations=max_iters, num_downscales=0)
    trainer = msplat.GaussianTrainer(dataset, config)

    def on_step(stats):
        msg = json.dumps({
            "step": stats.iteration,
            "splats": stats.splat_count,
        })
        print(f"PROGRESS:{msg}", flush=True)

    trainer.train(on_step, callback_every=50)

    ply_path = str(Path(output_dir) / "point_cloud.ply")
    trainer.export_ply(ply_path)

    ckpt_path = str(Path(output_dir) / "checkpoint.msplat")
    trainer.save_checkpoint(ckpt_path)

    print(f"RESULT:{json.dumps({'ply': ply_path, 'ckpt': ckpt_path})}", flush=True)
""")


class MsplatBackend(TrainingBackend):
    name = "msplat"

    def train(
        self,
        data_dir: str,
        output_dir: str,
        max_iterations: int = 30000,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TrainingResult:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback("Starting Metal training engine", 0.01)

        print(f"[Training] msplat subprocess: {max_iterations} iterations on Metal")

        proc = subprocess.Popen(
            [sys.executable, "-c", _TRAIN_SCRIPT, data_dir, output_dir, str(max_iterations)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        ply_path: Optional[str] = None
        ckpt_path: Optional[str] = None

        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("PROGRESS:"):
                payload = json.loads(line[len("PROGRESS:"):])
                step = payload["step"]
                splats = payload["splats"]
                if progress_callback:
                    progress = min(step / max_iterations, 0.99)
                    progress_callback(
                        f"Training: Step {step}/{max_iterations} ({splats:,} splats)",
                        progress,
                    )
            elif line.startswith("RESULT:"):
                payload = json.loads(line[len("RESULT:"):])
                ply_path = payload["ply"]
                ckpt_path = payload["ckpt"]
            else:
                print(f"[msplat] {line}")

        proc.wait()
        stderr = proc.stderr.read()
        if proc.returncode != 0:
            raise RuntimeError(
                f"msplat training failed (exit {proc.returncode}):\n{stderr}"
            )

        if not ply_path or not Path(ply_path).exists():
            raise RuntimeError("msplat training completed but PLY file not found")

        if progress_callback:
            progress_callback("Training complete", 1.0)
        print(f"[Training] msplat: exported {ply_path}")

        return TrainingResult(
            output_dir=str(output_path),
            checkpoint_path=ckpt_path,
            extra={"ply_path": ply_path},
        )

    def export_ply(
        self,
        result: TrainingResult,
        output_ply_path: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        """msplat already exports PLY during train(); copy or re-export."""
        embedded_ply = result.extra.get("ply_path")
        out = Path(output_ply_path)

        if embedded_ply and Path(embedded_ply).exists():
            if progress_callback:
                progress_callback("Copying PLY", 0.5)
            shutil.copy2(embedded_ply, out)
            if progress_callback:
                progress_callback("Export complete", 1.0)
            return out

        if not result.checkpoint_path or not Path(result.checkpoint_path).exists():
            raise RuntimeError("No checkpoint or PLY available for export")

        if progress_callback:
            progress_callback("Re-exporting from checkpoint", 0.2)

        proc = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(f"""\
                import msplat
                dataset = msplat.load_dataset("{result.extra.get('data_dir', result.output_dir)}", eval_mode=False)
                config = msplat.TrainingConfig(iterations=0)
                trainer = msplat.GaussianTrainer(dataset, config)
                trainer.load_checkpoint("{result.checkpoint_path}")
                trainer.export_ply("{out}")
            """)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"msplat export failed:\n{proc.stderr}")

        if progress_callback:
            progress_callback("Export complete", 1.0)
        return out
