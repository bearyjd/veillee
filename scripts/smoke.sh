#!/usr/bin/env bash
# Full-stack smoke test: real containers, empty archive, write -> record ->
# transcribe -> export, then tear down. This is the final gate.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source scripts/runtime.sh

COMPOSE="$(detect_compose)" || { echo "FAIL: no docker or podman found." >&2; exit 1; }
VEILLEE_RUN_AS="$(detect_run_as)"
PORT="${VEILLEE_SMOKE_PORT:-8113}"
WORKDIR="$(mktemp -d)"
PROJECT="veillee-smoke-$$"
TRANSCRIBE_TIMEOUT="${VEILLEE_SMOKE_TRANSCRIBE_TIMEOUT:-420}"
FAILED=0

export VEILLEE_RUN_AS

step()  { printf "\n\033[1m-- %s\033[0m\n" "$1"; }
ok()    { printf "   ok   %s\n" "$1"; }
fail()  { printf "   FAIL %s\n" "$1"; FAILED=1; }

cleanup() {
  step "tearing down"
  $COMPOSE -p "$PROJECT" --project-directory "$WORKDIR" -f "$WORKDIR/compose.yaml" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

step "starting from a completely empty archive"
mkdir -p "$WORKDIR/data"
echo "   data dir: $WORKDIR/data (empty: $(find "$WORKDIR/data" -type f | wc -l) files)"

# A compose file identical to the real one but pointed at the throwaway archive.
# The build context must be absolute: relative paths in a generated compose file
# resolve against that file's own directory, not against the repository.
REPO_ROOT="$(pwd)"
sed -e "s#\./data:/data#${WORKDIR}/data:/data#g" \
    -e "s#context: \.#context: ${REPO_ROOT}#g" \
    compose.yaml > "$WORKDIR/compose.yaml"

# Compose takes its variables from .env in the project directory, not from the
# shell. Every invocation below therefore passes --project-directory "$WORKDIR".
printf 'VEILLEE_PORT=%s\nVEILLEE_RUN_AS=%s\n' "$PORT" "$VEILLEE_RUN_AS" > "$WORKDIR/.env"

step "bringing the stack up"
$COMPOSE -p "$PROJECT" --project-directory "$WORKDIR" -f "$WORKDIR/compose.yaml" up -d --build

BASE="http://127.0.0.1:$PORT"
step "waiting for the site to become healthy"
for _ in $(seq 1 120); do
  if curl -sf "$BASE/healthz" >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! curl -sf "$BASE/healthz" >/dev/null 2>&1; then
  fail "the site never became healthy"
  $COMPOSE -p "$PROJECT" --project-directory "$WORKDIR" -f "$WORKDIR/compose.yaml" logs --tail 60
  exit 1
fi
STATUS=$(curl -s "$BASE/healthz" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])")
[ "$STATUS" = "ok" ] && ok "healthz reports ok" || fail "healthz reports $STATUS"

step "writing an answer"
curl -sf -X POST "$BASE/api/answer/q012" -H 'Content-Type: application/json' \
  -d '{"body":"She baked on a Saturday night for the Sunday."}' >/dev/null
READBACK=$(curl -s "$BASE/api/answer/q012" | python3 -c "import sys,json;print(json.load(sys.stdin)['body'])")
[ "$READBACK" = "She baked on a Saturday night for the Sunday." ] \
  && ok "the answer reads back over HTTP" || fail "the answer did not read back"

# The bind mount and uid mapping are the point of this check: the file must be
# readable by the person running the smoke test, not by root or a subuid.
ANSWER_FILE=$(find "$WORKDIR/data/answers" -name '012-*.md' 2>/dev/null | head -1)
if [ -n "$ANSWER_FILE" ] && [ -r "$ANSWER_FILE" ]; then
  ok "the markdown file is readable on the host as $(id -un)"
  grep -q "Saturday night" "$ANSWER_FILE" && ok "the file contains his words" \
    || fail "the file does not contain the text"
else
  fail "no readable answer file appeared on the host (uid mapping is wrong)"
fi

step "uploading a recording"
UPLOAD=$(curl -sf -X POST "$BASE/api/upload/q012" \
  -F "file=@tests/fixtures/sample.m4a" -F "device=smoke test" || echo '{}')
RECORDING_ID=$(echo "$UPLOAD" | python3 -c "import sys,json;print(json.load(sys.stdin).get('recording_id',''))")
if [ -n "$RECORDING_ID" ]; then
  ok "recording accepted: $RECORDING_ID"
else
  fail "the upload was rejected: $UPLOAD"
fi

for kind in flac opus json orig.m4a; do
  if find "$WORKDIR/data/audio" -name "*.${kind}" 2>/dev/null | grep -q .; then
    ok "$kind written to the archive"
  else
    fail "no $kind file was produced"
  fi
done

curl -sf -o /dev/null "$BASE/audio/$RECORDING_ID.opus" \
  && ok "the recording plays back" || fail "playback failed"

step "waiting for the worker to transcribe it (up to ${TRANSCRIBE_TIMEOUT}s)"
TRANSCRIBED=0
for _ in $(seq 1 "$TRANSCRIBE_TIMEOUT"); do
  if find "$WORKDIR/data/transcripts" -name '*.md' 2>/dev/null | grep -q .; then
    TRANSCRIBED=1; break
  fi
  DEAD=$(curl -s "$BASE/healthz" | python3 -c "import sys,json;print(json.load(sys.stdin)['queue'].get('dead',0))")
  [ "$DEAD" != "0" ] && break
  sleep 1
done

if [ "$TRANSCRIBED" = "1" ]; then
  ok "a transcript was written"
  TRANSCRIPT=$(find "$WORKDIR/data/transcripts" -name '*.md' | head -1)
  grep -q "reviewed: false" "$TRANSCRIPT" \
    && ok "the transcript is marked as an unreviewed draft" \
    || fail "the transcript is not marked unreviewed"
elif [ "${VEILLEE_SMOKE_ALLOW_NO_MODEL:-0}" = "1" ]; then
  echo "   SKIP transcription (VEILLEE_SMOKE_ALLOW_NO_MODEL=1); the queue holds the job"
else
  fail "no transcript appeared; check whether the whisper model was baked into the image"
  $COMPOSE -p "$PROJECT" --project-directory "$WORKDIR" -f "$WORKDIR/compose.yaml" logs --tail 30 worker || true
fi

step "exporting"
$COMPOSE -p "$PROJECT" --project-directory "$WORKDIR" -f "$WORKDIR/compose.yaml" run --rm -T app \
  veillee export --into /data/exports >/dev/null 2>&1 || fail "export command failed"

EXPORT_DIR=$(find "$WORKDIR/data/exports" -maxdepth 1 -type d -name 'veillee-*' 2>/dev/null | head -1)
if [ -n "$EXPORT_DIR" ]; then
  ok "export folder created"
  for artefact in veillee-book.md index.html manifest.json; do
    [ -f "$EXPORT_DIR/$artefact" ] && ok "$artefact present" || fail "$artefact missing"
  done
  if [ -r "$EXPORT_DIR/veillee-book.md" ]; then
    ok "the export is readable on the host as $(id -un)"
  else
    fail "the export is not readable by you (one-off commands ran as the wrong user)"
  fi
  grep -q "Saturday night" "$EXPORT_DIR/veillee-book.md" \
    && ok "the book contains his answer" || fail "the book is missing the answer"
  find "$EXPORT_DIR/audio" -name '*.opus' 2>/dev/null | grep -q . \
    && ok "audio is in the export" || fail "no audio in the export"
else
  fail "no export folder was written"
fi

step "verifying the index can be rebuilt from the archive alone"
$COMPOSE -p "$PROJECT" --project-directory "$WORKDIR" -f "$WORKDIR/compose.yaml" run --rm -T app rm -f /data/veillee.db /data/veillee.db-wal /data/veillee.db-shm
REINDEX=$($COMPOSE -p "$PROJECT" --project-directory "$WORKDIR" -f "$WORKDIR/compose.yaml" run --rm -T app veillee reindex 2>&1 || true)
# Match the counts, not the sentence. This assertion broke once because the
# wording changed when photographs were added, while the behaviour was fine.
if echo "$REINDEX" | grep -qE "Indexed 1 answers" && echo "$REINDEX" | grep -qE "1 recordings"; then
  ok "reindex recovered everything from disk"
else
  fail "reindex did not recover the archive: $REINDEX"
fi

echo
if [ "$FAILED" = "0" ]; then
  printf "\033[1;32mSMOKE PASSED\033[0m — the whole stack works from an empty archive.\n"
  exit 0
fi
printf "\033[1;31mSMOKE FAILED\033[0m\n"
exit 1
