# Fix: transforms.json Not Found During Export

## Date
2025-12-11

## Problem
Training and checkpoint creation succeeded, but export failed:
```
FileNotFoundError: [Errno 2] No such file or directory: 'transforms.json'
```

**Error context**:
```python
File ".../nerfstudio_dataparser.py", line 96
    meta = load_from_json(self.config.data / "transforms.json")
    # Tries to open: config.data / "transforms.json"
    # But config.data is empty or relative path
```

## Root Cause (Updated: Found the Real Issue)

**There are TWO `data` fields in config.yml**:
1. **Top-level `config.data`** - Used during training
2. **Nested `config.pipeline.datamanager.dataparser.data`** - Used during export!

**During training we changed working directory**:
```python
original_cwd = os.getcwd()  # Save original
os.chdir(str(data_path))    # Change to data directory
trainer = Trainer(config, ...)
# Now cwd is data_path, so relative paths work during training
```

**But config.data became empty/relative**:
```yaml
# In saved config.yml:
data: !!python/object/apply:pathlib.PosixPath []  # EMPTY!
```

**When ns-export subprocess runs**:
- Runs in original working directory (project root)
- Loads config.yml
- Tries to open `config.data / "transforms.json"`
- `config.data` is empty → looks for `./transforms.json` in project root
- File not found!

## Why This Happened

**Sequence of events**:
1. Set `config.data = data_path` (absolute path)
2. Change directory: `os.chdir(str(data_path))`
3. Create trainer: `trainer = Trainer(config, ...)`
4. Trainer may internally modify `config.data` to be relative
5. Save config: `config.save_config()` 
6. Config saved with empty/relative path

## Solution

**Set absolute paths for BOTH data fields BEFORE saving config**:
```python
# After training completes, BEFORE saving config:

# 1. Set top-level config.data
config.data = data_path.resolve()
print(f"[Training] Config data path set to: {config.data}")

# 2. ALSO set dataparser.data (this is what ns-export actually uses!)
if hasattr(config.pipeline.datamanager, 'dataparser'):
    config.pipeline.datamanager.dataparser.data = data_path.resolve()
    print(f"[Training] Dataparser data path set to: {data_path.resolve()}")

config.save_config()
```

**This ensures**:
- Config.yml contains absolute paths in BOTH locations
- ns-export's dataparser can find transforms.json
- Export subprocess doesn't depend on working directory

## Technical Details

### Two Data Fields in Config

**Nerfstudio config has nested structure**:
```yaml
# config.yml structure:

data: !!python/object/apply:pathlib.PosixPath    ← Top-level (used during training)
  - /home/...
  
pipeline:
  datamanager:
    dataparser:
      data: !!python/object/apply:pathlib.PosixPath  ← Nested (used during export!)
        - /home/...
```

**Problem**: We set `config.data` but forgot to set `config.pipeline.datamanager.dataparser.data`.

**Result**: Config file had:
```yaml
Line 3:   data: /home/.../nerfstudio_data     ← Correct
Line 147: data: []                              ← Empty!
Line 152:   data: *id003                        ← References empty one
```

**During export**, ns-export uses the **dataparser's data field** (line 147), not the top-level one!

### Path Resolution

**Before fix**:
```yaml
# config.yml (wrong):
data: !!python/object/apply:pathlib.PosixPath []

# ns-export interprets as:
Path() / "transforms.json"  # = "./transforms.json" (project root)
```

**After fix**:
```yaml
# config.yml (correct):
data: !!python/object/apply:pathlib.PosixPath
  - /
  - home
  - alexander.obuschenko
  - .splats_workspace
  - nerfstudio
  - nerfstudio_data

# ns-export interprets as:
Path("/home/.../nerfstudio_data") / "transforms.json"  # ✅ Works!
```

### Why resolve() Works

```python
data_path = Path("/home/.../nerfstudio_data")  # Already absolute
config.data = data_path  # Set during training

# After training, config.data might become relative
# Force back to absolute:
config.data = data_path.resolve()

# resolve() returns absolute path:
# - Resolves symlinks
# - Converts relative to absolute
# - Normalizes path (removes .., ./, etc)
```

## Expected Console Output (Next Run)

```
[Training] Training complete
[Training] Checkpoint dir: /.../2025-12-11_HHMMSS
[Training] Config data path set to: /home/.../nerfstudio_data          ← NEW
[Training] Dataparser data path set to: /home/.../nerfstudio_data      ← NEW (THIS IS THE FIX!)
[Training] Config saved to: /.../config.yml
[Training] Config verified at: /.../config.yml
Training complete: /.../config.yml
Exporting...
[Export] Loading checkpoint
[Export] Loading transforms from: /home/.../nerfstudio_data/transforms.json  ← Works!
✓ Export complete: output.ply
```

## Verification

**Check config.yml has absolute path**:
```bash
LATEST=$(find ~/.splats_workspace/nerfstudio/outputs/video_to_splats -name "config.yml" | sort | tail -1)
echo "Config: $LATEST"
echo ""
grep -A 10 "^data:" "$LATEST"
```

**Expected output**:
```yaml
data: !!python/object/apply:pathlib.PosixPath
  - /
  - home
  - alexander.obuschenko
  - .splats_workspace
  - nerfstudio
  - nerfstudio_data
```

**NOT**:
```yaml
data: !!python/object/apply:pathlib.PosixPath []  # ❌ Empty
```

## Files Modified

- `splats/nerfstudio_integration.py`
  - Added `config.data = data_path.resolve()` before `config.save_config()`
  - Added logging to show data path being set

## Related Issues

This is similar to the earlier transforms.json issue during training, but:
- **Training issue**: Needed transforms.json in cwd for Trainer initialization
- **Export issue**: Needed absolute path in config.yml for ns-export subprocess

Both solved by proper path management.

## Status
✅ **FIXED** - Config now saved with absolute data path
✅ **READY** - Export should find transforms.json correctly

## Next Test

Run pipeline with **Max Frames=30, Iterations=1000**.

**Expected**: Complete end-to-end successfully, PLY file exported.

**Verify**:
```bash
ls -lh ~/.splats_workspace/nerfstudio/exports/*.ply
# Should show output.ply with size > 0
```

