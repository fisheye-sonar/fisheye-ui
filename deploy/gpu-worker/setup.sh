#!/usr/bin/env bash
set -euo pipefail

# Provisions a fresh GPU worker instance to run FishEye UI directly via
# Poetry as a systemd service. Run this once, on the instance,
# after first boot. See README.md for AMI/security-group prerequisites.

REPO_URL="https://github.com/fisheye-sonar/fisheye-ui.git"
APP_DIR="/opt/fisheye-ui"

PYTHON_VERSION="3.10.14"

sudo apt-get update
# Build deps pyenv needs to compile Python from source - this AMI's Ubuntu
# release is new enough that neither the default repos nor the deadsnakes
# PPA have a prebuilt python3.10 package for it yet.
sudo apt-get install -y git curl build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev libncursesw5-dev xz-utils \
  tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

curl -fsSL https://pyenv.run | bash

# Make pyenv available in *this* script's shell right now - pyenv's installer
# says to restart your shell, but that's only needed for future interactive
# sessions; a script can just source the same init directly.
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
cat >> "$HOME/.bashrc" <<'EOF'
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
EOF

echo "Building Python $PYTHON_VERSION from source - this takes several minutes."
pyenv install "$PYTHON_VERSION"
pyenv global "$PYTHON_VERSION"

curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"

sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"
git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

poetry install

# fisheye_ui/static/ (what app.py serves at "/") is gitignored - it's the
# frontend's build output, generated from frontend/ via `npm run build`.
# git clone doesn't bring it over, so it has to be built here.
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

(cd frontend && npm install && npm run build)

echo
echo "Checking CUDA availability..."
poetry run python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
echo
echo "If that printed False, the default PyPI torch wheel didn't pick up"
echo "the GPU - reinstall with an explicit CUDA index, e.g.:"
echo "  poetry run pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu121"
echo

sudo cp deploy/gpu-worker/fisheye-ui.service /etc/systemd/system/fisheye-ui.service
sudo systemctl daemon-reload
sudo systemctl enable --now fisheye-ui

echo "Done."
echo "Check status: sudo systemctl status fisheye-ui"
echo "Check logs:   sudo journalctl -u fisheye-ui -f"
echo "Check health: curl localhost:8000/health"