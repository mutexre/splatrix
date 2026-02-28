# Fix: Silent Feature Extraction Phase

## Problem

**Symptom**: UI showed no progress updates during COLMAP feature extraction/matching phases.

**Root Cause**: COLMAP (pycolmap) is a C++ extension that logs to stderr using `std::cerr`. This writes directly to file descriptor 2, **bypassing Python's `sys.stderr.write`**.

### Why `sys.stderr.write` Hook Didn't Work

```python
# ❌ This DOESN'T capture C++ stderr output
sys.stderr.write = my_custom_function

# C++ code does:
std::cerr << "Processing image [10/100]" << std::endl;
# ^ Goes directly to FD 2, never calls sys.stderr.write()
```

**Python vs C++ stderr**:
- **Python**: `sys.stderr.write()` → Python-level IO buffering → eventually to FD 2
- **C++ extension**: `std::cerr` → C stdio → **directly to FD 2**

When you hook `sys.stderr.write`, you only intercept Python writes. C++ writes bypass this entirely.

## Solution

**Redirect stderr file descriptor to a pipe and read from it in a background thread.**

### Implementation

```python
import os, select, fcntl, threading

# 1. Duplicate original stderr FD (save it)
original_stderr_fd = os.dup(2)

# 2. Create pipe
stderr_pipe_read, stderr_pipe_write = os.pipe()

# 3. Redirect stderr FD to pipe write-end
os.dup2(stderr_pipe_write, 2)  # Now all writes to FD 2 go to pipe

# 4. Make read-end non-blocking
fcntl.fcntl(stderr_pipe_read, fcntl.F_SETFL, os.O_NONBLOCK)

# 5. Read from pipe in background thread
def read_stderr():
    while active:
        ready, _, _ = select.select([stderr_pipe_read], [], [], 0.1)
        if ready:
            data = os.read(stderr_pipe_read, 4096)
            text = data.decode('utf-8')
            
            # Parse COLMAP progress messages
            if "Processed file" in text:
                # Extract [N/M] and report progress
                ...
            
            # Write to original stderr (for logging)
            os.write(original_stderr_fd, data)

threading.Thread(target=read_stderr, daemon=True).start()
```

### Why This Works

- **FD 2 redirection**: All writes to stderr (Python AND C++) now go to our pipe
- **Background reader**: Continuously reads from pipe without blocking main thread
- **select()**: Efficiently waits for data with 100ms timeout
- **Non-blocking read**: Prevents deadlock if no data available
- **Line buffering**: Accumulates partial lines, processes complete lines

### Cleanup

```python
# Restore stderr FD
os.dup2(original_stderr_fd, 2)
os.close(original_stderr_fd)
os.close(stderr_pipe_read)
os.close(stderr_pipe_write)
```

## Results

**Before**:
```
Frame Extraction: 100%
[SILENCE for 2-3 minutes]
Training: 1%
```

**After**:
```
Frame Extraction: 100%
COLMAP: Extracting features [1/317]
COLMAP: Extracting features [50/317]
COLMAP: Extracting features [100/317]
...
COLMAP: Extracting features [317/317]
Feature extraction complete
COLMAP: Matching features [1/317]
COLMAP: Matching features [50/317]
...
Training: 1%
```

## Files Modified

- **`splats/nerfstudio_video_processor.py`**:
  - Replaced `sys.stderr.write` hook with FD redirection
  - Added `read_stderr()` background thread
  - Updated cleanup to restore FD and close pipes

- **`STAGE_TRACKING.md`**:
  - Updated COLMAP progress capture documentation
  - Explained why FD redirection is necessary

## Testing

```bash
conda activate splats
cd /home/alexander.obuschenko/Projects/splats
python run.py

# Select video, start conversion with Nerfstudio processor
# Watch for progress during feature extraction phase
# Should see continuous "[N/M]" updates
```

## Technical Notes

### File Descriptor Operations

- **`os.dup(fd)`**: Duplicate FD (creates new FD pointing to same underlying resource)
- **`os.dup2(src, dst)`**: Make `dst` point to same resource as `src`
- **`os.pipe()`**: Create unidirectional pipe (read FD, write FD)

### Why Non-Blocking?

Without `O_NONBLOCK`, `os.read()` blocks until data available. If writer closes pipe before reader calls read(), reader blocks forever. Non-blocking + select() prevents this.

### Why select()?

`select()` waits for FD to become readable (with timeout). More efficient than busy-wait polling. Returns immediately if data available.

### Buffer Management

COLMAP may write partial lines (no trailing `\n`). We accumulate in buffer:
```python
stderr_buffer = []

# Append new data
stderr_buffer.append(new_text)
full_text = ''.join(stderr_buffer)

# Split by \n, keep last incomplete line
lines = full_text.split('\n')
if not full_text.endswith('\n'):
    stderr_buffer = [lines[-1]]  # Incomplete line
    lines = lines[:-1]
else:
    stderr_buffer = []
```

### Thread Safety

- **FD operations**: Thread-safe (kernel handles synchronization)
- **Python callback**: Called from reader thread, must be thread-safe
  - Our `progress_callback` emits pyqtSignal → thread-safe

## References

- **Python os module**: https://docs.python.org/3/library/os.html#file-descriptor-operations
- **select module**: https://docs.python.org/3/library/select.html
- **fcntl module**: https://docs.python.org/3/library/fcntl.html
- **pycolmap**: https://github.com/colmap/pycolmap (C++ bindings)

## Lessons Learned

1. **Never assume Python hooks capture everything** - C extensions bypass Python-level IO
2. **File descriptor redirection is the only reliable way** to capture C++ stderr
3. **Always test with actual workload** - this bug only appeared during real COLMAP runs
4. **Background threads + select()** = efficient non-blocking IO monitoring
5. **Line buffering is essential** when parsing streaming output

