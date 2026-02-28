# Video to Gaussian Splats Converter

Convert video files to 3D Gaussian Splats in PLY format using a PyQt6 interface.

## Features

- **Video Processing**: Extract frames from video files (any format supported by OpenCV)
- **Multiple Reconstruction Methods**:
  - **Mock Mode**: Fast test mode with random Gaussian Splats
  - **Nerfstudio (Recommended)**: Full pipeline with splatfacto (camera pose estimation + training + export)
  - **COLMAP**: Structure from Motion (experimental)
- **Real-time Progress Tracking**: Live progress bars and logs
- **Non-blocking UI**: All operations run asynchronously - UI remains responsive
- **PLY Export**: Standard Gaussian Splats PLY format with positions, colors, scales, rotations, opacities

## Requirements

- Python 3.10+
- Conda environment: `splats`
- COLMAP (optional, for full 3D reconstruction)
- nerfstudio (optional, for advanced Gaussian Splatting)

## Installation

```bash
# Create conda environment
conda create -n splats python=3.10
conda activate splats

# Install PyTorch with CUDA (required for nerfstudio)
conda install pytorch torchvision pytorch-cuda=11.8 -c pytorch -c nvidia

# Install other dependencies
pip install -r requirements.txt
```

**Note**: Requires NVIDIA GPU with CUDA for nerfstudio Gaussian Splatting training.

## Usage

```bash
conda activate splats
python -m splats.main_window
```

## Usage Guide

### Quick Start (Mock Mode)

1. Launch application
2. Click "Select Video" and choose your video file
3. Keep "Mock (Fast, test only)" selected
4. Click "Start Conversion"
5. Wait ~10 seconds for mock data generation
6. Output PLY saved to `~/.splats_workspace/output.ply`

### Real Reconstruction (Nerfstudio)

1. Select "Nerfstudio (Real, GPU required)" method
2. Adjust training iterations (30,000 default, higher = better quality)
3. Click "Start Conversion"
4. Wait 10-30 minutes (depends on GPU and iterations)
5. Output PLY contains real trained Gaussian Splats

**Time estimates**:
- Data processing: 2-5 minutes
- Training: 10-25 minutes
- Export: < 1 minute

## Architecture

- `splats/main_window.py` - Main PyQt6 application window with responsive UI
- `splats/video_processor.py` - Video frame extraction using OpenCV/PyAV
- `splats/nerfstudio_integration.py` - Nerfstudio pipeline integration (splatfacto)
- `splats/reconstruction_pipeline.py` - Mock and COLMAP reconstruction
- `splats/ply_exporter.py` - PLY file generation
- `splats/worker_threads.py` - QThread workers for async operations

## Documentation

Comprehensive documentation available in the `docs/` directory:

- **Setup guides**: Installation, CUDA setup, nerfstudio configuration
- **Architecture docs**: System design, stage tracking, video processors
- **Bug fixes**: Detailed root cause analysis for all resolved issues
- **Troubleshooting**: Common problems and solutions
- **Debug guides**: Step-by-step debugging procedures

See [docs/INDEX.md](docs/INDEX.md) for complete documentation index

