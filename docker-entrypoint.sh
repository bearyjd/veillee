#!/bin/sh
# Work out which user to run as, so `docker compose up -d` is genuinely the
# whole story on any runtime.
#
# The problem this solves: rootless podman maps container root to your host
# user, so running as root is correct there. Rootful docker maps root to real
# root, so running as root would fill data/ with root-owned files you cannot
# open in a file browser - which defeats the entire point of storing his words
# as plain markdown.
#
# Rather than making you configure that, we detect it. /proc/self/uid_map tells
# us whether container uid 0 is real root or a user-namespace illusion.
set -e

DATA="${VEILLEE_DATA_DIR:-/data}"
mkdir -p "$DATA"

run_as_uid=""
run_as_gid=""

if [ "$(id -u)" = "0" ]; then
    if [ -n "${PUID:-}" ]; then
        # An explicit instruction always wins, on any runtime.
        run_as_uid="$PUID"
        run_as_gid="${PGID:-$PUID}"
    else
        # An identity mapping (container 0 -> host 0) means we are really root.
        host_uid_for_container_root="$(awk 'NR==1{print $2}' /proc/self/uid_map 2>/dev/null || echo 0)"

        if [ "$host_uid_for_container_root" = "0" ]; then
            # Rootful. Match whoever owns the bind mount so the archive stays
            # readable by a person.
            run_as_uid="$(stat -c %u "$DATA")"
            run_as_gid="$(stat -c %g "$DATA")"
        fi
        # Otherwise we are inside a user namespace: container root is already
        # your host user, so staying root is exactly right.
    fi

    if [ "$run_as_uid" = "0" ]; then
        echo "veillee: data/ is owned by root; writing as root." >&2
        echo "veillee: set PUID and PGID in .env to your own user if you want" >&2
        echo "veillee: to read the archive with an ordinary file browser." >&2
        run_as_uid=""
        run_as_gid=""
    fi
fi

if [ -n "$run_as_uid" ]; then
    # The directory has to be writable by the uid we are about to become.
    chown "$run_as_uid:$run_as_gid" "$DATA" 2>/dev/null || true
    echo "veillee: running as uid $run_as_uid (owner of $DATA)" >&2
    exec setpriv --reuid "$run_as_uid" --regid "$run_as_gid" --clear-groups "$@"
fi

exec "$@"
