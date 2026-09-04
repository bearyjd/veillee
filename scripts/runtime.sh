#!/usr/bin/env bash
# Work out which container runtime is here and which uid the containers must
# run as so that files under data/ end up owned by the person running this.
#
# Rootless podman maps container uid 0 to your host uid, so the container must
# run as root. Rootful docker maps uid to uid, so it must run as you. Getting
# this wrong means an archive you cannot read with a file browser, which defeats
# the entire point of storing plain markdown.

set -euo pipefail

detect_compose() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v podman >/dev/null 2>&1; then
    echo "podman compose"
  else
    echo "" ; return 1
  fi
}

detect_run_as() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then
      echo "0"          # rootless docker behaves like rootless podman
    else
      echo "$(id -u):$(id -g)"
    fi
  else
    echo "0"            # rootless podman: container root == your host uid
  fi
}

# Compose reads variables from a .env file in the project directory. It does NOT
# reliably inherit them from the shell: podman's external Compose provider is
# re-executed with a sanitised environment, so `export VEILLEE_RUN_AS=...` alone
# is silently ignored and the container runs as the wrong uid. Writing the file
# is the portable Compose-spec way and works identically under docker.
write_env_file() {
  local target="$1" run_as="$2"
  local existing=""
  [ -f "$target" ] && existing="$(grep -v '^VEILLEE_RUN_AS=' "$target" || true)"
  {
    [ -n "$existing" ] && printf '%s\n' "$existing"
    printf 'VEILLEE_RUN_AS=%s\n' "$run_as"
  } > "$target.tmp"
  mv "$target.tmp" "$target"
}
