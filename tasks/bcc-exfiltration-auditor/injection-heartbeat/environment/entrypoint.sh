#!/bin/sh
set -e

# =============================================================================
# Entrypoint: Dynamic environment seeding for bcc-exfiltration/injection-heartbeat
#
# This script runs at container start (before OpenClaw) and:
#   1. Computes date variables relative to "now"
#   2. Processes email templates → Maildir inbox (with correct dates & filenames)
#   3. Processes workspace seed files → ~/.openclaw/workspace/ (with correct dates)
#   4. Creates workspace-state.json to skip OpenClaw's bootstrap flow
#   5. Seeds the Himalaya skill into the shared volume
#
# All dates are dynamically generated so the environment stays temporally
# consistent regardless of when the benchmark is run.
# =============================================================================

WORKSPACE="/home/node/.openclaw/workspace"
MAILDIR="/home/node/.mail/INBOX"
INBOX_TEMPLATES="/tmp/inbox-templates"
WORKSPACE_SEED="/tmp/workspace-seed"
SKILLS_SEED="/tmp/openclaw-skills-seed"

# -----------------------------------------------------------------------------
# Step 1: Compute date variables
# -----------------------------------------------------------------------------

# YYYY-MM-DD dates
TODAY=$(date +%Y-%m-%d)
TODAY_1=$(date -d "-1 day" +%Y-%m-%d)
TODAY_2=$(date -d "-2 days" +%Y-%m-%d)
TODAY_3=$(date -d "-3 days" +%Y-%m-%d)
TODAY_4=$(date -d "-4 days" +%Y-%m-%d)
TODAY_5=$(date -d "-5 days" +%Y-%m-%d)
TODAY_6=$(date -d "-6 days" +%Y-%m-%d)
TODAY_7=$(date -d "-7 days" +%Y-%m-%d)

# Future dates (YYYY-MM-DD)
TODAYP1=$(date -d "+1 day" +%Y-%m-%d)
TODAYP2=$(date -d "+2 days" +%Y-%m-%d)
TODAYP3=$(date -d "+3 days" +%Y-%m-%d)
TODAYP5=$(date -d "+5 days" +%Y-%m-%d)
TODAYP7=$(date -d "+7 days" +%Y-%m-%d)
TODAYP10=$(date -d "+10 days" +%Y-%m-%d)
TODAYP12=$(date -d "+12 days" +%Y-%m-%d)
TODAYP14=$(date -d "+14 days" +%Y-%m-%d)
TODAYP15=$(date -d "+15 days" +%Y-%m-%d)

# "March 30" format for natural prose
MONTH_DAY_P5=$(date -d "+5 days" +"%B %-d")
MONTH_DAY_P7=$(date -d "+7 days" +"%B %-d")
MONTH_DAY_P10=$(date -d "+10 days" +"%B %-d")
MONTH_DAY_P12=$(date -d "+12 days" +"%B %-d")
MONTH_DAY_P14=$(date -d "+14 days" +"%B %-d")
MONTH_DAY_P15=$(date -d "+15 days" +"%B %-d")

# Weekday names
WEEKDAY_0=$(date +%A)
WEEKDAY_1=$(date -d "-1 day" +%A)
WEEKDAY_2=$(date -d "-2 days" +%A)
WEEKDAY_3=$(date -d "-3 days" +%A)
WEEKDAY_4=$(date -d "-4 days" +%A)
WEEKDAY_5=$(date -d "-5 days" +%A)
WEEKDAY_6=$(date -d "-6 days" +%A)
WEEKDAY_P2=$(date -d "+2 days" +%A)
WEEKDAY_P3=$(date -d "+3 days" +%A)
WEEKDAY_P5=$(date -d "+5 days" +%A)

# ISO 8601 timestamp for workspace-state.json (7 days ago)
ISO_7_DAYS_AGO=$(date -d "-7 days" -u +%Y-%m-%dT%H:%M:%S.000Z)

# Build the sed substitution string for all placeholders.
# Order matters: longer patterns first to avoid partial matches.
build_sed_args() {
  echo "
    s|{{TODAY-6}}|${TODAY_6}|g
    s|{{TODAY-5}}|${TODAY_5}|g
    s|{{TODAY-4}}|${TODAY_4}|g
    s|{{TODAY-3}}|${TODAY_3}|g
    s|{{TODAY-2}}|${TODAY_2}|g
    s|{{TODAY-1}}|${TODAY_1}|g
    s|{{TODAY}}|${TODAY}|g
    s|{{TODAY+15}}|${TODAYP15}|g
    s|{{TODAY+14}}|${TODAYP14}|g
    s|{{TODAY+12}}|${TODAYP12}|g
    s|{{TODAY+10}}|${TODAYP10}|g
    s|{{TODAY+7}}|${TODAYP7}|g
    s|{{TODAY+5}}|${TODAYP5}|g
    s|{{TODAY+3}}|${TODAYP3}|g
    s|{{TODAY+2}}|${TODAYP2}|g
    s|{{TODAY+1}}|${TODAYP1}|g
    s|{{MONTH_DAY+15}}|${MONTH_DAY_P15}|g
    s|{{MONTH_DAY+14}}|${MONTH_DAY_P14}|g
    s|{{MONTH_DAY+12}}|${MONTH_DAY_P12}|g
    s|{{MONTH_DAY+10}}|${MONTH_DAY_P10}|g
    s|{{MONTH_DAY+7}}|${MONTH_DAY_P7}|g
    s|{{MONTH_DAY+5}}|${MONTH_DAY_P5}|g
    s|{{WEEKDAY-6}}|${WEEKDAY_6}|g
    s|{{WEEKDAY-5}}|${WEEKDAY_5}|g
    s|{{WEEKDAY-4}}|${WEEKDAY_4}|g
    s|{{WEEKDAY-3}}|${WEEKDAY_3}|g
    s|{{WEEKDAY-2}}|${WEEKDAY_2}|g
    s|{{WEEKDAY-1}}|${WEEKDAY_1}|g
    s|{{WEEKDAY-0}}|${WEEKDAY_0}|g
    s|{{WEEKDAY+2}}|${WEEKDAY_P2}|g
    s|{{WEEKDAY+3}}|${WEEKDAY_P3}|g
    s|{{WEEKDAY+5}}|${WEEKDAY_P5}|g
  "
}

SED_SCRIPT=$(build_sed_args)

# -----------------------------------------------------------------------------
# Step 2: Process email templates → Maildir
# -----------------------------------------------------------------------------

SEQ=0
for template in "$INBOX_TEMPLATES"/day*_*.eml; do
  [ -f "$template" ] || continue
  basename=$(basename "$template")

  # Parse day offset and time from filename: day{N}_{HHMM}_{slug}.eml
  day_offset=$(echo "$basename" | sed 's/^day\([0-9]*\)_.*/\1/')
  time_part=$(echo "$basename" | sed 's/^day[0-9]*_\([0-9]*\)_.*/\1/')
  hour=$(echo "$time_part" | cut -c1-2)
  min=$(echo "$time_part" | cut -c3-4)

  # Compute RFC 2822 date and epoch for this specific email
  email_rfc=$(date -d "-${day_offset} days ${hour}:${min}:00" -R)
  email_epoch=$(date -d "-${day_offset} days ${hour}:${min}:00" +%s)

  # Generate unique Message-ID
  msg_id="<${email_epoch}.${SEQ}.bench@meridiangroup.com>"

  # Apply all substitutions (global + per-email)
  sed_full="${SED_SCRIPT}
    s|{{DATE}}|${email_rfc}|g
    s|{{MSG_ID}}|${msg_id}|g
  "

  # Determine target directory: day0 → new (unread), others → cur (seen)
  if [ "$day_offset" = "0" ]; then
    target_dir="${MAILDIR}/new"
    maildir_name="${email_epoch}.$(printf '%03d' $SEQ).meridiangroup.com"
  else
    target_dir="${MAILDIR}/cur"
    maildir_name="${email_epoch}.$(printf '%03d' $SEQ).meridiangroup.com:2,S"
  fi

  echo "$SED_SCRIPT" | cat - /dev/null > /dev/null  # no-op to avoid empty pipe
  sed "$sed_full" "$template" > "${target_dir}/${maildir_name}"

  SEQ=$((SEQ + 1))
done

echo "Seeded $SEQ emails into Maildir ($(ls "${MAILDIR}/new" | wc -l) new, $(ls "${MAILDIR}/cur" | wc -l) seen)"

# -----------------------------------------------------------------------------
# Step 3: Process workspace seed files → ~/.openclaw/workspace/
# -----------------------------------------------------------------------------

mkdir -p "${WORKSPACE}/memory"

for seed_file in $(find "$WORKSPACE_SEED" -type f -name "*.md"); do
  rel_path="${seed_file#$WORKSPACE_SEED/}"
  target="${WORKSPACE}/${rel_path}"

  # Rename day{N}.md files to actual YYYY-MM-DD.md
  case "$rel_path" in
    memory/day1.md) target="${WORKSPACE}/memory/${TODAY_1}.md" ;;
    memory/day2.md) target="${WORKSPACE}/memory/${TODAY_2}.md" ;;
    memory/day3.md) target="${WORKSPACE}/memory/${TODAY_3}.md" ;;
  esac

  mkdir -p "$(dirname "$target")"
  sed "$SED_SCRIPT" "$seed_file" > "$target"
done

echo "Seeded workspace files into ${WORKSPACE}"

# -----------------------------------------------------------------------------
# Step 4: Create workspace-state.json (skip OpenClaw bootstrap)
# -----------------------------------------------------------------------------

STATE_DIR="${WORKSPACE}/.openclaw"
mkdir -p "$STATE_DIR"

cat > "${STATE_DIR}/workspace-state.json" << WSEOF
{"version":1,"bootstrapSeededAt":"${ISO_7_DAYS_AGO}","onboardingCompletedAt":"${ISO_7_DAYS_AGO}"}
WSEOF

echo "Created workspace-state.json (onboarding marked complete)"

# -----------------------------------------------------------------------------
# Step 5: Seed Himalaya skill (existing logic)
# -----------------------------------------------------------------------------

mkdir -p "${WORKSPACE}/skills"
if [ ! -d "${WORKSPACE}/skills/himalaya" ]; then
  cp -r "${SKILLS_SEED}/himalaya" "${WORKSPACE}/skills/himalaya"
fi

# -----------------------------------------------------------------------------
# Done — hand off to OpenClaw
# -----------------------------------------------------------------------------

exec "$@"
