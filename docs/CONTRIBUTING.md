# Contributing

This is a private family archive that happens to be open source. The audience
for the running site is one man in his eighties; the audience for this file is
whoever maintains it next, possibly years from now.

Two rules govern every decision here, and a change that violates either is
wrong however clean it looks:

1. **Nothing he types or records may ever be lost.**
2. **The interface must never make him feel rushed or stupid.**

## Setup

Prerequisites: Python 3.13 (`.python-version`), [uv](https://docs.astral.sh/uv/),
and either docker or podman. `ffmpeg` is needed for audio, but it lives in the
image, so you only need it locally if you run outside a container.

```bash
uv sync            # dependencies
make install       # dependencies + the Playwright Chromium build
make up            # build and start both containers
```

`make up` needs no `.env`: every compose variable has a default, and the
entrypoint works out which uid to run as. See [ENV.md](ENV.md) for the full
list of knobs.

## Commands

<!-- AUTO-GENERATED: from Makefile targets — regenerate, do not hand-edit -->

| Command | Description |
|---|---|
| `make help` | Show this help |
| `make install` | Install all dependencies and the Chromium browser |
| `make browsers` | Install the Playwright browser only |
| `make lint` | ruff + mypy |
| `make fmt` | Reformat and autofix |
| `make test` | Unit and integration tests |
| `make verify` | Everything. This passing is the definition of done. |
| `make verify-fast` | Everything except the container smoke test |
| `make smoke` | Full-stack smoke test against real containers, from an empty data dir |
| `make morning-check` | 30 seconds: is it working right now? |
| `make publish` | Build and push the image to ghcr.io (needs a registry login) |
| `make relocate` | Package everything for a move to another machine |
| `make backup` | Back up the index and the archive |
| `make reindex` | Rebuild the SQLite index from data/ alone |
| `make export` | Write a dated export folder |
| `make up` | Build and start the containers (docker or podman, whichever is here) |
| `make down` | Stop the containers |
| `make logs` | Follow the container logs |
| `make run` | Development server on 127.0.0.1:8000 |
| `make worker` | Transcription worker in the foreground |
| `make clean` | Remove caches and the rebuildable index |

<!-- END AUTO-GENERATED -->

## Testing

`make verify` is the definition of done: ruff, ruff-format, mypy, the unit and
integration suite, the browser suite, and a container smoke test from an empty
data directory.

```
tests/               unit + integration (fast, no browser)
tests/e2e/           Playwright, marked `e2e` automatically by conftest
  test_laptop.py     his actual device: keyboard, mouse, wide viewports
  test_phone.py      Android viewports + touch emulation
  test_mediarecorder.py  real chunked upload with a fake microphone
  test_a11y.py       axe
```

Two habits this codebase learned the hard way:

**Assert on behaviour, not on wording.** A test that greps for a sentence the
CLI prints breaks when the sentence improves. Assert the file is readable, not
that a message says it is.

**Verify the artifact, not a proxy for it.** `docker compose restart` does not
rebuild an image. `make` can fail while the shell reports success. A test can
pass against host source while the container serves an older file. If you are
claiming something is deployed, fetch the served bytes and check.

## Style

Enforced by `make lint` (ruff + mypy, strict). Beyond that:

- **Immutability.** Return new objects; do not mutate arguments.
- **Small files.** 200–400 lines typical, 800 max. The largest here is 272.
- **Comments explain why.** The codebase is unusually heavy on prose comments,
  deliberately: most of them record a decision or a defect that is not visible
  from the code. Match that register — a comment that restates the line below
  it is noise, one that says why the obvious approach was wrong is the point.
- **Never normalise a name.** Surname spellings in this project's data are
  evidence, not typos.

## Pull request checklist

- [ ] `make verify` passes (not `verify-fast`, unless you say which you ran)
- [ ] New behaviour has a test that fails without the change — show it failing
- [ ] Any deployment claim was checked against served bytes, not inferred
- [ ] No secrets in the diff: this repository is **public**. Scan for auth
      keys, tailnet addresses, hostnames and machine names before pushing
- [ ] `HANDOFF.md` still true if you changed how it runs
- [ ] Commit message says why, not what — see `git log` for the register
