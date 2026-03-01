#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════
#  Splatrix Installer — zero-dependency, single-command install
#
#  Usage:
#    curl -fsSL https://splatrix.github.io/splatrix/install.sh | bash
#
#  What this does:
#    1. Installs micromamba (~5 MB static binary)
#    2. Downloads Splatrix source
#    3. Creates environment with all dependencies
#    4. Installs the 'splatrix' command
#
#  Requirements: Linux x86_64 with NVIDIA GPU + drivers installed
# ══════════════════════════════════════════════════════════════════

SPLATRIX_VERSION="${SPLATRIX_VERSION:-main}"
SPLATRIX_REPO="https://github.com/splatrix/splatrix"
SPLATRIX_HOME="${SPLATRIX_HOME:-$HOME/.splatrix}"
MAMBA_ROOT="${MAMBA_ROOT_PREFIX:-$HOME/.local/share/micromamba}"
ENV_NAME="splatrix"
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

[[ "$(uname -s)" == "Linux" ]] || fail "Splatrix currently supports Linux only."
[[ "$(uname -m)" == "x86_64" ]] || fail "Splatrix requires x86_64 architecture."

# Download tool
if command -v curl >/dev/null 2>&1; then
    DL="curl -fsSL"
elif command -v wget >/dev/null 2>&1; then
    DL="wget -qO-"
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

# ── micromamba ────────────────────────────────────────────────────

step "micromamba"

MAMBA_EXE="$LAUNCHER_DIR/micromamba"
mkdir -p "$LAUNCHER_DIR"

if [[ -f "$MAMBA_EXE" ]]; then
    ok "micromamba already installed"
else
    info "Downloading micromamba (~5 MB)..."
    $DL "https://micro.mamba.pm/api/micromamba/linux-64/latest" | tar xj -C "$LAUNCHER_DIR" --strip-components=1 bin/micromamba
    chmod +x "$MAMBA_EXE"
    ok "micromamba installed"
fi

export MAMBA_ROOT_PREFIX="$MAMBA_ROOT"
eval "$("$MAMBA_EXE" shell hook -s bash)"

# ── Download Splatrix ───────────────────────────────────────────────

step "Download Splatrix"

mkdir -p "$SPLATRIX_HOME"

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

# ── Environment ───────────────────────────────────────────────────

step "Create environment"

if "$MAMBA_EXE" env list 2>/dev/null | grep -q "${ENV_NAME}"; then
    info "Environment '${ENV_NAME}' exists, activating..."
else
    info "Creating environment '${ENV_NAME}' (Python ${PYTHON_VERSION})..."
    "$MAMBA_EXE" create -n "$ENV_NAME" python="${PYTHON_VERSION}" -y -c conda-forge -q > /dev/null 2>&1
    ok "Environment created"
fi

micromamba activate "$ENV_NAME"

# ── Dependencies ──────────────────────────────────────────────────

step "Install dependencies"

info "Installing PyTorch with CUDA ${CUDA_VERSION}... (this may take a few minutes)"
pip install torch torchvision \
    --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" \
    -q 2>/dev/null
ok "PyTorch installed"

info "Installing COLMAP and FFmpeg..."
"$MAMBA_EXE" install -n "$ENV_NAME" -c conda-forge colmap ffmpeg -y -q > /dev/null 2>&1
ok "COLMAP + FFmpeg installed"

info "Installing Nerfstudio... (this may take a few minutes)"
pip install nerfstudio -q 2>/dev/null
ok "Nerfstudio installed"

info "Installing Splatrix..."
pip install -e . -q 2>/dev/null
ok "Splatrix installed"

# ── Launcher ──────────────────────────────────────────────────────

step "Create launcher"

cat > "$LAUNCHER_DIR/splatrix" << LAUNCHER_EOF
#!/usr/bin/env bash
# Splatrix launcher — auto-activates environment via micromamba

export MAMBA_ROOT_PREFIX="${MAMBA_ROOT}"
MAMBA_EXE="${MAMBA_EXE}"

[[ -f "\$MAMBA_EXE" ]] || { echo "Error: micromamba not found at \$MAMBA_EXE"; exit 1; }

eval "\$("\$MAMBA_EXE" shell hook -s bash)"
micromamba activate splatrix 2>/dev/null || { echo "Error: 'splatrix' env not found. Run the installer."; exit 1; }

[[ -n "\${CONDA_PREFIX:-}" ]] && export LD_LIBRARY_PATH="\${CONDA_PREFIX}/lib:\${LD_LIBRARY_PATH:-}"

exec python -m splatrix.main_qml "\$@"
LAUNCHER_EOF

chmod +x "$LAUNCHER_DIR/splatrix"
ok "Launcher created: ${LAUNCHER_DIR}/splatrix"

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

    if [[ -n "$RC_FILE" ]]; then
        if [[ "$SHELL_NAME" == "fish" ]]; then
            grep -qF '.local/bin' "$RC_FILE" 2>/dev/null || echo 'set -gx PATH $HOME/.local/bin $PATH' >> "$RC_FILE"
        else
            grep -qF '.local/bin' "$RC_FILE" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$RC_FILE"
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
echo -e "${GREEN}║   ${BOLD}Splatrix installed successfully!${NC}${GREEN}                     ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║   Run:  ${CYAN}splatrix${NC}${GREEN}                                       ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

if [[ ":$PATH:" != *":$LAUNCHER_DIR:"* ]]; then
    warn "Restart your terminal or run: source ~/.bashrc"
fi
