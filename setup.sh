#!/usr/bin/env bash
# One-time setup for the ZoneClaw artifact.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " ZoneClaw Artifact Setup"
echo "========================================"
echo ""

# --- Dependency checks ---
echo "[1/6] Checking dependencies..."

check_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: '$1' not found."
    exit 1
  fi
}

check_cmd docker
check_cmd git
check_cmd python3
check_cmd uv
check_cmd flock
check_cmd realpath
check_cmd timeout

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose plugin not available."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not reachable. Start Docker and check user permissions."
  exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d. -f1-2 | tr -d '.')
if [ "$PYTHON_VERSION" -lt 312 ]; then
  echo "ERROR: Python 3.12+ required. Found: $(python3 --version)"
  exit 1
fi

echo "  docker:  $(docker --version | cut -d' ' -f3 | tr -d ',')"
echo "  compose: $(docker compose version --short)"
echo "  python3: $(python3 --version | cut -d' ' -f2)"
echo "  uv:      $(uv --version)"
echo ""

# --- Pinned upstream systems ---
echo "[2/6] Preparing pinned dependencies..."

python3 scripts/bootstrap_dependencies.py

echo "  Harbor:   $(git -C harbor log --oneline -1)"
echo "  OpenClaw: $(git -C openclaw log --oneline -1)"
echo "  Workspace-Bench: $(git -C workspace-bench log --oneline -1)"
echo ""

# --- Python dependencies ---
echo "[3/6] Installing Python dependencies..."

uv sync --all-extras --quiet --directory harbor
if [ ! -x ".venv/bin/python" ]; then
  uv venv --quiet .venv
fi
uv pip install --quiet --python .venv/bin/python -r requirements.txt
echo "  Harbor and artifact dependencies installed."
echo ""

# --- Build Docker image ---
echo "[4/6] Building OpenClaw Docker image..."
echo "  This takes 10-15 minutes on first run (subsequent runs use cache)."
echo ""

cd openclaw
# --load is required for Docker Desktop with containerd image store.
# Without it, the built image is not visible to docker-compose.
docker build --load -t openclaw:local .
docker tag openclaw:local openclaw:eval
echo ""
echo "  Image built: $(docker images openclaw:local --format '{{.Repository}}:{{.Tag}} ({{.Size}})')"
cd "$SCRIPT_DIR"
echo ""

# --- Build Workspace-Bench image ---
echo "[5/6] Building Workspace-Bench Docker image..."
docker build -t workspace-bench:local workspace-bench/evaluation/docker
echo "  Image built: workspace-bench:local"
echo ""

# --- Pre-pull external images ---
echo "[6/6] Pulling external Docker images..."

# Collect unique external images from all task docker-compose files.
EXTERNAL_IMAGES=$(grep -rh 'image:' tasks/*/environment/docker-compose.yaml \
                                    tasks/*/*/environment/docker-compose.yaml 2>/dev/null \
                  | grep -v 'openclaw' \
                  | sed 's/.*image:\s*//' | tr -d '"' | tr -d "'" \
                  | sort -u || true)

PULL_FAILED=0
for img in $EXTERNAL_IMAGES; do
  echo -n "  Pulling $img ... "
  if docker pull "$img" >/dev/null 2>&1; then
    echo "ok"
  else
    echo "FAILED"
    PULL_FAILED=1
  fi
done

if [ "$PULL_FAILED" -eq 1 ]; then
  echo ""
  echo "WARNING: Some image pulls failed. Common causes:"
  echo "  - No internet connection"
  echo "  - Broken Docker credential helper (WSL2: check ~/.docker/config.json"
  echo "    for 'credsStore: desktop.exe' — remove it if Docker Desktop is not running)"
  echo "  - Docker Hub rate limit"
  echo ""
  echo "You can retry pulls manually: docker pull <image>"
fi
echo ""

# --- Environment file ---
if [ ! -f ".env" ]; then
  cp .env.example .env
  GATEWAY_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  sed -i "s/^OPENCLAW_GATEWAY_TOKEN=.*/OPENCLAW_GATEWAY_TOKEN=$GATEWAY_TOKEN/" .env
  chmod 600 .env
  echo "NOTE: .env file created from .env.example."
  echo "      A private local gateway token was generated automatically."
  echo "      Edit .env and set the API key for the provider you will use."
  echo ""
else
  chmod 600 .env
fi

echo "========================================"
echo " Setup complete!"
echo " Edit .env before starting an experiment."
echo "========================================"
