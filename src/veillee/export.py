"""`veillee export` — a dated folder that outlives this software.

Three things go in it:

* one markdown book, ordered by chapter, that reads straight through;
* a self-contained static HTML site with playable audio that opens from a USB
  stick by double-clicking index.html, with no server and no network;
* manifest.json, with a SHA-256 for every file, so the copy can be checked.
"""

from __future__ import annotations

import html
import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import repository
from .config import Settings
from .db import closing_connection
from .questions import QuestionBank, load_bank
from .storage.answers import atomic_write
from .storage.audio import sha256_file
from .storage.paths import utc_now_iso

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportResult:
    directory: Path
    answers: int
    recordings: int
    files: int


def _markdown_book(connection: sqlite3.Connection, bank: QuestionBank) -> str:
    """The whole thing as one readable document, in chapter order."""
    answers = {a.question_id: a for a in repository.all_written_answers(connection)}
    lines = [
        "# Veillée",
        "",
        f"_An oral history. Exported {datetime.now(UTC):%d %B %Y}._",
        "",
    ]
    for chapter in bank.chapters:
        chapter_questions = [q for q in bank.in_chapter(chapter.slug) if q.id in answers]
        if not chapter_questions:
            continue
        lines += ["", f"## {chapter.title}", ""]
        for question in chapter_questions:
            answer = answers[question.id]
            lines += [f"### {question.text}", "", answer.body, ""]
    return "\n".join(lines) + "\n"


def _site_page(
    connection: sqlite3.Connection, bank: QuestionBank, recordings_by_question: dict[str, list]
) -> str:
    """One self-contained HTML file. No CDN, no fonts, no network of any kind."""
    answers = {a.question_id: a for a in repository.all_written_answers(connection)}
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Veillée</title><style>",
        "body{font-family:Georgia,'Times New Roman',serif;font-size:19px;line-height:1.7;",
        "color:#241f1a;background:#faf6ef;margin:0;padding:2rem 1.25rem 5rem}",
        "main{max-width:44rem;margin:0 auto}h1{font-size:2.2rem}h2{margin-top:3rem;",
        "border-bottom:1px solid #ddd2c2;padding-bottom:.5rem}",
        "h3{margin-top:2.5rem;font-size:1.3rem}",
        "audio{width:100%;margin:1rem 0}nav a{display:block;padding:.4rem 0;color:#7a4a2b}",
        "p{white-space:pre-wrap}.note{color:#6b6055;font-size:.95rem}",
        "</style></head><body><main>",
        "<h1>Veillée</h1>",
        f'<p class="note">Exported {html.escape(datetime.now(UTC).strftime("%d %B %Y"))}. '
        "Everything here opens without an internet connection.</p>",
        "<nav>",
    ]
    included = [
        chapter
        for chapter in bank.chapters
        if any(
            q.id in answers or recordings_by_question.get(q.id)
            for q in bank.in_chapter(chapter.slug)
        )
    ]
    for chapter in included:
        parts.append(f'<a href="#{html.escape(chapter.slug)}">{html.escape(chapter.title)}</a>')
    parts.append("</nav>")

    for chapter in included:
        parts.append(f'<h2 id="{html.escape(chapter.slug)}">{html.escape(chapter.title)}</h2>')
        for question in bank.in_chapter(chapter.slug):
            answer = answers.get(question.id)
            clips = recordings_by_question.get(question.id, [])
            if not answer and not clips:
                continue
            parts.append(f"<h3>{html.escape(question.text)}</h3>")
            if answer:
                parts.append(f"<p>{html.escape(answer.body)}</p>")
            for clip in clips:
                name = html.escape(f"audio/{clip.recording_id}.opus")
                parts.append(f'<audio controls preload="none" src="{name}"></audio>')
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def _write_manifest(directory: Path) -> int:
    """Checksum every file in the export, so a copy can be verified later."""
    entries = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        entries.append(
            {
                "path": str(path.relative_to(directory)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "exported": utc_now_iso(),
        "file_count": len(entries),
        "files": entries,
    }
    atomic_write(directory / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return len(entries)


def verify_manifest(directory: Path) -> list[str]:
    """Re-checksum an export against its own manifest. Empty list means sound."""
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        return [f"no manifest in {directory}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = []
    for entry in manifest.get("files", []):
        path = directory / str(entry["path"])
        if not path.exists():
            problems.append(f"missing: {entry['path']}")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"checksum mismatch: {entry['path']}")
    return problems


def export(settings: Settings, destination_root: Path | None = None) -> ExportResult:
    """Write a dated export folder. Never modifies anything under data/."""
    root = destination_root or Path("exports")
    directory = root / f"veillee-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    (directory / "audio").mkdir(parents=True, exist_ok=True)

    bank = load_bank(settings.questions_dir, settings.custom_questions_path)
    with closing_connection(settings.db_path) as connection:
        written = repository.all_written_answers(connection)
        recordings = repository.all_recordings(connection)

        by_question: dict[str, list] = {}
        for recording in recordings:
            source = Path(recording.opus_path)
            if source.exists():
                shutil.copy2(source, directory / "audio" / f"{recording.recording_id}.opus")
                by_question.setdefault(recording.question_id, []).append(recording)

        atomic_write(directory / "veillee-book.md", _markdown_book(connection, bank))
        atomic_write(directory / "index.html", _site_page(connection, bank, by_question))

    # The archive itself, copied verbatim: markdown, sidecars, transcripts.
    if settings.answers_dir.is_dir():
        shutil.copytree(settings.answers_dir, directory / "answers", dirs_exist_ok=True)
    if settings.transcripts_dir.is_dir() and any(settings.transcripts_dir.rglob("*.md")):
        shutil.copytree(settings.transcripts_dir, directory / "transcripts", dirs_exist_ok=True)

    file_count = _write_manifest(directory)
    logger.info("exported %d files to %s", file_count, directory)
    return ExportResult(
        directory=directory,
        answers=len(written),
        recordings=len(recordings),
        files=file_count,
    )
