"""The worker loop.

The queue primitives are tested separately and the smoke test proves a real
transcript appears end to end. What is tested here is the loop in between: that
one bad recording cannot stop every other recording being transcribed.
"""

from __future__ import annotations

import shutil

import pytest

from veillee import queue as q
from veillee.config import Settings
from veillee.db import closing_connection
from veillee.ingest import ingest_recording
from veillee.storage import audio as audio_storage
from veillee.transcribe import Segment, Transcription, TranscriptionError
from veillee.worker import Worker

FAKE = Transcription(
    segments=(Segment(0.0, 2.0, "She baked on a Saturday night."),),
    language="en",
    backend="local",
    model="small",
)


@pytest.fixture
def recording_id(settings: Settings, sample_m4a) -> str:
    staged = settings.data_dir / "in.m4a"
    shutil.copy2(sample_m4a, staged)
    with closing_connection(settings.db_path) as connection:
        recording = ingest_recording(
            settings,
            connection,
            question_id="q012",
            source_path=staged,
            original_suffix=".m4a",
        )
    return recording.recording_id


def _patch_transcribe(monkeypatch: pytest.MonkeyPatch, result: object) -> list[str]:
    """Replace the model with something fast and predictable."""
    seen: list[str] = []

    def fake(_settings: Settings, audio_path: object) -> Transcription:
        seen.append(str(audio_path))
        if isinstance(result, Exception):
            raise result
        return result  # type: ignore[return-value]

    monkeypatch.setattr("veillee.worker.transcribe", fake)
    return seen


class TestASuccessfulJob:
    def test_it_writes_a_transcript_and_marks_the_job_done(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_transcribe(monkeypatch, FAKE)
        worker = Worker(settings)

        with closing_connection(settings.db_path) as connection:
            assert worker.run_once(connection) is True
            assert q.depth(connection)["done"] == 1

        paths = audio_storage.transcript_paths(settings, recording_id)
        assert paths["markdown"].exists()
        assert paths["json"].exists()
        body = paths["markdown"].read_text(encoding="utf-8")
        assert "Saturday night" in body
        assert "[00:00:00]" in body, "segment timestamps are missing"

    def test_the_transcript_is_marked_as_an_unreviewed_draft(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_transcribe(monkeypatch, FAKE)
        with closing_connection(settings.db_path) as connection:
            Worker(settings).run_once(connection)

        body = audio_storage.transcript_paths(settings, recording_id)["markdown"].read_text()
        assert "reviewed: false" in body
        assert "Not shown to him" in body

    def test_it_transcribes_the_archival_flac_not_the_lossy_copy(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _patch_transcribe(monkeypatch, FAKE)
        with closing_connection(settings.db_path) as connection:
            Worker(settings).run_once(connection)
        assert seen and seen[0].endswith(".flac")

    def test_the_index_learns_where_the_transcript_is(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_transcribe(monkeypatch, FAKE)
        with closing_connection(settings.db_path) as connection:
            Worker(settings).run_once(connection)
            row = connection.execute(
                "SELECT transcript_path FROM recordings WHERE recording_id = ?", (recording_id,)
            ).fetchone()
        assert row["transcript_path"].endswith(f"{recording_id}.md")

    def test_an_empty_queue_is_not_an_error(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            assert Worker(settings).run_once(connection) is False


class TestAFailingJob:
    def test_a_failure_is_recorded_and_the_loop_survives(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One bad recording must not stop every other one being transcribed."""
        _patch_transcribe(monkeypatch, TranscriptionError("the model would not load"))
        worker = Worker(settings)

        with closing_connection(settings.db_path) as connection:
            assert worker.run_once(connection) is True
            row = connection.execute(
                "SELECT state, attempts, last_error FROM transcription_queue"
            ).fetchone()

        assert row["attempts"] == 1
        assert row["state"] == q.STATE_PENDING
        assert "would not load" in row["last_error"]
        assert not audio_storage.transcript_paths(settings, recording_id)["markdown"].exists()

    def test_it_gives_up_after_the_configured_attempts(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_transcribe(monkeypatch, TranscriptionError("still broken"))
        worker = Worker(settings)

        with closing_connection(settings.db_path) as connection:
            for _ in range(settings.max_attempts):
                connection.execute(
                    "UPDATE transcription_queue SET next_attempt_at = '2000-01-01T00:00:00Z'"
                )
                worker.run_once(connection)
            assert q.depth(connection)["dead"] == 1

    def test_a_job_for_a_recording_that_is_not_indexed_fails_cleanly(
        self, settings: Settings
    ) -> None:
        with closing_connection(settings.db_path) as connection:
            q.enqueue(connection, "20260904-000000-q999")
            assert Worker(settings).run_once(connection) is True
            row = connection.execute(
                "SELECT state, attempts, last_error FROM transcription_queue"
            ).fetchone()
        assert row["attempts"] == 1
        assert "not in the index" in row["last_error"]

    def test_the_audio_is_never_touched_by_a_failure(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transcription problem must never put his recording at risk."""
        before = {
            path: path.read_bytes() for path in settings.audio_dir.rglob("*") if path.is_file()
        }
        _patch_transcribe(monkeypatch, TranscriptionError("boom"))
        with closing_connection(settings.db_path) as connection:
            Worker(settings).run_once(connection)

        after = {
            path: path.read_bytes() for path in settings.audio_dir.rglob("*") if path.is_file()
        }
        assert before == after


class TestRestartRecovery:
    def test_a_job_interrupted_by_a_kill_is_picked_up_again(
        self, settings: Settings, recording_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with closing_connection(settings.db_path) as connection:
            claimed = q.claim_next(connection)
            assert claimed is not None  # the worker was killed holding this

        _patch_transcribe(monkeypatch, FAKE)
        with closing_connection(settings.db_path) as connection:
            assert q.recover_stale(connection) == 1
            assert Worker(settings).run_once(connection) is True
            assert q.depth(connection)["done"] == 1

    def test_stop_is_requested_politely(self, settings: Settings) -> None:
        worker = Worker(settings)
        assert worker.running is True
        worker.request_stop(15, None)
        assert worker.running is False
