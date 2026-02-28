# Fix: Cancel Button Not Working

## Date
2025-12-11

## Problem
Cancel button in UI did not properly stop running operations:
- Button appeared enabled during processing
- Clicking Cancel didn't terminate child processes (ffmpeg, COLMAP, training)
- Processes continued running after Cancel clicked
- UI remained in "processing" state after cancel

## Root Causes

### 1. Incomplete Cancellation Logic
Old `_on_cancel()` only set cancel flags but didn't:
- Wait for threads to stop
- Force terminate if threads didn't stop gracefully
- Handle all worker types (export_worker was missing)

### 2. Button State Logic Issue
`_update_button_states()` checked if workers exist (not None) instead of checking if they're actively running:
```python
# BAD: workers exist even after finishing
is_processing = self.nerfstudio_worker is not None

# GOOD: check if actually running
is_processing = self.nerfstudio_worker is not None and self.nerfstudio_worker.isRunning()
```

## Solution Applied

### 1. Enhanced `_on_cancel()` Method
Now matches `closeEvent()` termination logic:

```python
def _on_cancel(self):
    # For each worker:
    # 1. Call cancel() to set flag
    # 2. Wait up to 2s for graceful shutdown
    # 3. If still running, call terminate() to kill processes
    # 4. Wait additional time for forced termination
    
    if self.nerfstudio_worker and self.nerfstudio_worker.isRunning():
        self.nerfstudio_worker.cancel()
        self.nerfstudio_worker.wait(2000)  # Wait 2s
        if self.nerfstudio_worker.isRunning():
            self.nerfstudio_worker.terminate()  # Kill child processes
            self.nerfstudio_worker.wait(1000)
```

**Handles all worker types**:
- `nerfstudio_worker` (frame extraction, COLMAP, training)
- `video_worker` (standalone frame extraction)
- `reconstruction_worker` (standalone reconstruction)
- `export_worker` (PLY export)

### 2. Fixed `_update_button_states()`
Changed worker existence check to running check:

```python
is_processing = (
    (self.nerfstudio_worker is not None and self.nerfstudio_worker.isRunning()) or
    (self.video_worker is not None and self.video_worker.isRunning()) or
    (self.reconstruction_worker is not None and self.reconstruction_worker.isRunning()) or
    (self.export_worker is not None and self.export_worker.isRunning())
)
```

### 3. Stage Reset on Cancel
All pipeline stages reset to idle state with "Cancelled" status when Cancel clicked.

## Verification

**Test procedure**:
1. Start pipeline (frame extraction → COLMAP → training)
2. Click Cancel during any stage
3. **Expected behavior**:
   - Log shows "⚠ Cancelling operations (terminating processes)..."
   - Within 2-3 seconds: "✓ Operations cancelled"
   - All stage indicators show "Cancelled"
   - Cancel button becomes disabled
   - Start button becomes enabled again
   - No orphaned ffmpeg/colmap/training processes remain

**Check for orphaned processes**:
```bash
ps aux | grep -E 'ffmpeg|colmap|python.*nerfstudio'
# Should show no related processes after cancel
```

## Known Side Effects

**SIGTERM stack traces from pycolmap**: When terminating COLMAP processes (C++ extension), you may see stack traces on stderr. These are **cosmetic only** and indicate successful termination. They appear because:
- pycolmap is a C++ extension
- SIGTERM interrupts C++ code mid-operation
- C++ stack unwinding prints to stderr FD2 (bypasses Python stderr hooks)

**Visual appearance**:
```
Fatal Python error: Aborted
Thread 0x... (most recent call first):
  ...stack trace from pycolmap...
```

**This is normal and expected.** Processes are terminated successfully.

## Status
✅ **RESOLVED** - Cancel button now properly:
- Terminates all child processes (ffmpeg, COLMAP, training)
- Updates UI state correctly
- Enables Start button for restarting
- Clears all stage progress indicators

## Related Files
- `splats/main_window.py`: `_on_cancel()` and `_update_button_states()`
- `splats/worker_threads.py`: `NerfstudioWorker.terminate()` (already had proper process killing)

