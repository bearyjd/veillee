#!/usr/bin/env bash
# Package everything needed to run Veillee on another machine.
#
# Produces one tarball: the code, the compose file, and the whole archive with
# its git history. Nothing else is needed on the far end but a container runtime.
set -euo pipefail
cd "$(dirname "$0")/.."

STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="${VEILLEE_RELOCATE_DIR:-.}/veillee-move-$STAMP.tar.gz"
DATA_DIR="${VEILLEE_DATA_DIR:-data}"

echo "Packaging Veillee for a move..."

# Quiesce first: a tarball of a live SQLite file is not worth having. The index
# is rebuildable anyway, so it is deliberately excluded.
if [ -d "$DATA_DIR" ]; then
  ANSWERS=$(find "$DATA_DIR/answers" -name '*.md' 2>/dev/null | wc -l)
  RECORDINGS=$(find "$DATA_DIR/audio" -name '*.json' 2>/dev/null | wc -l)
  echo "  archive: $ANSWERS answers, $RECORDINGS recordings"
else
  echo "  archive: none yet"
fi

tar -czf "$OUT" \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='node_modules' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.ruff_cache' \
  --exclude='test-results' \
  --exclude='backups' \
  --exclude='exports' \
  --exclude="$DATA_DIR/veillee.db" \
  --exclude="$DATA_DIR/veillee.db-wal" \
  --exclude="$DATA_DIR/veillee.db-shm" \
  --exclude="$DATA_DIR/.uploads" \
  Dockerfile compose.yaml docker-entrypoint.sh Makefile pyproject.toml uv.lock \
  README.md HANDOFF.md BUILD_LOG.md LICENSE VERSION \
  src questions scripts tests docs \
  $([ -d "$DATA_DIR" ] && echo "$DATA_DIR") \
  $([ -f .env ] && echo .env)

SIZE=$(du -h "$OUT" | cut -f1)
echo "  wrote:   $OUT  ($SIZE)"
cat <<INSTRUCTIONS

Copy it over and start it:

  scp $OUT newhost:/tmp/
  ssh newhost
    mkdir -p /srv/veillee && cd /srv/veillee
    tar -xzf /tmp/$(basename "$OUT")
    docker compose up -d          # builds the image; first run takes a few minutes
    docker compose exec app veillee reindex

Then publish it on the new machine, and never with funnel:

    tailscale serve --bg 8000

The index is not in the tarball on purpose - it is rebuilt from the archive by
the reindex above, which is also a free check that nothing was lost in transit.
INSTRUCTIONS
