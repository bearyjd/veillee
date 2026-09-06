#!/usr/bin/env bash
# Back up the archive and the index. Run from a systemd timer; see HANDOFF.md.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA_DIR="${VEILLEE_DATA_DIR:-data}"

# The compose deployment keeps the index inside data/; `make run` keeps it in the
# repository root. Look in both rather than silently backing up neither.
if [ -n "${VEILLEE_DB_PATH:-}" ]; then
  DB_PATH="$VEILLEE_DB_PATH"
elif [ -f "$DATA_DIR/veillee.db" ]; then
  DB_PATH="$DATA_DIR/veillee.db"
else
  DB_PATH="veillee.db"
fi
BACKUP_DIR="${VEILLEE_BACKUP_DIR:-backups}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# The archive first. It is the thing that matters; the index is rebuildable.
tar -czf "$BACKUP_DIR/veillee-data-$STAMP.tar.gz" -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")"
echo "archive:  $BACKUP_DIR/veillee-data-$STAMP.tar.gz"

# sqlite3 .backup takes a consistent copy of a live, WAL-mode database.
if [ -f "$DB_PATH" ]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/veillee-db-$STAMP.sqlite'"
  else
    python3 -c "
import sqlite3, sys
source = sqlite3.connect(sys.argv[1]); target = sqlite3.connect(sys.argv[2])
source.backup(target); target.close(); source.close()
" "$DB_PATH" "$BACKUP_DIR/veillee-db-$STAMP.sqlite"
  fi
  echo "index:    $BACKUP_DIR/veillee-db-$STAMP.sqlite"

  python3 -c "
import sqlite3, sys, datetime
c = sqlite3.connect(sys.argv[1])
c.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
c.execute(\"INSERT INTO meta (key, value) VALUES ('last_backup', ?) \"
          'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
          (datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),))
c.commit(); c.close()
" "$DB_PATH"
fi

# Keep the last N of each kind. A nightly full copy of a growing audio archive
# would otherwise fill the disk quietly, which is a poor way to protect
# something whose whole promise is that it is never lost.
KEEP="${VEILLEE_BACKUP_KEEP:-14}"
prune() {
  local pattern="$1" kept=0
  # Newest first; anything past the limit goes.
  while IFS= read -r old; do
    kept=$((kept + 1))
    if [ "$kept" -gt "$KEEP" ]; then
      rm -f "$old"
      echo "pruned:   $(basename "$old")"
    fi
  done < <(find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -printf '%T@ %p\n' 2>/dev/null \
           | sort -rn | cut -d' ' -f2-)
}
prune 'veillee-data-*.tar.gz'
prune 'veillee-db-*.sqlite'

REMAINING=$(find "$BACKUP_DIR" -maxdepth 1 -name 'veillee-data-*.tar.gz' | wc -l)
TOTAL=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
echo "keeping:  $REMAINING backup(s), $TOTAL in $BACKUP_DIR (limit $KEEP)"
echo "Backup complete. Nothing was pushed anywhere."
