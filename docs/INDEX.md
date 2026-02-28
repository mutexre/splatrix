# Documentation Index

## Setup & Installation

- [INSTALLATION_COMPLETE.md](INSTALLATION_COMPLETE.md) - Installation completion checklist
- [NERFSTUDIO_SETUP.md](NERFSTUDIO_SETUP.md) - Nerfstudio installation guide
- [CUDA_SETUP_FIX.md](CUDA_SETUP_FIX.md) - CUDA toolkit setup
- [READY_TO_USE.md](READY_TO_USE.md) - Quick start guide

## Architecture & Design

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview
- [STAGE_TRACKING.md](STAGE_TRACKING.md) - Pipeline stage tracking design
- [VIDEO_PROCESSOR_ARCHITECTURE.md](VIDEO_PROCESSOR_ARCHITECTURE.md) - Video processor design
- [SUBPROCESS_USAGE.md](SUBPROCESS_USAGE.md) - Subprocess vs Python API usage

## Troubleshooting & Debugging

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - General troubleshooting guide
- [GPU_USAGE_INFO.md](GPU_USAGE_INFO.md) - GPU utilization expectations

## Debug Guides

- [DEBUG_FEATURE_EXTRACTION.md](DEBUG_FEATURE_EXTRACTION.md) - Feature extraction progress debugging
- [DEBUG_TRAINING_UI_UPDATE.md](DEBUG_TRAINING_UI_UPDATE.md) - Training UI update debugging

## Bug Fixes (Chronological)

### Core Issues
- [FIX_STDERR_CAPTURE.md](FIX_STDERR_CAPTURE.md) - FD-level stderr capture for COLMAP
- [FIX_TRANSFORMS_JSON_NOT_FOUND.md](FIX_TRANSFORMS_JSON_NOT_FOUND.md) - transforms.json path resolution
- [FIX_TIMESTAMP_PLACEHOLDER.md](FIX_TIMESTAMP_PLACEHOLDER.md) - Trainer timestamp handling
- [FIX_MAX_FRAMES_PARAMETER.md](FIX_MAX_FRAMES_PARAMETER.md) - Max frames propagation

### Training & Export Issues
- [FIX_GSPLAT_LINK_ERROR.md](FIX_GSPLAT_LINK_ERROR.md) - gsplat CUDA extension linking
- [FIX_CHECKPOINT_EXPORT.md](FIX_CHECKPOINT_EXPORT.md) - Checkpoint saving for short runs
- [FIX_OLD_CONFIG_PATH.md](FIX_OLD_CONFIG_PATH.md) - Using correct config path
- [FIX_TRANSFORMS_PATH_EXPORT.md](FIX_TRANSFORMS_PATH_EXPORT.md) - Config data path handling
- [FIX_DATAPARSER_PATH_FINAL.md](FIX_DATAPARSER_PATH_FINAL.md) - ~~Final fix for dataparser.data path~~ (obsolete)
- [FIX_EXPORT_WARNINGS.md](FIX_EXPORT_WARNINGS.md) - ~~PyTorch warning handling~~ (obsolete)
- [**PLY_EXPORT_APPROACHES.md**](PLY_EXPORT_APPROACHES.md) - **All 11 export approaches analyzed**
- [**DIRECT_EXPORT_SOLUTION.md**](DIRECT_EXPORT_SOLUTION.md) - **⭐ SOLUTION: Direct checkpoint loading**

### UI Issues
- [FIX_CANCEL_BUTTON.md](FIX_CANCEL_BUTTON.md) - Cancel button termination
- [FIX_VIDEO_PATH_PERSISTENCE.md](FIX_VIDEO_PATH_PERSISTENCE.md) - Settings persistence timing
- [FIX_VIDEO_INFO_PYAV.md](FIX_VIDEO_INFO_PYAV.md) - Video info display + PyAV integration

## Changelogs

- [CHANGELOG_GRANULAR_STAGES.md](CHANGELOG_GRANULAR_STAGES.md) - Granular stage panels
- [CHANGELOG_REMOVE_GLOBAL_PROGRESS.md](CHANGELOG_REMOVE_GLOBAL_PROGRESS.md) - Removed global progress bar
- [CHANGELOG_VIDEO_PROCESSORS.md](CHANGELOG_VIDEO_PROCESSORS.md) - Video processor architecture
- [UI_IMPROVEMENTS_TOTAL_COUNTS.md](UI_IMPROVEMENTS_TOTAL_COUNTS.md) - Total counts in UI

## Document Organization

**By Type**:
- Setup guides: Installation, configuration, environment setup
- Architecture docs: Design decisions, component structure
- Debug guides: Step-by-step debugging procedures
- Fix docs: Specific bug fixes with root cause analysis
- Changelogs: Feature additions and improvements

**By Topic**:
- Video processing: FIX_VIDEO_INFO_PYAV, VIDEO_PROCESSOR_ARCHITECTURE
- Training: FIX_GSPLAT_LINK_ERROR, DEBUG_TRAINING_UI_UPDATE, GPU_USAGE_INFO
- Export: FIX_CHECKPOINT_EXPORT, FIX_EXPORT_WARNINGS, FIX_DATAPARSER_PATH_FINAL
- UI: FIX_CANCEL_BUTTON, FIX_VIDEO_PATH_PERSISTENCE, STAGE_TRACKING
- COLMAP: FIX_STDERR_CAPTURE, DEBUG_FEATURE_EXTRACTION

## Most Important Documents (Start Here)

1. **README.md** (in project root) - Project overview
2. **INSTALLATION_COMPLETE.md** - Initial setup
3. **NERFSTUDIO_SETUP.md** - Nerfstudio installation
4. **ARCHITECTURE.md** - System design
5. **TROUBLESHOOTING.md** - Common issues
6. **⭐ DIRECT_EXPORT_SOLUTION.md** - **Latest breakthrough: Direct Python API export**
7. **PLY_EXPORT_APPROACHES.md** - All export approaches compared

## Latest Developments (2025-12-11)

Today's progress in order:
1. FIX_GSPLAT_LINK_ERROR - libcudart symlink
2. FIX_CANCEL_BUTTON - Process termination
3. FIX_VIDEO_INFO_PYAV - PyAV integration
4. FIX_EXPORT_WARNINGS - PyTorch warning suppression (obsolete)
5. FIX_CHECKPOINT_EXPORT - Short training checkpoint saving
6. FIX_OLD_CONFIG_PATH - Correct config selection
7. FIX_TRANSFORMS_PATH_EXPORT - Absolute path handling (obsolete)
8. FIX_DATAPARSER_PATH_FINAL - Dataparser path before Trainer creation (obsolete)
9. FIX_VIDEO_PATH_PERSISTENCE - Signal connection timing
10. **PLY_EXPORT_APPROACHES** - Analyzed all 11 possible export approaches
11. **DIRECT_EXPORT_SOLUTION** - ⭐ **Breakthrough: Direct checkpoint loading (no subprocess!)**

## Document Status

✅ All documentation organized in `docs/` folder  
✅ Project root clean (only README.md)  
✅ Index created for easy navigation

