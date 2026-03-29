#!/usr/bin/env bash
set -euo pipefail

# Dev helper: recreate a clean conda env and launch the app
# with the bootstrap dialog so you can test the first-run experience.
#
# Usage:
#   ./dev-bootstrap.sh

ENV_NAME="splatrix-dev-bootstrap"
PYTHON_VERSION="3.12"

echo "── Removing env '$ENV_NAME' if it exists..."
conda env remove -n "$ENV_NAME" -y 2>/dev/null || true

echo "── Creating fresh env with Python $PYTHON_VERSION..."
conda create -n "$ENV_NAME" "python=$PYTHON_VERSION" -y -q

echo "── Installing Splatrix (UI only, no ML deps)..."
conda run -n "$ENV_NAME" pip install -e . -q

echo "── Launching with bootstrap dialog..."
conda run -n "$ENV_NAME" python run.py --reset-bootstrap --force-bootstrap
