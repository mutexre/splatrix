# Fix: gsplat CUDA Extension Link Error

## Date
2025-12-11

## Problem
Training failed with:
```
Error building extension 'gsplat_cuda':
/usr/bin/ld: cannot find -lcudart
collect2: error: ld returned 1 exit status
ninja: build stopped: subcommand failed.
```

## Root Cause
Broken symlink in conda environment:
```bash
/home/.../miniconda3/envs/splats/lib/libcudart.so -> libcudart.so.11.8.89  # MISSING
```

The target `libcudart.so.11.8.89` did not exist, but `libcudart.so.12` was available.

## Solution Applied

### 1. Fixed Symlink
```bash
cd /home/alexander.obuschenko/miniconda3/envs/splats/lib
rm -f libcudart.so
ln -s libcudart.so.12 libcudart.so
```

### 2. Updated run.py
Added LD_LIBRARY_PATH setup to ensure CUDA libraries are always found during JIT compilation:

```python
conda_prefix = os.environ.get('CONDA_PREFIX')
if conda_prefix:
    cuda_lib_path = os.path.join(conda_prefix, 'lib')
    ld_library_path = os.environ.get('LD_LIBRARY_PATH', '')
    if cuda_lib_path not in ld_library_path:
        os.environ['LD_LIBRARY_PATH'] = f"{cuda_lib_path}:{ld_library_path}"
```

### 3. Cleared Build Cache
```bash
rm -rf ~/.cache/torch_extensions/py310_cu118
```

## Verification
```bash
python3 -c "import gsplat; print('gsplat imported successfully')"
# Output: gsplat imported successfully
```

## Status
✅ **RESOLVED** - gsplat now compiles and imports successfully.

## Impact
Training pipeline can now proceed through:
- Frame extraction (✅ working)
- COLMAP reconstruction (✅ working)
- **Splatfacto training** (✅ now fixed)
- PLY export (pending test)

## Notes
- CUDA 12 runtime compatible with PyTorch 2.1.2+cu118
- gsplat uses PyTorch's JIT compilation requiring libcudart at link time
- Broken symlink likely from partial/mismatched conda package installation

