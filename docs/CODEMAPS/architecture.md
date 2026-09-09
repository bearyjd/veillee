<!-- Generated: 2026-09-09 | Files scanned: 101 | Token estimate: ~750 -->

# Architecture

Private oral-history site. One elderly man answers questions; the answers must
outlive the software.

## The rule everything follows from

**The filesystem is the archive. SQLite is a rebuildable index.**
`veillee reindex` reconstructs the database from `data/` alone; a test proves
it. Delete the .db and lose nothing. This inverts the usual dependency and
explains most decisions below.

## Shape

```
browser (his phone / laptop)
   |  HTTPS only - browsers withhold the mic from insecure origins
   v
tailscale serve  ->  FastAPI app (uvicorn)
                       |
       +---------------+----------------+
       |               |                |
   markdown +       SQLite index    transcription
   audio + jpg      (throwaway)     queue table
   on disk                              |
       |                                v
   git auto-commit                  worker process
   per save                         faster-whisper (local)
                                    or OpenAI-compatible (remote)
```

Two processes, one image: `veillee serve` and `veillee worker`. They share
`data/` and the SQLite file; the queue table is the only handoff.

## Boundaries

| Concern | Module | Note |
|---|---|---|
| HTTP | `web/routes_*.py` | thin; no business logic |
| Domain | `repository.py`, `questions.py` | reads/writes the index |
| Persistence | `storage/` | the actual archive; owns file layout |
| Async work | `queue.py`, `worker.py`, `transcribe.py` | retries, backoff |
| Rebuild | `index.py` | filesystem -> SQLite, idempotent |

## Durability guarantees

- autosave every 5s, no save button
- a revision written before every overwrite (`data/.revisions/`)
- deletes move to `data/.trash/`; nothing is unlinked
- atomic writes throughout (`storage/answers.py:atomic_write`)
- `data/` is its own git repo, auto-committed (never auto-pushed)
- audio kept 3 ways: original untouched, FLAC 48k archival, Opus playback,
  all SHA-256'd into a JSON sidecar

## Security model

No accounts. The tailnet is the entire boundary. `VEILLEE_PASSCODE` optional
(currently unset); `VEILLEE_FAMILY_PASSCODE` gives read-only family access,
enforced in middleware (`web/auth.py`), transcripts excluded.
**Never `tailscale funnel`.**
