#!/usr/bin/env bash
# Bring the stack up. This is the whole story: no keys, no accounts, no wizard.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source scripts/runtime.sh

COMPOSE="$(detect_compose)" || { echo "No docker or podman found." >&2; exit 1; }
RUN_AS="$(detect_run_as)"

# Keep a port that was chosen before, so the URL he bookmarked keeps working.
PORT="$(configured_port)"
if [ -z "$PORT" ]; then
  PORT="$(find_free_port "${VEILLEE_PORT:-8000}")"
elif ! port_is_free "$PORT"; then
  # Already ours and running is fine; genuinely taken by something else is not.
  if ! curl -sf --max-time 3 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    echo "Port $PORT is taken by something that is not Veillee; choosing another." >&2
    PORT="$(find_free_port 8001)"
  fi
fi

write_env_file .env "$RUN_AS" "$PORT"
mkdir -p data

echo "Runtime:               $COMPOSE"
echo "Containers run as uid: $RUN_AS"
echo "Port:                  $PORT   (both written to .env, where Compose reads them)"
$COMPOSE up -d --build "$@"

echo
echo "Veillee is on http://127.0.0.1:$PORT"
echo "Publish it to your tailnet with:  tailscale serve --bg $PORT"
echo "NEVER use tailscale funnel."
