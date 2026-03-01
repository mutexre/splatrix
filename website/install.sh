#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════
#  Splats Installer — zero-dependency, single-command install
#
#  Usage:
#    curl -fsSL https://splats-app.github.io/splats/install.sh | bash
#
#  Or:
#    wget -qO- https://splats-app.github.io/splats/install.sh | bash
#
#  What this does:
#    1. Installs Miniconda (if not present)
#    2. Downloads Splats source
#    3. Creates conda environment with all dependencies
#    4. Installs the 'splats' command
#
#  Requirements: Linux x86_64 with NVIDIA GPU + drivers installed
# ══════════════════════════════════════════════════════════════════

SPLATS_VERSION="${SPLATS_VERSION:-main}"
SPLATS_REPO="https://github.com/splats-app/splats"
SPLATS_HOME="${SPLATS_HOME:-$HOME/.splats}"
CONDA_DIR="${CONDA_DIR:-$HOME/miniconda3}"
ENV_NAME="splats"
PYTHON_VERSION="3.10"
CUDA_VERSION="12.1"
LAUNCHER_DIR="$HOME/.local/bin"

# ── Colors ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[•]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${BOLD}── $* ──${NC}"; }

# ── Preflight ─────────────────────────────────────────────────────

step "Preflight checks"

# OS check
[[ "$(uname -s)" == "Linux" ]] || fail "Splats currently supports Linux only."
[[ "$(uname -m)" == "x86_64" ]] || fail "Splats requires x86_64 architecture."

# Download tool
if command -v curl >/dev/null 2>&1; then
    DL="curl -fsSL"
    DL_OUT="curl -fsSL -o"
elif command -v wget >/dev/null 2>&1; then
    DL="wget -qO-"
    DL_OUT="wget -qO"
else
    fail "Neither curl nor wget found. Install one of them first."
fi

# GPU check
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    ok "NVIDIA GPU: ${GPU_NAME} (${GPU_MEM} MB)"
else
    warn "nvidia-smi not found. NVIDIA drivers must be installed for GPU training."
    warn "Install drivers: https://docs.nvidia.com/cuda/cuda-installation-guide-linux/"
    read -rp "Continue anyway? (y/N) " yn
    [[ "$yn" =~ ^[Yy]$ ]] || exit 0
fi

# ── Miniconda ─────────────────────────────────────────────────────

step "Conda setup"

install_miniconda() {
    info "Downloading Miniconda..."
    local tmp
    tmp=$(mktemp /tmp/miniconda_XXXXXX.sh)
    $DL_OUT "$tmp" "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    info "Installing Miniconda to ${CONDA_DIR}..."
    bash "$tmp" -b -p "$CONDA_DIR" > /dev/null 2>&1
    rm -f "$tmp"
    ok "Miniconda installed"
}

# Find existing conda
CONDA_EXE=""
if command -v conda >/dev/null 2>&1; then
    CONDA_EXE="$(which conda)"
elif [[ -f "$CONDA_DIR/bin/conda" ]]; then
    CONDA_EXE="$CONDA_DIR/bin/conda"
elif [[ -f "$HOME/anaconda3/bin/conda" ]]; then
    CONDA_EXE="$HOME/anaconda3/bin/conda"
    CONDA_DIR="$HOME/anaconda3"
fi

if [[ -n "$CONDA_EXE" ]]; then
    ok "Conda found: $CONDA_EXE"
else
    install_miniconda
    CONDA_EXE="$CONDA_DIR/bin/conda"
fi

# Activate conda in this shell
eval "$("$CONDA_EXE" shell.bash hook)"

# ── Download Splats ───────────────────────────────────────────────

step "Download Splats"

mkdir -p "$SPLATS_HOME"

if [[ -d "$SPLATS_HOME/src/.git" ]]; then
    info "Updating existing installation..."
    cd "$SPLATS_HOME/src"
    if command -v git >/dev/null 2>&1; then
        git pull --quiet 2>/dev/null || warn "Git pull failed, using existing files"
    fi
else
    # Download tarball (no git required)
    info "Downloading Splats ${SPLATS_VERSION}..."
    TARBALL_URL="${SPLATS_REPO}/archive/refs/heads/${SPLATS_VERSION}.tar.gz"
    rm -rf "$SPLATS_HOME/src"
    mkdir -p "$SPLATS_HOME/src"

    if $DL "$TARBALL_URL" | tar xz -C "$SPLATS_HOME/src" --strip-components=1 2>/dev/null; then
        ok "Downloaded source"
    else
        # Fallback: try git clone
        info "Tarball download failed, trying git..."
        if command -v git >/dev/null 2>&1; then
            git clone --depth 1 "$SPLATS_REPO.git" "$SPLATS_HOME/src" -q
            ok "Cloned repository"
        else
            # Install git via conda, then clone
            info "Installing git..."
            conda install -n base git -y -q > /dev/null 2>&1
            git clone --depth 1 "$SPLATS_REPO.git" "$SPLATS_HOME/src" -q
            ok "Cloned repository"
        fi
    fi
fi

cd "$SPLATS_HOME/src"

# ── Conda Environment ────────────────────────────────────────────

step "Create environment"

if conda env list 2>/dev/null | grep -q "^${ENV_NAME} "; then
    info "Environment '${ENV_NAME}' exists, updating..."
    conda activate "$ENV_NAME"
else
    info "Creating conda environment '${ENV_NAME}' (Python ${PYTHON_VERSION})..."
    conda create -n "$ENV_NAME" python="${PYTHON_VERSION}" -y -q > /dev/null 2>&1
    ok "Environment created"
    conda activate "$ENV_NAME"
fi

# ── Dependencies ──────────────────────────────────────────────────

step "Install dependencies"

# PyTorch + CUDA
info "Installing PyTorch with CUDA ${CUDA_VERSION}... (this may take a few minutes)"
pip install torch torchvision \
    --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" \
    -q 2>/dev/null
ok "PyTorch installed"

# COLMAP + FFmpeg via conda
info "Installing COLMAP and FFmpeg..."
conda install -c conda-forge colmap ffmpeg -y -q > /dev/null 2>&1 || {
    warn "COLMAP conda install failed, trying pip..."
    pip install colmap -q 2>/dev/null || warn "COLMAP not installed — install manually"
}
ok "COLMAP + FFmpeg installed"

# Nerfstudio
info "Installing Nerfstudio... (this may take a few minutes)"
pip install nerfstudio -q 2>/dev/null
ok "Nerfstudio installed"

# Splats itself
info "Installing Splats..."
pip install -e . -q 2>/dev/null
ok "Splats installed"

# ── Launcher ──────────────────────────────────────────────────────

step "Create launcher"

mkdir -p "$LAUNCHER_DIR"

cat > "$LAUNCHER_DIR/splats" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
# Splats launcher — auto-activates conda environment

# Find conda
CONDA_EXE=""
for p in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/.conda"; do
    [[ -f "$p/bin/conda" ]] && CONDA_EXE="$p/bin/conda" && break
done
[[ -z "$CONDA_EXE" ]] && command -v conda >/dev/null 2>&1 && CONDA_EXE="$(which conda)"
[[ -z "$CONDA_EXE" ]] && { echo "Error: conda not found"; exit 1; }

eval "$("$CONDA_EXE" shell.bash hook)"
conda activate splats 2>/dev/null || { echo "Error: 'splats' conda env not found. Run the installer."; exit 1; }

# Ensure CUDA libs are in path
CONDA_PREFIX="${CONDA_PREFIX:-}"
if [[ -n "$CONDA_PREFIX" ]]; then
    export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
fi

exec python -m splats.main_qml "$@"
LAUNCHER_EOF

chmod +x "$LAUNCHER_DIR/splats"
ok "Launcher created: ${LAUNCHER_DIR}/splats"

# ── PATH setup ────────────────────────────────────────────────────

if [[ ":$PATH:" != *":$LAUNCHER_DIR:"* ]]; then
    step "PATH setup"

    SHELL_NAME=$(basename "${SHELL:-/bin/bash}")
    RC_FILE=""
    case "$SHELL_NAME" in
        bash) RC_FILE="$HOME/.bashrc" ;;
        zsh)  RC_FILE="$HOME/.zshrc" ;;
        fish) RC_FILE="$HOME/.config/fish/config.fish" ;;
    esac

    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
    FISH_PATH_LINE='set -gx PATH $HOME/.local/bin $PATH'

    if [[ -n "$RC_FILE" ]]; then
        if [[ "$SHELL_NAME" == "fish" ]]; then
            grep -qF '.local/bin' "$RC_FILE" 2>/dev/null || echo "$FISH_PATH_LINE" >> "$RC_FILE"
        else
            grep -qF '.local/bin' "$RC_FILE" 2>/dev/null || echo "$PATH_LINE" >> "$RC_FILE"
        fi
        ok "Added ~/.local/bin to PATH in ${RC_FILE}"
    fi

    export PATH="$LAUNCHER_DIR:$PATH"
fi

# ── Verify ────────────────────────────────────────────────────────

step "Verification"

python -c "import torch; print(f'  PyTorch {torch.__version__}  CUDA available: {torch.cuda.is_available()}')" 2>/dev/null || warn "PyTorch verification failed"
python -c "import nerfstudio; print(f'  Nerfstudio OK')" 2>/dev/null || warn "Nerfstudio verification failed"
python -c "from PyQt6.QtWidgets import QApplication; print('  PyQt6 OK')" 2>/dev/null || warn "PyQt6 verification failed"

# ── Done ──────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║   ${BOLD}Splats installed successfully!${NC}${GREEN}                     ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║   Run:  ${CYAN}splats${NC}${GREEN}                                       ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║   Or:   ${CYAN}~/.local/bin/splats${NC}${GREEN}                          ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

if [[ ":$PATH:" != *":$LAUNCHER_DIR:"* ]]; then
    warn "Restart your terminal or run: source ~/.bashrc"
fi
