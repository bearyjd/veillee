<!-- Generated: 2026-09-09 | Files scanned: 101 | Token estimate: ~650 -->

# Dependencies

**No third-party service is required at runtime.** No API keys, no cloud, no
telemetry, no CDN. It runs on an unplugged machine. This is a constraint, not
an accident: the archive must not depend on anyone still being in business.

## Python runtime (`pyproject.toml`, all pinned exactly)

```
fastapi 0.115.6          HTTP
uvicorn 0.34.0           ASGI server
jinja2 3.1.5             templates
python-multipart 0.0.20  uploads
pyyaml 6.0.2             question bank, frontmatter
httpx 0.28.1             remote transcription backend only
itsdangerous 2.2.0       signed passcode cookie
faster-whisper 1.1.1     LOCAL transcription (default)
requests 2.32.3          "
pillow 11.1.0            EXIF rotation, screen copies
```

Dev: pytest, pytest-asyncio, playwright, ruff, mypy.

## System binaries

- **ffmpeg** — FLAC/Opus transcode. Absence is reported by `/healthz`.
- **git** — `data/` auto-commit. Degrades gracefully if missing.
- **sqlite3** — backups only, not the app.

## Vendored, not fetched

`static/vendor/`: Milkdown editor (`editor.js` + `editor.css`), Alpine.js,
htmx. Checked into the repo so the page works with no network and no build
step. Grepped: zero CDN hosts referenced from any template.

## Transcription backends (`transcribe.py`)

| `VEILLEE_TRANSCRIPTION_BACKEND` | Behaviour |
|---|---|
| `local` (default) | faster-whisper in-process; model baked into the image |
| `remote` | any OpenAI-compatible endpoint via `VEILLEE_REMOTE_BASE_URL` |

Local is the default so nothing leaves the machine. The model is chosen at
**build** time (`VEILLEE_WHISPER_MODEL`, default `small`), which is why the
image is ~3GB.

## Deployment

```
compose.yaml            build locally (app + worker)
compose.registry.yaml   pull ghcr.io/bearyjd/veillee:latest - no build, no drift
compose.tailscale.yaml  overlay: Tailscale sidecar; app joins its netns and
                        publishes NO host ports
```

CI (`.github/workflows/publish.yml`) publishes `sha-<commit>` + `latest` to
GHCR on every push to main. Deploying is `pull && up -d`.

Tailscale sidecar: userspace networking (no NET_ADMIN, no /dev/net/tun),
`TS_SERVE_CONFIG` mounted as a **directory** (containerboot watches the parent),
`${TS_CERT_DOMAIN}` substituted by containerboot itself. State volume holds the
node's private key — gitignored, and the repo is public.

## Network posture

Reached only over a tailnet, via `tailscale serve` (HTTPS, real cert).
HTTPS is functionally required: browsers withhold the microphone from an
insecure origin, so plain http means no record button.
**Never `tailscale funnel`.**

## Sibling project

`irish-heritage` (private) is the genealogy archive this feeds. Testimony
captured here is filed there by hand as `class: testimony`; see
`00-project/capture-architecture-2026-09-06.md` in that repo. No code
dependency in either direction.
