# Changelog: Granular Stage Panels

## What Changed

**Refactored UI to show 6 separate stage panels instead of 4**, providing better visibility into each phase of the pipeline.

### Before (4 stages)
1. Frame Extraction
2. COLMAP / SfM ← (all COLMAP phases lumped together)
3. Training (Splatfacto)
4. Export PLY

### After (6 stages)
1. Frame Extraction
2. Feature Extraction ← **NEW**
3. Feature Matching ← **NEW**
4. Sparse Reconstruction ← **NEW**
5. Training (Splatfacto)
6. Export PLY

## Why This Change

**Problem**: During COLMAP processing (which takes 2-5 minutes), the UI showed a single "COLMAP / SfM" panel that switched between:
- "Extracting features"
- "Matching features"
- "Sparse reconstruction"

**User confusion**: Hard to tell which COLMAP phase was running and how much progress had been made in each sub-phase.

**Solution**: Split COLMAP into 3 separate panels, each showing:
- **Status icon**: ⚪ pending, 🔵 running, ✅ done, ❌ error
- **Progress count**: e.g., "150/317" for feature extraction
- **Details**: Descriptive text with percentage
- **View Files button**: Opens COLMAP output directory

## UI Changes

### Stage Panel Display

**Feature Extraction Panel**:
```
🔵 2. Feature Extraction          [View Files]
   150/317
   Extracting SIFT features (47%)
```

**Feature Matching Panel**:
```
🔵 3. Feature Matching             [View Files]
   100/317
   Matching features between images (32%)
```

**Sparse Reconstruction Panel**:
```
🔵 4. Sparse Reconstruction        [View Files]
   150 images
   Registering images and building 3D structure
```

### Progress Mapping

**Updated progress callbacks** to emit stage-specific updates:

| Progress Range | Stage | Display |
|----------------|-------|---------|
| 0-15% | Frame Extraction | "N frames" |
| 15-30% | Feature Extraction | "N/M" with % |
| 30-50% | Feature Matching | "N/M" with % |
| 50-80% | Sparse Reconstruction | "N images" |
| 80-95% | Training | "Step N/M" |
| 95-100% | Export | Status |

## Files Modified

### 1. `splats/main_window.py`

**Stage tracking updated**:
```python
# Old (4 stages)
self.stage_paths = {
    'frames': None,
    'colmap': None,  # ← Lumped all COLMAP phases
    'training': None,
    'export': None
}

# New (6 stages)
self.stage_paths = {
    'frames': None,
    'feature_extract': None,  # ← New
    'feature_match': None,     # ← New
    'reconstruction': None,     # ← New
    'training': None,
    'export': None
}
```

**UI creation updated**:
```python
# Old
self.stage_widgets['colmap'] = self._create_stage_widget("COLMAP / SfM", "colmap")

# New
self.stage_widgets['feature_extract'] = self._create_stage_widget("2. Feature Extraction", "feature_extract")
self.stage_widgets['feature_match'] = self._create_stage_widget("3. Feature Matching", "feature_match")
self.stage_widgets['reconstruction'] = self._create_stage_widget("4. Sparse Reconstruction", "reconstruction")
```

**Progress handling updated**:
```python
# Old - all COLMAP phases updated same widget
self._update_stage('colmap', 'running', display_text, ...)

# New - each COLMAP phase updates its own widget
elif "extracting features" in substage.lower():
    self._update_stage('feature_extract', 'running', f"{current}/{total}", ...)

elif "matching features" in substage.lower():
    self._update_stage('feature_match', 'running', f"{current}/{total}", ...)

elif "reconstruction" in substage.lower():
    self._update_stage('reconstruction', 'running', f"{num} images", ...)
```

### 2. `STAGE_TRACKING.md`

Updated documentation to reflect 6 stages with detailed descriptions of each COLMAP phase.

## User Benefits

1. **Better visibility**: See exactly which COLMAP phase is running
2. **Progress clarity**: Each phase shows specific progress (N/M counts)
3. **Time estimation**: Users can estimate remaining time per phase
4. **Debugging**: Easier to identify which phase failed if error occurs
5. **File access**: Each COLMAP phase has "View Files" button (all point to same colmap/ directory)

## Implementation Details

### State Transitions

**Normal flow**:
```
1. Frame Extraction: pending → running → done
2. Feature Extraction: pending → running → done
3. Feature Matching: pending → running → done
4. Sparse Reconstruction: pending → running → done
5. Training: pending → running → done
6. Export: pending → running → done
```

**When entering new stage**, previous stages automatically marked `done`:
```python
# When feature matching starts
self._update_stage('frames', 'done', "Complete")
self._update_stage('feature_extract', 'done', "Complete")
self._update_stage('feature_match', 'running', "0/317")
```

### Error Handling

**Progress-based error detection**:
```python
if progress < 10%:
    self._update_stage('frames', 'error', 'Failed')
elif progress < 25%:
    self._update_stage('feature_extract', 'error', 'Failed')
elif progress < 40%:
    self._update_stage('feature_match', 'error', 'Failed')
elif progress < 55%:
    self._update_stage('reconstruction', 'error', 'Failed')
...
```

## Testing

Start the GUI and process a video with Nerfstudio pipeline:

```bash
conda activate splats
python run.py
```

**Expected behavior**:
1. Select video
2. Start conversion (Nerfstudio mode)
3. Watch stage panels update sequentially:
   - Frame Extraction shows frame count
   - Feature Extraction shows "N/M" and percentage
   - Feature Matching shows "N/M" and percentage
   - Sparse Reconstruction shows "N images"
   - Training shows "Step N/M"
   - Export shows status

**Each panel should**:
- Show ⚪ when pending
- Show 🔵 when running with live progress
- Show ✅ when complete
- Enable "View Files" button when output directory created

## Backward Compatibility

✅ **Fully compatible** - no API changes, only UI refinement.

Existing code that doesn't interact with stage widgets continues to work unchanged.

## Performance Impact

**None** - same underlying logic, just more granular UI updates.

## Future Enhancements

Possible improvements:
1. **Progress bars per stage**: Add mini progress bar to each panel
2. **Time estimates**: Show estimated time remaining per stage
3. **Substage breakdown**: Show bundle adjustment sub-phases separately
4. **Collapsible panels**: Allow hiding completed stages
5. **Log filtering**: Filter log view by selected stage

## Related Changes

This change complements:
- **FD redirection** (FIX_STDERR_CAPTURE.md) - enables capturing COLMAP progress
- **Video processor refactor** (VIDEO_PROCESSOR_ARCHITECTURE.md) - provides progress callbacks
- **Stage tracking docs** (STAGE_TRACKING.md) - documents progress reporting

## Questions?

See `STAGE_TRACKING.md` for detailed documentation of each stage and progress tracking implementation.

