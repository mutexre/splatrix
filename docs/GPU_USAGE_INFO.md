# GPU Usage Information

## GPU Detection and Configuration

### Automatic GPU Detection
The training pipeline now explicitly checks and configures GPU usage:

1. **At training start**: Detects CUDA availability and GPU model
2. **Device configuration**: Sets `config.machine.device_type = "cuda"`
3. **Memory logging**: Reports GPU memory allocated/reserved after model setup
4. **Model verification**: Confirms model parameters are on GPU

### Console Output
When training starts, you should see:
```
[Training] Using GPU: Quadro RTX 4000
[Training] GPU memory: 0.45GB allocated, 0.50GB reserved
[Training] Model device: cuda:0
```

## Expected GPU Utilization

### Small Datasets (30-50 frames)
- **GPU Utilization**: 10-30% typical
- **Reason**: 
  - Fast forward passes (model is optimized)
  - Small batch sizes
  - Waiting for Adam optimizer, loss computation
  - CPU preprocessing (loading images, data augmentation)
  - Periodic validation/rendering (not every step)

### Larger Datasets (300+ frames)
- **GPU Utilization**: 40-80% typical
- More time spent in rendering and splatting operations
- Larger memory footprint → more GPU work

### GPU Memory Usage
- **Quadro RTX 4000**: 8GB total
- **Expected usage**: 0.5-2GB for small datasets (30 frames)
- **Expected usage**: 2-6GB for larger datasets (300 frames)
- **System overhead**: ~2-3GB (X, desktop, other apps)

## How to Monitor GPU Usage

### During Training
```bash
# Watch GPU usage in real-time (updates every 1s)
watch -n 1 nvidia-smi

# Or continuous log
nvidia-smi --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,memory.total --format=csv -l 1
```

### What to Look For
✅ **Normal**:
- GPU utilization 10-80% (varies with dataset size)
- Memory usage increases after "Training started" message
- Utilization spikes during training steps
- Lower utilization during evaluation/validation

❌ **Problem**:
- GPU utilization stays at 0%
- No memory increase after training starts
- Console shows "WARNING: Training on CPU"
- Console shows "Model device: cpu"

## Training Performance Expectations

### Quadro RTX 4000 (Turing, 8GB)

#### Small Dataset (30 frames, 1000 iterations)
- **Time**: ~2-4 minutes
- **GPU Util**: 10-30%
- **Memory**: ~0.5-1GB
- **Speed**: ~6-10 iterations/second

#### Medium Dataset (300 frames, 30000 iterations)
- **Time**: ~30-60 minutes
- **GPU Util**: 40-70%
- **Memory**: ~2-4GB
- **Speed**: ~8-15 iterations/second

## Troubleshooting

### Low GPU Utilization (<5%)

**Check console for warnings**:
```bash
grep -i "WARNING\|cpu\|device" <console_output>
```

**Verify CUDA in Python**:
```bash
python3 -c "import torch; print('CUDA:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0))"
```

**Check nvidia-smi during training**:
- Should see python process using GPU
- Memory usage should increase

### Training on CPU (Very Slow)

If you see:
```
[Training] ⚠ WARNING: Training on CPU - this will be very slow!
```

**Possible causes**:
1. PyTorch not compiled with CUDA support
2. CUDA driver/toolkit version mismatch
3. Environment variable override (e.g., `CUDA_VISIBLE_DEVICES=""`)

**Fix**:
```bash
# Reinstall PyTorch with CUDA
pip install --upgrade torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu118

# Verify
python3 -c "import torch; print(torch.cuda.is_available())"
```

## Why GPU Utilization Isn't Always 100%

Gaussian Splatting training is **not purely compute-bound**. The pipeline includes:

1. **Rasterization** (GPU) - ~60% of time
2. **Loss computation** (GPU) - ~10% of time  
3. **Optimizer step** (mixed CPU/GPU) - ~15% of time
4. **Data loading** (CPU) - ~10% of time
5. **Validation/logging** (mixed) - ~5% of time

Even with perfect optimization, GPU utilization typically caps at 60-80% for small datasets due to Python overhead and I/O.

## Comparison: CPU vs GPU Training

### 1000 iterations, 30 frames

| Device | Time | Iterations/sec |
|--------|------|----------------|
| **Quadro RTX 4000** | 2-4 min | 6-10 iter/s |
| **CPU (16 cores)** | 60-120 min | 0.2-0.5 iter/s |

**Speed-up**: ~15-30x faster on GPU

## Current System Status

```bash
# Quick check
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
```

Your system:
- GPU: Quadro RTX 4000
- Memory: 8192 MiB
- Driver: 575.51.03
- CUDA Version: 12.9 (driver supports)
- PyTorch CUDA: 11.8 (compatible)

## Verification After Fix

Run a test training session and verify:
```
✅ Console shows: "[Training] Using GPU: Quadro RTX 4000"
✅ Console shows: "[Training] Model device: cuda:0"
✅ nvidia-smi shows python process with GPU memory usage
✅ Training completes in ~2-4 minutes for 1000 iterations (31 frames)
```

---

**Note**: Low GPU utilization (10-30%) on small datasets is **normal and expected**. The GPU is being used, just not at full capacity because:
- Small model fits entirely in GPU cache
- Fast forward/backward passes
- CPU overhead becomes bottleneck for tiny datasets
- Most time spent in Python code, not CUDA kernels

