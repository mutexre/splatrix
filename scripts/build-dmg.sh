#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
#  Build Splatrix.dmg for macOS (arm64)
#
#  Usage:
#    ./scripts/build-dmg.sh
#
#  Prerequisites:
#    - macOS with Apple Silicon (or Rosetta)
#    - Python 3.12 (via Homebrew or system)
#
#  Output:
#    dist/Splatrix.dmg
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_VENV="$PROJECT_DIR/.build-venv"
APP_NAME="Splatrix"
DMG_NAME="$APP_NAME.dmg"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[•]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
fail()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${BOLD}── $* ──${NC}"; }

cd "$PROJECT_DIR"

# ── Preflight ────────────────────────────────────────────────────────────────

step "Preflight"

ARCH="$(uname -m)"
[[ "$ARCH" == "arm64" ]] || fail "This script targets arm64. Current arch: $ARCH"

PYTHON="${PYTHON:-python3.12}"
$PYTHON --version >/dev/null 2>&1 || fail "Python not found. Set PYTHON= or install Python 3.12."
PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Python $PY_VERSION ($PYTHON)"

# ── Build virtualenv ─────────────────────────────────────────────────────────

step "Build virtualenv"

if [[ -d "$BUILD_VENV" ]]; then
    info "Reusing existing build venv"
else
    info "Creating build virtualenv..."
    $PYTHON -m venv "$BUILD_VENV"
fi

source "$BUILD_VENV/bin/activate"

info "Installing build dependencies..."
pip install --upgrade pip -q
pip install pyinstaller -q

# Install only UI dependencies (no WebEngine, no ML stack)
pip install \
    "PyQt6>=6.6.0" \
    "PyQt6-Qt6>=6.6.0" \
    "psutil>=5.9.0" \
    "PyYAML>=6.0" \
    "numpy>=2.0.0" \
    "pillow>=10.0.0" \
    "plyfile>=1.0.0" \
    "av>=12.0.0" \
    "setproctitle>=1.3.0" \
    "transitions>=0.9.0" \
    -q

# Install splatrix itself (editable so source is importable)
pip install -e . --no-deps -q

ok "Build venv ready"

# ── PyInstaller ──────────────────────────────────────────────────────────────

step "PyInstaller build"

rm -rf "$PROJECT_DIR/build" "$PROJECT_DIR/dist"

info "Running PyInstaller..."
pyinstaller splatrix.spec --noconfirm 2>&1 | tail -5

APP_PATH="$PROJECT_DIR/dist/$APP_NAME.app"
[[ -d "$APP_PATH" ]] || fail "PyInstaller did not produce $APP_PATH"

APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)
ok "Built $APP_NAME.app ($APP_SIZE)"

# ── Code signing (ad-hoc) ────────────────────────────────────────────────────

step "Code signing"

if [[ -n "${DEVELOPER_ID:-}" ]]; then
    info "Signing with Developer ID: $DEVELOPER_ID"
    codesign --deep --force --options runtime \
        --sign "$DEVELOPER_ID" \
        "$APP_PATH"
    ok "Signed with Developer ID"
else
    info "Ad-hoc signing (no Developer ID set)"
    codesign --deep --force --sign - "$APP_PATH"
    ok "Ad-hoc signed"
fi

# ── DMG ──────────────────────────────────────────────────────────────────────

step "Create DMG"

DMG_PATH="$PROJECT_DIR/dist/$DMG_NAME"
DMG_STAGING="$PROJECT_DIR/dist/dmg-staging"

rm -rf "$DMG_STAGING" "$DMG_PATH"
mkdir -p "$DMG_STAGING"

cp -R "$APP_PATH" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"

info "Creating DMG..."
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -format UDZO \
    "$DMG_PATH" \
    >/dev/null

rm -rf "$DMG_STAGING"

DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
ok "Created $DMG_NAME ($DMG_SIZE)"

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Build complete!                                     ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║  DMG: dist/$DMG_NAME                            ║${NC}"
echo -e "${GREEN}║  App: dist/$APP_NAME.app ($APP_SIZE)               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

if [[ -z "${DEVELOPER_ID:-}" ]]; then
    echo "Note: Using ad-hoc signing. For distribution, set DEVELOPER_ID:"
    echo "  DEVELOPER_ID='Developer ID Application: Your Name' ./scripts/build-dmg.sh"
    echo ""
fi
