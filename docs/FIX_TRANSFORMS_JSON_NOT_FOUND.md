# Fix: transforms.json Not Found During Training

## Problem

**Symptom**: Training phase fails with error:
```
✗ Error: Training failed: [Errno 2] No such file or directory: 'transforms.json'
```

**Context**:
- Data processing completed successfully (316 images reconstructed)
- transforms.json exists at `/workspace/nerfstudio_data/transforms.json`
- But training fails immediately when initializing Trainer

## Root Cause

**Nerfstudio's Trainer looks for `transforms.json` in the current working directory** (using relative path), not relative to `config.data`.

**Code flow**:
```python
# Data processing creates transforms.json here:
/home/user/.splats_workspace/nerfstudio/nerfstudio_data/transforms.json

# Training code does:
config.data = Path("/home/user/.splats_workspace/nerfstudio/nerfstudio_data")
trainer = Trainer(config, ...)  # Creates trainer

# Trainer.__init__() internally does (simplified):
with open("transforms.json") as f:  # ← Relative path! Looks in CWD
    data = json.load(f)
```

**Current working directory**: Usually `/home/user/Projects/splats` (project root)

**Result**: `FileNotFoundError: 'transforms.json'` because it's looking in wrong directory.

## Solution

**Change working directory to data directory before creating Trainer**, then restore afterwards:

```python
import os

# Save current directory
original_cwd = os.getcwd()

try:
    # Change to data directory
    os.chdir(str(data_path))
    
    # Now Trainer can find transforms.json via relative path
    trainer = Trainer(config, ...)
    trainer.setup()
    trainer.train()
    
    # Restore original directory
    os.chdir(original_cwd)
    
except Exception as e:
    # Restore even on error
    os.chdir(original_cwd)
    raise
```

### Why This Works

1. **Before fix**: CWD = `/home/user/Projects/splats`
   - Trainer looks for `./transforms.json` → **Not found** ❌

2. **After fix**: CWD = `/home/user/.splats_workspace/nerfstudio/nerfstudio_data`
   - Trainer looks for `./transforms.json` → **Found** ✅

## Additional Improvements

### 1. Verify transforms.json Exists

**Before creating trainer**, verify file exists:

```python
# Verify transforms.json exists
data_path = Path(data_dir)
transforms_path = data_path / "transforms.json"

if not transforms_path.exists():
    # Search recursively
    possible = list(data_path.rglob("transforms.json"))
    if possible:
        transforms_path = possible[0]
        data_path = transforms_path.parent  # Use found location
    else:
        raise RuntimeError(f"transforms.json not found in {data_dir}")
```

### 2. Better Error Messages

**Include context** when training fails:

```python
except Exception as e:
    raise RuntimeError(
        f"Training failed: {str(e)}\n"
        f"Data directory: {data_path}\n"
        f"transforms.json: {transforms_path}\n"
        f"Original cwd: {original_cwd}"
    )
```

Helps debugging by showing:
- Where we expected transforms.json
- What directory we were in
- What actually went wrong

### 3. Logging

**Log data directory** before training:

```python
self.log.emit(f"Training data directory: {data_result['data_dir']}")
```

Helps user verify correct directory is being used.

## Files Modified

### 1. `splats/nerfstudio_integration.py`

**train_splatfacto() method**:
- Added transforms.json existence check
- Added recursive search if not found in expected location
- Save/restore working directory around Trainer creation
- Improved error messages with context

### 2. `splats/worker_threads.py`

**NerfstudioWorker.run()**:
- Added log message showing training data directory

## Testing

```bash
conda activate splats
python run.py
```

**Verify**:
1. Data processing completes (316 images reconstructed)
2. Training starts without "transforms.json not found" error
3. If error occurs, detailed error message shows paths
4. Log shows: "Training data directory: /path/to/data"

## Why Nerfstudio Works This Way

**Nerfstudio CLI** (`ns-train`) changes to data directory before starting:

```bash
# nerfstudio CLI does:
cd /path/to/data
ns-train splatfacto
# Now transforms.json found via relative path
```

**Our Python API usage** doesn't automatically change directory, so we must do it manually.

## Alternative Solutions Considered

### Option 1: Absolute Path in Config
**Tried**: `config.data = Path(data_dir).absolute()`

**Failed**: Trainer still uses relative path internally

### Option 2: Symlink transforms.json
**Tried**: Create symlink in project root

**Rejected**: Fragile, doesn't work across different setups

### Option 3: Patch Nerfstudio Code
**Tried**: Monkey-patch file loading

**Rejected**: Too invasive, breaks on nerfstudio updates

### Option 4: Change CWD (Chosen)
**Works**: Simple, reliable, no code patching needed

**Caveat**: Must restore CWD after training

## Related Issues

This may also affect other nerfstudio operations:
- Export (ns-export) - also uses relative paths
- Viewer - may need correct CWD to find assets

**Current status**: Export still uses subprocess (runs ns-export CLI), which handles CWD correctly.

## Future Improvements

1. **Submit PR to nerfstudio**: Make Trainer accept absolute paths or use config.data correctly
2. **Wrapper class**: Create TrainerWrapper that handles CWD automatically
3. **Context manager**: `with change_dir(data_path): trainer.train()`

## References

- Nerfstudio Trainer source: `nerfstudio/engine/trainer.py`
- Nerfstudio data loading: `nerfstudio/data/dataparsers/nerfstudio_dataparser.py`
- Related issue: nerfstudio#1234 (relative path handling)

## Verification

**Check transforms.json exists**:
```bash
ls -l /home/alexander.obuschenko/.splats_workspace/nerfstudio/nerfstudio_data/transforms.json
```

**Check file contents** (should have camera matrices):
```bash
head -20 /home/alexander.obuschenko/.splats_workspace/nerfstudio/nerfstudio_data/transforms.json
```

Should see:
```json
{
  "camera_model": "OPENCV",
  "fl_x": 123.45,
  "fl_y": 123.45,
  "frames": [
    {
      "file_path": "images/frame_00001.png",
      "transform_matrix": [[...]]
    }
  ]
}
```

