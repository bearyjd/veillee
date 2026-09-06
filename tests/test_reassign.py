"""Refiling a recording under a different question."""

from __future__ import annotations

import json
import shutil

import pytest

from veillee.config import Settings
from veillee.db import closing_connection
from veillee.index import reindex
from veillee.ingest import ingest_recording
from veillee.reassign import ReassignError, move_recording
from veillee.storage import audio as audio_storage
from veillee.storage.audio import sha256_file
from veillee.storage.frontmatter import dumps, loads


@pytest.fixture
def recording_id(settings: Settings, sample_m4a) -> str:
    staged = settings.data_dir / "in.m4a"
    shutil.copy2(sample_m4a, staged)
    with closing_connection(settings.db_path) as connection:
        recording = ingest_recording(
            settings,
            connection,
            question_id="q003",
            source_path=staged,
            original_suffix=".m4a",
        )
    return recording.recording_id


def _write_transcript(settings: Settings, recording_id: str, body: str) -> None:
    paths = audio_storage.transcript_paths(settings, recording_id)
    paths["markdown"].parent.mkdir(parents=True, exist_ok=True)
    paths["markdown"].write_text(
        dumps({"recording_id": recording_id, "question_id": "q003", "reviewed": True}, body),
        encoding="utf-8",
    )
    paths["json"].write_text('{"text": "machine output"}\n', encoding="utf-8")


class TestMovingARecording:
    def test_the_id_and_filenames_follow_the_new_question(
        self, settings: Settings, recording_id: str
    ) -> None:
        result = move_recording(settings, recording_id, "c001")

        assert result.new_recording_id.endswith("-c001")
        assert result.new_recording_id.split("-c001")[0] == recording_id.split("-q003")[0]
        assert not list(settings.audio_dir.rglob(f"{recording_id}.*"))
        assert list(settings.audio_dir.rglob(f"{result.new_recording_id}.flac"))

    def test_the_audio_is_not_re_encoded(self, settings: Settings, recording_id: str) -> None:
        """Only names change. The bytes and their checksums must be identical."""
        before = audio_storage.read_sidecar(
            next(p for p in audio_storage.iter_sidecars(settings) if p.stem == recording_id)
        )
        result = move_recording(settings, recording_id, "c001")
        after = audio_storage.read_sidecar(
            next(
                p
                for p in audio_storage.iter_sidecars(settings)
                if p.stem == result.new_recording_id
            )
        )

        assert after.sha256_original == before.sha256_original
        assert after.sha256_flac == before.sha256_flac
        assert after.sha256_opus == before.sha256_opus
        assert audio_storage.verify_recording(after) == []

    def test_the_sidecar_records_where_it_came_from(
        self, settings: Settings, recording_id: str
    ) -> None:
        result = move_recording(settings, recording_id, "c001")
        sidecar = next(
            p for p in audio_storage.iter_sidecars(settings) if p.stem == result.new_recording_id
        )
        payload = json.loads(sidecar.read_text(encoding="utf-8"))

        assert payload["question_id"] == "c001"
        assert payload["recording_id"] == result.new_recording_id
        assert payload["refiled_from"] == "q003", "the archive should say it was moved"

    def test_the_transcript_comes_with_it_and_keeps_its_review(
        self, settings: Settings, recording_id: str
    ) -> None:
        _write_transcript(settings, recording_id, "[00:00:00] The orchard story.")

        result = move_recording(settings, recording_id, "c001")

        old = audio_storage.transcript_paths(settings, recording_id)
        new = audio_storage.transcript_paths(settings, result.new_recording_id)
        assert not old["markdown"].exists()
        assert new["markdown"].exists()
        assert new["json"].exists()

        metadata, body = loads(new["markdown"].read_text(encoding="utf-8"))
        assert metadata["recording_id"] == result.new_recording_id
        assert metadata["question_id"] == "c001"
        assert metadata["reviewed"] is True, "a review already done must not be thrown away"
        assert "orchard story" in body

    def test_the_index_follows_after_a_reindex(self, settings: Settings, recording_id: str) -> None:
        result = move_recording(settings, recording_id, "c001")
        reindex(settings)

        with closing_connection(settings.db_path) as connection:
            rows = connection.execute("SELECT recording_id, question_id FROM recordings").fetchall()
        assert [tuple(r) for r in rows] == [(result.new_recording_id, "c001")]

    def test_it_survives_a_rebuild_from_disk_alone(
        self, settings: Settings, recording_id: str
    ) -> None:
        move_recording(settings, recording_id, "c001")
        for suffix in ("", "-wal", "-shm"):
            settings.db_path.with_name(settings.db_path.name + suffix).unlink(missing_ok=True)

        report = reindex(settings)

        assert report.ok
        assert report.recordings == 1


class TestRefusals:
    def test_an_unknown_recording_changes_nothing(self, settings: Settings) -> None:
        with pytest.raises(ReassignError, match="no recording called"):
            move_recording(settings, "20260906-000000-q003", "c001")

    def test_moving_it_where_it_already_is_is_refused(
        self, settings: Settings, recording_id: str
    ) -> None:
        with pytest.raises(ReassignError, match="already filed"):
            move_recording(settings, recording_id, "q003")

    def test_a_malformed_question_id_is_refused(
        self, settings: Settings, recording_id: str
    ) -> None:
        with pytest.raises(ValueError):
            move_recording(settings, recording_id, "not-a-question")
        assert list(settings.audio_dir.rglob(f"{recording_id}.flac")), "it moved anyway"

    def test_a_missing_audio_file_stops_the_move(
        self, settings: Settings, recording_id: str
    ) -> None:
        next(settings.audio_dir.rglob(f"{recording_id}.opus")).unlink()
        with pytest.raises(ReassignError, match="missing"):
            move_recording(settings, recording_id, "c001")


def test_checksums_still_verify_afterwards(settings: Settings, recording_id: str) -> None:
    result = move_recording(settings, recording_id, "c001")
    sidecar = next(
        p for p in audio_storage.iter_sidecars(settings) if p.stem == result.new_recording_id
    )
    recording = audio_storage.read_sidecar(sidecar)
    for path_text, expected in (
        (recording.flac_path, recording.sha256_flac),
        (recording.opus_path, recording.sha256_opus),
    ):
        from pathlib import Path

        assert sha256_file(Path(path_text)) == expected
