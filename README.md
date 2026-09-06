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
docker compose up -d
```

That is the whole story. No `.env`, no scripts, no setup: every variable in
`compose.yaml` carries a default, and the image works out at start-up which user
it must run as so `data/` stays readable by you. Rootless podman maps container
root to your host user; rootful docker does not, and the entrypoint detects
which it is rather than asking you. Set `VEILLEE_PUID`/`VEILLEE_PGID` to override.

`podman compose up -d` works identically. `./scripts/up.sh` is an optional
convenience that additionally picks a free port and pins it in `.env`.

Then publish it:

```bash
tailscale serve --bg 8000          # never `tailscale funnel`
```

**Use the https address `tailscale serve` prints.** Browsers withhold the
microphone from a page served over plain http on anything but localhost, so
in-page recording only works on a secure origin. Binding a tailnet address
directly (`VEILLEE_BIND_HOST` in `.env`) is private and works for everything
else, but the record button will not appear.

**Do not put a public reverse proxy in front of this.** There is no
authentication unless you set `VEILLEE_PASSCODE`; a public hostname means anyone
who finds it can read and overwrite the answers.

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

## Photographs, family reading, and the book

A photograph belongs with the story. The file he uploads is kept byte for byte;
a screen copy is derived beside it, stood upright from its EXIF tag. Captions are
editable at any time and live in the sidecar, so they survive a reindex.

`VEILLEE_FAMILY_PASSCODE` gives relatives a reading copy — every answer,
recording and photograph, and no way to change any of it. Enforced by the
middleware, not by hiding buttons. Transcripts stay out of their reach.

`/book` is the whole archive in reading order, laid out to print: a chapter to a
page, questions never split, and audio players replaced on paper by a line
saying the recording exists.

## Commands

```bash
make verify        # lint + 262 unit/integration + 82 browser + container smoke
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
| `VEILLEE_PASSCODE` | *(off)* | His passcode. Full access; the cookie lasts five years. |
| `VEILLEE_FAMILY_PASSCODE` | *(off)* | A read-only word for relatives. No writing, no transcripts. |
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
