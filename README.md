# Veillée

> ### Never use `tailscale funnel`.
> Publish this with **`tailscale serve`** only. Funnel exposes it to the public
> internet. This app has no accounts and treats the tailnet as its entire
> security boundary — Funnel would put an eighty-year-old man's private memoirs
> on the open web.

A private oral history site. One person answers questions about their life; the
answers are kept as plain markdown files that will still be readable in thirty
years by anyone with a file browser.

*veillée* — an evening gathering where people tell stories.

## Start it

```bash
./scripts/up.sh                    # builds and starts app + worker, on docker or podman
tailscale serve --bg "$(grep VEILLEE_PORT .env | cut -d= -f2)"
```

That is the whole story: no accounts, no API keys, no cloud, no setup wizard.
`up.sh` works out which container runtime is present, which uid the containers
must run as so that `data/` ends up owned by you, and a port that is actually
free. All of it goes into `.env`, which is where Compose reads variables from —
it does not inherit them from your shell.

Reading this the morning after a build? Go to **[HANDOFF.md](HANDOFF.md)**.

## The two rules everything follows from

1. **Nothing he types or records may ever be lost.**
2. **The interface must never make him feel rushed or stupid.**

So: autosave every five seconds with no save button, a revision kept before every
overwrite, deletions that move to `.trash/` instead of unlinking, `data/` as its
own auto-committing git repository, and atomic writes throughout. And: 20px body
text, 56px touch targets, one question per page, no sidebar, a warm count rather
than a percentage, and "Skip for now" given exactly the same weight as "Next".

## Where everything lives

The filesystem is the archive. SQLite is only an index and can be deleted at any
time; `veillee reindex` rebuilds it from `data/` alone, and a test proves it.

```
data/
  answers/02-childhood-and-home/012-your-mothers-kitchen.md
  audio/2026/09/20260903-141207-q012.{orig.m4a,flac,opus,json}
  transcripts/2026/09/20260903-141207-q012.md
  custom_questions.yaml   questions he added himself
  demo/                   a worked example of the format
  .revisions/             every autosave, timestamped, never pruned
  .trash/                 deletions land here; nothing is ever unlinked
```

## Audio: two paths, both real

**Path A** captures with `MediaRecorder` and uploads chunks *while he is still
talking*, so a dead battery costs seconds rather than an hour.

**Path B** is a plain file input on the same page — "Or upload a recording from
your phone" — for a Voice Memos recording made anywhere. It is not a degraded
mode. It exists because Safari's `MediaRecorder` is the least predictable piece
in the system, and it runs the identical server pipeline.

Both paths: keep the original untouched → FLAC at 48 kHz for the archive → Opus
at 48 kbps for playback → checksum all three into the sidecar → queue for
transcription.

## Transcripts are not shown to him

A machine transcript of an elderly man with an Irish accent will get his own
mother's name wrong. Transcripts are drafts, visible only at `/admin`, marked
"not yet reviewed". When you correct one, the machine's original wording is kept
beside it and never overwritten.

## Commands

```bash
make verify        # lint + 114 unit/integration + 38 browser + container smoke
make morning-check # 30 seconds: is it working right now?
make reindex       # rebuild the index from data/ alone
make export        # dated folder: markdown book, offline HTML site, manifest
make backup        # tar of data/ plus a consistent sqlite3 .backup
make up / down / logs
```

## Configuration

Everything has a working default and nothing is required.

| Variable | Default | What it does |
|---|---|---|
| `VEILLEE_PORT` | first free from 8000 | Chosen by `up.sh` and pinned in `.env`. |
| `VEILLEE_PASSCODE` | *(off)* | Optional single passcode; the cookie then lasts five years. |
| `VEILLEE_TRANSCRIPTION_BACKEND` | `local` | `local` (faster-whisper) or `remote` (OpenAI-compatible). |
| `VEILLEE_WHISPER_MODEL` | `small` | Baked into the image at build time. |
| `VEILLEE_GIT_AUTOCOMMIT` | `1` | Auto-commit `data/` on save. Never auto-pushes. |

Compose reads these from `.env` in the project directory, not from your shell.

## Documentation

- **[HANDOFF.md](HANDOFF.md)** — start here in the morning.
- [BUILD_LOG.md](BUILD_LOG.md) — what was built, what broke, what was done about it.
- [docs/prp/0001-veillee.md](docs/prp/0001-veillee.md) — why it is built this way.

## Licence

AGPL-3.0-or-later. See [LICENSE](LICENSE).
