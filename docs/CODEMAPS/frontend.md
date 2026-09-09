<!-- Generated: 2026-09-09 | Files scanned: 101 | Token estimate: ~700 -->

# Frontend

**No framework, no build step, no bundler.** Server-rendered Jinja2 plus three
hand-written JS files and vendored libraries. Deliberate: the archive has to
outlive its toolchain, and a build step is a thing that rots.

## Template tree

```
base.html                 viewport meta, css, skip-link
├── home.html             the next unanswered question
├── chapters.html         14 chapters + his own
├── chapter.html          questions within one
├── question.html         THE page: editor + recorder + photos (278 lines)
├── answers.html          everything answered
├── book.html             print layout, book.css, chapter per page
├── read_only.html        family view; no controls, no transcripts
├── enter.html            passcode
├── admin.html            transcript review queue
├── admin_transcript.html machine draft vs correction
└── 404.html
```

## JavaScript (`static/js/`)

| File | Role |
|---|---|
| `recorder.js` | MediaRecorder, chunked upload, screen wake lock, Path-B file upload |
| `editor-boot.js` | boots Milkdown; falls back to a plain textarea |
| `photos.js` | Alpine component: upload, caption, delete-with-confirm |

Vendored, not fetched: `static/vendor/` holds Milkdown (`editor.js`,
`editor.css`), Alpine (`alpine.min.js`) and htmx (`htmx.min.js`). Verified: no
CDN reference appears in any template. It must work with no internet.

## recorder.js contract

```
_pickFormat()      webm/opus -> webm -> mp4 -> ogg, by isTypeSupported
start()            getUserMedia, MediaRecorder(CHUNK_MS), wake lock
_onChunk()         POST each chunk while recording continues
_holdScreenAwake() navigator.wakeLock; fire-and-forget, never awaited
_watchVisibility() re-acquires on return-to-visible (locks drop when hidden)
uploadFile()       Path B: phone's own recorder, identical server pipeline
```

Degrades on purpose: no MediaRecorder / denied mic / insecure origin all fall
through to the file-upload path rather than failing.

## CSS (`static/css/veillee.css`, 547 lines)

Design tokens on `:root`: `--body-size: 20px`, `--touch: 56px`,
`--measure: 34rem`, serif body.

Two breakpoints only:
- `@media (max-width: 32rem)` - narrow-screen layout
- `@media (pointer: coarse), (max-width: 32rem)` - **touch targets**, keyed to
  the hand rather than the window so they survive rotation. A landscape phone
  is 851px; a width breakpoint alone silently reverted every target.
- `@media (max-height: 30rem) and (orientation: landscape)` - tighter spacing

`.editor-frame .milkdown .ProseMirror` overrides Milkdown's own
`padding: 60px 120px` (which loads after ours at equal specificity) with a
`clamp()` that scales. Without it the typing column is 119px on a 393px phone.

## Accessibility posture

20px body floor, 56px targets, focus-visible outlines, skip-link, pinch-zoom
left enabled. Tested by `tests/e2e/test_a11y.py` (axe) and
`test_phone.py` (Android viewports, touch emulation).
