# Splats

**Convert any video into 3D Gaussian Splats — one click.**

Splats is a desktop application that takes a video file and produces a 3D Gaussian Splat in PLY format. It wraps the [Nerfstudio](https://docs.nerf.studio/) pipeline behind an intuitive QML interface with real-time progress tracking, an embedded 3D viewer, and project persistence.

## Features

- **One-click pipeline** — drop a video, click Start, get a `.ply`
- **6-stage progress** — Frame Extraction → Feature Extraction → Feature Matching → Sparse Reconstruction → Training → Export
- **Embedded 3D viewer** — preview your Gaussian Splat right inside the app
- **Frame browser** — inspect extracted frames in a grid view
- **Video preview** — play/seek the source video
- **Project persistence** — save/restore projects, resume from any stage
- **Multi-window** — work on multiple projects simultaneously
- **ETA tracking** — estimated time remaining per stage

## Requirements

| Component | Version |
|-----------|---------|
| OS | Linux (tested on RHEL 9 / Ubuntu 22.04+) |
| Python | 3.10+ |
| GPU | NVIDIA with CUDA 12.x (required for training) |
| VRAM | 8 GB+ recommended |
| Conda | Miniconda or Anaconda |

## Install

One command, no prerequisites (just Linux x86_64 + NVIDIA drivers):

```bash
curl -fsSL https://splats-app.github.io/splats/install.sh | bash
```

This automatically installs Miniconda (if needed), PyTorch, COLMAP, FFmpeg, Nerfstudio, and the Splats app.

## Run

```bash
splats
```

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/splats-app/splats/main/uninstall.sh | bash
```

## Usage

1. Click **Select Video** and choose your video file
2. Adjust **Max Frames** (30 is a good default) and **Training Iterations** (default 30,000)
3. Click **Start Conversion**
4. Monitor progress across all 6 stages
5. When complete, view the result in the **3D Viewer** tab
6. Click **Export PLY** to save the result

### Time Estimates

| Stage | Duration |
|-------|----------|
| Data processing (frames, features, matching, reconstruction) | 2–10 min |
| Training | 10–30 min |
| Export | < 1 min |

## Project Structure

```
splats/
├── splats/               # Python package
│   ├── main_qml.py       # Application entry point
│   ├── qml_bridge.py     # Python ↔ QML bridge
│   ├── app_controller.py # Multi-window management
│   ├── project_manager.py # Project persistence (YAML)
│   ├── worker_threads.py # Background processing
│   ├── nerfstudio_integration.py
│   ├── direct_ply_export.py
│   ├── ply_exporter.py
│   ├── qml/              # QML UI files
│   └── viewer/           # Embedded 3D viewer (Three.js)
├── website/              # GitHub Pages site
├── install.sh            # One-line installer
├── pyproject.toml        # Package metadata
└── LICENSE               # MIT
```

## Development

```bash
# Install in development mode
conda activate splats
pip install -e ".[dev]"

# Run directly
python run_qml.py
```

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## License

MIT — see [LICENSE](LICENSE).
