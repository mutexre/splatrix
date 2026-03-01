# Splatrix Application Architecture

## Overview

Video → Gaussian Splats PLY conversion pipeline with PyQt6 UI.

## Pipeline Stages

### 1. Frame Extraction
- **Implementation**: ffmpeg subprocess (launched by nerfstudio)
- **Location**: `nerfstudio.process_data.video_to_nerfstudio_dataset.VideoToNerfstudioDataset`
- **Output**: `~/.splatrix/nerfstudio/nerfstudio_data/images/`

### 2. COLMAP / Structure from Motion
- **Implementation**: pycolmap Python API via custom wrapper
- **Wrapper**: `/path/to/conda/envs/splatrix/bin/colmap` (Python script)
- **Stages**:
  - Feature extraction: `pycolmap.extract_features()`
  - Feature matching: `pycolmap.match_*()` 
  - Sparse reconstruction: `pycolmap.incremental_mapping()`
- **Output**: `~/.splatrix/nerfstudio/nerfstudio_data/colmap/sparse/0/`

### 3. Training (Splatfacto)
- **Implementation**: nerfstudio Python API (pure Python, no subprocess)
- **Module**: `nerfstudio.engine.trainer.Trainer`
- **Output**: `~/.splatrix/nerfstudio/outputs/unnamed/splatfacto/{timestamp}/`

### 4. Export
- **Implementation**: ns-export CLI (subprocess)
- **Command**: `ns-export gaussian-splat --load-config config.yml`
- **Output**: User-specified PLY file

## Worker Thread Architecture

### NerfstudioWorker (Main Pipeline)
```
PyQt6 Main Thread
    └─> NerfstudioWorker (QThread)
            ├─> nerfstudio Python API
            │       └─> ffmpeg subprocess (frame extraction)
            │       └─> colmap wrapper subprocess → pycolmap
            └─> nerfstudio.Trainer.train() (pure Python, blocking)
            └─> subprocess.run(ns-export) (subprocess)
```

### Termination Handling

**When UI closes (`MainWindow.closeEvent()`):**

1. **Cancel workers**:
   ```python
   worker.cancel()  # Sets _is_cancelled flag
   worker.wait(2000)  # Wait up to 2s for graceful shutdown
   ```

2. **Force terminate if needed**:
   ```python
   if worker.isRunning():
       worker.terminate()  # Calls custom terminate()
   ```

3. **Custom terminate() kills child processes**:
   ```python
   def terminate(self):
       # Find all child processes (ffmpeg, colmap, ns-export)
       children = psutil.Process().children(recursive=True)
       
       # Graceful termination (SIGTERM)
       for child in children:
           child.terminate()
       
       # Wait 1s, then force kill (SIGKILL)
       gone, alive = psutil.wait_procs(children, timeout=1)
       for proc in alive:
           proc.kill()
       
       super().terminate()  # Terminate thread
   ```

### Cancellation Points

**Progress callbacks check `_is_cancelled`:**
```python
def progress_callback(stage, progress):
    if self._is_cancelled:
        raise InterruptedError("Operation cancelled")
    # ... emit progress
```

**Between stages:**
```python
if self._is_cancelled:
    self._emit_cancelled()
    return
```

## Process Tree (During Execution)

```
python run.py (PID 12345)
  └─> NerfstudioWorker thread
        ├─> ffmpeg (frame extraction)  ← killed on terminate()
        ├─> colmap wrapper (Python)
        │     └─> pycolmap (Python)   ← in-process
        └─> ns-export (subprocess)     ← killed on terminate()
```

## Limitations

### Gradual Termination
- **ffmpeg/colmap** may take 1-2 seconds to terminate after UI closes
- This is because they're grandchild processes launched by nerfstudio
- `psutil` tracks and kills them, but there's a brief delay

### Termination Stack Traces (Expected)
**When closing UI during COLMAP phase**, you may see:
```
*** SIGTERM (@0x...) received by PID ... ***
*** Aborted at ... ***
[stack trace from pycolmap]
```

**This is NORMAL and expected:**
- pycolmap is a C++ extension that logs SIGTERM receipts to stderr
- The process IS being terminated successfully
- Stack trace is informational (from C++ signal handler)
- Does not indicate an error or crash
- Can be safely ignored

### Training is Blocking
- `Trainer.train()` is a blocking Python call (no subprocess)
- Can only be interrupted at progress callback checkpoints
- If progress callbacks disabled, training runs to completion
- Our implementation checks `_is_cancelled` every 100 steps

### No Pause/Resume
- Pipeline must run start-to-finish or be cancelled
- No checkpointing between stages (nerfstudio limitation)

## Subprocess Detection

**Process identification:**
- `ffmpeg` - detected by process name
- `colmap` (wrapper) - Python script, detected by command line
- `ns-export` - detected by process name

**Cleanup strategy:**
- Get all children recursively: `psutil.Process().children(recursive=True)`
- Works across subprocess spawned by Python libraries (nerfstudio)
- Ensures no orphaned processes

## Thread Safety

**Signals (PyQt):**
- `progress` / `finished` / `error` signals are thread-safe
- Emitted from worker thread → handled in main thread

**State:**
- `_is_cancelled` flag checked in worker thread only
- No mutex needed (simple boolean, checked frequently)

## UI Stage Mapping

**Progress callback → UI stages:**
```python
if "Data" in stage:
    if "extracting frames" in substage:
        update_stage('frames', 'running', ...)
    elif "COLMAP" in substage:
        update_stage('colmap', 'running', ...)

elif "Training" in stage:
    update_stage('training', 'running', ...)

elif "Export" in stage:
    update_stage('export', 'running', ...)
```

**File browser buttons enabled when:**
- Stage status = 'running' or 'done'
- Path exists: `Path(stage_path).exists()`

## Dependencies

### Python Packages
- `PyQt6` - UI framework
- `psutil` - Process management & termination
- `nerfstudio` - 3D reconstruction & training
- `pycolmap` - COLMAP Python bindings

### System Requirements
- `ffmpeg` - Frame extraction
- `nvcc` / CUDA toolkit - gsplat compilation (GPU training)

## Configuration

**Workspace**: `~/.splatrix/`
```
.splatrix/
  ├── settings.json          # UI settings (last video, etc)
  └── nerfstudio/
      ├── nerfstudio_data/   # Processed data
      │   ├── images/        # Extracted frames
      │   ├── colmap/        # SfM results
      │   └── transforms.json
      └── outputs/           # Training outputs
          └── unnamed/
              └── splatfacto/
                  └── {timestamp}/
                      ├── config.yml
                      └── nerfstudio_models/
```

## Error Handling

**Common failures:**
1. **COLMAP fails** - insufficient overlap, texture, or motion
2. **Training OOM** - reduce resolution or iterations
3. **Export timeout** - model too large (>5min timeout)

**Recovery:**
- Cleanup temp files on error
- Emit error signal to UI
- Provide context-specific hints in log

## Future Improvements

1. **Pause/Resume**: Add checkpoint saving between stages
2. **Real-time streaming**: Replace subprocess with Python API where possible
3. **Progress granularity**: Better tracking within COLMAP/training
4. **Background mode**: Detach pipeline from UI (run in separate process)

