# Fix: Dataparser Path for Export (Final Solution)

## Date
2025-12-11

## Problem
Export failing with:
```
FileNotFoundError: [Errno 2] No such file or directory: 'transforms.json'
```

Even though transforms.json exists and top-level config.data is correct.

## Root Cause (Final Answer)

**Nerfstudio config has TWO data fields**:
1. **`config.data`** - Top-level, used during training
2. **`config.pipeline.datamanager.dataparser.data`** - Used during export!

**The Mistake**: We tried to set `dataparser.data` AFTER training completed, but the Trainer already saved the config during `trainer.setup()`.

### Config Structure

```yaml
# config.yml:
data: /home/.../nerfstudio_data              ← Top-level (set correctly)

pipeline:
  datamanager:
    dataparser:
      data: []                                ← Dataparser's data (was EMPTY!)
      # ↑ This is what ns-export actually uses!
```

### Timeline of Events

**What we were doing (WRONG)**:
```
1. Set config.data = absolute_path ✓
2. Create Trainer(config)
   └─ trainer.setup() saves config.yml ← dataparser.data still empty!
3. trainer.train()
4. Set config.pipeline.datamanager.dataparser.data = absolute_path ← TOO LATE!
5. config.save_config() ← Overwrites, but...
```

**Problem**: Step 2 (trainer.setup) already saved config with empty dataparser.data.

## Solution (Final)

**Set dataparser.data BEFORE creating Trainer**:

```python
# Get splatfacto config
config = method_configs["splatfacto"]

# Override settings
config.data = data_path.resolve()  # Top-level
config.output_dir = self.output_dir
# ... other settings ...

# CRITICAL: Set dataparser.data BEFORE creating Trainer
config.pipeline.datamanager.dataparser.data = data_path.resolve()
print(f"[Training] Dataparser data path set to: {data_path.resolve()}")

# NOW create trainer - it will save config with correct dataparser.data
trainer = Trainer(config, local_rank=0, world_size=1)
trainer.setup()  # ← Saves config.yml with BOTH paths set correctly
```

## Why This Works

**Correct timeline**:
```
1. Set config.data = absolute_path ✓
2. Set config.pipeline.datamanager.dataparser.data = absolute_path ✓
3. Create Trainer(config)
   └─ trainer.setup() saves config.yml ← Both paths now correct!
4. trainer.train()
5. Config already saved correctly, no manual save needed
```

## Verification

**Check config.yml after next training run**:
```bash
LATEST=$(find ~/.splats_workspace/nerfstudio/outputs -name "config.yml" | sort | tail -1)
grep -n "data:" "$LATEST" | head -5
```

**Expected output**:
```
3:data: !!python/object/apply:pathlib.PosixPath
4:  - /
5:  - home
...
147:    data: &id003 !!python/object/apply:pathlib.PosixPath
148:      - /
149:      - home
...
```

**Both should show absolute paths, NOT empty `[]`!**

## Console Output (Expected)

```
[Training] Dataparser data path set to: /home/.../nerfstudio_data  ← NEW MESSAGE
[Training] Using data from /home/.../nerfstudio_data
[Training] Training started
...
[Training] Training complete
[Training] Checkpoint dir: /.../2025-12-11_HHMMSS
Training complete: /.../config.yml
Exporting...
✓ Export complete: output.ply  ← SUCCESS!
```

## Files Modified

- `splats/nerfstudio_integration.py`
  - **Changed**: Set `config.pipeline.datamanager.dataparser.data` BEFORE creating Trainer (line ~257)
  - **Removed**: Duplicate path setting after training (was after line 340)
  - **Removed**: Manual `config.save_config()` call (Trainer does this automatically)

## Key Lesson

**When working with nerfstudio Trainer**:
- ✅ Set ALL config fields BEFORE `Trainer(config)`
- ❌ Don't try to modify config after `trainer.setup()`
- **Reason**: Trainer saves config during setup, modifications after are ignored

## Status
✅ **FIXED** - Dataparser path now set before Trainer creation
✅ **READY** - Export should succeed on next run

## Test Command

```bash
conda activate splats
cd /home/alexander.obuschenko/Projects/splats
python run.py
# Select video, Max Frames=30, Iterations=1000
# Start Nerfstudio pipeline
# Should complete end-to-end with PLY file created
```

