# Direct PLY Export Solution

## Question: Is Python API export blocked?

**Answer: NO! There is NO critical blocker.**

## The Misunderstanding

**What we thought**:
```
pymeshlab has Qt5 conflict with PyQt6
→ Can't import nerfstudio.scripts.exporter in GUI process
→ Must use subprocess for export
```

**Reality**:
- pymeshlab is ONLY needed for **mesh export** (Poisson reconstruction)
- **Gaussian Splat export does NOT need pymeshlab!**
- We can load checkpoint directly with `torch.load()` - no nerfstudio import needed

## The Solution: Direct Checkpoint Loading

### How It Works

```python
import torch

# 1. Load checkpoint directly (no nerfstudio import!)
checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=False)
state = checkpoint['pipeline']

# 2. Extract Gaussian parameters
means = state['_model.gauss_params.means']           # (N, 3) positions
scales = state['_model.gauss_params.scales']         # (N, 3) log space
quats = state['_model.gauss_params.quats']           # (N, 4) quaternions
opacities = state['_model.gauss_params.opacities']   # (N, 1) logit space
features_dc = state['_model.gauss_params.features_dc'] # (N, 3) SH DC term

# 3. Apply activation functions
scales_linear = torch.exp(scales)                    # log → linear
opacities_prob = torch.sigmoid(opacities)            # logit → probability
C0 = 0.28209479177387814                             # SH DC coefficient
colors_rgb = (features_dc * C0 + 0.5).clamp(0, 1) * 255  # SH → RGB

# 4. Convert to numpy
positions_np = means.cpu().numpy()
colors_np = colors_rgb.cpu().numpy()
scales_np = scales_linear.cpu().numpy()
rotations_np = quats.cpu().numpy()
opacities_np = opacities_prob.cpu().numpy()

# 5. Write PLY
PLYExporter.create_gaussian_splat_ply(
    positions=positions_np,
    colors=colors_np,
    scales=scales_np,
    rotations=rotations_np,
    opacities=opacities_np,
    output_path=output_ply_path
)
```

### Implementation

**File**: `splats/direct_ply_export.py`

**Functions**:
- `export_from_checkpoint(checkpoint_path, output_ply_path, progress_callback)` - Main export function
- `find_latest_checkpoint(output_dir)` - Find latest checkpoint in output directory

### Test Results

```bash
$ python3 test_direct_export.py
[ 10%] Loading checkpoint
[ 30%] Extracting Gaussian parameters
[ 50%] Applying activation functions
[ 70%] Converting to numpy arrays
[ 90%] Writing PLY file
[100%] Export complete
✓ Exported 8337 Gaussians to test_direct_export.ply

File size: 0.47 MB
Time: <1 second
```

## Benefits vs Subprocess Approach

| Aspect | Subprocess (OLD) | Direct (NEW) |
|--------|-----------------|-------------|
| **Speed** | ~5-10s | <1s |
| **Progress** | Indirect/parsed | Direct callbacks |
| **Error handling** | Parse stderr | Try/except |
| **Dependencies** | nerfstudio CLI | PyTorch only |
| **Config issues** | Many (paths) | None |
| **Qt conflicts** | Risk | None |
| **Debuggability** | Hard | Easy |
| **Complexity** | ~200 lines | ~50 lines |

## Integration Steps

### 1. Update NerfstudioPipeline

Replace export method in `splats/nerfstudio_integration.py`:

```python
def export_gaussian_splat(
    self,
    checkpoint_path: str,  # Changed from config_path
    output_ply_path: str,
    progress_callback: Optional[Callable] = None
) -> Path:
    """Export using direct checkpoint loading"""
    from .direct_ply_export import export_from_checkpoint
    
    return export_from_checkpoint(
        checkpoint_path,
        output_ply_path,
        progress_callback
    )
```

### 2. Update Worker Thread

Update `NerfstudioWorker` in `splats/worker_threads.py`:

```python
# After training completes
training_result = pipeline.train_splatfacto(...)

# Find checkpoint (instead of using config path)
from splats.direct_ply_export import find_latest_checkpoint
checkpoint_path = find_latest_checkpoint(training_result['output_dir'])

# Export
output_path = pipeline.export_gaussian_splat(
    checkpoint_path=checkpoint_path,  # Not config_path!
    output_ply_path=self.output_ply_path,
    progress_callback=export_progress
)
```

### 3. Remove Subprocess Code

Delete or comment out subprocess export code in `nerfstudio_integration.py`:
- Environment setup (`PYTHONWARNINGS=ignore`)
- Subprocess spawning
- Process monitoring
- Stderr parsing
- Exit code workarounds

## Technical Details

### Checkpoint Structure (Splatfacto)

```python
checkpoint = {
    'step': 1000,
    'pipeline': {
        '_model.gauss_params.means': Tensor(N, 3),
        '_model.gauss_params.scales': Tensor(N, 3),       # LOG space
        '_model.gauss_params.quats': Tensor(N, 4),
        '_model.gauss_params.opacities': Tensor(N, 1),    # LOGIT space
        '_model.gauss_params.features_dc': Tensor(N, 3),  # SH DC term
        '_model.gauss_params.features_rest': Tensor(N, 15, 3),  # Higher-order SH
        # ... other model weights ...
    },
    'optimizers': {...},
    'schedulers': {...},
}
```

### Activation Functions

**Why needed**: Model stores parameters in transformed spaces for optimization stability.

1. **Scales**: `exp(log_scales)` - stored in log space to keep positive
2. **Opacities**: `sigmoid(logits)` - stored in logit space for unconstrained optimization
3. **Rotations**: Already normalized quaternions (no activation needed)
4. **Colors**: SH to RGB conversion using DC coefficient

### Spherical Harmonics (SH) to RGB

Only DC (0th order) term needed for basic export:

```python
C0 = 0.28209479177387814  # sqrt(1/(4*pi))
rgb = features_dc * C0 + 0.5
rgb = rgb.clamp(0, 1) * 255
```

For higher quality:
- Use `features_rest` for view-dependent color
- Evaluate full SH basis functions
- Requires camera direction

## Comparison with Other Approaches

See [PLY_EXPORT_APPROACHES.md](PLY_EXPORT_APPROACHES.md) for full comparison.

**Summary**:
- **Approach 11** (Direct checkpoint loading) - ⭐⭐⭐⭐⭐ RECOMMENDED
- Approach 1 (ns-export CLI subprocess) - ⭐⭐⭐ Works but complex
- Approach 5 (Multiprocessing) - ⭐⭐⭐⭐ Overkill
- Approach 2 (Python API in-process) - ❌ Blocked by pymeshlab for mesh export only

## Next Steps

1. ✅ **Implementation complete**: `splats/direct_ply_export.py`
2. ✅ **Tested**: Exported 8337 Gaussians successfully
3. ⏳ **Integration**: Update NerfstudioPipeline and worker thread
4. ⏳ **Testing**: End-to-end GUI test with small video
5. ⏳ **Cleanup**: Remove subprocess export code

## Conclusion

**Direct Python API export is NOT blocked. It's the simplest and best approach.**

The pymeshlab/Qt conflict was a red herring - it only affects mesh export (Poisson reconstruction), not Gaussian Splat export. We can load checkpoints directly with PyTorch and extract all parameters without any nerfstudio import, making export faster, simpler, and more reliable than the subprocess approach.

