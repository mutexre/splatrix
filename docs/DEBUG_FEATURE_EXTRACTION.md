# Debug: Feature Extraction Progress Not Showing

## Changes Made

Added **debug logging** to stderr capture to diagnose why feature extraction progress isn't updating the UI.

### 1. Better Error Handling

**Before**:
```python
except Exception:
    pass  # Silent failure - bad!
```

**After**:
```python
except Exception as e:
    import traceback
    error_msg = f"stderr reader error: {e}\n{traceback.format_exc()}"
    os.write(original_stderr_fd, error_msg.encode())  # Log to console
```

Now errors in the stderr reader thread will be visible.

### 2. Debug Messages

Added **debug output** to trace execution:

```python
# When stderr reader starts
os.write(original_stderr_fd, b"[DEBUG] stderr reader thread started\n")

# When feature extraction message is caught
if "Processed file" in line:
    os.write(original_stderr_fd, f"[DEBUG] Caught feature extraction: {line}\n".encode())
```

## Testing

```bash
conda activate splats
python run.py
# Select video and start conversion
```

**Watch console output for**:

### 1. Stderr Reader Status
```
[DEBUG] stderr reader thread started
```
**If missing**: stderr reader thread not starting properly.

### 2. Feature Extraction Messages
```
[DEBUG] Caught feature extraction: Processed file [50/317]
[DEBUG] Caught feature extraction: Processed file [51/317]
...
```
**If missing**: COLMAP messages aren't being captured or format doesn't match.

### 3. Error Messages
```
stderr reader error: [exception details]
```
**If present**: indicates what's failing in stderr capture.

## Possible Issues

### Issue 1: COLMAP Message Format Changed

**Symptom**: No `[DEBUG] Caught feature extraction` messages

**Solution**: Check actual COLMAP output format. May need to adjust regex pattern.

**Current pattern**:
```python
if "Processed file" in line:
    match = re.search(r'\[(\d+)/(\d+)\]', line)
```

**Possible alternatives**:
- `"Processing file"` instead of `"Processed file"`
- Different bracket format
- Multi-line messages

### Issue 2: Stderr Not Being Redirected

**Symptom**: No stderr output at all during feature extraction

**Possible causes**:
- COLMAP writing to stdout instead of stderr
- Buffering issues (stderr not flushed)
- pycolmap version differences

**Solution**: Capture both stdout and stderr

### Issue 3: Thread Timing

**Symptom**: Reconstruction phase works but feature extraction doesn't

**Possible cause**: stderr reader starts too late or stops too early

**Solution**: Verify thread lifecycle with debug messages

## Manual Test

Run COLMAP directly to see actual output format:

```bash
conda activate splats

# Create test directory
mkdir -p /tmp/colmap_test/{images,database}

# Copy some frames
cp ~/.splats_workspace/nerfstudio/nerfstudio_data/images/frame_*.png /tmp/colmap_test/images/ 2>/dev/null | head -10

# Run pycolmap feature extraction (this is what our code does)
python3 -c "
import pycolmap
from pathlib import Path

db_path = '/tmp/colmap_test/database/database.db'
img_path = '/tmp/colmap_test/images'

print('Starting feature extraction...')
pycolmap.extract_features(
    database_path=db_path,
    image_path=img_path,
    camera_mode=pycolmap.CameraMode.SINGLE
)
print('Done')
" 2>&1 | grep -i "process"
```

**Look for**:
- Exact message format (case, wording, brackets)
- Whether messages go to stdout or stderr
- Message frequency (every file, every N files, only at end)

## Quick Fix: Fallback to Directory Polling

If stderr capture proves unreliable, can fall back to **polling COLMAP database**:

```python
def monitor_colmap_progress():
    """Monitor COLMAP database for progress"""
    import sqlite3
    
    db_path = colmap_dir / "database.db"
    while active:
        try:
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                cursor = conn.execute("SELECT COUNT(*) FROM images")
                count = cursor.fetchone()[0]
                conn.close()
                
                if count > last_count:
                    progress_callback(f"Feature extraction: {count} images", ...)
                    last_count = count
        except:
            pass
        time.sleep(0.5)
```

More reliable but less granular than stderr capture.

## Expected Output

**Working correctly**:
```
[DEBUG] stderr reader thread started
Extracting frames: 100
Extracting frames: 200
Extracting frames: 300
[DEBUG] Caught feature extraction: Processed file [1/317]
COLMAP: Extracting features [1/317]
[DEBUG] Caught feature extraction: Processed file [50/317]
COLMAP: Extracting features [50/317]
...
[DEBUG] Caught feature extraction: Processed file [317/317]
COLMAP: Extracting features [317/317]
Feature extraction complete
```

**Broken stderr capture**:
```
Extracting frames: 300
[silence for 2-3 minutes]
COLMAP: Reconstruction [50 images]
COLMAP: Reconstruction [100 images]
```

## Next Steps

1. **Run with debug enabled** and provide console output
2. **Check for debug messages** to narrow down issue
3. **If no messages appear**, may need alternative approach (database polling or nerfstudio API hooks)
4. **Once diagnosed**, remove debug output and implement proper fix

## Files Modified

- `splats/nerfstudio_video_processor.py`:
  - Better exception handling in stderr reader
  - Debug output at key points
  - Better error reporting

**No linter errors.**

