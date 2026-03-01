#!/usr/bin/env bash
set -euo pipefail

# ── Splats Installer ──────────────────────────────────────────────
# Installs the Splats application with all dependencies.
# Requirements: conda (Miniconda or Anaconda) must be installed.
# ──────────────────────────────────────────────────────────────────

ENVNAME="${SPLATS_ENV:-splats}"
PYTHON_VERSION="3.10"
CUDA_VERSION="12.1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ── Preflight checks ─────────────────────────────────────────────

command -v conda >/dev/null 2>&1 || fail "conda not found. Install Miniconda first: https://docs.conda.io/en/latest/miniconda.html"

# Detect NVIDIA GPU
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_INFO=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    ok "NVIDIA GPU detected: ${GPU_INFO}"
    HAS_GPU=true
else
    warn "No NVIDIA GPU detected. GPU-accelerated training will not be available."
    HAS_GPU=false
fi

# ── Conda environment ────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Initialize conda for this shell
eval "$(conda shell.bash hook)"

if conda env list | grep -q "^${ENVNAME} "; then
    info "Conda environment '${ENVNAME}' already exists."
    read -rp "Recreate it? (y/N) " yn
    if [[ "$yn" =~ ^[Yy]$ ]]; then
        info "Removing old environment..."
        conda env remove -n "$ENVNAME" -y
    else
        info "Using existing environment."
    fi
fi

if ! conda env list | grep -q "^${ENVNAME} "; then
    info "Creating conda environment '${ENVNAME}' with Python ${PYTHON_VERSION}..."
    conda create -n "$ENVNAME" python="${PYTHON_VERSION}" -y -q
fi

info "Activating environment '${ENVNAME}'..."
conda activate "$ENVNAME"

# ── PyTorch + CUDA ────────────────────────────────────────────────

if "$HAS_GPU"; then
    info "Installing PyTorch with CUDA ${CUDA_VERSION}..."
    pip install torch torchvision --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" -q
else
    info "Installing PyTorch (CPU only)..."
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu -q
fi

# ── COLMAP ────────────────────────────────────────────────────────

info "Installing COLMAP..."
conda install -c conda-forge colmap -y -q 2>/dev/null || warn "COLMAP install via conda failed — install manually if needed."

# ── FFmpeg ────────────────────────────────────────────────────────

info "Installing FFmpeg..."
conda install -c conda-forge ffmpeg -y -q 2>/dev/null || warn "FFmpeg install via conda failed."

# ── Nerfstudio ────────────────────────────────────────────────────

if "$HAS_GPU"; then
    info "Installing Nerfstudio..."
    pip install nerfstudio -q
fi

# ── Splats (this package) ────────────────────────────────────────

info "Installing Splats..."
cd "$SCRIPT_DIR"
pip install -e ".[nerfstudio]" -q 2>/dev/null || pip install -e . -q

# ── Verify ────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Splats installed successfully!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo ""
echo "  To run:"
echo -e "    ${CYAN}conda activate ${ENVNAME}${NC}"
echo -e "    ${CYAN}splats${NC}"
echo ""

if "$HAS_GPU"; then
    python -c "import torch; print(f'  PyTorch {torch.__version__}  CUDA: {torch.cuda.is_available()}')"
fi
