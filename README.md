# Veillée

> **Never expose this with `tailscale funnel`.** Use `tailscale serve` only. Funnel
> publishes to the public internet; serve keeps it inside your tailnet. This app has
> no accounts and assumes the tailnet *is* the security boundary.

A private oral history site. One person answers questions about their life; the
answers are kept as plain markdown files that will still be readable in thirty
years by anyone with a file browser.

*veillée* — an evening gathering where people tell stories.

## Start it

```bash
docker compose up -d          # or: podman compose up -d
tailscale serve --bg 8000
```

Open the URL Tailscale prints. That is the whole story: no accounts, no API keys,
no cloud, no setup wizard.

## Where everything lives

The filesystem is the archive; SQLite is only an index and can be deleted at any
time. `veillee reindex` rebuilds it from `data/` alone.

```
data/
  answers/02-childhood-and-home/012-your-mothers-kitchen.md
  audio/2026/09/20260903-141207-q012.{orig.m4a,flac,opus,json}
  transcripts/2026/09/20260903-141207-q012.md
  .revisions/       every autosave, timestamped, never pruned
  .trash/           deletions land here; nothing is ever unlinked
```

`data/` is its own git repository and auto-commits on every save. It is never
auto-pushed anywhere.

## Documentation

- `HANDOFF.md` — start here in the morning.
- `docs/prp/0001-veillee.md` — why it is built this way.
- `make verify` — the full test suite. This passing is the definition of done.

## Licence

AGPL-3.0-or-later. See `LICENSE`.
