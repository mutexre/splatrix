# UI Improvement: Show Total Counts Upfront

## Problem

**User feedback**: "It's not clear from the progress UI how many items are in total to process."

**Example of confusing display**:
```
🔵 2. Feature Extraction          [View Files]
   150/317                         ← Total only visible after progress starts
   Extracting SIFT features (47%)
```

User had to wait for first progress update to see that 317 images would be processed.

## Solution

**Show total count in details text immediately** when stage starts:

### Before
```
🔵 2. Feature Extraction          [View Files]
   Running
   Extracting SIFT features from images
```
User sees: "How many images?" 🤷

### After
```
🔵 2. Feature Extraction          [View Files]
   1/317                           ← Total visible immediately
   Processing 317 images - extracting SIFT features (0%)
```
User sees: "317 images to process" ✓

## Changes

### 1. Feature Extraction
```
Display: "1/317" or "150/317"
Details: "Processing 317 images - extracting SIFT features (47%)"
```

**Before first update**: "Starting"
**After first update**: Total count always visible

### 2. Feature Matching
```
Display: "1/317" or "100/317"
Details: "Processing 317 images - matching features (32%)"
```

### 3. Sparse Reconstruction
```
Display: "50 registered" or "150 registered"
Details: "Registered 150 images - building 3D structure"
```

**Sub-phases also show context**:
- Bundle adjustment: "Bundle adjustment - optimizing camera poses and 3D points"
- Refining: "Refining camera intrinsic parameters"

### 4. Training
```
Display: "1000/30000" or "15000/30000"
Details: "Training 30000 iterations - splatfacto model (50%)"
```

### 5. Frame Extraction
```
Display: "150 extracted"
Details: "Extracting frames from video (target: ~300)"
```

Shows approximate target since actual count depends on video length and sampling.

## Benefits

1. **Transparency**: Users know immediately what's coming
2. **Time estimation**: Seeing "30000 iterations" helps set expectations
3. **No surprises**: Users aren't caught off-guard by large totals
4. **Better UX**: Information available upfront, not hidden until progress starts

## Implementation

Updated `_on_nerfstudio_progress()` in `splats/main_window.py`:

```python
# OLD - no total visible upfront
if count_match:
    current = count_match.group(1)
    total = count_match.group(2)
    display_text = f"{current}/{total}"
    details_text = f"Extracting SIFT features ({percent}%)"
else:
    display_text = "Running"
    details_text = "Extracting SIFT features from images"

# NEW - total in details text
if count_match:
    current = count_match.group(1)
    total = count_match.group(2)
    display_text = f"{current}/{total}"
    details_text = f"Processing {total} images - extracting SIFT features ({percent}%)"
    #                          ^^^^^^^^^^^^^ Total visible immediately
else:
    display_text = "Starting"
    details_text = "Extracting SIFT features from images"
```

## Example UI Flow

**User starts conversion:**

```
1. Frame Extraction: Starting → 50 extracted → 150 extracted → 300 extracted → Complete
   Details: "Extracting frames from video (target: ~300)"

2. Feature Extraction: Starting → 1/317 → 50/317 → 150/317 → 317/317 → Complete
   Details: "Processing 317 images - extracting SIFT features (47%)"
                        ^^^ User knows total from first update

3. Feature Matching: Starting → 1/317 → 50/317 → 150/317 → 317/317 → Complete
   Details: "Processing 317 images - matching features (32%)"

4. Sparse Reconstruction: Starting → 50 registered → 150 registered → 300 registered
   Details: "Registered 150 images - building 3D structure"

5. Training: 100/30000 → 1000/30000 → 5000/30000 → ... → 30000/30000
   Details: "Training 30000 iterations - splatfacto model (17%)"
                     ^^^^^ User knows this will take a while

6. Export: Running → Complete
   Details: "Exporting Gaussian Splats to PLY format"
```

## User Experience Improvement

**Before**: "How long is this going to take? How many items?"  
**After**: "OK, 317 images in feature extraction, then 30000 training steps. I'll grab coffee."

Users can make informed decisions about:
- Whether to wait or do something else
- Whether the settings are appropriate (maybe 30000 iterations is too many for a test)
- Whether to cancel and adjust parameters

## Testing

```bash
conda activate splats
python run.py
```

**Watch for**:
1. Feature extraction panel shows "Processing 317 images" in details as soon as count is known
2. Training panel shows "Training 30000 iterations" as soon as training starts
3. All stage panels show totals prominently in details text
4. Users never have to guess "how many more?"

## Files Modified

**`splats/main_window.py`**:
- Updated feature extraction progress mapping
- Updated feature matching progress mapping
- Updated sparse reconstruction progress mapping
- Updated training progress mapping
- Updated frame extraction progress mapping

All stages now show totals in details text when available.

## Related Changes

This complements:
- **Granular stage panels** (CHANGELOG_GRANULAR_STAGES.md) - separate panels per phase
- **Remove global progress** (CHANGELOG_REMOVE_GLOBAL_PROGRESS.md) - focus on stage details
- **FD redirection** (FIX_STDERR_CAPTURE.md) - captures COLMAP progress for display

Together, these changes provide **complete visibility** into pipeline progress without overwhelming users with numbers they can't interpret.

