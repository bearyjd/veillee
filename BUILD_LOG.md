# Build log

One line in, one line out, for every phase. Anything that failed is recorded
here with what was done about it.

Session started 2026-09-04T03:30:37Z (UTC). Host: Fedora atomic, 22 cores, no Docker, podman 5.8.4.

## Phase 0 — repo skeleton, dependencies, toolchain

- **2026-09-04T03:30:37Z — start.** Empty directory, not yet a git repository.
- Oriented on the host before writing anything. Findings that changed the plan:
  - **Docker is not installed.** podman 5.8.4 is, rootless, with a working
    external Compose provider (Compose spec v5.5.0). Decision recorded in
    `HANDOFF.md`; `compose.yaml` is written to the Compose spec so it runs
    unmodified under either runtime, and the Makefile picks whichever is present.
  - **Rootless bind-mount ownership verified first**, before any code was
    written, because getting it wrong would have invalidated every file the
    later phases wrote. `podman run --userns=keep-id -v ...` produces files
    owned by host uid 1000 that the host user can read and append to. Confirmed
    by writing from a container and appending from the host.
  - ffmpeg 7.1.5 present on the host; Python 3.12.13 installed via uv.
- `superpowers:brainstorming` would normally apply to a build request. It is a
  dialogue-based skill and the instructions for this run forbid asking
  questions, so it was skipped. User instructions override skills. Noted once
  here; not revisited.
- Two toolchain gambles were de-risked in parallel at the very start rather than
  at the phase that needed them:
  - **Milkdown Crepe bundle: succeeded.** esbuild initially failed on 60
    unresolved KaTeX font references pulled in by the Crepe stylesheet; fixed by
    loading font types as `empty` (the LaTeX feature is disabled anyway).
    Bundle is 2.5 MB of JS plus 55 KB of CSS, committed to the repo.
    **The EasyMDE fallback was not needed and was not used.**
  - **faster-whisper on Python 3.12: succeeded**, after adding `requests`,
    which faster-whisper 1.1.1 imports without declaring.
- `uv sync` initially failed because `pyproject.toml` referenced a README that
  did not exist yet. Wrote the README, re-ran, green.
- **Gate: `make lint` green.**

## Phase 1 — storage layer, markdown read/write, reindex, revisions

- Frontmatter and sidecar schemas were designed *before* the database schema, so
  that reindex fidelity is structural rather than accidental: every column in
  the index has a source field on disk.
- `ffmpeg` transcode bug caught by running it rather than reading it: writing to
  a `.part` temp file broke container detection, so both FLAC and Opus failed to
  muxer-init. Fixed by passing `-f` explicitly. Verified by transcoding a real
  tone and re-probing the codec and duration of both outputs.
- **Gate: reindex test green** — five answers written, database deleted from
  disk, rebuilt from `data/` alone, rows compared and identical.

## Phases 2, 4, 5, 7 — site, both audio paths, export

- Pages, templates, and stylesheet written. 20px body text, 56px minimum touch
  targets, no sidebar, everything one click from home. Skip and Come back to
  this are the same size and weight as Next question.
- **Bug found by running the server, not by reading the code.** The first real
  autosave request returned 500 while *still writing the file correctly*:
  FastAPI resolves a sync dependency on a worker thread but ran the async
  handler on the event loop thread, so the SQLite connection crossed threads and
  raised `ProgrammingError`. Fixed with `check_same_thread=False`, which is
  correct here because a connection is per-request and never used concurrently.
  This would have been the failure at 7am, and no amount of re-reading the code
  would have surfaced it.
- Two smaller fixes from the same discipline: FastAPI could not build a response
  model from the `HTMLResponse | RedirectResponse` union on `/enter`, and the
  `.part` temp-file suffix broke ffmpeg's container detection.
- Verified over real HTTP against a running server: autosave, second save
  creating a revision, `data/` git auto-commit, skip redirect, adding his own
  question, Path B upload of a real `.m4a`, chunked Path A upload assembled from
  three parts, playback of both opus and flac, delete refusing without the typed
  word and moving files to `.trash/` when given it.
- Reindex re-verified with audio present: index deleted, rebuilt from disk
  alone, recovered 2 answers and 1 recording, and re-queued the recording that
  had no transcript on disk.
- Export produces the markdown book, the self-contained HTML site with playable
  audio, a copy of the archive, and a manifest that verifies its own checksums.

## Phases 3, 6 and the test suite

- **Crash-recovery test green**, and it is a real crash: the test types, waits
  past one autosave interval, then kills the renderer outright with
  `chrome://crash` so no unload handler, beacon, or flush can run. A fresh
  browser context then finds the words both in the page and in the markdown file
  on disk. Eight tests cover it, including typing and clicking Next immediately.
- **The Milkdown Crepe editor is what shipped.** A test asserts which editor is
  live and that exactly one of the two is in use, so the handover states a fact
  rather than an assumption.
- Three real defects found by tests rather than by reading:
  - **`make test` would have run nothing.** `pytest_collection_modifyitems` is a
    global hook, so the conftest in `tests/e2e/` was marking the *entire* suite
    as e2e and `-m "not e2e"` silently deselected all 152 tests. Now filtered by
    path. This is the kind of failure that makes a green suite meaningless.
  - **Fourteen questions opened as yes/no** ("Was there…", "Is there…"), against
    the explicit "never yes/no" requirement. A content guard test caught them;
    all fourteen were rewritten open, and the guard now protects the bank.
  - **Two serious accessibility violations on the question page** — the Milkdown
    `role="textbox"` had no accessible name and the wrapper div carried an
    `aria-label` it is not permitted to have. Both fixed; axe-core now reports
    zero critical *and* zero serious violations on every page template.
- One design fix from a test: "Next question" rendered 3.7px taller than "Skip
  for now" because an anchor and a button inherit different line heights. Skip
  and Come back to this are required to be equal in weight, so `.button` now
  sets line-height explicitly and the test asserts the heights match.
- MediaRecorder is tested with a real fake microphone
  (`--use-file-for-fake-audio-capture`), asserting both that a recording reaches
  disk as FLAC and that chunks are already durable on the server *while the
  recording is still running*.
- Totals at this point: 114 unit and integration tests, 38 browser tests.

## Phases 8 and 9 — containers, backup, smoke, demo

- One image, two roles. The whisper `small` model is baked in at build time
  (`model small baked in` in the build log), so the first recording of the
  morning does not wait on a 500 MB download.
- **Two container bugs found by running the smoke test, both of which would have
  been silent in production:**
  - **Compose does not inherit shell environment variables here.** `podman
    compose` re-executes its external provider with a sanitised environment, so
    `export VEILLEE_RUN_AS=…` was being dropped and the container would have run
    as the wrong uid — producing an archive owned by a subuid that the host user
    cannot open in a file browser, which is the exact failure the whole
    plain-markdown design exists to prevent. Confirmed by comparing `compose
    config` output with and without a `.env` file. Both `up.sh` and `smoke.sh`
    now write `.env` in the project directory, which is the portable
    Compose-spec mechanism and behaves identically under docker.
  - A generated compose file resolves `context: .` against its own directory,
    not the repository, so the smoke test could not build. Now absolute.
- Port 8000 is already occupied on this host by an unrelated service, so the
  smoke test uses 8113 and `HANDOFF.md` notes it.
- **Gate: `scripts/smoke.sh` green from a completely empty archive.** Eighteen
  checks: the stack builds and starts, `/healthz` is ok, an answer written over
  HTTP appears on the host as a file *readable by the host user* (the uid check),
  a real `.m4a` upload produces original/FLAC/Opus/sidecar and plays back, the
  worker genuinely transcribes it and marks the draft unreviewed, export writes
  the book, the offline site and a verifying manifest, and finally the database
  is deleted inside the container and rebuilt from `data/` alone.
- Demo content seeded at `data/demo/` — one answer and one recording in all three
  forms, produced by the real pipeline, kept outside `data/answers/` so it never
  mixes with his words or counts toward his progress.

## Review pass — three shipped paths that had never been executed

A review caught that `up.sh`, `backup.sh` and `morning-check.sh` had been
written, syntax-checked, and never actually run. `make verify` does not cover
them. Running them found four defects, one of them serious:

- **`morning-check.sh` would have destroyed an answer on its failure path.** The
  probe overwrites q120 and restores it afterwards — but the read-back-mismatch
  branch called `problem()`, which exits *before* the restore. The one morning
  the check failed, it would have left "morning check 06:45:12" as his answer to
  the last question in the book. That is governing principle #1 being broken by
  the diagnostic tool, at the worst possible moment. The restore now runs from a
  shell `trap`, and this was verified by forcing the failure branch and watching
  the original answer come back (exit code 1, answer intact).
- **`morning-check.sh` still used the exported-shell-variable mechanism** that
  had already been proven not to reach Compose. It predated that fix and was not
  swept. On rootless podman it lands on the right value by accident; on Docker it
  would have produced root-owned files.
- **Port 8000 is occupied on this host by an unrelated service.** The smoke test
  had been moved to 8113, but `up.sh`, the README and HANDOFF all still said
  8000 — so the very first command in the handover would have failed to bind.
  `up.sh` now finds a free port, pins it in `.env` so a bookmarked URL keeps
  working, and prints it. It chose 8002 here.
- **`up.sh` aborted silently** under `set -e`: `configured_port` returned
  non-zero when `.env` did not exist yet, killing the script inside a command
  substitution before it printed anything at all.
- `backup.sh` looked for the index only under `data/`, missing the
  repository-root database that `make run` creates.
- Missing audio fixtures were `pytest.skip`, which would have let the
  MediaRecorder round-trip and the Path B upload test silently not run inside a
  green build. They now fail, with a test asserting all three fixtures exist.

All three commands were then run for real against the live containers:
`./scripts/up.sh` (port 8002, files on the host owned by uid 1000 and readable),
`make backup` (archive tar plus a consistent sqlite copy, and `/healthz`
`last_backup` moved from `never` to a timestamp), and `make morning-check`
(PASS, with the probe restored).

## Final sweep against the specification

Re-read the original requirements line by line against what shipped. Two gaps:

- **Pause and resume were missing from the recorder.** Start and stop were
  implemented; the requirement said "pause/resume" and it had been dropped. Now
  implemented, with the elapsed clock frozen while paused, the level meter
  stilled, the message "paused. Nothing has been lost.", and a test that pauses
  mid-recording, resumes, stops, and asserts **one** file was produced rather
  than two.
- **htmx was vendored and loaded but never used.** Alpine earns its place
  driving the recorder; htmx had no honest job, because every page here is a
  full page with no partial-HTML swap. Shipping it would have been 51 KB of dead
  weight on every page he opens. The `<script>` tag was removed and the file
  kept for phase two. Recorded as a decision in HANDOFF.md rather than left
  unexplained.

Everything else in the specification was present and verified.

One more defect found by looking at the running system rather than the tests:
`podman ps` showed **the worker permanently "unhealthy"** while it was working
perfectly. It inherited the image's healthcheck, which asks for `/healthz` — a
URL only the app serves. At 6:45am that reads as a broken system and sends you
debugging something that is fine. The worker now has its own healthcheck asking
the only question that matters for it: can it reach the queue it drains.
Confirmed by recreating the container and watching it report healthy.

## Phase 9 — the gate

`make verify` run twice in a row from a fresh `git clone` of the committed tree
(`5ef5a03`), with no `.venv` and no `data/` carried over:

```
########## RUN 1 ##########          ########## RUN 2 ##########
ruff check ......... All checks       ruff check ......... All checks
ruff format ........ 48 formatted     ruff format ........ 48 formatted
mypy ............... 30 files, ok     mypy ............... 30 files, ok
pytest -m "not e2e"  116 passed       pytest -m "not e2e"  116 passed
pytest tests/e2e ... 40 passed        pytest tests/e2e ... 40 passed
scripts/smoke.sh ... SMOKE PASSED     scripts/smoke.sh ... SMOKE PASSED
RUN1_EXIT=0                           RUN2_EXIT=0
```

Both green. 156 tests, plus 18 smoke checks against real containers built from
an empty archive. Stopping here, as instructed: no refactoring, no polish, no
phase-two work.

## After the gate — the toolbar was missing

Asked directly whether there was a WYSIWYG editor, and checking the running site
rather than repeating the earlier claim, two things turned out to be true:

- **The rich editor was genuinely live and genuinely WYSIWYG.** Typing `## `
  produced a real `<h2>`, `- ` a real list item, with no console errors.
- **There was no toolbar at all.** The specification asked for bold, italic,
  heading, bullet list and quote. Crepe's own toolbar element was in the DOM but
  never became visible — not on load, and not on selection either.

Worse, the claim in the earlier handover that "a browser test asserts which
editor is live" was **not true**. That test asserted only that *exactly one of
the two* editors was in use, which passes whether the rich editor loaded or the
emergency textarea did. It was never checking the thing it was cited for.

Fixed:

- Five always-visible buttons, rendered by Veillee rather than Milkdown, wired to
  the commonmark commands through Crepe's editor instance. 48px targets, labelled
  for screen readers, and focus returns to the text after every press.
- Heading toggles back to plain text on a second press.
- The toolbar is hidden entirely when the plain-textarea fallback is in use,
  where he is typing markdown himself and buttons would be lying.
- **A real bug found by the test for that:** `display: flex` on the toolbar beat
  the `hidden` attribute's `display: none`, so the toolbar appeared in fallback
  mode with nothing behind it. Every button would have done nothing.
- The weak editor test was replaced with one that asserts Milkdown specifically,
  one that asserts markdown renders live as rich text, and one that blocks the
  bundle request to prove the fallback path.
- Eleven new toolbar tests, each asserting the markdown that reached the disk.

### Gate re-run after the toolbar

`make verify` twice in a row from a fresh clone of `9c8e224`:

```
#### RUN 1 ####                       #### RUN 2 ####
ruff + format + mypy .... clean       ruff + format + mypy .... clean
pytest -m "not e2e" ..... 116 passed  pytest -m "not e2e" ..... 116 passed
pytest tests/e2e ........ 53 passed   pytest tests/e2e ........ 53 passed
scripts/smoke.sh ........ PASSED      scripts/smoke.sh ........ PASSED
RUN1_EXIT=0                           RUN2_EXIT=0
```

169 tests, up from 156. The image was rebuilt and the live stack restarted, and
the toolbar was confirmed on the running containerised site rather than only in
the test harness.

## Audit: claims versus tests

Asked directly what else had been claimed but not tested. Audited the suite
rather than answering from memory, and found nine gaps. One was a false
statement in a shipped document: HANDOFF said the remote transcription backend
was "unit-tested" when it has no test at all. Corrected.

The largest gap is that **`data/` git auto-commit is exercised by no test
whatsoever** - both fixtures set `VEILLEE_GIT_AUTOCOMMIT=0` so tests do not
touch git. Auto-commit backs a "nothing is ever lost" promise, and it was
verified only by hand.

All nine are now listed in HANDOFF.md under "What is claimed here but not covered
by a test", so the edge of the suite is written down rather than implied.

## Closing the nine gaps

Asked to close all nine. Writing the tests found three real defects that the
existing suite could not have caught:

1. **`autocommit()` could raise.** Its contract is that a git problem never
   takes the site down mid-sentence, but `data_dir.mkdir()` sat outside the
   `try`, so an unwritable `data/` raised straight into the request. Moved in.
2. **Autosave on blur was half implemented.** The rich editor only bound
   `window`'s blur - which fires when the whole browser loses focus, not when he
   clicks from the text onto the page. The textarea fallback had a proper
   handler; the editor most people would use did not. Now bound to `focusout`,
   with a test asserting the words reach disk faster than the five-second timer
   could have written them.
3. **The editor was a keyboard trap.** Tab indents lists inside ProseMirror
   rather than moving focus on, which fails WCAG 2.1.2 and is invisible to
   axe-core. Escape now leaves the writing box, focus moves to the next control,
   and a hint appears under the box whenever it has focus - because the guideline
   requires the user be told the method, not just given one.

Plus one design change found by a test hitting the wrong instance: an explicitly
exported `VEILLEE_PORT` now beats the pinned value in `.env`, so a check can be
pointed at another instance without editing files.

New coverage: 12 git tests, 15 passcode tests (including open-redirect refusal
and a five-year cookie), 11 worker-loop tests, 13 transcript tests (that his
pages never contain the machine words, and that a second edit cannot overwrite
the machine original), 20 deployment tests covering `runtime.sh`, `backup.sh`,
`morning-check.sh` and `up.sh` against a stub runtime, plus the loopback-only
bind. 187 unit and integration tests, up from 116.

### A bug only a clean checkout could find

The first double-verify after closing the nine gaps **failed both runs**, on a
test that passed in the working tree. The cause was worth the trip:

`scripts/runtime.sh` began with `set -euo pipefail`. It is a *sourced* library,
so that silently imposed `-e` on every caller - including `morning-check.sh`,
which sets `set -uo pipefail` deliberately so it can report failures itself
rather than dying on the first non-zero return. With `-e` forced on,
`find data/answers` on a checkout that has no answers yet - the ordinary state
before he writes anything - killed the script *after* the probe had already
passed, so it printed "write and read back: ok" and then exited 1.

It passed locally only because the working tree happened to have a `data/`
directory. Running from a fresh clone is what surfaced it.

Fixed by removing the shell options from the sourced library (every caller
already sets its own, and morning-check's choice not to use `-e` is now
respected), and by treating a missing answers directory as zero rather than an
error. Two regression tests: one runs morning-check against a checkout with no
`data/` at all, the other asserts that sourcing `runtime.sh` cannot switch on
errexit behind its caller's back.

### Gate, after the nine gaps were closed

`make verify` twice in a row from a fresh clone of `3e5485d`, confirmed to have
no `data/` directory:

```
#### RUN 1 ####                       #### RUN 2 ####
ruff + format + mypy .... clean       ruff + format + mypy .... clean
pytest -m "not e2e" ..... 189 passed  pytest -m "not e2e" ..... 189 passed
pytest tests/e2e ........ 59 passed   pytest tests/e2e ........ 59 passed
scripts/smoke.sh ........ PASSED      scripts/smoke.sh ........ PASSED
RUN1_EXIT=0                           RUN2_EXIT=0
```

248 tests, up from 156 at the original gate. Four defects were found by writing
the tests for claims that had been made without them, and a fifth - the sourced
library forcing errexit - by running from a clean checkout rather than a working
tree.

## Published on the tailnet address

Asked to publish it on the tailscale IP. Done - `VEILLEE_BIND_HOST` in `.env`
points at `<tailnet-ip>`, and the site answers there across the tailnet with no
further commands.

Checking it first was worth it. Browsers withhold the microphone from a page
served over plain http on anything but localhost, so this **silently disables the
record button**. Verified on the running site rather than assumed:
`isSecureContext = false`, `navigator.mediaDevices` undefined, no record button
rendered. Everything else - writing, autosave, playback, upload - is unaffected,
and the graceful fallback behaved exactly as designed.

The page used to say "This browser won't let the page record directly", which is
wrong here and would send his son debugging Safari for an hour. It now names the
address as the cause and prints the one command that fixes it.

The bind test was rewritten to the honest rule - never `0.0.0.0`, always
defaulting to loopback - rather than "must literally be 127.0.0.1", since the
bind host is now deliberately configurable. Writing it found that a naive
`rsplit(":", 2)` mis-parses compose's `${VAR:-default}` syntax, because the
variable form contains colons of its own; it would have let a genuinely wrong
binding through. Now masks variables before splitting.

Gate: `make verify` green twice from a fresh clone of `0957449` - 189 unit and
integration, 64 browser, smoke passed. 253 tests.

## Making `docker compose up -d` the whole story

It was already containerised and running, but plain `docker compose up -d` was
not sufficient on its own: `compose.yaml` forced `user: ${VEILLEE_RUN_AS:-0}`,
and getting that value right needed `scripts/up.sh` to detect the runtime first.

The uid question is real - rootless podman maps container root to your host
user, so root is correct there, while rootful docker maps it to real root, where
it would fill `data/` with root-owned files nobody can open in a file browser.
That is the failure the whole plain-markdown design exists to prevent.

Rather than making the operator configure it, the image now decides at start-up.
`docker-entrypoint.sh` reads `/proc/self/uid_map`: an identity mapping means we
are really root, so it drops to whoever owns the bind mount; a namespaced
mapping means container root is already the host user, so staying root is right.
An explicit `PUID`/`PGID` always wins on either runtime.

Verified both branches against the real image: `PUID=1234` drops to uid 1234,
and the unset case under rootless podman stays root. Then verified the whole
thing from a directory containing nothing but `compose.yaml` - no `.env`, no
scripts - which started both containers, answered on the port, and wrote an
answer owned by the host user.

Seven new tests, including one asserting every compose variable carries a
default so a fresh host can boot without an env file.

## A Docker-only bug, found by running CI on Docker

Everything in this project was developed against podman, and every claim about
Docker rested on the compose file being spec-compliant. Adding `make smoke` to
CI - where the runner has real Docker - turned that claim into a test, and it
failed on the first run.

`docker compose exec` runs a command inside the already-running container and
**skips ENTRYPOINT entirely**. The entrypoint is what works out which uid to
run as, so `veillee export` and `veillee reindex` were executing as root on
rootful Docker and writing root-owned files into the bind-mounted archive:

```
grep: .../data/exports/.../veillee-book.md: Permission denied
   FAIL the book is missing the answer
```

This is invisible under rootless podman, where container root already maps to
the host user - so it would have shipped, and would have appeared the first time
anyone ran an export on a Docker host. The archive files themselves were fine;
only one-off commands were affected.

Fixed by using `docker compose run --rm`, which does go through the entrypoint.
The smoke test now also asserts the export is readable by the person running it,
rather than only that the files exist - the previous check passed on a file it
could not actually read.
