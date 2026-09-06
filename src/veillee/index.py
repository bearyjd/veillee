"""Rebuilding the SQLite index from `data/` alone.

If the database is deleted, this puts it back. Nothing here reads anything but
the filesystem, which is what makes that promise true rather than aspirational.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from .config import Settings
from .db import closing_connection, initialise, set_meta
from .models import Answer, Recording
from .queue import STATE_DONE, enqueue
from .storage import audio as audio_storage
from .storage import photos as photo_storage
from .storage.answers import iter_answer_files, read_answer
from .storage.frontmatter import FrontmatterError
from .storage.paths import utc_now_iso

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReindexReport:
    answers: int
    recordings: int
    photographs: int
    queued: int
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def upsert_answer(connection: sqlite3.Connection, answer: Answer) -> None:
    """Write one answer into the index."""
    connection.execute(
        "INSERT INTO answers (question_id, question_text, chapter_slug, chapter_order, body, "
        "status, created, updated, word_count, custom, path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(question_id) DO UPDATE SET "
        "question_text=excluded.question_text, chapter_slug=excluded.chapter_slug, "
        "chapter_order=excluded.chapter_order, body=excluded.body, status=excluded.status, "
        "created=excluded.created, updated=excluded.updated, word_count=excluded.word_count, "
        "custom=excluded.custom, path=excluded.path",
        (
            answer.question_id,
            answer.question_text,
            answer.chapter_slug,
            answer.chapter_order,
            answer.body,
            answer.status,
            answer.created,
            answer.updated,
            answer.word_count,
            int(answer.custom),
            str(answer.path),
        ),
    )


def upsert_recording(connection: sqlite3.Connection, recording: Recording) -> None:
    """Write one recording into the index."""
    connection.execute(
        "INSERT INTO recordings (recording_id, question_id, created, duration_seconds, device, "
        "original_path, flac_path, opus_path, sidecar_path, sha256_original, sha256_flac, "
        "sha256_opus, source, transcript_path, transcript_reviewed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(recording_id) DO UPDATE SET "
        "question_id=excluded.question_id, created=excluded.created, "
        "duration_seconds=excluded.duration_seconds, device=excluded.device, "
        "original_path=excluded.original_path, flac_path=excluded.flac_path, "
        "opus_path=excluded.opus_path, sidecar_path=excluded.sidecar_path, "
        "sha256_original=excluded.sha256_original, sha256_flac=excluded.sha256_flac, "
        "sha256_opus=excluded.sha256_opus, source=excluded.source, "
        "transcript_path=excluded.transcript_path, "
        "transcript_reviewed=excluded.transcript_reviewed",
        (
            recording.recording_id,
            recording.question_id,
            recording.created,
            recording.duration_seconds,
            recording.device,
            recording.original_path,
            recording.flac_path,
            recording.opus_path,
            recording.sidecar_path,
            recording.sha256_original,
            recording.sha256_flac,
            recording.sha256_opus,
            recording.source,
            recording.transcript_path,
            int(recording.transcript_reviewed),
        ),
    )


def upsert_photograph(connection: sqlite3.Connection, photo: photo_storage.Photograph) -> None:
    """Write one photograph into the index."""
    connection.execute(
        "INSERT INTO photographs (photo_id, question_id, created, caption, original_path, "
        "view_path, sidecar_path, sha256_original, sha256_view, width, height) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(photo_id) DO UPDATE SET "
        "question_id=excluded.question_id, created=excluded.created, caption=excluded.caption, "
        "original_path=excluded.original_path, view_path=excluded.view_path, "
        "sidecar_path=excluded.sidecar_path, sha256_original=excluded.sha256_original, "
        "sha256_view=excluded.sha256_view, width=excluded.width, height=excluded.height",
        (
            photo.photo_id,
            photo.question_id,
            photo.created,
            photo.caption,
            photo.original_path,
            photo.view_path,
            photo.sidecar_path,
            photo.sha256_original,
            photo.sha256_view,
            photo.width,
            photo.height,
        ),
    )


def _load_photographs(settings: Settings, connection: sqlite3.Connection) -> tuple[int, list[str]]:
    count, problems = 0, []
    for sidecar in photo_storage.iter_sidecars(settings):
        try:
            upsert_photograph(connection, photo_storage.read_sidecar(sidecar))
            count += 1
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"could not index {sidecar}: {exc}")
            logger.error("could not index %s: %s", sidecar, exc)
    return count, problems


def _load_answers(settings: Settings, connection: sqlite3.Connection) -> tuple[int, list[str]]:
    count, problems = 0, []
    for path in iter_answer_files(settings):
        try:
            upsert_answer(connection, read_answer(path))
            count += 1
        except (FrontmatterError, OSError, ValueError) as exc:
            # One unreadable file must not stop the rebuild; report it instead.
            problems.append(f"could not index {path}: {exc}")
            logger.error("could not index %s: %s", path, exc)
    return count, problems


def _load_recordings(
    settings: Settings, connection: sqlite3.Connection
) -> tuple[int, int, list[str]]:
    count, queued, problems = 0, 0, []
    for sidecar in audio_storage.iter_sidecars(settings):
        try:
            recording = audio_storage.read_sidecar(sidecar)
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"could not index {sidecar}: {exc}")
            logger.error("could not index %s: %s", sidecar, exc)
            continue
        upsert_recording(connection, recording)
        count += 1
        if recording.transcript_path:
            connection.execute(
                "INSERT INTO transcription_queue (recording_id, state, attempts, "
                "next_attempt_at, created, updated) VALUES (?, ?, 0, ?, ?, ?) "
                "ON CONFLICT(recording_id) DO NOTHING",
                (recording.recording_id, STATE_DONE, utc_now_iso(), utc_now_iso(), utc_now_iso()),
            )
        elif enqueue(connection, recording.recording_id):
            queued += 1
    return count, queued, problems


def reindex(settings: Settings) -> ReindexReport:
    """Rebuild the entire index from disk. Safe to run at any time."""
    settings.ensure_dirs()
    initialise(settings.db_path)
    with closing_connection(settings.db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            # The queue is intentionally preserved: its rows are rebuilt below
            # from what is and is not present on disk.
            connection.execute("DELETE FROM answers")
            connection.execute("DELETE FROM recordings")
            connection.execute("DELETE FROM photographs")
            answers, answer_problems = _load_answers(settings, connection)
            recordings, queued, recording_problems = _load_recordings(settings, connection)
            photographs, photo_problems = _load_photographs(settings, connection)
            set_meta(connection, "last_reindex", utc_now_iso())
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    report = ReindexReport(
        answers=answers,
        recordings=recordings,
        photographs=photographs,
        queued=queued,
        problems=tuple(answer_problems + recording_problems + photo_problems),
    )
    logger.info(
        "reindex complete: %d answers, %d recordings, %d photographs, %d queued, %d problems",
        report.answers,
        report.recordings,
        report.photographs,
        report.queued,
        len(report.problems),
    )
    return report
