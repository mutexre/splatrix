# Nerfstudio Integration Setup

This document explains how to setup and use the nerfstudio integration for real video-to-Gaussian-Splats conversion.

## Prerequisites

### 1. NVIDIA GPU with CUDA
- **Required**: CUDA-capable GPU (RTX 2060 or better recommended)
- **CUDA Version**: 11.8 or later
- **VRAM**: 8GB+ recommended

### 2. Check GPU
```bash
nvidia-smi
```

## Installation

### Step 1: Create Conda Environment
```bash
conda create -n splats python=3.10
conda activate splats
```

### Step 2: Install System Dependencies
```bash
# Install ffmpeg (for video processing)
conda install -c conda-forge ffmpeg

# Install COLMAP (for camera pose estimation)
conda install -c conda-forge colmap
```

### Step 3: Install PyTorch with CUDA
```bash
# For CUDA 11.8
conda install pytorch torchvision pytorch-cuda=11.8 -c pytorch -c nvidia

# For CUDA 12.1
conda install pytorch torchvision pytorch-cuda=12.1 -c pytorch -c nvidia
```

Verify PyTorch CUDA:
```bash
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

### Step 4: Install tiny-cuda-nn (Optional)
```bash
pip install ninja git+https://github.com/NVlabs/tiny-cuda-nn/#subdirectory=bindings/torch
```
Note: tinycudann is optional but provides performance improvements.

### Step 5: Install nerfstudio
```bash
pip install nerfstudio
```

### Step 6: Install other dependencies
```bash
cd /home/alexander.obuschenko/Projects/splats
pip install -r requirements.txt
```

## Verify Installation

```bash
# Check nerfstudio
ns-train -h

# Should show training options without errors
```

## Using Nerfstudio in the Application

### Quick Test
1. Launch: `python run.py`
2. Select video file
3. Choose "Nerfstudio (Real, GPU required)"
4. Set iterations (30,000 default)
5. Click "Start Conversion"
6. Monitor progress (10-30 minutes)

### Pipeline Stages

**Stage 1: Data Processing (2-5 min)**
- Extracts frames from video
- Runs COLMAP for camera pose estimation
- Creates transforms.json

**Stage 2: Training (10-25 min)**
- Trains 3D Gaussian Splatting model (splatfacto)
- Progress updates every 5% of iterations
- GPU memory usage: 6-8GB

**Stage 3: Export (< 1 min)**
- Exports trained model to PLY format
- Standard Gaussian Splats format

## Troubleshooting

### CUDA Out of Memory
- Reduce training iterations
- Close other GPU applications
- Use smaller video resolution

### "nerfstudio not found"
```bash
conda activate splats
pip install nerfstudio
```

### COLMAP fails
- Ensure video has enough camera motion
- Try video with more distinctive features
- Check video isn't too dark/bright

### Training too slow
- Reduce iterations (e.g., 10,000 for testing)
- Use shorter video (< 30 seconds)
- Upgrade GPU

## Performance Tips

### Fast Testing (5-10 min)
- Iterations: 10,000
- Video: 10-15 seconds

### Good Quality (15-20 min)
- Iterations: 30,000 (default)
- Video: 20-30 seconds

### High Quality (30-45 min)
- Iterations: 50,000+
- Video: 30-60 seconds

## Output Format

The exported PLY file contains:
- **Positions**: (x, y, z) coordinates
- **Colors**: RGB (0-255)
- **Scales**: 3D scale parameters
- **Rotations**: Quaternion rotations
- **Opacities**: Transparency values

Compatible with:
- [Gaussian Splatting Viewer](https://github.com/antimatter15/splat)
- [SuperSplat](https://playcanvas.com/supersplat)
- [Luma AI](https://lumalabs.ai/)
- Any Gaussian Splatting renderer

## Command Line Alternative

Without UI:
```bash
# Process video
ns-process-data video --data video.mp4 --output-dir data/

# Train
ns-train splatfacto --data data/

# Export
ns-export gaussian-splat --load-config outputs/.../config.yml --output-dir exports/
```

## Resources

- [Nerfstudio Documentation](https://docs.nerf.studio/)
- [Splatfacto Paper](https://arxiv.org/abs/2309.16653)
- [Gaussian Splatting](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/)

