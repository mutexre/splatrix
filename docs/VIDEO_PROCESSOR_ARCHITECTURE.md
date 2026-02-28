# Video Processing Architecture

## Overview

The project supports multiple video processing implementations via a common interface pattern. This allows for:
- Swapping implementations without changing pipeline code
- Testing different approaches (nerfstudio vs PyAV)
- Comparing performance and progress tracking quality

## Architecture

```
BaseVideoProcessor (ABC)
├── NerfstudioVideoProcessor (nerfstudio + pycolmap)
└── PyAVVideoProcessor (PyAV + pycolmap API)
```

### Base Interface

**File**: `splats/video_processing_base.py`

```python
class BaseVideoProcessor(ABC):
    def process_video(
        video_path: str,
        output_dir: Path,
        num_frames_target: int,
        progress_callback: Callable
    ) -> Dict
    
    def cancel() -> None
    def get_video_info(video_path: str) -> Dict
```

**Returns**:
```python
{
    'data_dir': str,              # Output directory path
    'transforms_path': str,       # Path to transforms.json
    'images_dir': str,            # Directory with extracted frames
    'frame_count': int            # Number of frames extracted
}
```

## Implementations

### 1. NerfstudioVideoProcessor (Default)

**File**: `splats/nerfstudio_video_processor.py`

**How it works**:
1. **Frame Extraction**: nerfstudio's `VideoToNerfstudioDataset` calls ffmpeg subprocess
2. **Progress Tracking**: Background thread monitors images/ directory (polls every 500ms)
3. **SfM**: pycolmap via nerfstudio integration
4. **Progress Hooks**: Intercepts stdout/stderr to parse COLMAP logs

**Pros**:
- ✅ Uses battle-tested nerfstudio frame selection logic
- ✅ Handles all video formats (via ffmpeg)
- ✅ Integrated with nerfstudio's processing pipeline
- ✅ No extra dependencies (ffmpeg already required)

**Cons**:
- ❌ Indirect progress (directory polling with ~500ms lag)
- ❌ ffmpeg output not captured (subprocess stdout)
- ❌ Fragile stdout/stderr parsing for COLMAP progress

**Progress Updates**:
- Frame extraction: Every 500ms (directory poll)
- Feature extraction: Per image (from COLMAP stderr)
- Feature matching: Per image pair (from COLMAP stderr)
- Reconstruction: Per registered image (from COLMAP stderr)

### 2. PyAVVideoProcessor (Experimental)

**File**: `splats/pyav_video_processor.py`

**How it works**:
1. **Frame Extraction**: PyAV Python bindings (direct libav API access)
2. **Progress Tracking**: Frame-by-frame callbacks during decode
3. **SfM**: pycolmap Python API (direct function calls)
4. **Transform Generation**: Custom code converts COLMAP reconstruction → transforms.json

**Pros**:
- ✅ Real-time frame-by-frame progress (no polling lag)
- ✅ Direct control over frame selection
- ✅ Direct pycolmap API (no subprocess/stdout parsing)
- ✅ Can add per-frame preprocessing/filtering

**Cons**:
- ❌ Requires additional dependencies (PyAV, scipy)
- ❌ Must replicate nerfstudio's frame selection logic
- ❌ Custom transforms.json generation (may differ from nerfstudio)
- ❌ More code to maintain

**Progress Updates**:
- Frame extraction: Every 10 frames (immediate callback)
- Feature extraction: Bulk operation (pycolmap API)
- Feature matching: Bulk operation (pycolmap API)
- Reconstruction: After mapping completes

**Dependencies**:
```bash
pip install av>=10.0.0  # PyAV (libav bindings)
pip install scipy>=1.10.0  # For quaternion/rotation conversions
```

## Usage

### From Python Code

```python
from splats.nerfstudio_integration import NerfstudioPipeline
from splats.video_processing_base import ProcessingConfig

# Option 1: Use nerfstudio processor (default)
pipeline = NerfstudioPipeline(video_processor="nerfstudio")

# Option 2: Use PyAV processor
pipeline = NerfstudioPipeline(
    video_processor="pyav",
    processing_config=ProcessingConfig(
        num_frames_target=300,
        matcher_type="sequential"
    )
)

# Setup and process
pipeline.setup_workspace("/path/to/workspace")
result = pipeline.process_video_data(
    video_path="/path/to/video.mp4",
    num_frames_target=300,
    progress_callback=lambda stage, progress: print(f"{stage}: {progress*100}%")
)
```

### From GUI

**File**: `splats/main_window.py`

The UI will have a selector:
```
Video Processor: [ Nerfstudio (recommended) ▼ ]
                 [ PyAV (experimental)       ]
```

Selection is passed to `NerfstudioWorker`:
```python
self.nerfstudio_worker = NerfstudioWorker(
    video_path=self.video_path,
    workspace_dir=str(workspace),
    output_ply_path=output_path,
    max_iterations=max_iterations,
    use_video_directly=True,
    video_processor="nerfstudio"  # or "pyav"
)
```

## Configuration

**File**: `splats/video_processing_base.py`

```python
class ProcessingConfig:
    num_frames_target: int = 300         # Target frame count
    camera_type: str = "perspective"     # Camera model
    matching_method: str = "sequential"  # sequential, exhaustive, vocab_tree
    gpu: bool = True                     # Use GPU for processing
    feature_type: str = "sift"           # SIFT, ORB, etc.
    matcher_type: str = "sequential"     # Matching strategy
```

## Progress Tracking Comparison

| Stage | Nerfstudio Processor | PyAV Processor |
|-------|---------------------|----------------|
| Frame Extraction | Directory polling (500ms lag) | Per-frame callback (immediate) |
| Feature Extraction | COLMAP stderr parsing | pycolmap API (bulk) |
| Feature Matching | COLMAP stderr parsing | pycolmap API (bulk) |
| Reconstruction | COLMAP stderr parsing | pycolmap API callbacks |

## When to Use Each

### Use Nerfstudio Processor When:
- Default choice for most users
- Want proven, stable frame extraction
- Don't need real-time per-frame progress
- Minimizing dependencies

### Use PyAV Processor When:
- Need real-time frame progress (e.g., for preview)
- Want programmatic frame filtering/preprocessing
- Comfortable with experimental features
- Don't mind extra dependencies

## Testing

Both implementations can be tested with the same video:

```bash
# Test nerfstudio processor
python -c "
from splats.nerfstudio_integration import NerfstudioPipeline
from pathlib import Path

pipeline = NerfstudioPipeline(video_processor='nerfstudio')
pipeline.setup_workspace('/tmp/test_nerfstudio')
result = pipeline.process_video_data(
    video_path='/path/to/video.mp4',
    num_frames_target=50,
    progress_callback=lambda s, p: print(f'{s}: {p*100:.1f}%')
)
print(result)
"

# Test PyAV processor
python -c "
from splats.nerfstudio_integration import NerfstudioPipeline
from pathlib import Path

pipeline = NerfstudioPipeline(video_processor='pyav')
pipeline.setup_workspace('/tmp/test_pyav')
result = pipeline.process_video_data(
    video_path='/path/to/video.mp4',
    num_frames_target=50,
    progress_callback=lambda s, p: print(f'{s}: {p*100:.1f}%')
)
print(result)
"
```

## Future Implementations

Possible additional processors:
- **OpenCVVideoProcessor**: Use OpenCV for frame extraction + pycolmap
- **CustomFFmpegProcessor**: Direct ffmpeg Python bindings with progress hooks
- **CloudProcessor**: Upload video, delegate processing to cloud service

All would implement `BaseVideoProcessor` interface.

## Migration Notes

### From Old Code

Old code (embedded in pipeline):
```python
# Direct nerfstudio call in process_video_data()
processor = VideoToNerfstudioDataset(...)
processor.main()
```

New code (pluggable processor):
```python
# Delegate to processor implementation
return self.video_processor.process_video(...)
```

**Benefits**:
- Cleaner separation of concerns
- Testable in isolation
- Easy to add new implementations
- Configuration centralized

## References

- nerfstudio docs: https://docs.nerf.studio/
- PyAV docs: https://pyav.org/
- pycolmap docs: https://github.com/colmap/pycolmap
- COLMAP: https://colmap.github.io/

