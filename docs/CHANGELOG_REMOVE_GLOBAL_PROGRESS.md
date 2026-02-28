# Changelog: Removed Global Progress Bar

## What Changed

**Removed global progress bar** from UI - replaced with simple pipeline status label.

### Before
```
┌─────────────────────────────────────┐
│ Progress: Data Processing: 47%     │
│ ████████████░░░░░░░░░░░░░░ 47%     │ ← Progress bar
└─────────────────────────────────────┘
```

### After
```
┌─────────────────────────────────────┐
│ Pipeline Status: Extracting features... │ ← Simple status
└─────────────────────────────────────┘
```

## Why This Change

**User feedback**: "UI doesn't need global progress display. Showing individual stages progress is enough."

**Problems with global progress bar:**

1. **Redundant**: Each stage panel already shows detailed progress
2. **Inaccurate**: No reliable way to compute overall progress
   - Different stages take vastly different times
   - Frame extraction: 30 seconds
   - Feature extraction: 2 minutes
   - Training: 10-30 minutes
   - Equal percentage weighting doesn't reflect reality
3. **Misleading**: Users see "47%" but don't know if that means 5 minutes or 30 minutes remaining
4. **Visual clutter**: Takes up screen space without adding value

## Benefits

1. ✅ **Cleaner UI**: More space for stage panels and logs
2. ✅ **Less confusion**: No misleading percentage numbers
3. ✅ **Focus on stages**: Users watch individual stage progress (which is accurate)
4. ✅ **Simpler code**: No need to calculate weighted progress percentages

## UI Changes

### New Status Display

**Simple text-only status** showing current high-level phase:

| Pipeline Phase | Status Label |
|----------------|--------------|
| Ready | "Ready" |
| Frame extraction | "Extracting frames..." |
| Feature extraction | "Extracting features..." |
| Feature matching | "Matching features..." |
| Reconstruction | "Building reconstruction..." |
| Training | "Training Gaussian Splatting model..." |
| Export | "Exporting PLY..." |
| Complete | "✓ Pipeline complete" |
| Failed | "✗ Pipeline failed" |

### Stage Panels (Unchanged)

Stage panels still show detailed progress:

```
🔵 2. Feature Extraction          [View Files]
   150/317
   Extracting SIFT features (47%)
```

This is where users get accurate, actionable progress information.

## Implementation Details

### Removed

- **QProgressBar widget** - deleted from UI
- **progress_bar.setValue()** - all 10+ calls removed
- **Percentage calculations** - weighted progress computation removed

### Simplified

**progress_label** updates:

```python
# Old - complex percentage tracking
progress_percent = int(progress * 100)
self.progress_bar.setValue(progress_percent)
self.progress_label.setText(f"{stage}: {progress_percent}%")

# New - simple status messages
self.progress_label.setText("Extracting features...")
```

### Error Detection

**Old approach** - based on progress percentage:
```python
if self.progress_bar.value() < 25:
    self._update_stage('feature_extract', 'error', 'Failed')
elif self.progress_bar.value() < 40:
    self._update_stage('feature_match', 'error', 'Failed')
...
```

**New approach** - based on stage status icons:
```python
# Find first stage that was pending or running
for stage_key in ['frames', 'feature_extract', ...]:
    status_label = stage_widget.findChild(QLabel, f"{stage_key}_status")
    if '⚪' in status_label.text() or '🔵' in status_label.text():
        self._update_stage(stage_key, 'error', 'Failed')
        break
```

More accurate - marks the actual stage where failure occurred.

## Files Modified

**`splats/main_window.py`**:
- Removed `QProgressBar` import
- Removed progress bar widget creation
- Simplified progress label to status label
- Removed all `progress_bar.setValue()` calls
- Simplified progress text updates
- Improved error detection logic

## Testing

```bash
conda activate splats
python run.py
```

**Verify:**
1. No progress bar visible in UI
2. Status label shows current phase: "Extracting frames...", "Extracting features...", etc.
3. Stage panels show detailed progress with counts and percentages
4. On completion: status shows "✓ Pipeline complete"
5. On error: status shows "✗ Pipeline failed" and correct stage marked error

## User Impact

**Positive:**
- Cleaner, less cluttered UI
- No more "stuck at 47%" confusion
- Focus shifts to accurate stage-by-stage progress

**Neutral:**
- Users who liked seeing overall percentage can still estimate from stage panels
- Overall time estimation still available (just not as misleading bar)

## Future Considerations

Could add back a **time-based progress indicator** if needed:
- "Elapsed: 5m 23s"
- "Estimated remaining: ~15 minutes" (based on typical times)

But **not percentage-based** - too inaccurate given variable stage durations.

## Related Changes

This change complements:
- **Granular stage panels** (CHANGELOG_GRANULAR_STAGES.md) - detailed per-stage progress
- **FD redirection** (FIX_STDERR_CAPTURE.md) - enables accurate stage progress
- **Stage tracking** (STAGE_TRACKING.md) - documents progress reporting

## Questions?

See stage panels for detailed progress. They show accurate N/M counts and percentages for each phase.

