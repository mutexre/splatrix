"""First-run dependency bootstrapper for Splatrix.

Downloads and installs ML pipeline components (PyTorch, Nerfstudio, COLMAP,
FFmpeg) on first launch.  Installs into the currently active Python environment.
State is persisted to ~/.splatrix/bootstrap.json so interrupted installs resume
from the last completed step.

Two modes:
  - Managed: already inside a conda/mamba env (CONDA_PREFIX set).
    Installs packages via pip and conda into the active env.
  - Standalone: no env (future .app bundle).
    Sets up ~/.splatrix/ with micromamba, creates an env, then installs.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, pyqtProperty


# ── Paths ──────────────────────────────────────────────────────────────────────

SPLATRIX_HOME = Path.home() / ".splatrix"
BOOTSTRAP_FILE = SPLATRIX_HOME / "bootstrap.json"


# ── Environment detection ──────────────────────────────────────────────────────

def _detect_platform() -> tuple[str, str, str]:
    """Returns (os_name, arch, mamba_platform)."""
    os_name = platform.system()
    arch = platform.machine()

    if os_name == "Darwin":
        mamba_platform = "osx-arm64" if arch == "arm64" else "osx-64"
    elif os_name == "Linux":
        if arch != "x86_64":
            raise RuntimeError(f"Linux: only x86_64 supported (got {arch})")
        mamba_platform = "linux-64"
    else:
        raise RuntimeError(f"Unsupported platform: {os_name} {arch}")

    return os_name, arch, mamba_platform


def _in_conda_env() -> bool:
    """True if we're running inside an activated conda/mamba environment."""
    return bool(os.environ.get("CONDA_PREFIX"))


def _conda_prefix() -> Optional[Path]:
    cp = os.environ.get("CONDA_PREFIX")
    return Path(cp) if cp else None


def _pip_cmd() -> list[str]:
    """pip command that installs into the current environment."""
    return [sys.executable, "-m", "pip"]


def _conda_cmd() -> Optional[list[str]]:
    """Returns a conda/mamba/micromamba command list, or None."""
    for name in ("mamba", "micromamba", "conda"):
        path = shutil.which(name)
        if path:
            return [path]
    mamba = SPLATRIX_HOME / "bin" / "micromamba"
    if mamba.exists():
        return [str(mamba)]
    return None


# ── Steps definition ───────────────────────────────────────────────────────────

def _build_steps() -> list[dict]:
    """Build step list based on current environment."""
    steps = []

    if not _in_conda_env():
        steps.append({"id": "micromamba",  "label": "Package manager",    "weight": 1})
        steps.append({"id": "environment", "label": "Python environment", "weight": 2})

    steps += [
        {"id": "pytorch",     "label": "PyTorch",            "weight": 5},
        {"id": "tools",       "label": "COLMAP + FFmpeg",    "weight": 2},
        {"id": "nerfstudio",  "label": "Nerfstudio",         "weight": 4},
    ]

    os_name, arch, _ = _detect_platform()
    if os_name == "Darwin" and arch == "arm64":
        steps.append({"id": "msplat", "label": "Metal training engine", "weight": 1})

    steps.append({"id": "finalize", "label": "Finalize setup", "weight": 1})
    return steps


# ── Bootstrap check ───────────────────────────────────────────────────────────

def is_bootstrap_needed() -> bool:
    """Fast check: are ML pipeline dependencies available?"""
    steps = _build_steps()

    if BOOTSTRAP_FILE.exists():
        try:
            with open(BOOTSTRAP_FILE) as f:
                state = json.load(f)
            step_states = state.get("steps", {})
            if all(
                step_states.get(s["id"], {}).get("status") == "completed"
                for s in steps
            ):
                return False
        except Exception:
            pass

    return not _deps_available()


def _deps_available() -> bool:
    """Check if critical ML deps are importable/callable."""
    try:
        import torch  # noqa: F401
        import nerfstudio  # noqa: F401
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5, check=True)
        _mark_all_completed()
        return True
    except Exception:
        return False


# ── State persistence ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if BOOTSTRAP_FILE.exists():
        try:
            with open(BOOTSTRAP_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": 1, "steps": {}}


def _save_state(state: dict):
    SPLATRIX_HOME.mkdir(parents=True, exist_ok=True)
    tmp = BOOTSTRAP_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(BOOTSTRAP_FILE)


def _update_step(step_id: str, status: str, error: str = None):
    state = _load_state()
    state.setdefault("steps", {})[step_id] = {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **({"error": error} if error else {}),
    }
    _save_state(state)


def _mark_all_completed():
    steps = _build_steps()
    state = _load_state()
    for s in steps:
        state.setdefault("steps", {})[s["id"]] = {
            "status": "completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    _save_state(state)


def _load_bootstrap_config() -> dict:
    config_path = Path(__file__).parent / "bootstrap_config.json"
    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception:
        return {}


def reset_bootstrap():
    """Delete bootstrap state file."""
    if BOOTSTRAP_FILE.exists():
        BOOTSTRAP_FILE.unlink()
        print(f"Removed {BOOTSTRAP_FILE}")
    else:
        print(f"Nothing to reset ({BOOTSTRAP_FILE} does not exist)")


# ── Worker thread ──────────────────────────────────────────────────────────────

class BootstrapWorker(QThread):
    """Runs installation steps in a background thread."""

    step_started = pyqtSignal(str, str)       # step_id, label
    step_completed = pyqtSignal(str)           # step_id
    step_failed = pyqtSignal(str, str)         # step_id, error
    progress_changed = pyqtSignal(float)       # 0.0 – 1.0
    status_message = pyqtSignal(str)           # human-readable status
    all_completed = pyqtSignal()
    install_failed = pyqtSignal(str)           # overall error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        self._os, self._arch, self._mamba_platform = _detect_platform()
        self._steps = _build_steps()
        self._total_weight = sum(s["weight"] for s in self._steps)

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            state = _load_state()
            weight_done = 0.0

            for step in self._steps:
                if self._cancelled:
                    return

                sid = step["id"]
                step_status = state.get("steps", {}).get(sid, {}).get("status")

                if step_status == "completed":
                    weight_done += step["weight"]
                    self.progress_changed.emit(weight_done / self._total_weight)
                    continue

                self.step_started.emit(sid, step["label"])
                _update_step(sid, "in_progress")

                try:
                    getattr(self, f"_step_{sid}")()
                    _update_step(sid, "completed")
                    self.step_completed.emit(sid)
                    weight_done += step["weight"]
                    self.progress_changed.emit(weight_done / self._total_weight)
                except Exception as e:
                    _update_step(sid, "failed", str(e))
                    self.step_failed.emit(sid, str(e))
                    self.install_failed.emit(f"{step['label']}: {e}")
                    return

            self.progress_changed.emit(1.0)
            self.all_completed.emit()
        except Exception as e:
            self.install_failed.emit(str(e))

    # ── Helpers ────────────────────────────────────────────────────────────

    def _run(
        self,
        cmd: list[str],
        desc: str = "",
        env_extra: dict = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        env = {**os.environ}
        if env_extra:
            env.update(env_extra)

        if desc:
            self.status_message.emit(desc)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
        )

        lines = []
        for line in proc.stdout:
            lines.append(line.rstrip())

        proc.wait()

        if check and proc.returncode != 0:
            tail = "\n".join(lines[-30:])
            raise RuntimeError(
                f"Command exited with code {proc.returncode}\n{tail}"
            )

        return subprocess.CompletedProcess(cmd, proc.returncode, "\n".join(lines))

    def _download(self, url: str, dest: Path, desc: str = "Downloading"):
        self.status_message.emit(f"{desc}...")
        dest.parent.mkdir(parents=True, exist_ok=True)

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 256 * 1024

            with open(dest, "wb") as f:
                while True:
                    if self._cancelled:
                        raise RuntimeError("Cancelled")
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded * 100 / total)
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total / (1024 * 1024)
                        self.status_message.emit(
                            f"{desc}  {mb_done:.0f} / {mb_total:.0f} MB ({pct}%)"
                        )

    # ── Step: micromamba (standalone only) ──────────────────────────────────

    def _step_micromamba(self):
        mamba = SPLATRIX_HOME / "bin" / "micromamba"
        if mamba.exists() and os.access(mamba, os.X_OK):
            self.status_message.emit("micromamba already installed")
            return

        (SPLATRIX_HOME / "bin").mkdir(parents=True, exist_ok=True)

        url = f"https://micro.mamba.pm/api/micromamba/{self._mamba_platform}/latest"
        with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            self._download(url, tmp_path, "Downloading micromamba")
            self.status_message.emit("Extracting micromamba...")
            subprocess.run(
                [
                    "tar", "xjf", str(tmp_path),
                    "-C", str(SPLATRIX_HOME / "bin"),
                    "--strip-components=1", "bin/micromamba",
                ],
                check=True,
                capture_output=True,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        mamba.chmod(0o755)

        r = subprocess.run([str(mamba), "--version"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("micromamba verification failed")
        self.status_message.emit(f"micromamba {r.stdout.strip()}")

    # ── Step: environment (standalone only) ─────────────────────────────────

    def _step_environment(self):
        prefix = SPLATRIX_HOME / "envs" / "splatrix"
        if (prefix / "conda-meta").is_dir():
            self.status_message.emit("Python environment already exists")
            return

        mamba = str(SPLATRIX_HOME / "bin" / "micromamba")
        self._run(
            [mamba, "create", "-p", str(prefix),
             "python=3.10", "-y", "-c", "conda-forge"],
            desc="Creating Python 3.10 environment...",
            env_extra={"MAMBA_ROOT_PREFIX": str(SPLATRIX_HOME)},
        )

    # ── Step: PyTorch ──────────────────────────────────────────────────────

    def _step_pytorch(self):
        r = subprocess.run(
            [sys.executable, "-c", "import torch; print(torch.__version__)"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            self.status_message.emit(f"PyTorch {r.stdout.strip()} already installed")
            return

        pip = _pip_cmd()

        if self._os == "Linux":
            has_nvidia = subprocess.run(
                ["nvidia-smi"], capture_output=True,
            ).returncode == 0

            if has_nvidia:
                self._run(
                    [*pip, "install", "torch", "torchvision",
                     "--index-url", "https://download.pytorch.org/whl/cu121"],
                    desc="Installing PyTorch with CUDA 12.1...",
                )
                conda = _conda_cmd()
                if conda and _conda_prefix():
                    try:
                        self._run(
                            [*conda, "install",
                             "-p", str(_conda_prefix()),
                             "-c", "conda-forge",
                             "cuda-nvcc", "cuda-version=12.1.*", "-y"],
                            desc="Installing CUDA toolkit...",
                            check=False,
                        )
                    except Exception:
                        pass
            else:
                self._run(
                    [*pip, "install", "torch", "torchvision"],
                    desc="Installing PyTorch (CPU)...",
                )
        else:
            accel = "MPS" if self._arch == "arm64" else "CPU"
            self._run(
                [*pip, "install", "torch", "torchvision"],
                desc=f"Installing PyTorch ({accel})...",
            )

    # ── Step: COLMAP + FFmpeg + OpenCV ─────────────────────────────────────

    def _step_tools(self):
        pip = _pip_cmd()

        # FFmpeg
        if not shutil.which("ffmpeg"):
            conda = _conda_cmd()
            prefix = _conda_prefix()
            if conda and prefix:
                self._run(
                    [*conda, "install", "-p", str(prefix),
                     "-c", "conda-forge", "ffmpeg", "-y"],
                    desc="Installing FFmpeg...",
                )
            else:
                raise RuntimeError(
                    "FFmpeg not found. Install it with: brew install ffmpeg"
                )
        else:
            self.status_message.emit("FFmpeg already available")

        # COLMAP
        if not shutil.which("colmap"):
            conda = _conda_cmd()
            prefix = _conda_prefix()
            if conda and prefix:
                try:
                    self._run(
                        [*conda, "install", "-p", str(prefix),
                         "-c", "conda-forge", "colmap", "-y"],
                        desc="Installing COLMAP...",
                    )
                except RuntimeError:
                    if self._os == "Darwin" and self._arch == "arm64":
                        self.status_message.emit(
                            "COLMAP not available via conda — "
                            "install manually: brew install colmap"
                        )
                    else:
                        raise
            else:
                self.status_message.emit(
                    "COLMAP not found — install manually: brew install colmap"
                )
        else:
            self.status_message.emit("COLMAP already available")

        # OpenCV
        r = subprocess.run(
            [sys.executable, "-c", "import cv2"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            self._run(
                [*pip, "install", "opencv-python-headless"],
                desc="Installing OpenCV...",
            )
        else:
            self.status_message.emit("OpenCV already installed")

    # ── Step: Nerfstudio ───────────────────────────────────────────────────

    def _step_nerfstudio(self):
        r = subprocess.run(
            [sys.executable, "-c", "import nerfstudio"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            self.status_message.emit("Nerfstudio already installed")
            return

        self._run(
            [*_pip_cmd(), "install", "nerfstudio"],
            desc="Installing Nerfstudio (this may take several minutes)...",
        )

    # ── Step: msplat (macOS Apple Silicon only) ──────────────────────────

    def _step_msplat(self):
        r = subprocess.run(
            [sys.executable, "-c", "import msplat"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            self.status_message.emit("msplat already installed")
            return

        self._run(
            [*_pip_cmd(), "install", "msplat"],
            desc="Installing Metal training engine...",
        )

    # ── Step: Finalize ─────────────────────────────────────────────────────

    def _step_finalize(self):
        self.status_message.emit("Applying compatibility patches...")

        r = subprocess.run(
            [sys.executable, "-c",
             "import nerfstudio.process_data.colmap_utils as m; print(m.__file__)"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            self.status_message.emit("Skipping patch (nerfstudio colmap_utils not found)")
            return

        utils_path = r.stdout.strip()

        r = subprocess.run(
            [sys.executable, "-c",
             f"print('yes' if '_extract_gpu_flag' in open({utils_path!r}).read() else 'no')"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and "yes" in r.stdout:
            self.status_message.emit("Already patched")
            return

        patch_script = _build_patch_script(utils_path)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False,
        ) as f:
            f.write(patch_script)
            patch_file = f.name

        try:
            subprocess.run(
                [sys.executable, patch_file],
                check=True, capture_output=True,
            )
        finally:
            Path(patch_file).unlink(missing_ok=True)

        self.status_message.emit("Compatibility patches applied")


def _build_patch_script(utils_path: str) -> str:
    return f'''import pathlib

p = pathlib.Path({utils_path!r})
t = p.read_text()

t = t.replace("FeatureExtraction.use_gpu", "SiftExtraction.use_gpu")
t = t.replace("FeatureMatching.use_gpu", "SiftMatching.use_gpu")

t = t.replace(
    'f"--SiftExtraction.use_gpu {{int(gpu)}}"',
    "_extract_gpu_flag",
)
t = t.replace(
    'f"--SiftMatching.use_gpu {{int(gpu)}}"',
    "_match_gpu_flag",
)

old = "    colmap_version = get_colmap_version(colmap_cmd)\\n"
new = """    colmap_version = get_colmap_version(colmap_cmd)

    try:
        import subprocess as _sp
        _h = _sp.run(
            [colmap_cmd, "feature_extractor", "-h"],
            capture_output=True, text=True, timeout=10,
        )
        _ht = (_h.stdout or "") + (_h.stderr or "")
    except Exception:
        _ht = ""

    if "FeatureExtraction" in _ht:
        _extract_gpu_flag = f"--FeatureExtraction.use_gpu {{int(gpu)}}"
        _match_gpu_flag = f"--FeatureMatching.use_gpu {{int(gpu)}}"
    else:
        _extract_gpu_flag = f"--SiftExtraction.use_gpu {{int(gpu)}}"
        _match_gpu_flag = f"--SiftMatching.use_gpu {{int(gpu)}}"
"""

if old in t:
    t = t.replace(old, new, 1)
    p.write_text(t)
    print("Patched successfully")
else:
    print("Patch point not found — skipping")
'''


# ── QML controller ─────────────────────────────────────────────────────────────

class BootstrapController(QObject):
    """QML-facing controller for the bootstrap process."""

    progressChanged = pyqtSignal()
    statusMessageChanged = pyqtSignal()
    currentStepChanged = pyqtSignal()
    stepsModelChanged = pyqtSignal()
    isRunningChanged = pyqtSignal()
    isCompleteChanged = pyqtSignal()
    errorMessageChanged = pyqtSignal()

    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self._status_message = ""
        self._current_step = ""
        self._is_running = False
        self._is_complete = False
        self._error_message = ""
        self._worker: Optional[BootstrapWorker] = None
        self._shutting_down = False

        self._steps = _build_steps()
        self._steps_status: dict[str, str] = {}
        for s in self._steps:
            self._steps_status[s["id"]] = "pending"

        self._load_existing_state()

    def _load_existing_state(self):
        if not BOOTSTRAP_FILE.exists():
            return
        try:
            with open(BOOTSTRAP_FILE) as f:
                state = json.load(f)
            for step_id, info in state.get("steps", {}).items():
                status = info.get("status", "pending")
                if status == "in_progress":
                    status = "pending"
                if step_id in self._steps_status:
                    self._steps_status[step_id] = status
        except Exception:
            pass

    # ── Properties ─────────────────────────────────────────────────────────

    @pyqtProperty(float, notify=progressChanged)
    def progress(self):
        return self._progress

    @pyqtProperty(str, notify=statusMessageChanged)
    def statusMessage(self):
        return self._status_message

    @pyqtProperty(str, notify=currentStepChanged)
    def currentStep(self):
        return self._current_step

    @pyqtProperty(bool, notify=isRunningChanged)
    def isRunning(self):
        return self._is_running

    @pyqtProperty(bool, notify=isCompleteChanged)
    def isComplete(self):
        return self._is_complete

    @pyqtProperty(str, notify=errorMessageChanged)
    def errorMessage(self):
        return self._error_message

    @pyqtProperty("QVariantList", notify=stepsModelChanged)
    def stepsModel(self):
        return [
            {
                "stepId": s["id"],
                "label": s["label"],
                "status": self._steps_status[s["id"]],
            }
            for s in self._steps
        ]

    @pyqtProperty(bool, constant=True)
    def hasPartialInstall(self):
        statuses = set(self._steps_status.values())
        return "completed" in statuses and statuses != {"completed"}

    @pyqtProperty(str, constant=True)
    def sizeEstimate(self):
        config = _load_bootstrap_config()
        sizes = config.get("size_estimates", {})

        os_name = platform.system()
        if os_name == "Linux":
            try:
                r = subprocess.run(["nvidia-smi"], capture_output=True)
                if r.returncode == 0:
                    return sizes.get("linux_cuda", "")
            except Exception:
                pass

        return sizes.get("default", "")

    @pyqtProperty(bool, constant=True)
    def needsRestart(self):
        return False

    # ── Slots ──────────────────────────────────────────────────────────────

    @pyqtSlot()
    def startInstall(self):
        if self._is_running:
            return

        self._error_message = ""
        self.errorMessageChanged.emit()
        self._is_running = True
        self.isRunningChanged.emit()

        self._worker = BootstrapWorker()
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_completed.connect(self._on_step_completed)
        self._worker.step_failed.connect(self._on_step_failed)
        self._worker.progress_changed.connect(self._on_progress)
        self._worker.status_message.connect(self._on_status)
        self._worker.all_completed.connect(self._on_all_completed)
        self._worker.install_failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_thread_finished)
        self._worker.start()

    @pyqtSlot()
    def cancelInstall(self):
        if self._worker:
            self._worker.cancel()

    @pyqtSlot()
    def quit(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        if self._worker:
            self._worker.cancel()
            self._worker.wait(5000)
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    @pyqtSlot()
    def proceed(self):
        self._shutting_down = True
        self.finished.emit()

    # ── Signal handlers ────────────────────────────────────────────────────

    def _on_step_started(self, step_id: str, label: str):
        self._current_step = step_id
        self._steps_status[step_id] = "in_progress"
        self.currentStepChanged.emit()
        self.stepsModelChanged.emit()

    def _on_step_completed(self, step_id: str):
        self._steps_status[step_id] = "completed"
        self.stepsModelChanged.emit()

    def _on_step_failed(self, step_id: str, error: str):
        self._steps_status[step_id] = "failed"
        self.stepsModelChanged.emit()

    def _on_progress(self, value: float):
        self._progress = value
        self.progressChanged.emit()

    def _on_status(self, message: str):
        self._status_message = message
        self.statusMessageChanged.emit()

    def _on_all_completed(self):
        self._is_complete = True
        self._is_running = False
        self._status_message = "Done"
        self.isCompleteChanged.emit()
        self.isRunningChanged.emit()
        self.statusMessageChanged.emit()

    def _on_failed(self, message: str):
        self._error_message = message
        self._is_running = False
        self.errorMessageChanged.emit()
        self.isRunningChanged.emit()

    def _on_thread_finished(self):
        self._worker = None
