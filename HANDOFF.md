# Handover

You are reading this at 6:45am with coffee. Here is everything, in the order you
need it.

---

## 1. Start here

```bash
cd /var/home/user/Documents/vibe-code/veille-webserver
./scripts/up.sh
```

That builds and starts both containers and prints the URL. Then publish it to
your tailnet:

```bash
tailscale serve --bg 8000
```

Open the `https://<machine>.<tailnet>.ts.net` address Tailscale prints. That is
the address to give him. **Never run `tailscale funnel`** — that publishes to the
public internet. `serve` keeps it inside your tailnet, which is this app's entire
security boundary.

There is no login, no API key, and no setup wizard. He opens the link and writes.

**This machine has no Docker.** It has podman 5.8.4 with a working Compose
provider, and `up.sh` detects whichever runtime is present. `compose.yaml` is
plain Compose spec, so it will run unmodified on a Docker host too.

---

## 2. Is it working?

```bash
make morning-check
```

Thirty seconds. It starts the stack if it is down, checks `/healthz`, writes a
real answer and reads it back, restores the question to how it was, and prints
`PASS` or the one specific thing that is wrong plus what to do about it.

The fuller gate, if you have ten minutes and want to be certain:

```bash
make verify        # lint, 114 unit/integration tests, 38 browser tests, then the container smoke test
```

`make verify` passing is the definition of done, and it passed twice from a
clean checkout before this was written.

---

## 3. Decisions I made for you

**Podman instead of Docker.** Docker is not installed on this machine. Podman is,
rootless, with a working Compose provider. `compose.yaml` stays plain Compose
spec so nothing is locked to podman.

**The uid the containers run as.** This is the one container detail that would
have quietly ruined everything, so it was checked before any code was written.
Rootless podman maps *container root* to *your host uid*; rootful Docker maps
uid-to-uid. Run it the wrong way and `data/` fills with files owned by a subuid
that you cannot open in a file browser — which defeats the whole point of storing
plain markdown. `scripts/runtime.sh` detects the runtime and sets `VEILLEE_RUN_AS`
accordingly, and the smoke test asserts the files are readable by *you*.

**Milkdown Crepe shipped; EasyMDE was not needed.** The esbuild bundle worked
inside the 45-minute box (after teaching esbuild to drop the KaTeX fonts that the
Crepe stylesheet pulls in). `static/vendor/editor.js` is 2.5 MB and committed. A
browser test asserts which editor is actually live, so this claim is checked
rather than assumed. If the bundle ever fails to load, the page falls back to a
plain textarea and **autosave works identically** — that path is tested too.

**Fourteen questions were rewritten.** A test guarding the "never yes/no" rule
caught fourteen questions that opened with "Was there…" or "Is there…". They are
now open-ended. The guard stays in the suite, so the bank cannot regress if you
add questions later.

**Transcription is `small` on CPU and the model is baked into the image.** The
first recording in the morning does not wait on a 500 MB download. If the
download had failed at build time the app would still come up green with jobs
queued; it did not fail, and the smoke test transcribes a real clip end to end.

**Abandoned upload staging goes to `.trash/`, not to `rm`.** Every finished
upload leaves a small staging directory in `data/.trash/`. It is a few kilobytes
per recording and it is deliberate: no code path in this project deletes anything
a person might have authored. Clear it by hand whenever you like.

**`/healthz` degrades rather than failing.** If the index is unreadable or ffmpeg
vanishes it reports `degraded` with specific problems and still serves pages, so
a broken transcode never stops him writing.

**The passcode is off.** `VEILLEE_PASSCODE` in the environment turns it on; the
cookie then lasts five years so he is never asked twice on a device.

---

## 4. What is not built

**Nothing from the required scope was skipped.** All ten phases are done and
gated. For completeness, the things deliberately left out:

- Photographs, family read-only access, and a printable book layout. These were
  named as phase two. Seams are clean and nothing is stubbed — there is no
  placeholder UI, no handler returning fake data, and no commented-out test.
- No accounts, analytics, telemetry, or public deployment, by design.
- The remote transcription backend is implemented and unit-tested but has never
  been run against a live endpoint, because that would have needed an API key.
  Local is the default and is what the smoke test exercises.
- `data/` auto-commits but never pushes. Setting up a remote is a decision about
  where his private words travel, and it is yours to make.

---

## 5. Known risks

### iPad Safari — read this one

**This is the most likely thing to be wrong this morning.** MediaRecorder was
tested in headless Chromium with a fake microphone and works. It could not be
tested on his actual iPad overnight. Safari's MediaRecorder support is the least
predictable piece in the whole system.

**Test Path A on his device in three minutes:**

1. Open the tailnet URL on the iPad and go to any question.
2. If you see a large **Start recording** button, MediaRecorder is available.
   If you instead see *"This browser won't let the page record directly"*, the
   API is missing — skip to the workaround below; nothing is broken.
3. Tap **Start recording**. Safari asks for microphone permission. Allow it.
4. Talk for about ten seconds. Watch for the level meter moving and the timer
   counting. If both move, chunks are already reaching the server.
5. Tap **Stop recording**. Within a few seconds an audio player should appear
   under "What you've recorded for this question". Play it back.
6. Confirm on the host: `find data/audio -name '*.flac' | tail -1` should show a
   new file.

**If any of that fails, the morning is still fine.** On the same page, below the
record button, is *"Or upload a recording from your phone"*. He records in Voice
Memos, taps share, and picks the file. It runs the identical server pipeline —
same FLAC, same Opus, same sidecar, same transcription — and it is covered by its
own browser test using a real `.m4a`. Tell him to use that and debug Safari later.

### The others

- **Disk.** Audio is the only thing here that grows. `/healthz` reports free
  space and warns below 1 GB.
- **Transcription is slow on CPU.** `small` on a few minutes of speech takes
  minutes. Jobs queue, retry with backoff, and dead-letter after five attempts;
  none of that ever blocks him from writing.
- **Transcripts are wrong on purpose-adjacent grounds.** They are machine drafts
  and are never shown to him. They live at `/admin` marked "not yet reviewed".
  When you edit one, the machine's original wording is preserved beside it and
  never overwritten.

---

## 6. If something breaks while he is using it

**His words are at `data/answers/`, as plain markdown, organised by chapter.**
That is true no matter what the software is doing. If everything else is on fire,
that directory is the thing that matters and it is intact.

**Look at the logs**

```bash
make logs                 # both containers, following
podman compose logs --tail 100 app
podman compose logs --tail 100 worker
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool
```

**Restore something he lost**

Every autosave keeps a copy first. Nothing prunes them.

```bash
ls -lt data/.revisions/q012/          # newest first
cp data/.revisions/q012/<stamp>.md data/answers/02-childhood-and-home/012-*.md
make reindex
```

Deleted recordings are in `data/.trash/`, never unlinked. `data/` is also a git
repository: `git -C data log --oneline` and `git -C data show <commit>` will show
you every save.

**The site loads but shows nothing / shows stale answers**

The index has drifted from the archive. Rebuild it — this is always safe, and it
reads only from disk:

```bash
make reindex
```

**A recording will not process**

```bash
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool   # look at "queue"
```

`dead` above zero means a job gave up. Open `/admin`, find the recording, and
press **Transcribe again**. The audio itself is already safe on disk regardless.

**Roll the whole thing back**

```bash
git log --oneline
git checkout <commit>
./scripts/up.sh
```

`data/` is a separate repository and is untouched by that, so rolling back the
code never touches a word he wrote.

**Back it up**

```bash
make backup     # tar of data/ plus a consistent sqlite3 .backup, into backups/
```

To run it nightly, create `~/.config/systemd/user/veillee-backup.service`:

```ini
[Unit]
Description=Veillee backup

[Service]
Type=oneshot
WorkingDirectory=/var/home/user/Documents/vibe-code/veille-webserver
ExecStart=/var/home/user/Documents/vibe-code/veille-webserver/scripts/backup.sh
```

and `~/.config/systemd/user/veillee-backup.timer`:

```ini
[Unit]
Description=Nightly Veillee backup

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

then `systemctl --user enable --now veillee-backup.timer`. `/healthz` reports the
last successful backup.

---

## 7. One thing worth saying to him

He does not need to be told about any of the above. He needs to be told three
things: he can answer in any order, he can stop whenever he likes, and there is
no save button because it saves itself. Everything else on the page is designed
to stay out of his way.
