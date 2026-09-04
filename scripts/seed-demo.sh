#!/usr/bin/env bash
# Put one demo answer and one demo recording under data/demo/.
#
# This is a worked example of the archive format, kept deliberately *outside*
# data/answers/ so it never mixes with anything he wrote and never appears in
# his progress count.
set -euo pipefail
cd "$(dirname "$0")/.."

DEMO_DIR="${VEILLEE_DATA_DIR:-data}/demo"
mkdir -p "$DEMO_DIR/audio"

cat > "$DEMO_DIR/README.md" <<'INNER'
# Demo

An example of what this archive looks like, so you can see the format without
opening the application.

- `012-example-answer.md` — an answer exactly as the app writes one. YAML
  frontmatter, then plain markdown.
- `audio/` — a recording in the three forms every recording is kept in: the
  untouched original, an archival FLAC, and a small Opus for playback, plus the
  sidecar JSON that describes them and checksums all three.

Nothing here is his. Delete this directory whenever you like; nothing refers to it.
INNER

cat > "$DEMO_DIR/012-example-answer.md" <<'INNER'
---
question_id: q012
question_text: What did your mother's kitchen smell like on a Sunday?
chapter: childhood-and-home
chapter_order: 2
created: '2026-09-04T09:00:00Z'
updated: '2026-09-04T09:14:00Z'
word_count: 62
status: answered
custom: false
---

Bread, mostly. She baked on the Saturday night so the house still had it in the
walls on Sunday morning, and you would come down to the range still warm.

There was turf under all of it. You never noticed the turf until you went
somewhere that did not have it, and then you noticed nothing else.
INNER

# A real recording, run through the real pipeline, so the demo is not a fiction.
if command -v ffmpeg >/dev/null 2>&1 && [ -f tests/fixtures/sample.m4a ]; then
  STAMP="20260904-090000-q012"
  cp tests/fixtures/sample.m4a "$DEMO_DIR/audio/$STAMP.orig.m4a"
  ffmpeg -y -v error -i "$DEMO_DIR/audio/$STAMP.orig.m4a" -vn -ar 48000 \
      -c:a flac -compression_level 5 "$DEMO_DIR/audio/$STAMP.flac"
  ffmpeg -y -v error -i "$DEMO_DIR/audio/$STAMP.orig.m4a" -vn -ar 48000 \
      -c:a libopus -b:a 48k "$DEMO_DIR/audio/$STAMP.opus"

  python3 - "$DEMO_DIR/audio" "$STAMP" <<'INNER'
import hashlib, json, sys
from pathlib import Path

directory, stamp = Path(sys.argv[1]), sys.argv[2]

def entry(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"name": path.name, "sha256": digest, "bytes": path.stat().st_size}

payload = {
    "sidecar_version": 1,
    "recording_id": stamp,
    "question_id": "q012",
    "created": "2026-09-04T09:00:00Z",
    "duration_seconds": 2.0,
    "device": "demo seed",
    "source": "upload",
    "files": {
        "original": entry(directory / f"{stamp}.orig.m4a"),
        "flac": entry(directory / f"{stamp}.flac"),
        "opus": entry(directory / f"{stamp}.opus"),
    },
}
(directory / f"{stamp}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
INNER
  echo "demo recording written to $DEMO_DIR/audio/"
else
  echo "ffmpeg or the fixture is missing; wrote the demo answer only" >&2
fi

echo "Demo seeded at $DEMO_DIR"
