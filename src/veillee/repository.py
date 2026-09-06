"""Read queries against the index, shaped the way the pages need them.

Everything returned here is derived from files on disk; the index is only how
we avoid walking the whole archive on every request.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import STATUS_ANSWERED, STATUS_LATER, Answer, Question, Recording
from .questions import QuestionBank
from .storage.photos import Photograph


@dataclass(frozen=True)
class Progress:
    answered: int
    total: int
    words: int
    recordings: int


@dataclass(frozen=True)
class ChapterSummary:
    order: int
    slug: str
    title: str
    total: int
    answered: int


def _row_to_answer(row: sqlite3.Row) -> Answer:
    return Answer(
        question_id=str(row["question_id"]),
        question_text=str(row["question_text"]),
        chapter_slug=str(row["chapter_slug"]),
        chapter_order=int(row["chapter_order"]),
        body=str(row["body"]),
        status=str(row["status"]),
        created=str(row["created"]),
        updated=str(row["updated"]),
        word_count=int(row["word_count"]),
        custom=bool(row["custom"]),
        path=Path(str(row["path"])),
    )


def _row_to_recording(row: sqlite3.Row) -> Recording:
    return Recording(
        recording_id=str(row["recording_id"]),
        question_id=str(row["question_id"]),
        created=str(row["created"]),
        duration_seconds=float(row["duration_seconds"]),
        device=str(row["device"]),
        original_path=str(row["original_path"]),
        flac_path=str(row["flac_path"]),
        opus_path=str(row["opus_path"]),
        sidecar_path=str(row["sidecar_path"]),
        sha256_original=str(row["sha256_original"]),
        sha256_flac=str(row["sha256_flac"]),
        sha256_opus=str(row["sha256_opus"]),
        source=str(row["source"]),
        transcript_path=row["transcript_path"],
        transcript_reviewed=bool(row["transcript_reviewed"]),
    )


def get_answer(connection: sqlite3.Connection, question_id: str) -> Answer | None:
    row = connection.execute(
        "SELECT * FROM answers WHERE question_id = ?", (question_id,)
    ).fetchone()
    return _row_to_answer(row) if row else None


def answered_ids(connection: sqlite3.Connection) -> set[str]:
    """Ids of questions with actual written or recorded content."""
    rows = connection.execute(
        "SELECT question_id FROM answers WHERE status = ? AND TRIM(body) != '' "
        "UNION SELECT DISTINCT question_id FROM recordings",
        (STATUS_ANSWERED,),
    ).fetchall()
    return {str(row["question_id"]) for row in rows}


def marked_later_ids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT question_id FROM answers WHERE status = ?", (STATUS_LATER,)
    ).fetchall()
    return {str(row["question_id"]) for row in rows}


def progress(connection: sqlite3.Connection, bank: QuestionBank) -> Progress:
    """The warm count shown on the home page. Never a percentage."""
    answered = answered_ids(connection)
    words = connection.execute(
        "SELECT COALESCE(SUM(word_count), 0) AS n FROM answers WHERE status = ?",
        (STATUS_ANSWERED,),
    ).fetchone()["n"]
    recordings = connection.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"]
    return Progress(
        answered=len(answered),
        total=len(bank.questions),
        words=int(words),
        recordings=int(recordings),
    )


def chapter_summaries(connection: sqlite3.Connection, bank: QuestionBank) -> list[ChapterSummary]:
    """One row per chapter for the browse page."""
    answered = answered_ids(connection)
    summaries = []
    for chapter in bank.chapters:
        questions = bank.in_chapter(chapter.slug)
        summaries.append(
            ChapterSummary(
                order=chapter.order,
                slug=chapter.slug,
                title=chapter.title,
                total=len(questions),
                answered=sum(1 for q in questions if q.id in answered),
            )
        )
    return summaries


def unanswered(connection: sqlite3.Connection, bank: QuestionBank) -> list[Question]:
    """Questions with nothing written or recorded, skipped ones included."""
    answered = answered_ids(connection)
    return [q for q in bank.questions if q.id not in answered]


def random_unanswered(
    connection: sqlite3.Connection, bank: QuestionBank, *, seed: int | None = None
) -> Question | None:
    """A question he has not answered yet, chosen at random."""
    remaining = unanswered(connection, bank)
    if not remaining:
        return None
    chooser = random.Random(seed) if seed is not None else random
    return chooser.choice(remaining)


def continue_where_left_off(
    connection: sqlite3.Connection, bank: QuestionBank
) -> tuple[Question | None, str]:
    """The question to offer first, and why we are offering it."""
    # Anything the family has pinned comes before everything else, until he has
    # answered it. This is how someone asks him a particular question.
    answered = answered_ids(connection)
    for pinned in bank.questions:
        if pinned.pinned and pinned.id not in answered:
            return pinned, pinned.note or "A question from your family"

    later = connection.execute(
        "SELECT question_id FROM answers WHERE status = ? ORDER BY updated DESC LIMIT 1",
        (STATUS_LATER,),
    ).fetchone()
    if later:
        question = bank.by_id(str(later["question_id"]))
        if question:
            return question, "You said you would come back to this one"

    recent = connection.execute(
        "SELECT question_id FROM answers WHERE status = ? AND TRIM(body) != '' "
        "ORDER BY updated DESC LIMIT 1",
        (STATUS_ANSWERED,),
    ).fetchone()
    if recent:
        question = bank.by_id(str(recent["question_id"]))
        if question:
            return question, "The last one you were writing"

    remaining = unanswered(connection, bank)
    if remaining:
        return remaining[0], "Where to begin"
    return None, ""


def answers_for_chapter(connection: sqlite3.Connection, chapter_slug: str) -> dict[str, Answer]:
    rows = connection.execute(
        "SELECT * FROM answers WHERE chapter_slug = ?", (chapter_slug,)
    ).fetchall()
    return {str(row["question_id"]): _row_to_answer(row) for row in rows}


def all_written_answers(connection: sqlite3.Connection) -> list[Answer]:
    """Everything he has actually written, in chapter order."""
    rows = connection.execute(
        "SELECT * FROM answers WHERE status = ? AND TRIM(body) != '' "
        "ORDER BY chapter_order, question_id",
        (STATUS_ANSWERED,),
    ).fetchall()
    return [_row_to_answer(row) for row in rows]


def recordings_for(connection: sqlite3.Connection, question_id: str) -> list[Recording]:
    rows = connection.execute(
        "SELECT * FROM recordings WHERE question_id = ? ORDER BY created", (question_id,)
    ).fetchall()
    return [_row_to_recording(row) for row in rows]


def get_recording(connection: sqlite3.Connection, recording_id: str) -> Recording | None:
    row = connection.execute(
        "SELECT * FROM recordings WHERE recording_id = ?", (recording_id,)
    ).fetchone()
    return _row_to_recording(row) if row else None


def all_recordings(connection: sqlite3.Connection) -> list[Recording]:
    rows = connection.execute("SELECT * FROM recordings ORDER BY created DESC").fetchall()
    return [_row_to_recording(row) for row in rows]


def delete_recording_row(connection: sqlite3.Connection, recording_id: str) -> None:
    connection.execute("DELETE FROM recordings WHERE recording_id = ?", (recording_id,))
    connection.execute("DELETE FROM transcription_queue WHERE recording_id = ?", (recording_id,))


def _row_to_photograph(row: sqlite3.Row) -> Photograph:
    return Photograph(
        photo_id=str(row["photo_id"]),
        question_id=str(row["question_id"]),
        created=str(row["created"]),
        caption=str(row["caption"]),
        original_path=str(row["original_path"]),
        view_path=str(row["view_path"]),
        sidecar_path=str(row["sidecar_path"]),
        sha256_original=str(row["sha256_original"]),
        sha256_view=str(row["sha256_view"]),
        width=int(row["width"]),
        height=int(row["height"]),
    )


def photographs_for(connection: sqlite3.Connection, question_id: str) -> list[Photograph]:
    rows = connection.execute(
        "SELECT * FROM photographs WHERE question_id = ? ORDER BY created", (question_id,)
    ).fetchall()
    return [_row_to_photograph(row) for row in rows]


def get_photograph(connection: sqlite3.Connection, photo_id: str) -> Photograph | None:
    row = connection.execute("SELECT * FROM photographs WHERE photo_id = ?", (photo_id,)).fetchone()
    return _row_to_photograph(row) if row else None


def all_photographs(connection: sqlite3.Connection) -> list[Photograph]:
    rows = connection.execute("SELECT * FROM photographs ORDER BY question_id, created").fetchall()
    return [_row_to_photograph(row) for row in rows]


def delete_photograph_row(connection: sqlite3.Connection, photo_id: str) -> None:
    connection.execute("DELETE FROM photographs WHERE photo_id = ?", (photo_id,))


def photograph_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) AS n FROM photographs").fetchone()["n"])
