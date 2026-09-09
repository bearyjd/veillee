<!-- Generated: 2026-09-09 | Files scanned: 101 | Token estimate: ~900 -->

# Backend

FastAPI. Routers are thin: parse, validate, delegate to `storage/` or
`repository.py`, return. Business rules live below the HTTP layer.

## Pages (`web/routes_pages.py`)

```
GET  /                      -> home, the next unanswered question
GET  /chapters              -> chapter list
GET  /chapter/{slug}        -> questions in a chapter
GET  /question/{id}         -> the writing/recording page
GET  /random                -> jump to a random unanswered question
GET  /answers               -> everything answered so far
GET  /book                  -> whole archive in reading order, print CSS
GET|POST /enter             -> passcode gate (when configured)
```

## Answers (`web/routes_answers.py`)

```
POST /api/answer/{id}       -> autosave; revision first, then atomic write
GET  /api/answer/{id}       -> current text (editor recovery)
POST /question/{id}/skip    -> mark skipped, same weight as answering
POST /question/{id}/later   -> mark deferred
POST /questions/new         -> he adds his own question -> custom_questions.yaml
```

## Audio (`web/routes_audio.py`, 272 lines - the largest)

```
POST /api/recording/{qid}/start      -> open an upload, return upload_id
POST /api/recording/{uid}/chunk      -> chunks land WHILE he is still talking
POST /api/recording/{uid}/finish     -> assemble -> transcode -> enqueue
POST /api/upload/{qid}               -> whole-file path (phone voice memo)
GET  /audio/{rid}.{ext}              -> stream opus/flac
POST /api/recording/{rid}/delete     -> requires confirm:"delete"; -> .trash/
```

Two capture paths, one server pipeline. Chunked upload means a dead battery
costs seconds, not an hour.

## Photographs (`web/routes_photos.py`)

```
POST /api/photo/{qid}             -> original kept byte-for-byte; view copy
                                     derived, EXIF-rotated upright
GET  /photo/{pid}.jpg             -> screen copy
GET  /photo/{pid}/original        -> untouched original
POST /api/photo/{pid}/caption     -> caption lives in the sidecar, survives reindex
POST /api/photo/{pid}/delete      -> confirm word required; -> .trash/
```

## Admin (`web/routes_admin.py`) - never shown to him

```
GET  /admin                          -> transcripts awaiting review
GET  /admin/transcript/{rid}         -> machine draft
POST /admin/transcript/{rid}         -> correction; machine original retained
POST /admin/requeue/{rid}            -> re-run transcription
```

## Health (`web/routes_health.py`)

`GET /healthz` -> status, disk, queue depth, last_backup, counts, git state,
ffmpeg presence, transcription backend. Used by the container healthcheck and
by `make morning-check`.

## Ingest pipeline (`ingest.py` -> `transcode.py` -> `queue.py`)

```
upload -> keep original -> ffmpeg FLAC 48k mono (archive)
                        -> ffmpeg Opus 48kbps (playback)
                        -> sha256 all three -> JSON sidecar
                        -> INSERT transcription_queue
worker.py polls -> transcribe.py -> markdown + json transcript -> mark done
```

`transcribe.py` seeds faster-whisper's `initial_prompt` from
`data/transcription-hints.txt` (family surnames, place names) - without it
"Beary" transcribes as "Berry" every time.

## Key files

```
web/app.py          131  wiring, startup reindex, static mount
web/auth.py         127  passcode + family read-only middleware
repository.py       262  index reads/writes
index.py            215  filesystem -> SQLite rebuild
storage/answers.py  190  atomic write, revisions, trash
storage/audio.py    145  sidecars, checksums
storage/gitrepo.py  124  auto-commit data/
reassign.py         127  move a recording to a different question
export.py           211  dated folder: md book + offline HTML + manifest
```
