#!/usr/bin/env bash
set -euo pipefail

# ── Splatrix Uninstaller ────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

SPLATRIX_HOME="${SPLATRIX_HOME:-$HOME/.splatrix}"

echo -e "${BOLD}Splatrix Uninstaller${NC}"
echo ""
echo "This will remove:"
echo "  - Everything in: ${SPLATRIX_HOME}"
echo "  - Desktop entry: ~/.local/share/applications/splatrix.desktop"
echo ""
echo -e "${YELLOW}Your project files will NOT be removed.${NC}"
echo ""
read -rp "Continue? (y/N) " yn
[[ "$yn" =~ ^[Yy]$ ]] || exit 0

# Remove splatrix directory (contains micromamba, envs, source, launcher)
if [[ -d "$SPLATRIX_HOME" ]]; then
    echo -e "${CYAN}[•]${NC} Removing ${SPLATRIX_HOME}..."
    rm -rf "$SPLATRIX_HOME"
    echo -e "${GREEN}[✓]${NC} Application removed"
else
    echo -e "${YELLOW}[!]${NC} ${SPLATRIX_HOME} not found"
fi

# Remove desktop entry (Linux)
DESKTOP_FILE="$HOME/.local/share/applications/splatrix.desktop"
if [[ -f "$DESKTOP_FILE" ]]; then
    rm -f "$DESKTOP_FILE"
    echo -e "${GREEN}[✓]${NC} Desktop entry removed"
fi

echo ""
echo -e "${GREEN}Splatrix has been uninstalled.${NC}"
echo ""
