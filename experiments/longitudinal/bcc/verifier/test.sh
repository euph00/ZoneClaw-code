#!/usr/bin/env bash
set -euo pipefail

python3 /tests/verify.py /tests/expected.json

# Preserve the probe workspace and transcripts for post-hoc audits. Probe
# outputs are never fed back into the parent longitudinal trajectory.
STATE_DIR="/tmp/openclaw-state"
WORKSPACE="$STATE_DIR/workspace"
ARTIFACT_WS="/logs/artifacts/workspace"
ARTIFACT_TX="/logs/artifacts/transcripts"

mkdir -p "$ARTIFACT_WS"
cp -a "$WORKSPACE"/. "$ARTIFACT_WS/" 2>/dev/null || true

if [ -d "$STATE_DIR/agents" ]; then
  cd "$STATE_DIR"
  find agents -name "*.jsonl" -type f 2>/dev/null | while IFS= read -r rel; do
    mkdir -p "$ARTIFACT_TX/$(dirname "$rel")"
    cp "$rel" "$ARTIFACT_TX/$rel"
  done
fi

