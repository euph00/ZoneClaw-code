#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${SYSTEM:?Set SYSTEM=no-defense or SYSTEM=zoneclaw}"
: "${SCHEDULE:?Set SCHEDULE=benign-only, repeated-attack, benign-before-attack, or delayed-activation}"

ARGS=(
  --config "$SCRIPT_DIR/experiments/longitudinal/bcc/study.json"
  --system "$SYSTEM"
  --schedule "$SCHEDULE"
  -N "${N:-3}"
  -P "${P:-1}"
)

if [ -n "${MODEL:-}" ]; then
  ARGS+=(--model "$MODEL")
fi
if [ -n "${OPENCLAW_THINKING:-}" ]; then
  ARGS+=(--thinking "$OPENCLAW_THINKING")
fi
if [ -n "${CHECKPOINTS:-}" ]; then
  read -r -a CHECKPOINT_VALUES <<< "$CHECKPOINTS"
  ARGS+=(--checkpoints "${CHECKPOINT_VALUES[@]}")
fi
if [ -n "${TIMELINE_END_DATE:-}" ]; then
  ARGS+=(--timeline-end-date "$TIMELINE_END_DATE")
fi
if [ -n "${OUTPUT:-}" ]; then
  ARGS+=(--output "$OUTPUT")
fi

exec python3 "$SCRIPT_DIR/scripts/longitudinal/bench.py" "${ARGS[@]}"
