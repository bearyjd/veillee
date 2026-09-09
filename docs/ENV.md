# Environment variables

Complete reference, generated from `src/veillee/config.py` and the compose
files. `README.md` carries a shorter list of the ones you are likely to want;
this is all of them.

**Nothing here is required.** Every variable has a working default, and the app
starts with an empty environment. Compose reads them from `.env` in the project
directory — *not* from your shell.

<!-- AUTO-GENERATED: from src/veillee/config.py — do not hand-edit this table -->

## Application (read by `config.py`)

| Variable | Default | Purpose |
|---|---|---|
| `VEILLEE_DATA_DIR` | `data` | The archive. Everything else is derived from it. |
| `VEILLEE_DB_PATH` | `<data>/veillee.db` | The rebuildable index. Safe to delete. |
| `VEILLEE_QUESTIONS_DIR` | `questions` | The question bank (read-only YAML). |
| `VEILLEE_PASSCODE` | *(unset)* | His passcode. Unset means **no authentication at all**. |
| `VEILLEE_FAMILY_PASSCODE` | *(unset)* | Read-only word for relatives. No writes, no transcripts. |
| `VEILLEE_SECRET_KEY` | `veillee-local-tailnet-only` | Signs the passcode cookie. Change it if you set a passcode. |
| `VEILLEE_GIT_AUTOCOMMIT` | `1` | Auto-commit `data/` on save. Never auto-pushes. |
| `VEILLEE_MAX_UPLOAD_BYTES` | `2147483648` (2 GiB) | Upload ceiling. |
| `VEILLEE_TRANSCRIPTION_BACKEND` | `local` | `local` (faster-whisper) or `remote`. |
| `VEILLEE_WHISPER_MODEL` | `small` | Baked in at **build** time; changing it needs a rebuild. |
| `VEILLEE_WHISPER_COMPUTE_TYPE` | `int8` | faster-whisper compute type. |
| `VEILLEE_WHISPER_DEVICE` | `cpu` | `cpu` or `cuda`. |
| `VEILLEE_REMOTE_BASE_URL` | *(unset)* | OpenAI-compatible endpoint, when backend is `remote`. |
| `VEILLEE_REMOTE_API_KEY` | *(unset)* | Key for that endpoint. |
| `VEILLEE_REMOTE_MODEL` | `whisper-1` | Model name for that endpoint. |
| `VEILLEE_WORKER_POLL_SECONDS` | `3.0` | Queue poll interval. |
| `VEILLEE_MAX_ATTEMPTS` | `5` | Transcription retries before a job is marked dead. |

## Deployment (read by compose and `scripts/`, not by the app)

| Variable | Default | Purpose |
|---|---|---|
| `VEILLEE_PORT` | first free from 8000 | Chosen by `up.sh`, pinned in `.env` so his bookmark keeps working. |
| `VEILLEE_BIND_HOST` | `127.0.0.1` | Loopback. Set to a tailnet address to publish directly — read the HANDOFF warning first. |
| `VEILLEE_PROXY_BIND` | `127.0.0.1` | Second address for an external reverse proxy. |
| `VEILLEE_PROXY_PORT` | `8082` | Port for that second address. |
| `VEILLEE_RUN_AS` | detected | uid the containers run as. `runtime.sh` detects podman vs docker and rewrites it. |
| `VEILLEE_PUID` / `VEILLEE_PGID` | *(unset)* | Override file ownership of `data/`. |
| `VEILLEE_IMAGE` | `ghcr.io/bearyjd/veillee:latest` | Image for `compose.registry.yaml`. Override for a fork. |
| `VEILLEE_PULL_POLICY` | `always` | Pull policy for the registry compose. |
| `VEILLEE_BACKUP_KEEP` | `14` | Backups retained per kind. |
| `VEILLEE_RELOCATE_DIR` | `.` | Where `make relocate` writes its tarball. |
| `TS_AUTHKEY` | *(unset)* | Tailscale sidecar only. Optional; without it the container logs a login URL. |

<!-- END AUTO-GENERATED -->

## Two that deserve more than a table row

**`VEILLEE_PASSCODE`.** Unset means anyone who can reach the site can read and
overwrite his answers. That is a defensible trade when the only route in is a
private tailnet and the only device is a laptop at home. It is a different
question once he is carrying it on a phone. The cookie lasts five years, so he
would type it once.

**`VEILLEE_WHISPER_MODEL`.** Baked into the image at build time, not read at
startup, which is why the image is ~3 GB. Changing it means rebuilding and
republishing, not restarting.
