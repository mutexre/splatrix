#!/usr/bin/env bash
set -euo pipefail

# ── Splats Uninstaller ────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

SPLATS_HOME="${SPLATS_HOME:-$HOME/.splats}"
LAUNCHER="$HOME/.local/bin/splats"

echo -e "${BOLD}Splats Uninstaller${NC}"
echo ""
echo "This will remove:"
echo "  - Conda environment: splats"
echo "  - Application files: ${SPLATS_HOME}"
echo "  - Launcher: ${LAUNCHER}"
echo ""
echo -e "${YELLOW}Your project files in ~/Documents/SplatsProjects will NOT be removed.${NC}"
echo ""
read -rp "Continue? (y/N) " yn
[[ "$yn" =~ ^[Yy]$ ]] || exit 0

# Remove conda environment
if command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook 2>/dev/null)"
    if conda env list 2>/dev/null | grep -q "^splats "; then
        echo -e "${CYAN}[•]${NC} Removing conda environment..."
        conda deactivate 2>/dev/null || true
        conda env remove -n splats -y > /dev/null 2>&1
        echo -e "${GREEN}[✓]${NC} Conda environment removed"
    fi
fi

# Remove app files
if [[ -d "$SPLATS_HOME" ]]; then
    echo -e "${CYAN}[•]${NC} Removing ${SPLATS_HOME}..."
    rm -rf "$SPLATS_HOME"
    echo -e "${GREEN}[✓]${NC} Application files removed"
fi

# Remove launcher
if [[ -f "$LAUNCHER" ]]; then
    rm -f "$LAUNCHER"
    echo -e "${GREEN}[✓]${NC} Launcher removed"
fi

echo ""
echo -e "${GREEN}Splats has been uninstalled.${NC}"
echo ""
echo "Note: Miniconda was NOT removed. To remove it:"
echo "  rm -rf ~/miniconda3"
