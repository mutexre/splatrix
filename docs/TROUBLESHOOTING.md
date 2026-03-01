# Troubleshooting Guide

## Library Conflicts (RESOLVED)

### Issue: PyQt6 harfbuzz/freetype conflicts
**Symptoms:**
```
ImportError: libharfbuzz.so.0: undefined symbol: FT_Get_Colorline_Stops
```

**Root Cause:**
COLMAP installation brings conda's `qt-main` and `harfbuzz` packages which conflict with PyQt6's bundled Qt6 libraries.

**Solution:**
```bash
# Remove conflicting packages
conda remove qt-main harfbuzz pango --force -y

# PyQt6 (pip) has its own complete Qt6 bundle
# COLMAP and nerfstudio commands use system libraries via subprocess environment
```

### Issue: ffmpeg pango/harfbuzz dependencies
**Symptoms:**
```
ffprobe: symbol lookup error: libpango-1.0.so.0: undefined symbol: hb_ot_color_has_paint
```

**Root Cause:**
ffmpeg depends on pango which needs harfbuzz, but conda's harfbuzz conflicts with PyQt6.

**Solution:**
```bash
# Remove conda pango
conda remove pango --force -y

# Let ffmpeg use system harfbuzz libraries
# subprocess environment automatically filters out conda lib paths
```

### Issue: COLMAP parameter incompatibility
**Symptoms:**
```
Failed to parse options - unrecognised option '--SiftExtraction.use_gpu'
```

**Root Cause:**
COLMAP 3.13 changed parameter names. Nerfstudio expects COLMAP 3.8 parameters.

**Solution:**
```bash
conda install -c conda-forge "colmap=3.8" -y
conda remove qt-main harfbuzz --force -y  # Remove re-added packages
```

## Current Configuration

### Working Setup
- **Python**: 3.10.19
- **PyQt6**: 6.10.1 (pip, with bundled Qt6)
- **PyTorch**: 2.7.1+cu118 (pip)
- **CUDA**: 11.8
- **Nerfstudio**: 1.1.5
- **ffmpeg**: conda-forge (without pango/harfbuzz)
- **COLMAP**: 3.8 (conda-forge, without qt-main/harfbuzz)

### Library Strategy
1. **UI Libraries**: PyQt6 via pip (self-contained Qt6 bundle)
2. **Compute**: PyTorch via pip (CUDA 11.8)
3. **Video Processing**: ffmpeg via conda (uses system harfbuzz)
4. **3D Reconstruction**: COLMAP 3.8 via conda (uses system Qt/harfbuzz)
5. **Subprocess Environment**: Filters conda lib paths to use system libraries

## COLMAP Reconstruction Failures

### Issue: "ERROR: failed to create sparse model"

**Possible Causes:**
1. **Insufficient Frames**: Too few frames for overlap
2. **Motion Blur**: Frames too blurry for feature detection
3. **Rapid Scene Changes**: Not enough visual continuity
4. **Texture-less Scenes**: Not enough distinctive features
5. **Sampling Too Sparse**: Frames too far apart in time

**Solutions:**
```bash
# Increase frame count
ns-process-data video --num-frames-target 300  # Default
ns-process-data video --num-frames-target 500  # More frames

# For static scenes or slow camera motion
ns-process-data video --num-frames-target 100

# For fast motion or quick cuts
# May not work - use different video
```

**Alternative Approach:**
If COLMAP consistently fails:
1. Use videos with slow, smooth camera motion
2. Ensure good lighting and sharp focus
3. Avoid videos with cuts or quick edits
4. Try mock mode for testing UI/workflow

## Environment Commands

### Quick Fix Script
```bash
# If you encounter library conflicts again
cd /home/alexander.obuschenko/Projects/splatrix
conda activate splatrix
conda remove qt-main harfbuzz pango --force -y
```

### Verify Installation
```bash
conda activate splatrix

# Check PyQt6
python -c "from PyQt6.QtWidgets import QApplication; print('✓ PyQt6 OK')"

# Check PyTorch CUDA
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}')"

# Check nerfstudio
ns-train -h | head -5

# Check ffmpeg
ffmpeg -version | head -1

# Check COLMAP
colmap -h | head -1
```

### Clean Reinstall
```bash
# If environment is corrupted
conda deactivate
conda env remove -n splatrix
conda create -n splatrix python=3.10 -y
conda activate splatrix

# Install in this order
conda install -c conda-forge ffmpeg colmap=3.8 -y
conda remove qt-main harfbuzz pango --force -y

pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install nerfstudio
pip install -r requirements.txt
```

## Application Issues

### UI Not Loading
```bash
# Check if harfbuzz was re-added
conda list | grep harfbuzz

# If found, remove it
conda remove harfbuzz qt-main --force -y
```

### Nerfstudio Commands Not Found
```bash
# Verify nerfstudio installation
conda activate splatrix
which ns-train

# Should show: /home/alexander.obuschenko/miniconda3/envs/splatrix/bin/ns-train
```

### GPU Not Detected
```bash
# Check CUDA
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"

# Reinstall PyTorch if needed
pip uninstall torch torchvision -y
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

## Video Requirements

### Best Results
- **Camera Motion**: Slow, smooth panning or orbit
- **Scene**: Static objects with texture
- **Lighting**: Well-lit, consistent
- **Duration**: 10-30 seconds
- **Cuts**: None (single continuous shot)
- **Focus**: Sharp, not blurry

### Poor Results Expected
- Fast motion or shaky camera
- Rapid cuts or scene changes
- Low light or motion blur
- Reflective/glass surfaces
- Sky-only or texture-less scenes

## Getting Help

1. Check this troubleshooting guide
2. Review NERFSTUDIO_SETUP.md
3. Check INSTALLATION_COMPLETE.md
4. Test with mock mode first
5. Try a different video if COLMAP fails

---

**Last Updated**: December 10, 2025

