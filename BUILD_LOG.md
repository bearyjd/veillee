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
