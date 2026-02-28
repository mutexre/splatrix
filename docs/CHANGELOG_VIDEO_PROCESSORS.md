# Changelog: Video Processor Refactor

## What Changed

Refactored video processing phase to use pluggable architecture with two implementations:

### New Files

1. **`splats/video_processing_base.py`**
   - Abstract base class `BaseVideoProcessor`
   - Configuration class `ProcessingConfig`
   - Common interface for all video processors

2. **`splats/nerfstudio_video_processor.py`**
   - Nerfstudio-based implementation (default)
   - Uses nerfstudio's `VideoToNerfstudioDataset` + pycolmap
   - Directory monitoring for frame extraction progress

3. **`splats/pyav_video_processor.py`**
   - PyAV-based implementation (experimental)
   - Direct libav bindings for frame extraction
   - Direct pycolmap API calls for SfM
   - Frame-by-frame progress callbacks

4. **`VIDEO_PROCESSOR_ARCHITECTURE.md`**
   - Comprehensive architecture documentation
   - Usage examples and comparison table

### Modified Files

1. **`splats/nerfstudio_integration.py`**
   - `NerfstudioPipeline.__init__()` now accepts `video_processor` parameter
   - `process_video_data()` simplified to delegate to processor implementation
   - Removed ~160 lines of embedded processing logic

2. **`splats/worker_threads.py`**
   - `NerfstudioWorker.__init__()` accepts `video_processor` parameter
   - Passes processor selection to pipeline

3. **`requirements.txt`**
   - Added optional PyAV and scipy dependencies (commented out)

4. **`splats/__init__.py`**
   - Exports new processor classes

## Why This Change

### Problems Solved

1. **Code Organization**: Video processing logic was embedded in `NerfstudioPipeline.process_video_data()` (~250 lines)
2. **Testing**: Couldn't test different processing approaches without modifying core pipeline
3. **Extension**: Adding new processors required changing existing code
4. **Progress Tracking**: Directory monitoring was the only option (not ideal)

### Benefits

1. **Separation of Concerns**: Each processor handles its own frame extraction and SfM
2. **Extensibility**: Add new implementations by subclassing `BaseVideoProcessor`
3. **Testability**: Processors can be tested independently
4. **Flexibility**: Users can choose between implementations based on needs

## Migration Guide

### For End Users (GUI)

**No changes required.** Default processor ("nerfstudio") is automatically selected.

**Optional**: Future GUI update will allow selecting processor from dropdown.

### For Python API Users

**Before**:
```python
from splats.nerfstudio_integration import NerfstudioPipeline

pipeline = NerfstudioPipeline()
pipeline.setup_workspace("/workspace")
result = pipeline.process_video_data("/video.mp4")
```

**After (default behavior unchanged)**:
```python
from splats.nerfstudio_integration import NerfstudioPipeline

pipeline = NerfstudioPipeline()  # Uses "nerfstudio" processor by default
pipeline.setup_workspace("/workspace")
result = pipeline.process_video_data("/video.mp4")
```

**After (with PyAV processor)**:
```python
from splats.nerfstudio_integration import NerfstudioPipeline
from splats.video_processing_base import ProcessingConfig

# Option 1: Simple
pipeline = Nerfstudio Pipeline(video_processor="pyav")

# Option 2: With custom config
config = ProcessingConfig(
    num_frames_target=300,
    matcher_type="sequential"
)
pipeline = NerfstudioPipeline(
    video_processor="pyav",
    processing_config=config
)

pipeline.setup_workspace("/workspace")
result = pipeline.process_video_data("/video.mp4", num_frames_target=300)
```

## Testing

### Test Nerfstudio Processor

```bash
conda activate splats
python -c "
from splats import NerfstudioPipeline
pipeline = NerfstudioPipeline(video_processor='nerfstudio')
pipeline.setup_workspace('/tmp/test_ns')
result = pipeline.process_video_data(
    video_path='/path/to/video.mp4',
    num_frames_target=50,
    progress_callback=lambda s, p: print(f'{s}: {p*100:.1f}%')
)
print(f'Extracted {result[\"frame_count\"]} frames')
"
```

### Test PyAV Processor

```bash
conda activate splats
pip install av scipy  # Install PyAV dependencies
python -c "
from splats import NerfstudioPipeline
pipeline = NerfstudioPipeline(video_processor='pyav')
pipeline.setup_workspace('/tmp/test_pyav')
result = pipeline.process_video_data(
    video_path='/path/to/video.mp4',
    num_frames_target=50,
    progress_callback=lambda s, p: print(f'{s}: {p*100:.1f}%')
)
print(f'Extracted {result[\"frame_count\"]} frames')
"
```

## Future Work

### Planned

1. **GUI Selector**: Add dropdown in UI to choose video processor
2. **Performance Comparison**: Benchmark both implementations
3. **Documentation**: Add examples and best practices

### Possible Extensions

1. **OpenCVVideoProcessor**: Use OpenCV VideoCapture
2. **CustomFFmpegProcessor**: Direct ffmpeg-python bindings
3. **CloudProcessor**: Upload video to cloud processing service
4. **StreamProcessor**: Process live video streams

## Backward Compatibility

✅ **Fully backward compatible.**

Existing code using `NerfstudioPipeline()` will continue to work unchanged. The default processor is "nerfstudio", which uses the same underlying implementation (nerfstudio's `VideoToNerfstudioDataset`).

## Performance Impact

**None for default usage.**

- Nerfstudio processor uses identical logic to previous implementation
- Added one level of indirection (method call to processor)
- Negligible overhead (~microseconds)

## Dependencies

### Core (no change)
- nerfstudio
- pycolmap
- torch, torchvision

### Optional (new)
- `av>=10.0.0` - PyAV (for PyAVVideoProcessor)
- `scipy>=1.10.0` - SciPy (for quaternion conversions in PyAVVideoProcessor)

Install with:
```bash
pip install av scipy
```

## Questions?

See `VIDEO_PROCESSOR_ARCHITECTURE.md` for detailed documentation.

