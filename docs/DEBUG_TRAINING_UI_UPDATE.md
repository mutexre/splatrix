# Debug: Training UI Not Updating

## Date
2025-12-11

## Problem
Training progress shows in console but UI training stage panel not updating.

## Investigation

### Issue Found #1: Missing `progress_percent` Variable
**Location**: `main_window.py::_on_nerfstudio_progress()`

**Error**: `progress_percent` used but never defined (line 794, 938)
- Would cause NameError when code path executed
- May have been silently caught or prevented UI updates

**Fix**: Added `progress_percent = int(progress * 100)` at start of method

### Added Debug Logging

To diagnose the issue, added debug output at three key points:

#### 1. Raw Progress Data Reception
```python
if "Training" in stage:
    print(f"[UI DEBUG] stage='{stage}', substage='{substage}', progress={progress}")
```

**Expected output during training**:
```
[UI DEBUG] stage='Training Gaussian Splats', substage='Training: Step 50/1000', progress=0.235
[UI DEBUG] stage='Training Gaussian Splats', substage='Training: Step 100/1000', progress=0.27
[UI DEBUG] stage='Training Gaussian Splats', substage='Training: Step 150/1000', progress=0.305
```

#### 2. Step Parsing Result
```python
if step_match:
    current_step = step_match.group(1)
    total_steps = step_match.group(2)
    info_text = f"{current_step}/{total_steps}"
    print(f"[UI] Training progress: {info_text} ({progress_percent}%)")
```

**Expected output**:
```
[UI] Training progress: 50/1000 (23%)
[UI] Training progress: 100/1000 (27%)
[UI] Training progress: 150/1000 (30%)
```

#### 3. Stage Widget Update
```python
if stage_key == 'training':
    print(f"[UI DEBUG] _update_stage: status={status}, info={info}, details={details[:50]}")
```

**Expected output**:
```
[UI DEBUG] _update_stage: status=running, info=50/1000, details=Training 1000 iterations - splatfacto model (23%)
[UI DEBUG] _update_stage: status=running, info=100/1000, details=Training 1000 iterations - splatfacto model (27%)
```

## Testing Instructions

### Run Training with Debug Output

1. **Start app**:
   ```bash
   conda activate splats
   cd /home/alexander.obuschenko/Projects/splats
   python run.py 2>&1 | tee training_debug.log
   ```

2. **Start training** with Max Frames=30, Iterations=1000

3. **Watch console for debug output**

### Expected vs Actual Behavior

#### ✅ If Working Correctly
Console shows all three debug outputs interleaved:
```
[Training] Training: Step 50/1000
[UI DEBUG] stage='Training Gaussian Splats', substage='Training: Step 50/1000', progress=0.235
[UI] Training progress: 50/1000 (23%)
[UI DEBUG] _update_stage: status=running, info=50/1000, details=Training 1000 iterations - splatfacto model (23%)
```

**AND** UI training panel shows:
- Icon: 🔵 (running)
- Info: "50/1000"
- Details: "Training 1000 iterations - splatfacto model (23%)"
- Updates every ~2-5 seconds

#### ❌ If Still Not Working

**Scenario A**: No debug output at all
- Progress signal not reaching UI
- Check QThread connection
- Check if worker still running

**Scenario B**: Debug output #1 appears but not #2 or #3
- Regex not matching
- Check substage format
- Check if "Training" check failing

**Scenario C**: Debug output #1 and #2 appear but not #3
- _update_stage not being called
- Check code flow after regex match

**Scenario D**: All debug output appears but UI still not updating
- Qt widget update issue
- Check if widgets exist (self.stage_widgets['training'])
- Check if running on UI thread

## Data Flow

```
nerfstudio_integration.py
  └─ progress_callback("Training: Step 50/1000", 0.035)
       ↓
worker_threads.py::training_progress()
  └─ self.progress.emit({'stage': 'Training Gaussian Splats', 'progress': 0.235, 'substage': 'Training: Step 50/1000'})
       ↓
main_window.py::_on_nerfstudio_progress(data)
  └─ [DEBUG #1] Print raw data
  └─ Check "Training" in stage ✓
  └─ Regex match: r'Step (\d+)/(\d+)' on substage
       ↓ (if match)
  └─ [DEBUG #2] Print parsed step
  └─ self._update_stage('training', 'running', '50/1000', details='...')
       ↓
main_window.py::_update_stage(stage_key, status, info, details)
  └─ [DEBUG #3] Print update call
  └─ Find QLabel widgets by object name
  └─ Update text on widgets
```

## Possible Root Causes

### 1. Threading Issue (Most Likely)
- Progress signal emitted from worker thread
- UI updates must happen on main/GUI thread
- Qt should handle this automatically via pyqtSignal
- **Check**: Verify signal connected with Qt.QueuedConnection (default for cross-thread)

### 2. Widget Not Found
- `self.stage_widgets.get('training')` returns None
- **Check**: Verify training stage widget created in _create_progress_section()

### 3. Progress Data Format Mismatch
- Worker emitting wrong format
- **Check**: Verify emit dict has 'stage', 'progress', 'substage' keys

### 4. Regex Not Matching
- Substage format different than expected
- **Check**: Debug output #1 will show actual format

### 5. Missing Error Handling
- Silent exception in _on_nerfstudio_progress
- **Check**: Wrap in try/except and log any errors

## Next Steps Based on Test Results

### If Debug Output Shows Progress Data Received
→ Issue is in UI update code (_update_stage or widget finding)

### If Debug Output Shows No Progress Data
→ Issue is in signal emission or connection

### If Training Console Shows Steps But No UI Debug
→ Signal not connected or progress dict missing keys

## Temporary Workaround

If UI still not updating after fix, force refresh by calling:
```python
QApplication.processEvents()
```

After widget updates in _update_stage() - but this is a hack and shouldn't be needed.

## Files Modified

- `splats/main_window.py`
  - Added `progress_percent` variable definition
  - Added three debug print statements
  - Fixed NameError that would prevent updates

## Clean Up After Debugging

Once issue found and fixed, remove debug prints:
```bash
grep -n "DEBUG" splats/main_window.py
# Remove lines with [UI DEBUG] and [UI] Training progress
```

