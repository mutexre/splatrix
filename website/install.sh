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
#    1. Installs micromamba (~5 MB) if no conda/mamba found
#    2. Downloads Splats source
#    3. Creates environment with all dependencies
#    4. Installs the 'splats' command
#
#  Requirements: Linux x86_64 with NVIDIA GPU + drivers installed
# ══════════════════════════════════════════════════════════════════

SPLATS_VERSION="${SPLATS_VERSION:-main}"
SPLATS_REPO="https://github.com/splats-app/splats"
SPLATS_HOME="${SPLATS_HOME:-$HOME/.splats}"
MAMBA_ROOT="${MAMBA_ROOT_PREFIX:-$HOME/.local/share/micromamba}"
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

# ── Package manager ───────────────────────────────────────────────
# Prefer: micromamba > mamba > conda (existing install)

step "Package manager"

MAMBA_EXE=""
USE_CONDA=false

# Check for existing micromamba
if command -v micromamba >/dev/null 2>&1; then
    MAMBA_EXE="$(command -v micromamba)"
    ok "micromamba found: $MAMBA_EXE"
elif [[ -f "$LAUNCHER_DIR/micromamba" ]]; then
    MAMBA_EXE="$LAUNCHER_DIR/micromamba"
    ok "micromamba found: $MAMBA_EXE"
# Check for existing mamba
elif command -v mamba >/dev/null 2>&1; then
    MAMBA_EXE="$(command -v mamba)"
    ok "mamba found: $MAMBA_EXE"
    USE_CONDA=true
# Check for existing conda (use it rather than installing micromamba)
elif command -v conda >/dev/null 2>&1; then
    MAMBA_EXE="$(command -v conda)"
    ok "conda found: $MAMBA_EXE (will use existing)"
    USE_CONDA=true
else
    # Install micromamba — single 5 MB static binary
    info "Installing micromamba (~5 MB)..."
    mkdir -p "$LAUNCHER_DIR"
    $DL "https://micro.mamba.pm/api/micromamba/linux-64/latest" | tar xj -C "$LAUNCHER_DIR" --strip-components=1 bin/micromamba
    chmod +x "$LAUNCHER_DIR/micromamba"
    MAMBA_EXE="$LAUNCHER_DIR/micromamba"
    ok "micromamba installed: $MAMBA_EXE"
fi

# Set up shell integration
export MAMBA_ROOT_PREFIX="$MAMBA_ROOT"

if $USE_CONDA; then
    # Activate conda/mamba in this shell
    CONDA_BASE=""
    if [[ "$MAMBA_EXE" == *conda* ]] || [[ "$MAMBA_EXE" == *mamba* ]]; then
        # Find the conda executable for shell hook
        CONDA_FOR_HOOK="$MAMBA_EXE"
        [[ "$MAMBA_EXE" == *mamba* ]] && command -v conda >/dev/null 2>&1 && CONDA_FOR_HOOK="$(command -v conda)"
        eval "$("$CONDA_FOR_HOOK" shell.bash hook 2>/dev/null)" || true
    fi
    PKG_CMD="$MAMBA_EXE"
    ACTIVATE_CMD="conda activate"
else
    eval "$("$MAMBA_EXE" shell hook -s bash 2>/dev/null)" || true
    PKG_CMD="$MAMBA_EXE"
    ACTIVATE_CMD="micromamba activate"
fi

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
    info "Downloading Splats ${SPLATS_VERSION}..."
    TARBALL_URL="${SPLATS_REPO}/archive/refs/heads/${SPLATS_VERSION}.tar.gz"
    rm -rf "$SPLATS_HOME/src"
    mkdir -p "$SPLATS_HOME/src"

    if $DL "$TARBALL_URL" | tar xz -C "$SPLATS_HOME/src" --strip-components=1 2>/dev/null; then
        ok "Downloaded source"
    else
        info "Tarball download failed, trying git..."
        if command -v git >/dev/null 2>&1; then
            git clone --depth 1 "$SPLATS_REPO.git" "$SPLATS_HOME/src" -q
        else
            # Install git via package manager
            info "Installing git..."
            $PKG_CMD install -n base git -y -q > /dev/null 2>&1 || true
            git clone --depth 1 "$SPLATS_REPO.git" "$SPLATS_HOME/src" -q
        fi
        ok "Cloned repository"
    fi
fi

cd "$SPLATS_HOME/src"

# ── Environment ───────────────────────────────────────────────────

step "Create environment"

ENV_EXISTS=false
if $USE_CONDA; then
    conda env list 2>/dev/null | grep -q "^${ENV_NAME} " && ENV_EXISTS=true
else
    "$MAMBA_EXE" env list 2>/dev/null | grep -q "${ENV_NAME}" && ENV_EXISTS=true
fi

if $ENV_EXISTS; then
    info "Environment '${ENV_NAME}' exists, activating..."
else
    info "Creating environment '${ENV_NAME}' (Python ${PYTHON_VERSION})..."
    $PKG_CMD create -n "$ENV_NAME" python="${PYTHON_VERSION}" -y -q ${USE_CONDA:+} > /dev/null 2>&1 \
        || $PKG_CMD create -n "$ENV_NAME" python="${PYTHON_VERSION}" -y -c conda-forge > /dev/null 2>&1
    ok "Environment created"
fi

$ACTIVATE_CMD "$ENV_NAME" 2>/dev/null || eval "$($MAMBA_EXE shell hook -s bash)" && $ACTIVATE_CMD "$ENV_NAME"

# ── Dependencies ──────────────────────────────────────────────────

step "Install dependencies"

# PyTorch + CUDA
info "Installing PyTorch with CUDA ${CUDA_VERSION}... (this may take a few minutes)"
pip install torch torchvision \
    --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" \
    -q 2>/dev/null
ok "PyTorch installed"

# COLMAP + FFmpeg via conda/mamba (much faster with micromamba)
info "Installing COLMAP and FFmpeg..."
$PKG_CMD install -n "$ENV_NAME" -c conda-forge colmap ffmpeg -y -q > /dev/null 2>&1 || {
    warn "COLMAP install failed via package manager"
    warn "Install COLMAP manually: https://colmap.github.io/install.html"
}
ok "COLMAP + FFmpeg installed"

# Nerfstudio
info "Installing Nerfstudio... (this may take a few minutes)"
pip install nerfstudio -q 2>/dev/null
ok "Nerfstudio installed"

# Splats
info "Installing Splats..."
pip install -e . -q 2>/dev/null
ok "Splats installed"

# ── Launcher ──────────────────────────────────────────────────────

step "Create launcher"

mkdir -p "$LAUNCHER_DIR"

# Determine activation method for the launcher
if $USE_CONDA; then
    # Launcher uses existing conda
    cat > "$LAUNCHER_DIR/splats" << 'LAUNCHER_CONDA_EOF'
#!/usr/bin/env bash
# Splats launcher — auto-activates environment

CONDA_EXE=""
for p in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" "$HOME/mambaforge"; do
    [[ -f "$p/bin/conda" ]] && CONDA_EXE="$p/bin/conda" && break
done
[[ -z "$CONDA_EXE" ]] && command -v conda >/dev/null 2>&1 && CONDA_EXE="$(which conda)"
[[ -z "$CONDA_EXE" ]] && { echo "Error: conda not found"; exit 1; }

eval "$("$CONDA_EXE" shell.bash hook)"
conda activate splats 2>/dev/null || { echo "Error: 'splats' env not found. Run the installer."; exit 1; }

[[ -n "${CONDA_PREFIX:-}" ]] && export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"

exec python -m splats.main_qml "$@"
LAUNCHER_CONDA_EOF
else
    # Launcher uses micromamba
    cat > "$LAUNCHER_DIR/splats" << LAUNCHER_MAMBA_EOF
#!/usr/bin/env bash
# Splats launcher — auto-activates environment via micromamba

export MAMBA_ROOT_PREFIX="${MAMBA_ROOT}"
MAMBA_EXE="${MAMBA_EXE}"

[[ -f "\$MAMBA_EXE" ]] || { echo "Error: micromamba not found at \$MAMBA_EXE"; exit 1; }

eval "\$("\$MAMBA_EXE" shell hook -s bash)"
micromamba activate splats 2>/dev/null || { echo "Error: 'splats' env not found. Run the installer."; exit 1; }

[[ -n "\${CONDA_PREFIX:-}" ]] && export LD_LIBRARY_PATH="\${CONDA_PREFIX}/lib:\${LD_LIBRARY_PATH:-}"

exec python -m splats.main_qml "\$@"
LAUNCHER_MAMBA_EOF
fi

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

python -c "import torch; print(f'  PyTorch {torch.__version__}  CUDA: {torch.cuda.is_available()}')" 2>/dev/null || warn "PyTorch verification failed"
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
