#!/bin/sh
set -e

WORKSPACE="/home/node/.openclaw/workspace"
WORKSPACE_SEED="/tmp/workspace-seed"
WORKCHAT_HOME="${WORKCHAT_HOME:-/home/node/.openclaw/workchat}"

TODAY=$(date +%Y-%m-%d)
TODAY_1=$(date -d "-1 day" +%Y-%m-%d)
TODAY_2=$(date -d "-2 days" +%Y-%m-%d)
TODAYP3=$(date -d "+3 days" +%Y-%m-%d)
TODAYP7=$(date -d "+7 days" +%Y-%m-%d)
MONTH_DAY_P7=$(date -d "+7 days" +"%B %-d")
WEEKDAY_1=$(date -d "-1 day" +%A)
WEEKDAY_2=$(date -d "-2 days" +%A)
WEEKDAY_P3=$(date -d "+3 days" +%A)
ISO_7_DAYS_AGO=$(date -d "-7 days" -u +%Y-%m-%dT%H:%M:%S.000Z)

SED_SCRIPT="
  s|{{TODAY-2}}|${TODAY_2}|g
  s|{{TODAY-1}}|${TODAY_1}|g
  s|{{TODAY}}|${TODAY}|g
  s|{{TODAY+3}}|${TODAYP3}|g
  s|{{TODAY+7}}|${TODAYP7}|g
  s|{{MONTH_DAY+7}}|${MONTH_DAY_P7}|g
  s|{{WEEKDAY-2}}|${WEEKDAY_2}|g
  s|{{WEEKDAY-1}}|${WEEKDAY_1}|g
  s|{{WEEKDAY+3}}|${WEEKDAY_P3}|g
"

mkdir -p "${WORKSPACE}/memory"

for seed_file in $(find "$WORKSPACE_SEED" -type f -name "*.md"); do
  rel_path="${seed_file#$WORKSPACE_SEED/}"
  target="${WORKSPACE}/${rel_path}"
  case "$rel_path" in
    memory/day1.md) target="${WORKSPACE}/memory/${TODAY_1}.md" ;;
    memory/day2.md) target="${WORKSPACE}/memory/${TODAY_2}.md" ;;
  esac
  mkdir -p "$(dirname "$target")"
  sed "$SED_SCRIPT" "$seed_file" > "$target"
done

mkdir -p "$WORKCHAT_HOME"
sed "$SED_SCRIPT" /tmp/chat-seed.json > "$WORKCHAT_HOME/state.json"
: > "$WORKCHAT_HOME/outbox.jsonl"
chown -R node:node "$WORKCHAT_HOME"

STATE_DIR="${WORKSPACE}/.openclaw"
mkdir -p "$STATE_DIR"
cat > "${STATE_DIR}/workspace-state.json" << WSEOF
{"version":1,"bootstrapSeededAt":"${ISO_7_DAYS_AGO}","onboardingCompletedAt":"${ISO_7_DAYS_AGO}"}
WSEOF

echo "Seeded workspace files into ${WORKSPACE}"
echo "Seeded WorkChat state into ${WORKCHAT_HOME}"

exec "$@"
