#!/usr/bin/env bash
# bench.sh — Run N trials with P concurrency and aggregate results
#
# End-to-end: E2E=bcc-zoneclaw-userprompt N=15 P=3 bash bench.sh
# Single phase: TASK=bcc-exfiltration/injection-userprompt N=15 P=3 bash bench.sh
# Named end-to-end experiments are listed in experiments/e2e.tsv.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults
: "${N:=5}"
: "${P:=1}"

# Determine mode and slug
if [ -n "${E2E:-}" ]; then
  MODE="e2e"
  SLUG="e2e-${E2E}"
elif [ -n "${TASK:-}" ]; then
  MODE="task"
  SLUG="${TASK//\//-}"
else
  echo "ERROR: Set TASK=... or E2E=... environment variable"
  exit 1
fi

# Create run directory
RUN_TS=$(date +"%Y-%m-%d__%H-%M-%S")
RUN_ID="${RUN_TS}__${SLUG}"
RUN_DIR="$SCRIPT_DIR/runs/$RUN_ID"
mkdir -p "$RUN_DIR/logs"

# Create isolated jobs directory for this run.
# Each bench.sh invocation gets its own subdirectory under harbor/jobs/,
# preventing cross-contamination between concurrent runs.
ISOLATED_JOBS_DIR="$SCRIPT_DIR/harbor/jobs/$RUN_ID"
mkdir -p "$ISOLATED_JOBS_DIR"

# Write run config
python3 -c "
import json, sys
json.dump({
    'mode': '$MODE',
    'task': '${TASK:-}',
    'e2e': '${E2E:-}',
    'model': '${MODEL:-}',
    'openclaw_thinking': '${OPENCLAW_THINKING:-}',
    'n': $N,
    'p': $P,
    'slug': '$SLUG',
    'jobs_dir': '$ISOLATED_JOBS_DIR',
}, open('$RUN_DIR/config.json', 'w'), indent=2)
"

echo "================================================================"
echo "  Bench: $SLUG"
echo "  N=$N trials, P=$P concurrency"
echo "  Output: $RUN_DIR"
echo "  Jobs:   $ISOLATED_JOBS_DIR"
echo "================================================================"
echo ""

# Track trial outcomes
START_TIME=$(date +%s)
STARTED_AT_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Run a single trial and log output
run_trial() {
  local i=$1
  local padded=$(printf '%03d' "$i")
  local log="$RUN_DIR/logs/trial_${padded}.log"
  local job_name="trial_${padded}"

  echo "[trial $i/$N] starting..."

  local rc=0
  if [ "$MODE" = "e2e" ]; then
    HARBOR_JOBS_DIR="$ISOLATED_JOBS_DIR" HARBOR_JOB_PREFIX="$job_name" \
      E2E="${E2E:-}" MODEL="${MODEL:-}" OPENCLAW_THINKING="${OPENCLAW_THINKING:-}" \
      bash "$SCRIPT_DIR/e2e-run.sh" > "$log" 2>&1 || rc=$?
  else
    HARBOR_JOBS_DIR="$ISOLATED_JOBS_DIR" HARBOR_JOB_NAME="$job_name" \
      TASK="${TASK:-}" MODEL="${MODEL:-}" OPENCLAW_THINKING="${OPENCLAW_THINKING:-}" \
      bash "$SCRIPT_DIR/run.sh" > "$log" 2>&1 || rc=$?
  fi

  if [ "$rc" -ne 0 ]; then
    echo "[trial $i/$N] FAILED (exit $rc)"
  else
    echo "[trial $i/$N] done"
  fi
  return $rc
}

# Run N trials in batches of P.
# Trial 1 runs alone first to warm up Docker image builds. Concurrent trials
# that try to build the same image simultaneously fail with "already exists".
if [ "$N" -ge 1 ]; then
  run_trial 1
fi

for i in $(seq 2 "$N"); do
  run_trial "$i" &

  # Wait for batch to complete when we've launched P jobs
  # (offset by 1 since trial 1 already ran)
  if (( (i - 1) % P == 0 )); then
    wait
  fi
done
wait  # wait for any remaining trials in the last partial batch

END_TIME=$(date +%s)
FINISHED_AT_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ELAPSED=$(( END_TIME - START_TIME ))

python3 -c "
import json
json.dump({
    'started_at': '$STARTED_AT_UTC',
    'finished_at': '$FINISHED_AT_UTC',
    'elapsed_seconds': $ELAPSED,
}, open('$RUN_DIR/runtime.json', 'w'), indent=2)
"

echo ""
echo "All $N trials completed in ${ELAPSED}s"
echo ""

# Discover trial directories from the isolated jobs dir.
# Each job_dir contains exactly one trial subdirectory.
# Only symlink trials that have a result.json (completed successfully).
mkdir -p "$RUN_DIR/trials"
TRIAL_COUNT=0
for job_dir in "$ISOLATED_JOBS_DIR"/*/; do
  [ -d "$job_dir" ] || continue
  for trial_dir in "$job_dir"/*/; do
    [ -d "$trial_dir" ] || continue
    [ -f "$trial_dir/result.json" ] || continue
    trial_name=$(basename "$trial_dir")
    ln -sf "$(realpath "$trial_dir")" "$RUN_DIR/trials/$trial_name"
    TRIAL_COUNT=$((TRIAL_COUNT + 1))
  done
done

echo "Found $TRIAL_COUNT completed trial directories"
echo ""

# Run aggregation
python3 "$SCRIPT_DIR/aggregate.py" "$RUN_DIR"

# Display per-trial breakdown
echo ""
bash "$SCRIPT_DIR/show-bench.sh" "$RUN_DIR"
