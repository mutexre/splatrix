# Subprocess Usage in Pipeline

## Current Architecture: Mostly Python API

The pipeline uses **Python API integration** for most stages, with subprocess calls only for specific utilities.

## Stage-by-Stage Breakdown

### 1. Video Metadata (get_video_info)
**Method**: Python API  
**Tool**: `PyAV` (ffmpeg Python bindings)  
**Why**: Direct ffmpeg library access, no subprocess overhead  
**Location**: `video_processor.py::get_video_info()` and `nerfstudio_video_processor.py::get_video_info()`  
```python
import av
with av.open(video_path) as container:
    video_stream = container.streams.video[0]
    width = video_stream.width
    fps = float(video_stream.average_rate)
```

### 2. Frame Extraction
**Method**: Subprocess (internal to nerfstudio)  
**Tool**: `ffmpeg` CLI  
**Integration**: Via nerfstudio's `VideoToNerfstudioDataset.main()`  
**Why**: Nerfstudio uses ffmpeg internally; we hook into their Python API  
**Our Code**: `nerfstudio_video_processor.py::process_video()`  
**Nerfstudio's Internal Call**: `ffmpeg -i video.mov ... output/images/frame_%05d.png`

**Note**: We don't call ffmpeg directly; we call:
```python
processor = VideoToNerfstudioDataset(...)
processor.main()  # This internally spawns ffmpeg subprocess
```

**Progress Capture**: 
- Directory polling (count extracted frames)
- FD-level stderr capture for ffmpeg progress (if available)

### 3. COLMAP Processing (Feature Extraction, Matching, Reconstruction)
**Method**: Python API  
**Tool**: `pycolmap` Python bindings  
**Integration**: Via nerfstudio's `ImagesToNerfstudioDataset` or `VideoToNerfstudioDataset`  
**Why**: Direct C++ binding, no subprocess overhead  
**Our Code**: Calls nerfstudio Python API which uses pycolmap  

**Inside Nerfstudio's processing**:
```python
# Nerfstudio internally uses:
import pycolmap
database = pycolmap.Database(...)
database.add_camera(...)
pycolmap.extract_features(...)
pycolmap.match_exhaustive_features(...)
pycolmap.incremental_mapping(...)
```

**Progress Capture**: 
- FD-level stderr redirect (C++ extension writes to stderr FD2)
- Parse "Processed file [N/M]", "Processing image [N/M]"

### 4. Training (Gaussian Splatting)
**Method**: Python API  
**Tool**: Nerfstudio's `Trainer` class  
**Integration**: Direct instantiation and method calls  
**Why**: Full control over training loop, progress callbacks  
**Our Code**: `nerfstudio_integration.py::train_splatfacto()`  

```python
from nerfstudio.engine.trainer import Trainer
trainer = Trainer(config, local_rank=0, world_size=1)
trainer.setup()
trainer.train()  # Fully in-process, Python + PyTorch + CUDA
```

**Progress Capture**:
- Hook into `trainer.train_iteration()` method
- Direct progress callbacks every N steps

### 5. PLY Export
**Method**: Subprocess  
**Tool**: `ns-export` CLI  
**Why**: Avoid pymeshlab Qt conflicts in GUI process  
**Our Code**: `nerfstudio_integration.py::export_gaussian_splat()`  

```python
subprocess.run([
    "ns-export", "gaussian-splat",
    "--load-config", config_path,
    "--output-dir", output_dir
], capture_output=True, text=True, timeout=300)
```

**Note**: Could be converted to Python API but kept as subprocess to isolate potential Qt/GUI conflicts from pymeshlab dependency.

## Summary Table

| Stage | Method | Tool | Reason for Choice |
|-------|--------|------|-------------------|
| Video metadata | Python API | PyAV | Direct ffmpeg library access, no subprocess |
| Frame extraction | Subprocess (via nerfstudio) | ffmpeg | Nerfstudio uses ffmpeg internally |
| COLMAP feature extraction | Python API | pycolmap | Direct C++ binding, better integration |
| COLMAP matching | Python API | pycolmap | Direct C++ binding, better integration |
| COLMAP reconstruction | Python API | pycolmap | Direct C++ binding, better integration |
| Training | Python API | Trainer | Full control, progress hooks, GPU ops |
| PLY Export | Subprocess | ns-export | Avoid pymeshlab Qt conflicts |

## Process Hierarchy During Training

```
python run.py (GUI process)
├─ QThread: NerfstudioWorker
   ├─ NerfstudioPipeline.process_video_data()
   │  └─ VideoToNerfstudioDataset.main()
   │     └─ [subprocess] ffmpeg -i video.mov ...  ← SUBPROCESS
   │
   ├─ NerfstudioPipeline.train_splatfacto()
   │  └─ Trainer(config).train()  ← PYTHON API (PyTorch CUDA kernels)
   │
   └─ NerfstudioPipeline.export_gaussian_splat()
      └─ [subprocess] ns-export gaussian-splat ...  ← SUBPROCESS
```

## Subprocess Detection for Cancellation

The `NerfstudioWorker.terminate()` method uses `psutil` to find and kill all child processes:

```python
import psutil
current_process = psutil.Process(os.getpid())
children = current_process.children(recursive=True)

for child in children:
    child.terminate()  # SIGTERM
    
# Wait, then force kill if needed
gone, alive = psutil.wait_procs(children, timeout=1)
for proc in alive:
    proc.kill()  # SIGKILL
```

This catches:
- `ffmpeg` processes (frame extraction)
- `ns-export` processes (PLY export)
- Any other spawned processes

## Why Not All Python API?

### ffmpeg (Frame Extraction)
- No mature Python ffmpeg binding for complex filter graphs
- ffmpeg-python exists but still spawns subprocess
- PyAV alternative implemented (`pyav_video_processor.py`) for users wanting pure Python

### ns-export (PLY Export)
- Could use direct model checkpoint loading + PLY writing
- Kept as subprocess to:
  1. Isolate pymeshlab (Qt conflicts with PyQt6 GUI)
  2. Use nerfstudio's tested export path
  3. Handle multiple export formats (PLY, splat, ply-mesh)
  
### Future: Could convert export to Python API if needed

## Benefits of Current Hybrid Approach

### Python API Stages (COLMAP, Training)
✅ Better progress reporting (direct callbacks)  
✅ No subprocess buffering issues  
✅ Faster (no IPC overhead)  
✅ Better error handling  
✅ GPU operations stay in same process  

### Subprocess Stages (ffmpeg, ns-export)
✅ Proven, battle-tested tools  
✅ Isolation from main process  
✅ Easy to swap implementations  
✅ No Qt/GUI conflicts  

## Verification

**Check which processes are subprocesses:**
```bash
# During frame extraction:
ps aux | grep ffmpeg
# Should show: ffmpeg -i video.mov ...

# During training:
ps aux | grep -E 'python.*splats|train'
# Should show: python run.py (NO separate training subprocess)

# During export:
ps aux | grep ns-export
# Should show: ns-export gaussian-splat ...
```

**Check nvidia-smi for GPU processes:**
```bash
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```
Should show:
- During training: Same PID as `python run.py` (in-process, not subprocess)
- GPU memory used directly by GUI process's QThread

## Historical Context

**Original Design** (v1): All subprocesses
- ffmpeg subprocess
- colmap CLI subprocess  
- ns-train CLI subprocess
- ns-export CLI subprocess

**Current Design** (v2): Hybrid
- Moved COLMAP to pycolmap Python API
- Moved training to Trainer Python API
- Kept ffmpeg/export as subprocess

**Reason for Change**: Subprocess output buffering made progress reporting unreliable and jumpy. Python API gives direct control.

**Result**: Continuous, real-time progress updates during feature extraction, matching, and training.

