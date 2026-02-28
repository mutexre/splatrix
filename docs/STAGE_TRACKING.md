# Stage Tracking & Progress Display

## UI Enhancements

### Stage Panels
Each pipeline stage now has a dedicated panel showing:
- **Status icon**: ⚪ pending, 🔵 running, ✅ done, ❌ error
- **Progress info**: Current count/percentage
- **File browser button**: Opens system file browser to stage outputs

### Stages

UI now has **6 separate stage panels** for detailed progress tracking:

#### 1. Frame Extraction
- **Panel Title**: "1. Frame Extraction"
- **Progress**: `N frames`
- **Detection**: Directory monitoring of `images/` folder
- **Method**: Background thread counts `frame_*.png` files every 500ms
- **Why**: ffmpeg is subprocess - output bypasses Python print hooks
- **Updates**: When frame count increases
- **Output**: `~/.splats_workspace/nerfstudio/nerfstudio_data/images/`

#### 2. Feature Extraction (COLMAP Phase 1)
- **Panel Title**: "2. Feature Extraction"
- **Progress**: `N/M` (e.g., "150/317")
- **Details**: "Extracting SIFT features (47%)"
- **Detection**: `"Processed file [N/M]"` from COLMAP stderr
- **Source**: `pycolmap.extract_features()` → C++ extension logs to stderr FD
- **Capture Method**: File descriptor redirection (see below)
- **Updates**: Every image processed
- **Output**: `~/.splats_workspace/nerfstudio/nerfstudio_data/colmap/`

#### 3. Feature Matching (COLMAP Phase 2)
- **Panel Title**: "3. Feature Matching"
- **Progress**: `N/M` (e.g., "100/317")
- **Details**: "Matching features between images (32%)"
- **Detection**: `"Processing image [N/M]"` from COLMAP stderr
- **Source**: `pycolmap.match_sequential()` → C++ pairing code
- **Capture Method**: File descriptor redirection
- **Updates**: Every image pair matched
- **Output**: `~/.splats_workspace/nerfstudio/nerfstudio_data/colmap/`

#### 4. Sparse Reconstruction (COLMAP Phase 3)
- **Panel Title**: "4. Sparse Reconstruction"
- **Progress**: `N images` (e.g., "150 images")
- **Details**: "Registering images and building 3D structure"
- **Detection**: 
  - `"Registering image ... num_reg_frames=N"` for image count
  - `"Done COLMAP bundle adjustment"` for bundle adjustment
  - `"Done refining intrinsics"` for refinement
- **Source**: `pycolmap.incremental_mapping()` → incremental pipeline
- **Capture Method**: File descriptor redirection
- **Updates**: Each image registered, bundle adjustment phases
- **Sub-phases**:
  - Image registration (reports registered count)
  - Bundle adjustment (optimization)
  - Refining intrinsics (camera parameter refinement)
- **Output**: `~/.splats_workspace/nerfstudio/nerfstudio_data/colmap/sparse/0/`

#### 5. Training (Splatfacto)
- **Progress**: `Training: Step N/M`
- **Detection**: Hook into `trainer.train_iteration()`
- **Updates**: Every 100 steps (or significant milestones)
- **Output**: `~/.splats_workspace/nerfstudio/outputs/unnamed/splatfacto/{timestamp}/`

#### 6. Export PLY
- **Progress**: Stage name + percentage
- **Detection**: `ns-export` subprocess monitoring
- **Output**: User-specified PLY file path

## Progress Tracking Implementation

### COLMAP Progress Capture

**Challenge**: COLMAP C++ extension writes to stderr file descriptor (FD 2) directly, bypassing Python's `sys.stderr.write`.

**Solution**: Redirect stderr FD to pipe and read in background thread:

```python
import os, select, fcntl

# Duplicate stderr FD and create pipe
original_stderr_fd = os.dup(2)
stderr_pipe_read, stderr_pipe_write = os.pipe()
os.dup2(stderr_pipe_write, 2)  # Redirect FD 2 to pipe

# Make read end non-blocking
fcntl.fcntl(stderr_pipe_read, fcntl.F_SETFL, os.O_NONBLOCK)

def read_stderr():
    while active:
        ready, _, _ = select.select([stderr_pipe_read], [], [], 0.1)
        if ready:
            data = os.read(stderr_pipe_read, 4096)
            text = data.decode('utf-8')
            # Parse for "Processed file [N/M]", "Processing image [N/M]", etc.
            if "Processed file" in text:
                progress_callback(f"Extracting features [{N}/{M}]", ...)
            
threading.Thread(target=read_stderr, daemon=True).start()
```

**Why FD redirection?**
- pycolmap is C++ extension compiled with Python bindings
- C++ code uses `std::cerr` → writes to file descriptor 2
- Python's `sys.stderr.write` only intercepts Python-level writes
- Must redirect at OS level to capture C++ output

### Frame Extraction Progress

**Challenge**: ffmpeg is subprocess - output doesn't go through Python print hooks.

**Solution**: Monitor images directory in background thread:

```python
def monitor_frames():
    images_dir = workspace / "images"
    while active:
        frame_files = list(images_dir.glob("frame_*.png"))
        count = len(frame_files)
        progress_callback(f"Extracting frames: {count}", ...)
        time.sleep(0.5)  # Check every 500ms

threading.Thread(target=monitor_frames, daemon=True).start()
```

### Training Progress

**Challenge**: Trainer.train() is blocking.

**Solution**: Hook training iteration:

```python
original_train_iteration = trainer.train_iteration

def tracked_train_iteration(step: int):
    result = original_train_iteration(step)
    if step % 100 == 0:  # Report every 100 steps
        progress_callback(f"Step {step}/{max_iterations}", ...)
    return result

trainer.train_iteration = tracked_train_iteration
```

## Termination Behavior

### When UI Closes

**Sequence:**
1. `MainWindow.closeEvent()` called
2. `worker.cancel()` sets `_is_cancelled` flag
3. Progress callbacks raise `InterruptedError`
4. `worker.wait(2000)` waits for graceful exit
5. If still running → `worker.terminate()` called
6. `worker.terminate()` kills child processes via `psutil`

### Process Kill Chain

```python
# Find all child processes
children = psutil.Process().children(recursive=True)

# Send SIGTERM (graceful)
for child in children:
    child.terminate()

# Wait 1 second
gone, alive = psutil.wait_procs(children, timeout=1)

# Send SIGKILL (force) to survivors
for proc in alive:
    proc.kill()
```

### Expected Output During Termination

**COLMAP/pycolmap:**
```
*** SIGTERM (@0x...) received by PID ... ***
*** Aborted at ... ***
[C++ stack trace]
```
**This is NORMAL** - pycolmap C++ code logs signal receipt. Process is terminated successfully.

**ffmpeg:**
```
[... frame processing ...]
^C
```
Terminates quickly, may show partial frame info.

**Training:**
- Stops at next progress callback (within 100 steps)
- No stack trace (pure Python)

**Export:**
- Subprocess killed mid-execution
- Temp files cleaned up

## UI Update Flow

```
nerfstudio API
  └─> progress_callback("stage", progress)
      └─> worker.progress.emit({...})
          └─> main_window._on_nerfstudio_progress({...})
              └─> _update_stage(stage_key, status, info, ...)
                  ├─> Update status icon
                  ├─> Update info label
                  ├─> Update details (optional)
                  ├─> Set file path
                  └─> Enable browse button
```

## File Browser Access

**Button enabled when:**
- Path is set via `_update_stage(..., path="/some/path")`
- Directory exists

**Opens:**
- System file browser (Nautilus/Dolphin/Finder)
- Direct navigation to stage output directory

**Paths:**
- Frames: `images/` directory
- COLMAP: `colmap/` directory (contains `database.db`, `sparse/0/`)
- Training: `outputs/` directory
- Export: Parent directory of PLY file

## Progress Update Frequency

**Frame extraction**: Every 500ms (directory monitoring)
**Feature extraction**: Every image (317 total for test video)
**Feature matching**: Every image pair (317 total for test video)  
**Reconstruction**: Every registered image (~317 total)
**Training**: Every 100 steps (default 30,000 total)
**Export**: Start, middle, end (3 updates typical)

## Deduplication

**Prevents spam:**
- `last_reported` dict tracks last value per metric
- Only emit when value changes
- Filters spinner/animation characters from log

**Example:**
```python
if frame_num % 10 == 0 and last_reported.get('frame') != frame_num:
    progress_callback(...)
    last_reported['frame'] = frame_num
```

