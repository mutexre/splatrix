#!/usr/bin/env bash
set -euo pipefail

# ── Splatrix Uninstaller ────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

SPLATRIX_HOME="${SPLATRIX_HOME:-$HOME/.splatrix}"
MAMBA_ROOT="${MAMBA_ROOT_PREFIX:-$HOME/.local/share/micromamba}"
LAUNCHER="$HOME/.local/bin/splatrix"
MAMBA_BIN="$HOME/.local/bin/micromamba"

echo -e "${BOLD}Splatrix Uninstaller${NC}"
echo ""
echo "This will remove:"
echo "  - Environment: splatrix"
echo "  - Application files: ${SPLATRIX_HOME}"
echo "  - Launcher: ${LAUNCHER}"
echo ""
echo -e "${YELLOW}Your project files in ~/Documents/SplatrixProjects will NOT be removed.${NC}"
echo ""
read -rp "Continue? (y/N) " yn
[[ "$yn" =~ ^[Yy]$ ]] || exit 0

# Remove environment — try micromamba first, then conda
if [[ -f "$MAMBA_BIN" ]]; then
    export MAMBA_ROOT_PREFIX="$MAMBA_ROOT"
    echo -e "${CYAN}[•]${NC} Removing environment via micromamba..."
    "$MAMBA_BIN" env remove -n splatrix -y > /dev/null 2>&1 || true
    echo -e "${GREEN}[✓]${NC} Environment removed"
elif command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook 2>/dev/null)"
    if conda env list 2>/dev/null | grep -q "^splatrix "; then
        echo -e "${CYAN}[•]${NC} Removing conda environment..."
        conda deactivate 2>/dev/null || true
        conda env remove -n splatrix -y > /dev/null 2>&1
        echo -e "${GREEN}[✓]${NC} Environment removed"
    fi
fi

# Remove app files
if [[ -d "$SPLATRIX_HOME" ]]; then
    echo -e "${CYAN}[•]${NC} Removing ${SPLATRIX_HOME}..."
    rm -rf "$SPLATRIX_HOME"
    echo -e "${GREEN}[✓]${NC} Application files removed"
fi

# Remove launcher
[[ -f "$LAUNCHER" ]] && rm -f "$LAUNCHER" && echo -e "${GREEN}[✓]${NC} Launcher removed"

echo ""
echo -e "${GREEN}Splatrix has been uninstalled.${NC}"
echo ""

# Offer to remove micromamba if we installed it
if [[ -f "$MAMBA_BIN" ]]; then
    echo "micromamba binary is still at: $MAMBA_BIN"
    echo "micromamba data is at: $MAMBA_ROOT"
    read -rp "Remove micromamba too? (y/N) " yn2
    if [[ "$yn2" =~ ^[Yy]$ ]]; then
        rm -f "$MAMBA_BIN"
        rm -rf "$MAMBA_ROOT"
        echo -e "${GREEN}[✓]${NC} micromamba removed"
    fi
fi
