#!/usr/bin/env bash
# Work out which container runtime is here and which uid the containers must
# run as so that files under data/ end up owned by the person running this.
#
# Rootless podman maps container uid 0 to your host uid, so the container must
# run as root. Rootful docker maps uid to uid, so it must run as you. Getting
# this wrong means an archive you cannot read with a file browser, which defeats
# the entire point of storing plain markdown.
#
# This file is *sourced*, so it deliberately sets no shell options. It used to
# `set -euo pipefail`, which silently imposed `-e` on every caller - including
# morning-check.sh, which sets `set -uo pipefail` on purpose so it can report
# failures itself rather than dying on the first non-zero return.

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
  local target="$1" run_as="$2" port="${3:-}"
  local existing=""
  [ -f "$target" ] && existing="$(grep -vE '^VEILLEE_RUN_AS=' "$target" || true)"
  [ -n "$port" ] && existing="$(printf '%s\n' "$existing" | grep -vE '^VEILLEE_PORT=' || true)"
  {
    [ -n "$existing" ] && printf '%s\n' "$existing"
    printf 'VEILLEE_RUN_AS=%s\n' "$run_as"
    [ -n "$port" ] && printf 'VEILLEE_PORT=%s\n' "$port"
  } | atomic_write "$target"
}

# Replace $1 with stdin, atomically, keeping its permissions. The env file holds
# passcodes and the signing key, so a new file is 600 and an existing file keeps
# whatever mode it had; the temp file is never world-readable, even briefly.
atomic_write() {
  local target="$1" tmp
  tmp="$(umask 077; mktemp "$target.XXXXXX")" || return 1
  cat > "$tmp"
  if [ -f "$target" ]; then
    chmod --reference="$target" "$tmp" 2>/dev/null || chmod 600 "$tmp"
  else
    chmod 600 "$tmp"
  fi
  mv "$tmp" "$target"
}

# The value of VEILLEE_* variable $1 in env file $2, as Compose would read it:
# the last assignment wins, an optional `export ` is ignored, and surrounding
# whitespace and one pair of quotes are removed. Empty if unset.
env_file_value() {
  local v
  v="$(grep -E "^(export[[:space:]]+)?$1=" "$2" | tail -1 | sed -E 's/^(export[[:space:]]+)?[A-Z_]+=//' || true)"
  v="$(printf '%s' "$v" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  case "$v" in
    \"*\") v="${v#\"}"; v="${v%\"}" ;;
    \'*\') v="${v#\'}"; v="${v%\'}" ;;
  esac
  printf '%s' "$v" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
}

# Make sure a deployment with a passcode has a usable VEILLEE_SECRET_KEY in the
# env file. The app refuses to start otherwise: the key must be at least 32
# characters, have at least 16 distinct ones, and differ from both passcodes.
# A missing key, or a key that is set but too weak, is REPLACED with a fresh
# random one, and every device is then asked for the passcode once. A good key
# is left alone. Does nothing when no passcode is set or the file does not
# exist. Always succeeds, for the same `set -e` reason as configured_port.
ensure_secret_key() {
  local target="${1:-.env}" key pass family distinct
  [ -f "$target" ] || return 0
  pass="$(env_file_value VEILLEE_PASSCODE "$target")"
  family="$(env_file_value VEILLEE_FAMILY_PASSCODE "$target")"
  [ -n "$pass$family" ] || return 0
  key="$(env_file_value VEILLEE_SECRET_KEY "$target")"
  distinct="$(printf '%s' "$key" | fold -w1 | sort -u | wc -l)"
  if [ "${#key}" -ge 32 ] && [ "$distinct" -ge 16 ] && [ "$key" != "$pass" ] && [ "$key" != "$family" ]; then
    return 0
  fi
  key="$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')"
  {
    grep -vE '^(export[[:space:]]+)?VEILLEE_SECRET_KEY=' "$target" || true
    printf 'VEILLEE_SECRET_KEY=%s\n' "$key"
  } | atomic_write "$target"
  echo "Replaced VEILLEE_SECRET_KEY in $target (it was missing or too weak, including a short custom key); every device will be asked for the passcode once." >&2
  return 0
}

# The port already chosen for this deployment, or empty if none has been.
# Always succeeds: callers run under `set -e`, where a non-zero return from a
# command substitution would abort the whole script.
configured_port() {
  if [ -f .env ]; then
    grep -E '^VEILLEE_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2
  fi
  return 0
}

port_is_free() {
  ! ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN
}

# Pick a port that is actually free. 8000 is the obvious default but it is a
# popular one, and a bind failure at 7am reads as "the whole thing is broken".
find_free_port() {
  local preferred="${1:-8000}" candidate
  if port_is_free "$preferred"; then echo "$preferred"; return 0; fi
  for candidate in 8001 8002 8010 8080 8111 8222 8888; do
    if port_is_free "$candidate"; then echo "$candidate"; return 0; fi
  done
  echo "$preferred"
}
