#!/usr/bin/env bash
# Pull the published image and restart, but only when there is something new
# and only when he is not in the middle of talking.
#
# CI publishes on every push to main; this closes the gap between publishing
# and serving, which otherwise depends on somebody remembering. Run from a
# systemd timer - see docs/RUNBOOK.md.
#
# It is deliberately conservative. Doing nothing is always an acceptable
# outcome; interrupting a recording is not.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA_DIR="${VEILLEE_DATA_DIR:-data}"
COMPOSE="${VEILLEE_COMPOSE:-docker compose -f compose.registry.yaml -f compose.tailscale.yaml}"
IMAGE="${VEILLEE_IMAGE:-ghcr.io/bearyjd/veillee:latest}"
APP_CONTAINER="${VEILLEE_APP_CONTAINER:-veillee-app-1}"
# How recently a chunk must have landed for us to assume he is still talking.
QUIET_MINUTES="${VEILLEE_QUIET_MINUTES:-15}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# ---- 1. Never restart out from under a recording --------------------------
# Chunks land in .uploads/<id>/ while he is still speaking. A file touched in
# the last few minutes means a recording is open, and restarting the app would
# throw away whatever has not been assembled yet.
UPLOADS="$DATA_DIR/.uploads"
if [ -d "$UPLOADS" ] && find "$UPLOADS" -type f -mmin "-$QUIET_MINUTES" 2>/dev/null | read -r _; then
  log "a recording is in flight; leaving it alone"
  exit 0
fi

# ---- 2. Is there anything new? --------------------------------------------
RUNNING="$(docker inspect "$APP_CONTAINER" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || echo none)"

$COMPOSE pull >/dev/null 2>&1 || { log "pull failed; leaving the running version alone"; exit 0; }

PULLED="$(docker image inspect "$IMAGE" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || echo unknown)"

if [ "$RUNNING" = "$PULLED" ]; then
  log "already current at ${RUNNING:0:12}"
  exit 0
fi

# ---- 3. Swap, then confirm it came back -----------------------------------
log "updating ${RUNNING:0:12} -> ${PULLED:0:12}"
$COMPOSE up -d >/dev/null

for _ in $(seq 1 30); do
  STATE="$(docker inspect "$APP_CONTAINER" --format '{{.State.Health.Status}}' 2>/dev/null || echo starting)"
  [ "$STATE" = "healthy" ] && { log "healthy at ${PULLED:0:12}"; exit 0; }
  sleep 5
done

log "WARNING: did not report healthy within 150s; still on ${PULLED:0:12}"
exit 1
