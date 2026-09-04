#!/usr/bin/env bash
# Thirty seconds. Is it working right now?
# Prints PASS, or the one specific thing that is wrong and what to do about it.
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source scripts/runtime.sh

COMPOSE="$(detect_compose 2>/dev/null || true)"
PORT="$(configured_port)"; PORT="${PORT:-${VEILLEE_PORT:-8000}}"
BASE="http://127.0.0.1:$PORT"

PROBE_ID="q120"
PROBE_BEFORE=""
PROBE_TAKEN=0

# The probe overwrites a real answer and puts it back. Restoring must happen on
# EVERY exit path, including the failure paths, or the one morning this check
# fails is the morning it eats the last answer in the book.
restore_probe() {
  [ "$PROBE_TAKEN" = "1" ] || return 0
  curl -sf -X POST "$BASE/api/answer/$PROBE_ID" -H 'Content-Type: application/json' \
    -d "$(python3 -c "import json,sys;print(json.dumps({'body': sys.argv[1]}))" "$PROBE_BEFORE")" \
    >/dev/null 2>&1 \
    && printf "  restored %s to how it was\n" "$PROBE_ID" \
    || printf "  NOTE: could not restore %s; the original is in data/.revisions/%s/\n" \
         "$PROBE_ID" "$PROBE_ID"
}
trap restore_probe EXIT

problem() {
  printf "\n\033[1;31mFAIL\033[0m  %s\n" "$1"
  printf "      %s\n" "$2"
  exit 1
}

printf "Checking Veillee on %s\n" "$BASE"

# 1. Is it up? If not, try to start it once before giving up.
if ! curl -sf --max-time 4 "$BASE/healthz" >/dev/null 2>&1; then
  printf "  not running — starting it\n"
  [ -z "$COMPOSE" ] && problem "No container runtime found." \
    "Install podman or docker, then run: ./scripts/up.sh"
  # Compose reads these from .env, never from the shell.
  write_env_file .env "$(detect_run_as)" "$PORT"
  $COMPOSE up -d >/dev/null 2>&1
  for _ in $(seq 1 60); do
    curl -sf --max-time 2 "$BASE/healthz" >/dev/null 2>&1 && break
    sleep 1
  done
fi

HEALTH=$(curl -sf --max-time 5 "$BASE/healthz" 2>/dev/null) || problem \
  "The site is not answering on $BASE." \
  "Look at the logs with: ${COMPOSE:-podman compose} logs --tail 50 app"

STATUS=$(echo "$HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null)
printf "  health: %s\n" "$STATUS"
if [ "$STATUS" != "ok" ]; then
  echo "$HEALTH" | python3 -c "
import sys, json
for item in json.load(sys.stdin).get('problems', []):
    print('    -', item)
"
  printf "  (degraded, but writing still works if the checks below pass)\n"
fi

# 2. Can he actually write? This is the only question that matters.
PROBE_BEFORE=$(curl -sf "$BASE/api/answer/$PROBE_ID" 2>/dev/null \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['body'])" 2>/dev/null) || PROBE_BEFORE=""
STAMP="morning check $(date -u +%H:%M:%S)"
PROBE_TAKEN=1

curl -sf -X POST "$BASE/api/answer/$PROBE_ID" -H 'Content-Type: application/json' \
  -d "$(python3 -c "import json,sys;print(json.dumps({'body': sys.argv[1]}))" "$STAMP")" \
  >/dev/null 2>&1 || problem \
  "Writing an answer failed." \
  "The site is up but cannot save. Check disk space and permissions on data/."

READBACK=$(curl -sf "$BASE/api/answer/$PROBE_ID" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['body'])" 2>/dev/null)
[ "$READBACK" = "$STAMP" ] || problem \
  "An answer was saved but read back wrong." \
  "Expected '$STAMP', got '$READBACK'. Run: make reindex"
printf "  write and read back: ok\n"

# 3. Is the archive readable by a human with a file browser?
COUNT=$(find data/answers -name '*.md' 2>/dev/null | wc -l)
DISK=$(echo "$HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin)['disk'].get('free_human','?'))" 2>/dev/null)
BACKUP=$(echo "$HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin).get('last_backup','?'))" 2>/dev/null)
printf "  answers on disk: %s\n" "$COUNT"
printf "  disk free: %s\n" "$DISK"
printf "  last backup: %s\n" "$BACKUP"

printf "\n\033[1;32mPASS\033[0m  Veillee is working. Open %s\n" "$BASE"
printf "      Publish to your tailnet with: tailscale serve --bg %s\n" "$PORT"
printf "      Never use tailscale funnel.\n"
