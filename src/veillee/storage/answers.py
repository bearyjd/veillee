"""Reading and writing answers.

Two rules govern every function here:

1. Nothing is ever lost. Before a file is overwritten, its current contents are
   copied into `data/.revisions/`. Deletions move files into `data/.trash/`;
   we never call unlink on anything a person wrote.
2. Writes are atomic. We write a sibling temp file and rename it into place, so
   a crash mid-write leaves the previous version intact rather than a truncated one.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..config import Settings
from ..models import STATUS_ANSWERED, VALID_STATUSES, Answer, Question
from . import frontmatter
from .paths import answer_relpath, count_words, revision_stamp, utc_now_iso

FRONTMATTER_KEYS = (
    "question_id",
    "question_text",
    "chapter",
    "chapter_order",
    "created",
    "updated",
    "word_count",
    "status",
    "custom",
)


def atomic_write(path: Path, text: str) -> None:
    """Write text to path atomically, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def answer_path(settings: Settings, question: Question) -> Path:
    """Absolute path of the answer file for a question."""
    relative = answer_relpath(
        question.chapter_order, question.chapter_slug, question.id, question.text
    )
    return settings.answers_dir / relative


def save_revision(settings: Settings, question_id: str, path: Path) -> Path | None:
    """Copy the current on-disk answer into .revisions/ before it is overwritten."""
    if not path.exists():
        return None
    destination = settings.revisions_dir / question_id / f"{revision_stamp()}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def list_revisions(settings: Settings, question_id: str) -> list[Path]:
    """All stored revisions for a question, oldest first."""
    directory = settings.revisions_dir / question_id
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"))


def move_to_trash(settings: Settings, path: Path) -> Path | None:
    """Move a file into data/.trash/, preserving its relative layout."""
    if not path.exists():
        return None
    try:
        relative = path.relative_to(settings.data_dir)
    except ValueError:
        relative = Path(path.name)
    destination = settings.trash_dir / revision_stamp() / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(destination))
    return destination


def read_answer(path: Path) -> Answer:
    """Load an answer from disk. Raises FrontmatterError on a malformed file."""
    text = path.read_text(encoding="utf-8")
    metadata, body = frontmatter.loads(text)
    missing = {"question_id", "question_text"} - set(metadata)
    if missing:
        raise frontmatter.FrontmatterError(
            f"{path}: frontmatter is missing required keys: {sorted(missing)}"
        )
    status = str(metadata.get("status", STATUS_ANSWERED))
    if status not in VALID_STATUSES:
        status = STATUS_ANSWERED
    return Answer(
        question_id=str(metadata["question_id"]),
        question_text=str(metadata["question_text"]),
        chapter_slug=str(metadata.get("chapter", "")),
        chapter_order=int(metadata.get("chapter_order", 0)),
        body=body,
        status=status,
        created=str(metadata.get("created", "")),
        updated=str(metadata.get("updated", "")),
        word_count=int(metadata.get("word_count", count_words(body))),
        custom=bool(metadata.get("custom", False)),
        path=path,
    )


def iter_answer_files(settings: Settings) -> Iterator[Path]:
    """Every answer file on disk, in a stable order."""
    if not settings.answers_dir.is_dir():
        return
    yield from sorted(settings.answers_dir.rglob("*.md"))


def serialise(answer: Answer) -> str:
    """Render an Answer back into its on-disk form."""
    metadata = {
        "question_id": answer.question_id,
        "question_text": answer.question_text,
        "chapter": answer.chapter_slug,
        "chapter_order": answer.chapter_order,
        "created": answer.created,
        "updated": answer.updated,
        "word_count": answer.word_count,
        "status": answer.status,
        "custom": answer.custom,
    }
    return frontmatter.dumps(metadata, answer.body)


def write_answer(
    settings: Settings,
    question: Question,
    body: str,
    *,
    status: str = STATUS_ANSWERED,
) -> Answer:
    """Persist an answer, keeping a revision of whatever was there before.

    Returns the Answer as it now exists on disk.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown answer status: {status!r}")

    path = answer_path(settings, question)
    save_revision(settings, question.id, path)

    now = utc_now_iso()
    created = now
    if path.exists():
        try:
            created = read_answer(path).created or now
        except frontmatter.FrontmatterError:
            created = now

    answer = Answer(
        question_id=question.id,
        question_text=question.text,
        chapter_slug=question.chapter_slug,
        chapter_order=question.chapter_order,
        body=body.strip("\n"),
        status=status,
        created=created,
        updated=now,
        word_count=count_words(body),
        custom=question.custom,
        path=path,
    )
    atomic_write(path, serialise(answer))
    return answer


def load_answer(settings: Settings, question: Question) -> Answer | None:
    """Read a question's answer if one exists on disk."""
    path = answer_path(settings, question)
    if not path.exists():
        return None
    return read_answer(path)
