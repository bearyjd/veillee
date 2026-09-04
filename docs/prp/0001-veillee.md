# 0001 — Veillée

*A record of what was built and why, written during the build.*

## The problem

One man, eighty years old, is the only person who will ever write here. His son
will read it. Nobody else has an account, because there are no accounts.

Two requirements dominate every other consideration:

1. **Nothing he types or records may ever be lost.**
2. **The interface must never make him feel rushed or stupid.**

Everything below follows from those two sentences. Where a decision was close,
the tie went to whichever option better served them.

## The filesystem is the archive

The most likely way to lose this material is not disk failure. It is
obsolescence: a database format, a framework, or a hosting company that stops
existing while the files are still wanted. So the durable artifact is a
directory of plain markdown with YAML frontmatter, readable in any text editor
in 2050, organised by chapter with human-readable filenames.

SQLite is an *index*. It makes the site fast and answers questions like "what
has he not answered yet". It is disposable by design: `veillee reindex` rebuilds
it from `data/` alone, and there is a test that deletes the database and asserts
the rebuild is identical. That test is what makes the claim true rather than
merely intended.

Consequence, accepted deliberately: every field the index knows must have a
source on disk. Frontmatter carries `question_id`, `question_text`, `chapter`,
`chapter_order`, `created`, `updated`, `word_count`, `status`, and `custom`. The
audio sidecar carries the question id, duration, device string, source, and
SHA-256 of all three audio files. Questions he adds himself go to
`data/custom_questions.yaml` — inside the archive, not in the code — for the
same reason.

## Nothing is ever deleted

Three layers, because "never lost" deserves more than one:

- **Revisions.** Every save copies the current file into `data/.revisions/`
  first. Autosave runs every five seconds, so this is not a version history so
  much as a continuous one. Nothing prunes it. Text is small; his words are not
  replaceable.
- **Trash.** Deleting a recording moves files to `data/.trash/`. The code never
  calls `unlink` on anything a person authored.
- **Git.** `data/` is its own repository and auto-commits on save. Never
  auto-pushed: pushing is a decision about where his private words travel, and
  that is his son's to make, not the software's.

Writes are atomic — temp file, fsync, rename — so a crash mid-write leaves the
previous version intact rather than a half-written one.

## Why autosave, and why no save button

A save button is a thing you can forget to press. At the far end of forgetting
to press it is a lost afternoon of talking about his mother. Autosave every five
seconds and on blur, with a quiet "Saved 2:14pm" line and no button at all,
removes the entire category of error.

The single most important test in the suite follows directly: type, wait, kill
the browser context outright, reopen, and assert the text is there. Not a mock —
an actual killed browser.

## Why two audio paths, not one

`MediaRecorder` is the right primary path: chunks upload *while* recording, so a
dead battery costs a few seconds rather than an hour. Chunks are written to
`data/.uploads/<id>/NNNNN.part` as they arrive, never buffered in memory, which
is what makes "at most a few seconds" true and makes the mid-upload disconnect
test straightforward.

But this ships to an iPad that could not be tested overnight, and Safari's
`MediaRecorder` support is the least predictable part of the entire system. So
there is a second, mandatory path: a plain file input, on the same page, equal
in weight. Voice Memos plus that button is a complete workaround requiring no
debugging at 7am. Both paths run the identical server pipeline.

The pipeline stores the original untouched, then derives FLAC (48 kHz, archival)
and Opus (48 kbps, playback), checksums all three into the sidecar, and enqueues
transcription. The original is kept because every transcode is a decision that
might turn out wrong later.

## Why transcripts are not shown to him

A machine transcript of an elderly man with an Irish accent will contain errors,
and some of them will be about his own mother's name. Showing him that is a way
of making him feel stupid, which is the thing we said we would not do.
Transcripts are drafts, visible only in the admin view, marked "not yet
reviewed", with the machine original preserved in frontmatter history when
edited. They are a convenience for his son, not a product surface for him.

`small` on CPU is the default because a cold start must never hang, and the
model is baked into the image so the morning is not blocked on a download.

## Security boundary

The tailnet is the boundary. The app binds `127.0.0.1` and is reached through
`tailscale serve`, never Funnel. The optional passcode exists for the case where
someone else uses the same tailnet; it is off by default and, when on, sets a
long-lived signed cookie so he is never asked twice on a device. Asking an
eighty-year-old for a password repeatedly is a way to lose a user.

## What was deliberately not built

Accounts, multi-tenancy, analytics, telemetry, public deployment, and any
AI-generated prose anywhere near his answers. Photographs, family read-only
access, and a printable book layout are phase two; seams are left clean and
nothing is stubbed. A stub that returns fake data is worse than an absence,
because an absence cannot be mistaken for working.
