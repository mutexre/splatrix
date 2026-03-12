#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════
#  Splatrix Installer — self-contained, zero system modification
#
#  Usage:
#    curl -fsSL https://mutexre.github.io/splatrix/install.sh | bash
#
#  Everything goes into ~/.splatrix/ — nothing else is touched.
#
#  Layout:
#    ~/.splatrix/
#    ├── bin/micromamba
#    ├── bin/splatrix       ← launcher script
#    ├── envs/              ← conda environments (created by micromamba)
#    ├── src/               ← splatrix source code
#    └── splatrix.desktop   ← Linux desktop entry (optional)
#
#  Requirements:
#    Linux x86_64:  NVIDIA GPU + drivers
#    macOS arm64:   Apple Silicon (MPS acceleration)
#    macOS x86_64:  NVIDIA GPU or CPU-only
# ══════════════════════════════════════════════════════════════════

SPLATRIX_VERSION="${SPLATRIX_VERSION:-main}"
SPLATRIX_REPO="https://github.com/mutexre/splatrix"
SPLATRIX_HOME="${SPLATRIX_HOME:-$HOME/.splatrix}"
ENV_NAME="splatrix"
PYTHON_VERSION="3.10"

# ── Colors ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[•]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${BOLD}── $* ──${NC}"; }

# ── Detect platform ──────────────────────────────────────────────

step "Preflight checks"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)
        [[ "$ARCH" == "x86_64" ]] || fail "Linux: only x86_64 supported (got $ARCH)."
        PLATFORM="linux-64"
        ;;
    Darwin)
        case "$ARCH" in
            arm64)  PLATFORM="osx-arm64" ;;
            x86_64) PLATFORM="osx-64" ;;
            *)      fail "macOS: unsupported architecture $ARCH." ;;
        esac
        ;;
    *)
        fail "Unsupported OS: $OS. Use install.ps1 for Windows."
        ;;
esac

ok "Platform: $OS $ARCH ($PLATFORM)"

# Download tool
if command -v curl >/dev/null 2>&1; then
    DL="curl -fsSL"
elif command -v wget >/dev/null 2>&1; then
    DL="wget -qO-"
else
    fail "Neither curl nor wget found. Install one first."
fi

# GPU check
if [[ "$OS" == "Linux" ]]; then
    if command -v nvidia-smi >/dev/null 2>&1; then
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
        ok "NVIDIA GPU: ${GPU_NAME} (${GPU_MEM} MB)"
        CUDA_VERSION="12.1"
    else
        warn "nvidia-smi not found. NVIDIA drivers required for GPU training."
        warn "Install drivers: https://docs.nvidia.com/cuda/cuda-installation-guide-linux/"
        read -rp "Continue without GPU? (y/N) " yn
        [[ "$yn" =~ ^[Yy]$ ]] || exit 0
        CUDA_VERSION=""
    fi
elif [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
    ok "Apple Silicon detected — MPS acceleration available"
    CUDA_VERSION=""
else
    info "macOS x86_64 — CPU-only (no CUDA on macOS)"
    CUDA_VERSION=""
fi

# ── Create directory structure ────────────────────────────────────

step "Setup directories"

mkdir -p "$SPLATRIX_HOME/bin"
mkdir -p "$SPLATRIX_HOME/envs"

ok "Install directory: $SPLATRIX_HOME"

# ── micromamba ────────────────────────────────────────────────────

step "micromamba"

MAMBA_EXE="$SPLATRIX_HOME/bin/micromamba"
export MAMBA_ROOT_PREFIX="$SPLATRIX_HOME"

if [[ -f "$MAMBA_EXE" ]]; then
    ok "micromamba already installed"
else
    info "Downloading micromamba (~5 MB)..."
    $DL "https://micro.mamba.pm/api/micromamba/${PLATFORM}/latest" \
        | tar xj -C "$SPLATRIX_HOME/bin" --strip-components=1 bin/micromamba
    chmod +x "$MAMBA_EXE"
    ok "micromamba installed"
fi

eval "$("$MAMBA_EXE" shell hook -s bash)"

# ── Download Splatrix ────────────────────────────────────────────

step "Download Splatrix"

if [[ -d "$SPLATRIX_HOME/src/.git" ]]; then
    info "Updating existing installation..."
    cd "$SPLATRIX_HOME/src"
    command -v git >/dev/null 2>&1 && git pull --quiet 2>/dev/null || true
else
    info "Downloading Splatrix ${SPLATRIX_VERSION}..."
    rm -rf "$SPLATRIX_HOME/src"
    mkdir -p "$SPLATRIX_HOME/src"
    $DL "${SPLATRIX_REPO}/archive/refs/heads/${SPLATRIX_VERSION}.tar.gz" \
        | tar xz -C "$SPLATRIX_HOME/src" --strip-components=1
    ok "Downloaded source"
fi

cd "$SPLATRIX_HOME/src"

# ── Environment ──────────────────────────────────────────────────

step "Create environment"

ENV_PREFIX="$MAMBA_ROOT_PREFIX/envs/$ENV_NAME"

if [[ -d "$ENV_PREFIX/conda-meta" ]]; then
    info "Environment '${ENV_NAME}' exists, activating..."
else
    info "Creating environment '${ENV_NAME}' (Python ${PYTHON_VERSION})..."
    "$MAMBA_EXE" create -p "$ENV_PREFIX" python="${PYTHON_VERSION}" -y -c conda-forge -q > /dev/null 2>&1
    ok "Environment created"
fi

micromamba activate "$ENV_PREFIX"

# ── Dependencies ─────────────────────────────────────────────────

step "Install dependencies"

# PyTorch
if [[ -n "$CUDA_VERSION" ]]; then
    info "Installing PyTorch with CUDA ${CUDA_VERSION}... (may take a few minutes)"
    pip install torch torchvision \
        --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" \
        -q 2>/dev/null
    ok "PyTorch installed"

    # CUDA toolkit (nvcc) — needed by gsplat for JIT kernel compilation
    info "Installing CUDA toolkit (for gsplat JIT)..."
    "$MAMBA_EXE" install -p "$ENV_PREFIX" -c conda-forge cuda-nvcc "cuda-version=${CUDA_VERSION}.*" -y -q > /dev/null 2>&1 \
        && ok "CUDA toolkit installed" \
        || warn "CUDA toolkit install failed — gsplat may fall back to CPU"
else
    info "Installing PyTorch (CPU/MPS)... (may take a few minutes)"
    pip install torch torchvision -q 2>/dev/null
    ok "PyTorch installed"
fi

# COLMAP + FFmpeg
info "Installing COLMAP and FFmpeg..."
if [[ "$PLATFORM" == "osx-arm64" ]]; then
    # conda-forge COLMAP may not be available for osx-arm64
    "$MAMBA_EXE" install -n "$ENV_NAME" -c conda-forge ffmpeg -y -q > /dev/null 2>&1
    # Try COLMAP — fall back to brew suggestion
    if ! "$MAMBA_EXE" install -n "$ENV_NAME" -c conda-forge colmap -y -q > /dev/null 2>&1; then
        warn "COLMAP not available via conda for Apple Silicon."
        warn "Install manually: brew install colmap"
    fi
else
    "$MAMBA_EXE" install -n "$ENV_NAME" -c conda-forge colmap ffmpeg -y -q > /dev/null 2>&1
fi
ok "COLMAP + FFmpeg installed"

# OpenCV (needed for feature overlays)
info "Installing OpenCV..."
pip install opencv-python-headless -q 2>/dev/null
ok "OpenCV installed"

# Nerfstudio
info "Installing Nerfstudio... (may take a few minutes)"
pip install nerfstudio -q 2>/dev/null
ok "Nerfstudio installed"

# Patch nerfstudio colmap_utils to be version-aware (SiftExtraction vs FeatureExtraction)
COLMAP_UTILS="$(python -c 'import nerfstudio.process_data.colmap_utils as m; print(m.__file__)')"
if [ -f "$COLMAP_UTILS" ] && ! grep -q "_extract_gpu_flag" "$COLMAP_UTILS"; then
    python -c "
import pathlib
p = pathlib.Path('$COLMAP_UTILS')
t = p.read_text()

# Undo any previous blanket rename (FeatureExtraction->SiftExtraction) so we start clean
t = t.replace('FeatureExtraction.use_gpu', 'SiftExtraction.use_gpu')
t = t.replace('FeatureMatching.use_gpu', 'SiftMatching.use_gpu')

# Insert version-gated flag variables after 'colmap_version = get_colmap_version(colmap_cmd)'
old = '    colmap_version = get_colmap_version(colmap_cmd)\n'
new = '''    colmap_version = get_colmap_version(colmap_cmd)

    # COLMAP 3.11+ renamed SiftExtraction/SiftMatching -> FeatureExtraction/FeatureMatching
    from packaging.version import Version as _V
    if colmap_version >= _V(\"3.11\"):
        _extract_gpu_flag = f\"--FeatureExtraction.use_gpu {int(gpu)}\"
        _match_gpu_flag = f\"--FeatureMatching.use_gpu {int(gpu)}\"
    else:
        _extract_gpu_flag = f\"--SiftExtraction.use_gpu {int(gpu)}\"
        _match_gpu_flag = f\"--SiftMatching.use_gpu {int(gpu)}\"
'''

if old in t:
    t = t.replace(old, new, 1)
    t = t.replace('f\"--SiftExtraction.use_gpu {int(gpu)}\"', '_extract_gpu_flag')
    t = t.replace('f\"--SiftMatching.use_gpu {int(gpu)}\"', '_match_gpu_flag')
    p.write_text(t)
    print('Patched successfully')
else:
    print('Patch point not found — may already be patched')
"
    ok "Patched nerfstudio for COLMAP version compatibility"
fi

# Splatrix
info "Installing Splatrix..."
pip install -e . -q 2>/dev/null
ok "Splatrix installed"

# ── Launcher script ──────────────────────────────────────────────

step "Create launcher"

cat > "$SPLATRIX_HOME/bin/splatrix" << 'LAUNCHER_OUTER'
#!/usr/bin/env bash
# Splatrix launcher — self-contained, no PATH modification needed

SPLATRIX_HOME="${SPLATRIX_HOME:-$HOME/.splatrix}"
MAMBA_EXE="$SPLATRIX_HOME/bin/micromamba"
export MAMBA_ROOT_PREFIX="$SPLATRIX_HOME"

[[ -f "$MAMBA_EXE" ]] || { echo "Error: micromamba not found. Run the installer."; exit 1; }

eval "$("$MAMBA_EXE" shell hook -s bash)"
micromamba activate splatrix 2>/dev/null || { echo "Error: 'splatrix' env not found. Run the installer."; exit 1; }

[[ -n "${CONDA_PREFIX:-}" ]] && export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"

# Force PyQt6's bundled Qt6 paths (avoid conda Qt5 conflicts)
QT6_DIR="$(python -c 'import PyQt6.QtCore; import os; print(os.path.dirname(PyQt6.QtCore.__file__))' 2>/dev/null)"
if [[ -d "${QT6_DIR}/Qt6" ]]; then
    export QT_PLUGIN_PATH="${QT6_DIR}/Qt6/plugins"
    export QML_IMPORT_PATH="${QT6_DIR}/Qt6/qml"
    export QML2_IMPORT_PATH="${QT6_DIR}/Qt6/qml"
    export QT_QPA_PLATFORM_PLUGIN_PATH="${QT6_DIR}/Qt6/plugins/platforms"
fi

exec python -m splatrix.main_qml "$@"
LAUNCHER_OUTER

chmod +x "$SPLATRIX_HOME/bin/splatrix"
ok "Launcher: $SPLATRIX_HOME/bin/splatrix"

# ── Desktop entry (Linux only) ───────────────────────────────────

if [[ "$OS" == "Linux" ]]; then
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"

    cat > "$DESKTOP_DIR/splatrix.desktop" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Splatrix
Comment=Video to 3D Gaussian Splats
Exec=$SPLATRIX_HOME/bin/splatrix
Icon=$SPLATRIX_HOME/src/splatrix/qml/icons/app-icon.svg
Terminal=false
Categories=Graphics;3DGraphics;Science;
DESKTOP_EOF

    ok "Desktop entry installed (app menu)"
fi

# ── Add to PATH ──────────────────────────────────────────────────

SPLATRIX_BIN="$SPLATRIX_HOME/bin"
PATH_LINE="export PATH=\"\$HOME/.splatrix/bin:\$PATH\""
FISH_PATH_LINE="fish_add_path -g \$HOME/.splatrix/bin"
ADDED_PATH=false

add_to_file() {
    local file="$1" line="$2"
    if [ -f "$file" ] && grep -qF ".splatrix/bin" "$file" 2>/dev/null; then
        return 0  # already present
    fi
    echo "" >> "$file"
    echo "# Splatrix" >> "$file"
    echo "$line" >> "$file"
    return 0
}

# Detect current shell and patch its profile
CURRENT_SHELL="$(basename "${SHELL:-/bin/bash}")"
case "$CURRENT_SHELL" in
    zsh)
        add_to_file "$HOME/.zshrc" "$PATH_LINE"
        ADDED_PATH=true
        ;;
    fish)
        mkdir -p "$HOME/.config/fish"
        add_to_file "$HOME/.config/fish/config.fish" "$FISH_PATH_LINE"
        ADDED_PATH=true
        ;;
    *)
        add_to_file "$HOME/.bashrc" "$PATH_LINE"
        ADDED_PATH=true
        ;;
esac

# Also add to .profile for login shells (non-fish)
if [[ "$CURRENT_SHELL" != "fish" ]] && [ -f "$HOME/.profile" ]; then
    add_to_file "$HOME/.profile" "$PATH_LINE"
fi

if $ADDED_PATH; then
    ok "Added ~/.splatrix/bin to PATH (restart shell or source your profile)"
fi

# ── Verify ───────────────────────────────────────────────────────

step "Verification"

python -c "import torch; print(f'  PyTorch {torch.__version__}  CUDA: {torch.cuda.is_available()}')" 2>/dev/null || warn "PyTorch verification failed"
python -c "import nerfstudio; print('  Nerfstudio OK')" 2>/dev/null || warn "Nerfstudio verification failed"
python -c "from PyQt6.QtWidgets import QApplication; print('  PyQt6 OK')" 2>/dev/null || warn "PyQt6 verification failed"

# ── Done ─────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║   ${BOLD}Splatrix installed successfully!${NC}${GREEN}                     ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║   Run:  ${CYAN}splatrix${NC}${GREEN}                                       ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
INSTALL_SIZE=$(du -sh "$SPLATRIX_HOME" 2>/dev/null | cut -f1)
echo "Total install size: ${BOLD}${INSTALL_SIZE}${NC}"
echo ""
echo "Restart your shell (or run 'source ~/${CURRENT_SHELL}rc') then type: splatrix"
echo ""
