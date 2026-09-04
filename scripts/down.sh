#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source scripts/runtime.sh
COMPOSE="$(detect_compose)" || { echo "No docker or podman found." >&2; exit 1; }
write_env_file .env "$(detect_run_as)" "$(configured_port)"
$COMPOSE down "$@"
