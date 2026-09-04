#!/usr/bin/env bash
# Thirty seconds. Is it working right now?
# Prints PASS, or the one specific thing that is wrong and what to do about it.
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source scripts/runtime.sh

PORT="${VEILLEE_PORT:-8000}"
BASE="http://127.0.0.1:$PORT"
COMPOSE="$(detect_compose 2>/dev/null || true)"
export VEILLEE_RUN_AS="$(detect_run_as 2>/dev/null || echo 0)"

problem() {
  printf "\n\033[1;31mFAIL\033[0m  %s\n" "$1"
  printf "      %s\n" "$2"
  exit 1
}

printf "Checking Veillée on %s\n" "$BASE"

# 1. Is it up? If not, try to start it once before giving up.
if ! curl -sf --max-time 4 "$BASE/healthz" >/dev/null 2>&1; then
  printf "  not running — starting it\n"
  [ -z "$COMPOSE" ] && problem "No container runtime found." \
    "Install podman or docker, then run: ./scripts/up.sh"
  $COMPOSE up -d >/dev/null 2>&1
  for _ in $(seq 1 60); do
    curl -sf --max-time 2 "$BASE/healthz" >/dev/null 2>&1 && break
    sleep 1
  done
fi

HEALTH=$(curl -sf --max-time 5 "$BASE/healthz" 2>/dev/null) || problem \
  "The site is not answering on $BASE." \
  "Look at the logs with: $COMPOSE logs --tail 50 app"

STATUS=$(echo "$HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null)
printf "  health: %s\n" "$STATUS"

if [ "$STATUS" != "ok" ]; then
  echo "$HEALTH" | python3 -c "
import sys, json
for problem in json.load(sys.stdin).get('problems', []):
    print('    -', problem)
"
  # A degraded site he can still write on is not a failure worth waking up to.
  printf "  (degraded, but writing still works if the checks below pass)\n"
fi

# 2. Can he actually write? This is the only question that matters.
TEST_ID="q120"
STAMP="morning check $(date -u +%H:%M:%S)"
BEFORE=$(curl -sf "$BASE/api/answer/$TEST_ID" 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['body'])" 2>/dev/null || echo "")

curl -sf -X POST "$BASE/api/answer/$TEST_ID" -H 'Content-Type: application/json' \
  -d "{\"body\": \"$STAMP\"}" >/dev/null 2>&1 || problem \
  "Writing an answer failed." \
  "The site is up but cannot save. Check disk space and permissions on data/."

READBACK=$(curl -sf "$BASE/api/answer/$TEST_ID" | python3 -c "import sys,json;print(json.load(sys.stdin)['body'])" 2>/dev/null)
[ "$READBACK" = "$STAMP" ] || problem \
  "An answer was saved but read back wrong." \
  "Expected '$STAMP', got '$READBACK'. Run: make reindex"
printf "  write and read back: ok\n"

# Put back whatever was there, so this check never costs him anything.
curl -sf -X POST "$BASE/api/answer/$TEST_ID" -H 'Content-Type: application/json' \
  -d "$(python3 -c "import json,sys;print(json.dumps({'body': sys.argv[1]}))" "$BEFORE")" >/dev/null 2>&1
printf "  restored the question to how it was\n"

# 3. Is the archive readable by a human with a file browser?
COUNT=$(find data/answers -name '*.md' 2>/dev/null | wc -l)
printf "  answers on disk: %s\n" "$COUNT"
DISK=$(echo "$HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin)['disk'].get('free_human','?'))" 2>/dev/null)
printf "  disk free: %s\n" "$DISK"

printf "\n\033[1;32mPASS\033[0m  Veillée is working. Open %s\n" "$BASE"
printf "      Publish to your tailnet with: tailscale serve --bg %s\n" "$PORT"
printf "      Never use tailscale funnel.\n"
