# Handover

You are reading this at 6:45am with coffee. Here is everything, in the order you
need it.

---

## 1. Start here

```bash
cd /var/home/user/Documents/vibe-code/veille-webserver
docker compose up -d          # or: podman compose up -d
```

That needs no `.env` and no scripts — every compose variable has a default, and
the image works out which uid to run as by itself. `./scripts/up.sh` still works
and additionally finds a free port for you.

That builds and starts both containers and prints the URL and the port. **Use the
port it prints.** Something unrelated on this machine already occupies 8000, so
`up.sh` picks the first free port instead and records it in `.env` so it stays
the same on every restart. When this was last run it chose **8002**:

```
Veillee is on http://127.0.0.1:8002
```

**It is published, over HTTPS, on your tailnet.** Give him this address:

```
https://<machine>.<tailnet>.ts.net
```

No port, no IP, a real Let's Encrypt certificate, and nothing further to run.
`tailscale serve` is already configured to proxy it to `127.0.0.1:8002`, and the
app is bound to loopback only, so that address is the single way in.

**It is not public.** The serve configuration has no `AllowFunnel` key, which is
the setting that would expose it to the internet. Verified after applying it.

**Recording works on this address and would not have on a plain-http one.**
Browsers withhold the microphone from any non-localhost page served over `http`.
Checked on the live site: `isSecureContext` is true, `getUserMedia` is available,
and the record button renders.

If you ever need to reconfigure it, the equivalent command on the host is:

```bash
tailscale serve --bg 8002        # never `tailscale funnel`
```

**Correction on `<your-proxy-hostname>`.** It is *not* exposed to the internet, contrary
to what the `Public` label in the proxy UI suggests. Public DNS (checked against
1.1.1.1 and 8.8.8.8) returns `<proxy-tailnet-ip>` and `<tailnet-ipv6>` —
CGNAT and ULA addresses, neither routable from the internet. "Public" there means
a publicly-signed certificate, not public reachability. Anyone can look the name
up; only a device on your tailnet can connect to it. Both addresses below are
equivalent in reach.

**Never run `tailscale funnel`** — that publishes to the public internet.
`serve` keeps it inside your tailnet, which is this app's entire security
boundary. The same goes for any reverse proxy: this app has **no authentication
at all** unless you set `VEILLEE_PASSCODE`, so a public hostname in front of it
means anyone who finds the name can read his answers and overwrite them.

It is already running as you read this, with an empty archive and the demo
under `data/demo/`.

There is no login, no API key, and no setup wizard. He opens the link and writes.

**`tailscale serve` must be run on the host, in your own terminal.** The session
that built this ran inside a container with no `tailscale` CLI and no systemd,
so it could not run that command for you — which is why the site was published
by binding the tailnet address directly instead.

**Still only reachable from your tailnet.** `VEILLEE_BIND_HOST` in `.env` is set
to `<tailnet-ip>`, which is a tailnet-only interface — not the LAN, and not the
internet. Set it back to `127.0.0.1` to return to loopback-only. A test asserts
the bind host always defaults to loopback and can never become `0.0.0.0`, which
is the setting that *would* expose him.

**This machine has no Docker.** It has podman 5.8.4 with a working Compose
provider, and `up.sh` detects whichever runtime is present. `compose.yaml` is
plain Compose spec, so it will run unmodified on a Docker host too.

---

### He has to be on your tailnet

There is no login. He opens the link and writes — that is the whole design. But
both addresses resolve only to tailnet addresses, so **his device must be signed
in to your tailnet or it cannot reach the site at all**. Nothing in the device
list looks like his iPad yet.

Give him access by one of:

- **Install Tailscale on his iPad** and sign it in to your tailnet. Best option:
  nothing to remember, and it is how the security model is meant to work.
- **Share a device** with his Apple ID from the Tailscale admin console, if you
  do not want him in the tailnet proper.
- If neither is workable, tell me and I will set up a genuinely internet-facing
  route with `VEILLEE_PASSCODE` on and an unauthenticated request verified to be
  refused before it goes live. That is a real change of security model, so I will
  not do it without you asking.

## 2. Is it working?

```bash
make morning-check
```

Thirty seconds. It starts the stack if it is down, checks `/healthz`, writes a
real answer and reads it back, restores the question to how it was, and prints
`PASS` or the one specific thing that is wrong plus what to do about it.

The probe writes to q120 and puts back whatever was there. The restore runs from
a shell `trap`, so it happens on the failure paths too — this was tested by
forcing the failure branch and confirming the original answer came back. And
whatever happens, the previous version is also in `data/.revisions/q120/`.

The fuller gate, if you have ten minutes and want to be certain:

```bash
make verify        # lint, 189 unit/integration tests, 64 browser tests, then the container smoke test
```

`make verify` passing is the definition of done. It was run twice in a row from
a fresh `git clone`, and `./scripts/up.sh`, `make backup` and `make morning-check`
were each run by hand against the real containers — see BUILD_LOG.md.

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
Crepe stylesheet pulls in). `static/vendor/editor.js` is 2.5 MB and committed.
Typing `## ` or `- ` renders as a real heading or bullet as he types; the file on
disk stays plain markdown. If the bundle ever fails to load, the page falls back
to a plain textarea and **autosave works identically** — that path is tested by
blocking the bundle request outright.

**The toolbar is Veillee's own, not Milkdown's.** Crepe ships a toolbar that only
appears once you have already selected text, and in practice it never became
visible at all. That is no use to someone who does not know it is there, so the
page renders its own row of five always-visible buttons — bold, italic, heading,
bullet list, quote, and nothing more — each a 48px touch target. Every button has
a test asserting the **markdown it writes to disk**, because a button that styles
the screen and writes nothing is worse than no button. Heading toggles back to
plain text on a second press, so it is never a one-way door.

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

**htmx is vendored but not loaded.** The stack named htmx and Alpine. Alpine
does real work — it drives the recorder. htmx never found an honest job: every
page here is a full page, one click from home, with no partial-HTML swap
anywhere. Loading it anyway would have put 51 KB of dead JavaScript on every
page he opens on an iPad over Tailscale. The file stays vendored in
`static/vendor/` for phase two; the `<script>` tag is gone.

**The passcode is off.** `VEILLEE_PASSCODE` in `.env` turns it on; the cookie
then lasts five years so he is never asked twice on a device.

**The port is chosen, not assumed.** 8000 is taken on this host by something
else, so `up.sh` finds a free port, writes it to `.env`, and reuses it forever
after so a bookmarked URL keeps working.

**Compose variables live in `.env`, not your shell.** `podman compose` re-runs
its external Compose provider with a sanitised environment, so exported shell
variables are silently ignored. Everything that needs to reach a container is
written to `.env` instead. If you set something by hand, put it there.

---

## 3b. Publishing the image

The image is the easy way to move hosts: the new machine pulls it instead of
building, and nothing but `compose.registry.yaml` and `data/` needs to travel.

**Where:** GitHub Container Registry, `ghcr.io`. You are already signed in to
GitHub as `bearyjd`, it is free for both public and private images, and it has
none of Docker Hub's pull rate limits. `.github/workflows/publish.yml` builds and
pushes on every push to `main` and on any `v*` tag, using the built-in
`GITHUB_TOKEN` — there is no secret to configure.

```bash
gh repo create veillee --private --source=. --remote=origin --push
```

**Make the repository private, or scrub these files first.** The *image* is
clean — checked: no `data/`, no `.env`, no tailnet identifiers anywhere in it.
But `HANDOFF.md` and `BUILD_LOG.md` name `<machine>.<tailnet>.ts.net`,
`<your-proxy-hostname>`, `<tailnet-ip>` and `<proxy-tailnet-ip>`. A public repository would
publish your tailnet topology along with the code.

The combination I would use: **private repository, public package.** The source
keeps your notes to itself; the image needs no login to pull, so a new host can
`docker compose -f compose.registry.yaml up -d` with nothing configured. Set the
package to public once in the GitHub UI, under the package's settings.

If you would rather not use a registry at all, there are two other ways:

```bash
make relocate                    # one tarball: code + archive + compose
podman save veillee:latest | gzip > veillee.tar.gz   # just the image, 2.1 GB
```

**On the new host:**

```bash
docker compose -f compose.registry.yaml up -d
docker compose -f compose.registry.yaml exec app veillee reindex
```

The image is 2.1 GB, most of it the baked-in whisper model (464 MB) and the
Python environment (456 MB). Setting `--build-arg WHISPER_MODEL=tiny` makes it
much smaller at the cost of worse transcripts.

---

## 4. What is not built

**Nothing from the required scope was skipped.** All ten phases are done and
gated. For completeness, the things deliberately left out:

- Photographs, family read-only access, and a printable book layout. These were
  named as phase two. Seams are clean and nothing is stubbed — there is no
  placeholder UI, no handler returning fake data, and no commented-out test.
- No accounts, analytics, telemetry, or public deployment, by design.
- The remote transcription backend is implemented but **has no test of any kind**
  and has never been run against a live endpoint. Treat it as unverified code.
  Local is the default and is what the smoke test exercises.
- `data/` auto-commits but never pushes. Setting up a remote is a decision about
  where his private words travel, and it is yours to make.

### What is claimed here but not covered by a test

Every gap that used to be listed here has since been closed with a real test.
Two of them were closed by fixing a defect the new test found:

- `data/` git auto-commit is now exercised by twelve tests, including one over
  real HTTP. Writing them found that `autocommit()` could **raise** when `data/`
  was unwritable, despite its whole contract being that it never raises into a
  request. `mkdir` sat outside the `try`.
- "Autosave on blur" turned out to be **only half implemented**: the rich editor
  bound `window`'s blur, which fires when the whole browser loses focus, not
  when he clicks from the text onto the page. Now bound to `focusout`.
- Fixing that surfaced a third: Tab indents lists inside the editor rather than
  moving on, which made the writing box a **keyboard trap** (WCAG 2.1.2) that
  axe-core cannot detect. Escape now leaves the box, and a hint under it says so
  whenever it has focus.

The remaining honest limits:

| Claim | Status |
|---|---|
| The remote transcription backend | **No test, never run.** Unverified code. Local is the default and is what everything else exercises. |
| `up.sh` starting real containers | The port choice, `.env` writing and refusal to clobber are tested against a stub runtime. The container start itself is covered by `scripts/smoke.sh`. |

---|---|
| `data/` auto-commits on save | **No test.** Both fixtures set `VEILLEE_GIT_AUTOCOMMIT=0`, so no test ever exercises it. Verified by hand over HTTP; `git -C data log` showed the commits. |
| `data/` is never auto-pushed | **No test.** True by inspection — no push call exists anywhere in the code. |
| The passcode flow | **No test** beyond an accessibility scan of `/enter`. Nothing checks that a wrong passcode is rejected, that a right one sets the cookie, or that the cookie persists. It is off by default. |
| Transcripts are never shown to him | **No test.** Enforced by the routes, but nothing asserts a transcript's words are absent from his pages. |
| The machine transcript is preserved when you edit it | **No test.** The code writes a `.machine.md` beside it and a history entry; nothing verifies it happens. |
| The worker loop itself | **No unit test.** The queue primitives are tested and the smoke test proves a real transcript appears end to end, but `Worker.run_once` and its failure handling are not directly tested. |
| Autosave on blur | **No test.** The five-second interval and the beacon on navigation are both tested; the blur handler specifically is not. |
| `up.sh`, `backup.sh`, `morning-check.sh` | **No automated coverage.** `make verify` does not touch them. Each was run by hand against the live containers, and the morning-check failure path was tested by forcing it. |
| The app binds 127.0.0.1 only | **No test.** It is the default in `cli.py` and compose publishes to `127.0.0.1:`. Check it with `ss -ltn`. |

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
