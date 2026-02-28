# Fix: {timestamp} Placeholder Not Expanded

## Problem

**Symptom**: Training fails with error showing literal `{timestamp}` in path:
```
No such file or directory: '/home/user/.splats_workspace/nerfstudio/outputs/unnamed/splatfacto/{timestamp}'
```

**Expected**: Path should have actual timestamp like:
```
/home/user/.splats_workspace/nerfstudio/outputs/video_to_splats/splatfacto/2024-12-11_153045
```

## Root Cause

**Nerfstudio's TrainerConfig uses template placeholders** that need to be explicitly set:
- `{timestamp}` → replaced by calling `config.set_timestamp()`
- Experiment name → set by calling `config.set_experiment_name()`

**What we were doing**:
```python
config.output_dir = self.output_dir  # Just set base directory
trainer = Trainer(config, ...)  # {timestamp} not expanded!
```

**Result**: Trainer tries to create directory with literal `{timestamp}` string → fails because it's an invalid path.

## Solution

**Set timestamp and experiment name as direct attributes** (not method calls):

```python
from datetime import datetime

# Set base output directory
config.output_dir = self.output_dir

# Set timestamp directly (replaces {timestamp} placeholder)
config.timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

# Set experiment name directly (replaces {experiment_name} if used)
config.experiment_name = "video_to_splats"

# Now Trainer will create:
# outputs/video_to_splats/splatfacto/2024-12-11_153045/
```

**Note**: `set_timestamp()` and `set_experiment_name()` methods exist but **take no arguments** - they auto-generate values. To set custom values, assign to attributes directly.

## Nerfstudio Config Structure

**TrainerConfig attributes**:
```python
config.output_dir         # Base directory (e.g., "outputs")
config.experiment_name    # Experiment name (e.g., "my_video")
config.timestamp          # Timestamp string (e.g., "2024-12-11_153045")
config.method_name        # Method name (e.g., "splatfacto")
```

**Directory structure created**:
```
{output_dir}/{experiment_name}/{method_name}/{timestamp}/
```

Example:
```
outputs/video_to_splats/splatfacto/2024-12-11_153045/
├── config.yml
├── nerfstudio_models/
│   └── step-000030000.ckpt
└── ...
```

## Methods to Use

### config.set_timestamp(timestamp_str)
Sets the timestamp used in output path.

**Usage**:
```python
from datetime import datetime
timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
config.set_timestamp(timestamp)
```

### config.set_experiment_name(name)
Sets the experiment name used in output path.

**Usage**:
```python
config.set_experiment_name("my_experiment")
```

### config.get_base_dir()
Returns the full base directory path for outputs.

### config.get_checkpoint_dir()
Returns the directory where checkpoints will be saved.

## Why This Wasn't Obvious

**Nerfstudio CLI** (`ns-train`) automatically calls these methods:
```bash
ns-train splatfacto --data /path/to/data
# Internally does:
# config.set_timestamp(datetime.now().strftime(...))
# config.set_experiment_name("unnamed" or from --experiment-name)
```

**Python API** requires manual calls - not documented clearly.

## Alternative: Let Nerfstudio Auto-Generate

Could also let nerfstudio use defaults:
```python
# Don't set timestamp/experiment_name
# Nerfstudio will use:
# - experiment_name = "unnamed"
# - timestamp = auto-generated when Trainer created

# But safer to set explicitly for:
# 1. Predictable paths
# 2. Meaningful experiment names
# 3. Avoiding race conditions
```

## Files Modified

**`splats/nerfstudio_integration.py`**:
- Added `set_timestamp()` call with current datetime
- Added `set_experiment_name()` call with "video_to_splats"
- Ensures proper directory creation

## Testing

```bash
conda activate splats
python run.py
```

**Verify**:
1. Training starts without path errors
2. Output directory created: `~/.splats_workspace/nerfstudio/outputs/video_to_splats/splatfacto/YYYY-MM-DD_HHMMSS/`
3. Config and checkpoints saved to that directory

**Check output structure**:
```bash
ls -la ~/.splats_workspace/nerfstudio/outputs/
# Should see: video_to_splats/

ls -la ~/.splats_workspace/nerfstudio/outputs/video_to_splats/splatfacto/
# Should see: 2024-12-11_153045/ (with actual timestamp)
```

## Related Issues

Other nerfstudio operations that might have similar issues:
- Custom trainer configs
- Multiple training runs (need unique timestamps)
- Resuming training from checkpoint

## Best Practices

1. **Always set timestamp explicitly** when using nerfstudio Python API
2. **Use meaningful experiment names** instead of "unnamed"
3. **Create unique timestamps** for each training run to avoid overwrites
4. **Check output directory** exists before starting export

## References

- Nerfstudio TrainerConfig: `nerfstudio/engine/trainer.py`
- Config methods: `set_timestamp()`, `set_experiment_name()`, `get_base_dir()`
- CLI implementation: `nerfstudio/scripts/train.py` (shows how CLI does it)

## Error Message Improvements

Added better error context in training failure:
```python
except Exception as e:
    raise RuntimeError(
        f"Training failed: {str(e)}\n"
        f"Data directory: {data_path}\n"
        f"Output directory: {config.get_base_dir()}\n"  # Show actual path
        f"transforms.json: {transforms_path}"
    )
```

Now shows where training tried to save outputs.

