<!-- Generated: 2026-09-09 | Files scanned: 101 | Token estimate: ~800 -->

# Data

**Two stores, and only one of them matters.** The filesystem is the archive.
SQLite is an index that can be deleted at any moment and rebuilt with
`veillee reindex`. Never treat a SQLite row as the source of truth.

## Filesystem (the archive)

```
data/
  answers/<NN-chapter-slug>/<NNN-question-slug>.md   YAML frontmatter + markdown
  audio/YYYY/MM/<recid>.orig.<ext>                   original, byte-for-byte
                <recid>.flac                         48kHz mono, archival
                <recid>.opus                         48kbps, playback
                <recid>.json                         sidecar: checksums, duration
  transcripts/YYYY/MM/<recid>.md|.json               machine draft + corrections
  photographs/YYYY/MM/<pid>.orig.jpg                 untouched
                      <pid>.jpg                      EXIF-rotated screen copy
                      <pid>.json                     caption + checksums
  custom_questions.yaml                              questions the family added
  transcription-hints.txt                            whisper initial_prompt seed
  .revisions/<qid>/<stamp>.md                        every autosave, never pruned
  .trash/<stamp>/<original path>                     deletions; nothing unlinked
  veillee.db                                         THE INDEX (throwaway)
  .git/                                              auto-commit per save
```

Ids are `YYYYMMDD-HHMMSS-<questionid>`, so a filename alone locates a record
in time and subject.

## SQLite index (`db.py`)

```sql
answers(question_id PK, question_text, chapter_slug, chapter_order, body,
        status, created, updated, word_count, custom, path)
  idx answers_by_chapter(chapter_order, question_id)
  idx answers_by_updated(updated DESC)

recordings(recording_id PK, question_id, created, duration_seconds, device,
           original_path, flac_path, opus_path, sidecar_path,
           sha256_original, sha256_flac, sha256_opus, source,
           transcript_path, transcript_reviewed)
  idx recordings_by_question(question_id, created)

photographs(photo_id PK, question_id, created, caption, original_path,
            view_path, sidecar_path, sha256_original, sha256_view,
            width, height)
  idx photographs_by_question(question_id, created)

transcription_queue(id PK, recording_id, state, attempts, next_attempt_at,
                    last_error, created, updated)
  idx queue_by_state(state, next_attempt_at)

meta(key PK, value)
```

No foreign keys. Rows are derived from files; the file is the record.

## Question bank (`questions/*.yaml`, read-only)

14 chapters, ~120 questions, plus `data/custom_questions.yaml` (a 15th
chapter, "questions he asked himself"). 141 total at last load.
Ids: `qNNN` for the bank, `cNNN` for custom. `pinned: true` floats a
question to the top of his home page until answered.

## State machines

```
answer.status      unanswered -> answered | skipped | later
queue.state        pending -> running -> done | dead   (retries w/ backoff)
transcript         reviewed=0 (machine draft, hidden from him) -> 1
```

## Migrations

None. `CREATE TABLE IF NOT EXISTS` at startup, and the index is disposable —
a schema change is handled by deleting the .db and reindexing. This is only
safe because the filesystem is authoritative.

## Backups

`scripts/backup.sh`, nightly at 03:30 via systemd user timer on the host that
serves. Tar of `data/` + consistent `sqlite3 .backup`. Retention 14.
`data/` has **no git remote** by design: it holds a living person's words.
