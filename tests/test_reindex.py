"""The promise: delete the database, and `veillee reindex` puts it back exactly.

If these tests pass, the filesystem really is the source of truth. If they fail,
every other claim in this project is decoration.
"""

from __future__ import annotations

import sqlite3

from veillee.config import Settings
from veillee.db import closing_connection
from veillee.index import reindex
from veillee.ingest import ingest_recording
from veillee.models import STATUS_LATER
from veillee.questions import QuestionBank
from veillee.storage.answers import write_answer


def _snapshot(settings: Settings, table: str) -> list[tuple]:
    with closing_connection(settings.db_path) as connection:
        connection.row_factory = sqlite3.Row
        order = "question_id" if table == "answers" else "recording_id"
        return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}")]


def _destroy_index(settings: Settings) -> None:
    """Delete the database as completely as a person with rm would."""
    for suffix in ("", "-wal", "-shm"):
        candidate = settings.db_path.with_name(settings.db_path.name + suffix)
        candidate.unlink(missing_ok=True)
    assert not settings.db_path.exists()


class TestReindexFidelity:
    def test_answers_survive_the_database_being_deleted(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        for question in bank.questions[:12]:
            write_answer(settings, question, f"An answer to {question.id}.\n\nSecond paragraph.")
        reindex(settings)
        before = _snapshot(settings, "answers")
        assert len(before) == 12

        _destroy_index(settings)
        report = reindex(settings)

        assert report.ok
        assert report.answers == 12
        assert _snapshot(settings, "answers") == before

    def test_recordings_survive_too(
        self, settings: Settings, bank: QuestionBank, sample_m4a
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        with closing_connection(settings.db_path) as connection:
            ingest_recording(
                settings,
                connection,
                question_id=question.id,
                source_path=_copy(sample_m4a, settings),
                original_suffix=".m4a",
                device="test",
            )
        reindex(settings)
        before = _snapshot(settings, "recordings")
        assert len(before) == 1

        _destroy_index(settings)
        report = reindex(settings)

        assert report.ok
        assert report.recordings == 1
        assert _snapshot(settings, "recordings") == before

    def test_status_and_word_count_come_back(self, settings: Settings, bank: QuestionBank) -> None:
        question = bank.by_id("q020")
        assert question is not None
        write_answer(settings, question, "one two three four five", status=STATUS_LATER)
        _destroy_index(settings)
        reindex(settings)

        with closing_connection(settings.db_path) as connection:
            row = connection.execute(
                "SELECT status, word_count FROM answers WHERE question_id = 'q020'"
            ).fetchone()
        assert row["status"] == STATUS_LATER
        assert row["word_count"] == 5

    def test_a_corrupt_file_is_reported_without_stopping_the_rebuild(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        for question in bank.questions[:4]:
            write_answer(settings, question, "Fine.")
        broken = settings.answers_dir / "01-ancestors-and-the-crossing" / "999-broken.md"
        broken.write_text("this is not a frontmatter document", encoding="utf-8")

        report = reindex(settings)

        assert report.answers == 4
        assert len(report.problems) == 1
        assert "999-broken.md" in report.problems[0]

    def test_reindex_is_idempotent(self, settings: Settings, bank: QuestionBank) -> None:
        for question in bank.questions[:5]:
            write_answer(settings, question, "Body.")
        reindex(settings)
        first = _snapshot(settings, "answers")
        reindex(settings)
        assert _snapshot(settings, "answers") == first

    def test_empty_archive_rebuilds_to_an_empty_index(self, settings: Settings) -> None:
        report = reindex(settings)
        assert report.ok
        assert report.answers == 0


def _copy(source, settings: Settings):
    """Ingest moves its input, so give it a copy rather than the fixture itself."""
    import shutil

    destination = settings.data_dir / f"incoming{source.suffix}"
    shutil.copy2(source, destination)
    return destination
