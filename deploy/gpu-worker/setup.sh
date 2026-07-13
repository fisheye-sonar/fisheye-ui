#!/usr/bin/env bash
set -euo pipefail

# Provisions a fresh GPU worker instance to run FishEye UI directly via
# Poetry (no Docker) as a systemd service. Run this once, on the instance,
# after first boot. See README.md for AMI/security-group prerequisites.

REPO_URL="https://github.com/fisheye-sonar/fisheye-ui.git"
APP_DIR="/opt/fisheye-ui"

sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv git

curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"

sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"
git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

poetry install

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