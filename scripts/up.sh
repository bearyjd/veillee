#!/usr/bin/env bash
# Bring the stack up. This is the whole story: no keys, no accounts, no wizard.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source scripts/runtime.sh

COMPOSE="$(detect_compose)" || { echo "No docker or podman found." >&2; exit 1; }
RUN_AS="$(detect_run_as)"
write_env_file .env "$RUN_AS"

mkdir -p data
echo "Runtime:        $COMPOSE"
echo "Containers run as uid: $RUN_AS  (written to .env, where Compose will read it)"
$COMPOSE up -d --build "$@"

PORT="$(grep -E '^VEILLEE_PORT=' .env 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-8000}"
echo
echo "Veillee is on http://127.0.0.1:$PORT"
echo "Publish it to your tailnet with:  tailscale serve --bg $PORT"
echo "NEVER use tailscale funnel."
