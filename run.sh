#!/usr/bin/env bash
# run.sh — run a single task or all phases of a scenario against OpenClaw
#
# Usage:
#   TASK=bcc-exfiltration/injection-userprompt bash run.sh
#   SCENARIO=bcc-exfiltration bash run.sh
#   bash run.sh                          # runs the sanity check by default
#
# Environment variables:
#   TASK       path under tasks/ to run (e.g. bcc-exfiltration/injection-userprompt)
#   SCENARIO   scenario directory under tasks/ — runs all phases in order
#   MODEL              override model (reads from task's openclaw.json by default)
#   OPENCLAW_THINKING  override reasoning effort for models that support it
#   OPENCLAW_PROVIDER_BASE_URL     optional provider baseUrl override
#   OPENCLAW_PROVIDER_API          optional provider API adapter override
#   OPENCLAW_PROVIDER_API_KEY_ENV  optional env var name for provider API key
#   OPENCLAW_PROVIDER_REASONING    optional model reasoning capability (true/false)
#   OPENCLAW_PROVIDER_CONTEXT_WINDOW optional model context-window size
#   OPENCLAW_PROVIDER_MAX_TOKENS   optional model maximum output tokens
#   OPENCLAW_OPENAI_API_KEY_FROM_ENV  copy this env var into OPENAI_API_KEY
#   HARBOR_AGENT_TIMEOUT_MULTIPLIER optional agent timeout multiplier
#   BENCH_TOKEN_PRICES_FILE        optional USD-per-million token price JSON

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

# Z.AI exposes an OpenAI-compatible API, but benchmark Compose files already
# forward OPENAI_API_KEY rather than ZAI_API_KEY. Reuse that container-only
# carrier while retaining a distinct zai provider in OpenClaw's model config.
if [[ "${MODEL:-}" == zai/* ]] && [ -n "${ZAI_API_KEY:-}" ]; then
  : "${OPENCLAW_OPENAI_API_KEY_FROM_ENV:=ZAI_API_KEY}"
  : "${OPENCLAW_PROVIDER_BASE_URL:=https://api.z.ai/api/paas/v4}"
  : "${OPENCLAW_PROVIDER_API:=openai-completions}"
  : "${OPENCLAW_PROVIDER_API_KEY_ENV:=OPENAI_API_KEY}"
  : "${OPENCLAW_PROVIDER_REASONING:=true}"
  : "${OPENCLAW_PROVIDER_CONTEXT_WINDOW:=204800}"
  : "${OPENCLAW_PROVIDER_MAX_TOKENS:=131072}"
  : "${HARBOR_AGENT_TIMEOUT_MULTIPLIER:=2}"
fi
# Alibaba Model Studio exposes an OpenAI-compatible endpoint.
# Compose files already forward OPENAI_API_KEY, so use it as a container-only
# carrier while keeping ALIBABA_KEY distinct in the host environment.
if [[ "${MODEL:-}" == alibaba/* ]] && [ -n "${ALIBABA_KEY:-}" ]; then
  : "${OPENCLAW_OPENAI_API_KEY_FROM_ENV:=ALIBABA_KEY}"
  : "${OPENCLAW_PROVIDER_BASE_URL:=https://ws-rfp5oblpw7gfblfz.cn-beijing.maas.aliyuncs.com/compatible-mode/v1}"
  : "${OPENCLAW_PROVIDER_API:=openai-completions}"
  : "${OPENCLAW_PROVIDER_API_KEY_ENV:=OPENAI_API_KEY}"
  if [[ "$MODEL" == alibaba/qwen3.8-* ]]; then
    : "${OPENCLAW_PROVIDER_REASONING:=true}"
    : "${OPENCLAW_PROVIDER_CONTEXT_WINDOW:=1000000}"
    : "${OPENCLAW_PROVIDER_MAX_TOKENS:=32768}"
    : "${OPENCLAW_THINKING:=medium}"
    export BENCH_RAW_API_CAPTURE=alibaba
  elif [[ "$MODEL" == alibaba/qwen3.7-* ]]; then
    : "${OPENCLAW_PROVIDER_REASONING:=true}"
    : "${OPENCLAW_PROVIDER_CONTEXT_WINDOW:=1000000}"
    : "${OPENCLAW_PROVIDER_MAX_TOKENS:=32768}"
    : "${OPENCLAW_THINKING:=medium}"
    export BENCH_RAW_API_CAPTURE=alibaba
  elif [[ "$MODEL" == alibaba/qwen3.5-plus* ]]; then
    : "${OPENCLAW_PROVIDER_REASONING:=true}"
    : "${OPENCLAW_PROVIDER_CONTEXT_WINDOW:=1000000}"
    : "${OPENCLAW_PROVIDER_MAX_TOKENS:=32768}"
    : "${OPENCLAW_THINKING:=medium}"
    export BENCH_RAW_API_CAPTURE=alibaba
  elif [[ "$MODEL" == alibaba/qwen3.5-* ]]; then
    : "${OPENCLAW_PROVIDER_REASONING:=true}"
    : "${OPENCLAW_PROVIDER_CONTEXT_WINDOW:=262144}"
    : "${OPENCLAW_PROVIDER_MAX_TOKENS:=32768}"
    : "${OPENCLAW_THINKING:=medium}"
    export BENCH_RAW_API_CAPTURE=alibaba
  elif [[ "$MODEL" == alibaba/qwen3-max-2025-09-23 ]]; then
    : "${OPENCLAW_PROVIDER_REASONING:=false}"
    : "${OPENCLAW_PROVIDER_CONTEXT_WINDOW:=262144}"
    : "${OPENCLAW_PROVIDER_MAX_TOKENS:=32768}"
    : "${OPENCLAW_THINKING:=off}"
    export BENCH_RAW_API_CAPTURE=alibaba
  else
    : "${OPENCLAW_PROVIDER_REASONING:=false}"
    : "${OPENCLAW_PROVIDER_CONTEXT_WINDOW:=262144}"
    : "${OPENCLAW_PROVIDER_MAX_TOKENS:=8192}"
    : "${OPENCLAW_THINKING:=off}"
  fi
  : "${HARBOR_AGENT_TIMEOUT_MULTIPLIER:=2}"
fi
if [ -n "${OPENCLAW_OPENAI_API_KEY_FROM_ENV:-}" ]; then
  export OPENAI_API_KEY="${!OPENCLAW_OPENAI_API_KEY_FROM_ENV:-}"
fi

# Model is read from each task's openclaw.json (source of truth).
# MODEL env var can override for quick experiments.

# Ensure openclaw:eval image is available
if ! docker image inspect openclaw:local >/dev/null 2>&1; then
  echo "ERROR: openclaw:local image not found. Run setup.sh first."
  exit 1
fi
BASE_IMAGE=openclaw:local
if [ "${BENCH_RAW_API_CAPTURE:-}" = alibaba ]; then
  # Instrument the image without changing the pinned OpenClaw source/dependencies.
  (
    flock 9
    docker build -q -f "$SCRIPT_DIR/agents/telemetry.Dockerfile" \
      -t openclaw:telemetry "$SCRIPT_DIR/agents" >/dev/null
  ) 9>/tmp/openclaw-telemetry-build.lock
  BASE_IMAGE=openclaw:telemetry
fi
docker tag "$BASE_IMAGE" openclaw:eval

# Resolve which tasks to run
TASKS_DIR="$SCRIPT_DIR/tasks"

if [ -n "${TASK_PATH:-}" ]; then
  # Absolute path to a task directory (used by e2e-run.sh for temp tasks)
  if [ ! -d "$TASK_PATH" ]; then
    echo "ERROR: task not found: $TASK_PATH"
    exit 1
  fi
  TASK_PATHS="$TASK_PATH"
elif [ -n "${SCENARIO:-}" ]; then
  # Run all phases in the scenario directory in alphabetical order
  SCENARIO_DIR="$TASKS_DIR/$SCENARIO"
  if [ ! -d "$SCENARIO_DIR" ]; then
    echo "ERROR: scenario not found: $SCENARIO_DIR"
    exit 1
  fi
  TASK_PATHS=$(find "$SCENARIO_DIR" -mindepth 1 -maxdepth 1 -type d | sort)
  if [ -z "$TASK_PATHS" ]; then
    echo "ERROR: no tasks found in scenario: $SCENARIO_DIR"
    exit 1
  fi
elif [ -n "${TASK:-}" ]; then
  TASK_PATH="$TASKS_DIR/$TASK"
  if [ ! -d "$TASK_PATH" ]; then
    echo "ERROR: task not found: $TASK_PATH"
    exit 1
  fi
  TASK_PATHS="$TASK_PATH"
else
  # Default: run the sanity check
  TASK_PATHS="$TASKS_DIR/_sanity/openclaw-hello"
fi

# Pin container cleanup on unexpected exit.
# Pin containers hold references to Docker images (both harness and external),
# preventing docker compose down --rmi all from removing them during concurrent
# trials. Without this, trial N's teardown can delete python:3.12-slim while
# trial N+1 is starting its containers.
PIN_CONTAINERS=()
# Per-trial openclaw.json override file (created when MODEL env var is set).
# Each parallel run.sh process gets its own file via $$ to avoid contention.
OPENCLAW_CONFIG_OVERRIDE="/tmp/openclaw-cfg-$$.json"
cleanup_pins() {
  for c in "${PIN_CONTAINERS[@]}"; do
    docker rm "$c" >/dev/null 2>&1 || true
  done
  rm -f "$OPENCLAW_CONFIG_OVERRIDE"
}
trap cleanup_pins EXIT

# Run each task
for TASK_PATH in $TASK_PATHS; do
  TASK_NAME="${TASK_PATH#$TASKS_DIR/}"

  # Read model from the task's openclaw.json (single source of truth).
  # MODEL env var overrides if set.
  TASK_OPENCLAW_JSON="$TASK_PATH/environment/openclaw.json"
  if [ -n "${MODEL:-}" ]; then
    TASK_MODEL="$MODEL"
  elif [ -f "$TASK_OPENCLAW_JSON" ]; then
    TASK_MODEL=$(python3 -c "
import json, sys
cfg = json.load(open('$TASK_OPENCLAW_JSON'))
m = cfg.get('agents',{}).get('defaults',{}).get('model','')
if isinstance(m, dict): m = m.get('primary','')
print(m or 'unknown (not set in openclaw.json)')
" 2>/dev/null || echo "unknown")
  else
    TASK_MODEL="unknown (no openclaw.json)"
  fi

  # Per-trial openclaw.json override.
  # The OpenClaw gateway reads its model from openclaw.json (mounted into the
  # gateway container). Harbor's -m flag is metadata only and does NOT change
  # which model the gateway actually uses. To honor MODEL=..., we write a
  # patched copy of the task's openclaw.json to a per-process temp path and
  # export OPENCLAW_CONFIG_FILE so the docker-compose volume mount picks it up
  # (compose files use ${OPENCLAW_CONFIG_FILE:-./openclaw.json}).
  unset OPENCLAW_CONFIG_FILE
  if { [ -n "${MODEL:-}" ] || [ -n "${OPENCLAW_THINKING:-}" ]; } && [ -f "$TASK_OPENCLAW_JSON" ]; then
    python3 -c "
import json
cfg = json.load(open('$TASK_OPENCLAW_JSON'))
defaults = cfg.setdefault('agents', {}).setdefault('defaults', {})
m = defaults.get('model', '')
model_override = '''${MODEL:-}'''
thinking_override = '''${OPENCLAW_THINKING:-}'''
provider_base_url = '''${OPENCLAW_PROVIDER_BASE_URL:-}'''
provider_api = '''${OPENCLAW_PROVIDER_API:-}'''
provider_key_env = '''${OPENCLAW_PROVIDER_API_KEY_ENV:-}'''
provider_reasoning = '''${OPENCLAW_PROVIDER_REASONING:-false}'''.strip().lower() in ('1', 'true', 'yes', 'on')
provider_context_window = int('''${OPENCLAW_PROVIDER_CONTEXT_WINDOW:-128000}''')
provider_max_tokens = int('''${OPENCLAW_PROVIDER_MAX_TOKENS:-8192}''')
active_model = model_override
if model_override:
    if isinstance(m, dict):
        m['primary'] = model_override
    else:
        defaults['model'] = model_override
elif isinstance(m, dict):
    active_model = m.get('primary', '')
else:
    active_model = m or ''
if active_model and (provider_base_url or provider_api or provider_key_env):
    if '/' not in active_model:
        raise SystemExit(f'MODEL must be provider/model when provider overrides are set: {active_model}')
    provider_id, model_id = active_model.split('/', 1)
    providers = cfg.setdefault('models', {}).setdefault('providers', {})
    provider_cfg = providers.setdefault(provider_id, {})
    if provider_base_url:
        provider_cfg['baseUrl'] = provider_base_url
    if provider_api:
        provider_cfg['api'] = provider_api
    if provider_key_env:
        cfg.setdefault('secrets', {}).setdefault('providers', {}).setdefault('default', {'source': 'env'})
        provider_cfg['apiKey'] = {'source': 'env', 'provider': 'default', 'id': provider_key_env}
    models = provider_cfg.setdefault('models', [])
    if not any(isinstance(item, dict) and item.get('id') == model_id for item in models):
        models.append({
            'id': model_id,
            'name': model_id,
            'reasoning': provider_reasoning,
            'input': ['text'],
            'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
            'contextWindow': provider_context_window,
            'maxTokens': provider_max_tokens,
        })
    if provider_id == 'alibaba' and model_id.startswith('qwen3.8-'):
        entry = next(item for item in models if item.get('id') == model_id)
        entry['compat'] = {
            'thinkingFormat': 'openai', 'supportsReasoningEffort': True,
            'supportsDeveloperRole': False, 'supportsStore': False,
            'supportsUsageInStreaming': True, 'supportsStrictMode': False,
            'maxTokensField': 'max_completion_tokens',
        }
        defaults.setdefault('models', {}).setdefault(active_model, {}).setdefault('params', {})['maxTokens'] = provider_max_tokens
    elif provider_id == 'alibaba' and model_id.startswith('qwen3.7-'):
        entry = next(item for item in models if item.get('id') == model_id)
        entry['compat'] = {
            'thinkingFormat': 'qwen', 'supportsReasoningEffort': False,
            'supportsDeveloperRole': False, 'supportsStore': False,
            'supportsUsageInStreaming': True, 'supportsStrictMode': False,
            'maxTokensField': 'max_tokens',
        }
        defaults.setdefault('models', {}).setdefault(active_model, {}).setdefault('params', {})['maxTokens'] = provider_max_tokens
    elif provider_id == 'alibaba' and model_id.startswith('qwen3.5-'):
        entry = next(item for item in models if item.get('id') == model_id)
        entry['compat'] = {
            'thinkingFormat': 'qwen', 'supportsReasoningEffort': False,
            'supportsDeveloperRole': False, 'supportsStore': False,
            'supportsUsageInStreaming': True, 'supportsStrictMode': False,
            'maxTokensField': 'max_tokens',
        }
        defaults.setdefault('models', {}).setdefault(active_model, {}).setdefault('params', {})['maxTokens'] = provider_max_tokens
    elif provider_id == 'alibaba' and model_id == 'qwen3-max-2025-09-23':
        entry = next(item for item in models if item.get('id') == model_id)
        entry['compat'] = {
            'thinkingFormat': 'qwen', 'supportsReasoningEffort': False,
            'supportsDeveloperRole': False, 'supportsStore': False,
            'supportsUsageInStreaming': True, 'supportsStrictMode': False,
            'maxTokensField': 'max_tokens',
        }
        defaults.setdefault('models', {}).setdefault(active_model, {}).setdefault('params', {})['maxTokens'] = provider_max_tokens
if thinking_override:
    defaults['thinkingDefault'] = thinking_override
    if active_model:
        params = defaults.setdefault('models', {}).setdefault(active_model, {}).setdefault('params', {})
        params['thinking'] = thinking_override
json.dump(cfg, open('$OPENCLAW_CONFIG_OVERRIDE', 'w'), indent=2)
"
    export OPENCLAW_CONFIG_FILE="$OPENCLAW_CONFIG_OVERRIDE"
  fi
  # Host-only metadata for measurement; never passed into agent prompts.
  export BENCH_OPENCLAW_CONFIG_FILE="${OPENCLAW_CONFIG_FILE:-$TASK_OPENCLAW_JSON}"

  # Determine agent adapter from task.toml (default: standard chat completions)
  TASK_TOML="$TASK_PATH/task.toml"
  TASK_ADAPTER=$(python3 -c "
try:
    import tomllib
except ImportError:
    import tomli as tomllib
with open('$TASK_TOML', 'rb') as f:
    cfg = tomllib.load(f)
print(cfg.get('agent', {}).get('adapter', 'default'))
" 2>/dev/null || echo "default")

  case "$TASK_ADAPTER" in
    heartbeat)
      AGENT_IMPORT="agents.openclaw_heartbeat_agent:OpenClawHeartbeatAgent"
      ;;
    *)
      AGENT_IMPORT="agents.openclaw_agent:OpenClawAgent"
      ;;
  esac

  # Pre-build harness image to prevent concurrent Docker build collisions.
  # When docker_image is set in task.toml, Harbor uses "prebuilt mode" and skips
  # its own docker compose build. We build here with flock for cross-process
  # serialization, ensuring only one build runs at a time per image name.
  HARNESS_IMAGE=$(python3 -c "
try:
    import tomllib
except ImportError:
    import tomli as tomllib
with open('$TASK_PATH/task.toml', 'rb') as f:
    cfg = tomllib.load(f)
print(cfg.get('environment', {}).get('docker_image', ''))
" 2>/dev/null || echo "")

  PIN_CONTAINERS=()
  if [ -n "$HARNESS_IMAGE" ]; then
    # Sanitise image name for use in lock path and container name.
    _img_safe="${HARNESS_IMAGE//[^a-zA-Z0-9_-]/-}"
    BUILD_LOCK="/tmp/harbor-build-${_img_safe}.lock"
    _pin="hb-pin-${_img_safe}-$BASHPID"
    # Build and create the pin container under the same flock so the image
    # is never unprotected between build completion and pin creation.
    # The created (non-running) container prevents docker compose down --rmi all
    # from removing the shared harness image while another trial is starting
    # its containers.
    (
      flock 9
      docker build -t "$HARNESS_IMAGE" "$TASK_PATH/environment/" >/dev/null 2>&1
      # Create pin container. If it already exists (name collision from a
      # concurrent trial), remove the old one first.
      docker rm "$_pin" >/dev/null 2>&1 || true
      docker create --name "$_pin" "$HARNESS_IMAGE" >/dev/null 2>&1
    ) 9>"$BUILD_LOCK"
    PIN_CONTAINERS+=("$_pin")
  fi

  # Pre-pull external images AND pin them with non-running containers.
  # Harbor's cleanup runs docker compose down --rmi all, which removes ALL
  # images including pulled ones (python:3.12-slim, mailhog). Under concurrency,
  # trial N's cleanup can delete images that trial N+1 needs. Pinning with a
  # container reference prevents removal even if another trial's teardown runs.
  TASK_COMPOSE="$TASK_PATH/environment/docker-compose.yaml"
  if [ -f "$TASK_COMPOSE" ]; then
    docker compose -f "$TASK_COMPOSE" pull --ignore-buildable 2>/dev/null || true

    # Extract external image names (services with `image:` but no `build:`) and
    # pin each one. Uses grep/sed to avoid a pyyaml dependency.
    _ext_images=$( (grep -A1 '^\s*image:' "$TASK_COMPOSE" 2>/dev/null || true) \
      | (grep '^\s*image:' || true) \
      | sed 's/.*image:\s*//' | tr -d '"' | tr -d "'" \
      | while read -r _img; do
          # Skip if this service also has a build: directive (it's a built image)
          # Simple heuristic: only pin images that look like registry pulls
          case "$_img" in
            *:*) echo "$_img" ;;  # e.g. python:3.12-slim, mailhog/mailhog:v1.0.1
          esac
        done | sort -u)

    for _ext_img in $_ext_images; do
      _ext_safe="${_ext_img//[^a-zA-Z0-9_-]/-}"
      _ext_pin="hb-pin-ext-${_ext_safe}-$BASHPID"
      docker create --name "$_ext_pin" "$_ext_img" >/dev/null 2>&1 || true
      PIN_CONTAINERS+=("$_ext_pin")
    done
  fi

  echo "Running task: $TASK_NAME"
  echo "Model:        $TASK_MODEL"
  echo "Adapter:      $TASK_ADAPTER"
  echo ""

  PYTHONPATH="$SCRIPT_DIR" uv run --directory "$SCRIPT_DIR/harbor" harbor run \
    -p "$TASK_PATH" \
    --agent-import-path "$AGENT_IMPORT" \
    -m "$TASK_MODEL" \
    ${HARBOR_AGENT_TIMEOUT_MULTIPLIER:+--agent-timeout-multiplier "$HARBOR_AGENT_TIMEOUT_MULTIPLIER"} \
    ${HARBOR_JOBS_DIR:+--jobs-dir "$HARBOR_JOBS_DIR"} \
    ${HARBOR_JOB_NAME:+--job-name "$HARBOR_JOB_NAME"}

  # Remove pin containers — allows Harbor's teardown to clean up images.
  for _pc in "${PIN_CONTAINERS[@]}"; do
    docker rm "$_pc" >/dev/null 2>&1 || true
  done
  PIN_CONTAINERS=()

  # Re-tag before next task (Harbor removes openclaw:eval on teardown)
  docker tag "$BASE_IMAGE" openclaw:eval 2>/dev/null || true

  echo ""
done
