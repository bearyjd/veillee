# Runbook

Operating the running site. **For "something is broken while he is using it",
go to `HANDOFF.md` §6** — that is the incident guide and this file deliberately
does not duplicate it. This one covers deploying, rolling back, and checking.

## Where it runs

Two hosts, only one of them live. Both answer, so check before you act:

```bash
curl -s https://<his-hostname>/healthz | grep -o '"total_human":"[^"]*"'
```

The live host is a 104 GB machine; the old one is 8 TB. The real hostnames are
in `LOCAL.md`, which is gitignored. See `HANDOFF.md` §0 for the current split.

## Deploy

The image is published by CI on every push to `main`, tagged `sha-<commit>` and
`latest`. Deploying is pulling that tag — the push and the deploy are the same
act, and the host cannot drift from `main`.

```bash
ssh <live-host>
cd /home/user/docker/veillee
docker compose -f compose.registry.yaml -f compose.tailscale.yaml pull
docker compose -f compose.registry.yaml -f compose.tailscale.yaml up -d
```

Then confirm the running image is the commit you expect:

```bash
docker inspect veillee-app-1 --format '{{.Config.Image}}'
curl -s https://<his-hostname>/healthz | python3 -m json.tool | head -5
```

**Do not deploy while he is recording.** Chunks upload during a recording;
restarting the app mid-recording loses whatever has not landed. Check first:

```bash
docker compose ... logs app | grep -v healthz | tail -5
```

## It deploys itself, nightly

A systemd user timer on the live host runs `scripts/auto-deploy.sh` at 04:00,
half an hour after the backup, so the night's backup is always of the version
that was serving before the change.

```bash
systemctl --user list-timers veillee-deploy.timer
journalctl --user -u veillee-deploy.service -n 20
```

The script is built to prefer doing nothing:

- **It will not restart while he is recording.** Chunks land in `.uploads/`
  while he is still speaking and are assembled only when he stops; restarting
  between those two moments discards the part of the story he was in the
  middle of telling. A file touched there in the last fifteen minutes stops
  the deploy, and it says so in the journal.
- **It only restarts when the image actually changed**, comparing the running
  container's `org.opencontainers.image.revision` label against the pulled
  one.
- **A failed pull is not an error.** A registry outage leaves the running
  version alone rather than taking the site down.

Deploying by hand is still the procedure above, and is what you want when you
have just pushed something and do not intend to wait until four in the
morning.

## Health

`GET /healthz` returns status, disk, queue depth, `last_backup`, archive
counts, git state, ffmpeg presence and the transcription backend. It is what
the container healthcheck and `make morning-check` both use.

Worth alarming on, if you ever add monitoring:

| Signal | Meaning |
|---|---|
| `status != "ok"` or `problems` non-empty | the app has found something wrong itself |
| `last_backup` is `never` or old | the archive is unprotected — see below |
| `queue.dead > 0` | transcriptions exhausted their retries |
| `git.ok false` | `data/` is no longer versioning his words |
| `ffmpeg false` | audio will be accepted and never transcoded |

## Rollback

Every push is a tagged image, so rollback is a pin:

```bash
VEILLEE_IMAGE=ghcr.io/bearyjd/veillee:sha-<goodcommit> \
  docker compose -f compose.registry.yaml -f compose.tailscale.yaml up -d
```

Put that line in `.env` to make it stick across restarts, and take it out when
you go forward again.

**The archive is not rolled back by this and does not need to be.** `data/` is
its own git repository with a commit per save, deletions go to `.trash/`, and
every autosave is kept in `.revisions/`. To recover a specific answer, go into
`data/` and use git; do not restore a whole backup to fix one file.

## Backups

Nightly at 03:30, systemd user timer **on whichever host is live**, with
lingering enabled so it runs without a login. Retention 14.

```bash
systemctl --user list-timers veillee-backup.timer
systemctl --user start veillee-backup.service   # prove it, do not trust it
journalctl --user -u veillee-backup.service -n 20
```

The trap this project already fell into: after a host migration the timer ran
on the **old** machine, faithfully backing up a copy nobody was writing to,
while the live archive reported `last_backup: never`. If you move hosts, move
the timer, and disable the one you left behind.

`data/` has **no git remote** by design — it is a living person's words. The
nightly backup sits on the same disk as the original, so a second machine's
copy is the only real redundancy. Keep one.

## Moving to another machine

```bash
make relocate            # one tarball: code, compose overlays, whole archive
scp veillee-move-*.tar.gz newhost:/tmp/
# on the new host:
tar -xzf /tmp/veillee-move-*.tar.gz
docker compose -f compose.registry.yaml -f compose.tailscale.yaml up -d
docker compose ... exec app veillee reindex
```

The SQLite index is deliberately **not** in the tarball. Rebuilding it on the
far side is a free proof that nothing was lost in transit — compare the counts
it prints against the source. Checksum the archive files on both ends too; it
costs one command and it is the only thing that actually proves the move.

Also: the tarball carries the source host's `.env`, whose addresses are wrong
on the new machine. Strip `VEILLEE_PROXY_BIND` / `VEILLEE_PROXY_PORT` before
starting, or the bind fails.

## Publishing it

`tailscale serve` only. **Never `tailscale funnel`** — that puts an elderly
man's private memoirs on the public internet. There is no authentication
unless `VEILLEE_PASSCODE` is set, and it currently is not.

HTTPS is functionally required, not cosmetic: browsers withhold the microphone
from an insecure origin, so plain http means the record button never appears.
