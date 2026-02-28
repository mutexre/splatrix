# gsplat CUDA Setup Fix

## Issue
```
gsplat: No CUDA toolkit found. gsplat will be disabled.
AttributeError: 'NoneType' object has no attribute 'CameraModelType'
```

## Root Cause
gsplat requires **nvcc compiler** (CUDA toolkit) to JIT-compile its CUDA kernels. PyTorch ships with CUDA runtime libraries but NOT the compiler.

## Solution

### Step 1: Install CUDA Toolkit 11.8
```bash
conda activate splats
conda install -c nvidia/label/cuda-11.8.0 cuda-toolkit -y
```

**Important**: Must use CUDA 11.8 toolkit to match PyTorch CUDA 11.8 runtime. CUDA 12.x has incompatible header structure (`nv/target`).

### Step 2: Verify nvcc
```bash
which nvcc
nvcc --version
```

Should show: `/home/alexander.obuschenko/miniconda3/envs/splats/bin/nvcc`

### Step 3: Clear gsplat Cache
```bash
rm -rf ~/.cache/torch_extensions/*
```

### Step 4: Test gsplat Compilation
```bash
python -c "
import os
os.environ['CUDA_HOME'] = '/home/alexander.obuschenko/miniconda3/envs/splats'
import gsplat
from gsplat.rendering import rasterization
print('✓ gsplat CUDA compiled successfully')
"
```

### Step 5: Update Application
The application's `_get_subprocess_env()` method in `nerfstudio_integration.py` now sets:
- `CUDA_HOME` environment variable
- Proper `LD_LIBRARY_PATH` (system libs first, then conda)

## Complete Working Configuration

```bash
# Environment
conda env: splats
Python: 3.10.19
PyTorch: 2.7.1+cu118
CUDA Runtime: 11.8 (from PyTorch)
CUDA Toolkit: 11.8.89 (nvcc compiler - MUST MATCH PyTorch)
nvcc: 11.8 (in conda env)
gsplat: 1.4.0 (JIT-compiled with nvcc 11.8)
nerfstudio: 1.1.5
COLMAP: 3.8
GPU: Quadro RTX 4000

# Library Strategy
- PyQt6: pip (self-contained)
- PyTorch: pip with CUDA 11.8
- CUDA Toolkit 11.8: conda (for nvcc - version must match!)
- ffmpeg/COLMAP: conda (no qt-main/harfbuzz)
- gsplat: pip (JIT compiles with nvcc 11.8)
```

## Why This Works

1. **PyTorch Runtime**: Provides CUDA libraries for running models
2. **CUDA Toolkit**: Provides nvcc compiler for building extensions
3. **gsplat JIT**: Compiles CUDA kernels on first use using nvcc
4. **Subprocess Environment**: Preserves CUDA_HOME and nvcc in PATH

## Verification Commands

```bash
# Check all components
conda activate splats

# PyTorch CUDA
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}')"

# nvcc compiler
nvcc --version

# gsplat
python -c "import gsplat; from gsplat.rendering import rasterization; print('OK')"

# nerfstudio
ns-train -h | head -3

# Test training (should not show "No CUDA toolkit found")
ns-train splatfacto --help
```

## Common Issues

### "No CUDA toolkit found" still appears
- Clear cache: `rm -rf ~/.cache/torch_extensions/*`
- Verify nvcc: `which nvcc`
- Check CUDA_HOME: `echo $CUDA_HOME`

### nvcc not found
```bash
conda install -c nvidia/label/cuda-11.8.0 cuda-toolkit -y
```

### CUDA version mismatch error (nv/target not found)
**Symptom**: `fatal error: nv/target: No such file or directory`
**Cause**: CUDA toolkit version doesn't match PyTorch CUDA version
**Fix**: 
```bash
conda remove cuda-toolkit -y
conda install -c nvidia/label/cuda-11.8.0 cuda-toolkit -y
rm -rf ~/.cache/torch_extensions/*
```

## Timeline of Fixes

1. ✓ Resolved PyQt6/harfbuzz conflicts
2. ✓ Fixed ffmpeg/pango library issues  
3. ✓ Downgraded COLMAP to 3.8 (parameter compatibility)
4. ✓ Installed CUDA toolkit for nvcc
5. ✓ Updated subprocess environment for CUDA_HOME

## Testing Status

- ✓ gsplat imports without errors
- ✓ CUDA kernels compile successfully
- ✓ ns-train starts without "No CUDA toolkit" error
- ✓ Training runs (tested with 100 iterations)

---

**Last Updated**: December 10, 2025  
**Status**: RESOLVED - Full pipeline operational

