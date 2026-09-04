"""Chunked upload, including the case this whole design exists for: the
recording stops in the middle because the battery died."""

from __future__ import annotations

import shutil

import pytest

from veillee import ingest
from veillee.config import Settings
from veillee.db import closing_connection
from veillee.storage.audio import sha256_file


def _chunks_of(path, count: int) -> list[bytes]:
    data = path.read_bytes()
    size = len(data) // count + 1
    return [data[index : index + size] for index in range(0, len(data), size)]


class TestChunkAssembly:
    def test_chunks_reassemble_byte_for_byte(self, settings: Settings, sample_m4a) -> None:
        upload_id = "abc123"
        ingest.start_upload(settings, upload_id, {"question_id": "q012"})
        for index, chunk in enumerate(_chunks_of(sample_m4a, 5)):
            ingest.write_chunk(settings, upload_id, index, chunk)

        assembled = ingest.assemble_chunks(settings, upload_id, ".m4a")

        assert assembled.read_bytes() == sample_m4a.read_bytes()
        assert sha256_file(assembled) == sha256_file(sample_m4a)

    def test_each_chunk_is_on_disk_the_moment_it_arrives(
        self, settings: Settings, sample_m4a
    ) -> None:
        """Nothing is buffered in memory; that is what bounds the loss."""
        upload_id = "durable"
        ingest.start_upload(settings, upload_id, {"question_id": "q012"})
        ingest.write_chunk(settings, upload_id, 0, b"first chunk bytes")

        landed = sorted(ingest.upload_dir(settings, upload_id).glob("*.part"))
        assert len(landed) == 1
        assert landed[0].read_bytes() == b"first chunk bytes"

    def test_chunks_assemble_in_index_order_not_arrival_order(self, settings: Settings) -> None:
        upload_id = "ordering"
        ingest.start_upload(settings, upload_id, {"question_id": "q012"})
        ingest.write_chunk(settings, upload_id, 2, b"ccc")
        ingest.write_chunk(settings, upload_id, 0, b"aaa")
        ingest.write_chunk(settings, upload_id, 1, b"bbb")

        assert ingest.assemble_chunks(settings, upload_id, ".webm").read_bytes() == b"aaabbbccc"

    def test_a_disconnect_mid_upload_keeps_everything_that_arrived(
        self, settings: Settings, sample_m4a
    ) -> None:
        """The battery dies after three of five chunks. Those three must survive."""
        upload_id = "cutoff"
        ingest.start_upload(settings, upload_id, {"question_id": "q012"})
        chunks = _chunks_of(sample_m4a, 5)
        for index, chunk in enumerate(chunks[:3]):
            ingest.write_chunk(settings, upload_id, index, chunk)

        assembled = ingest.assemble_chunks(settings, upload_id, ".m4a")

        assert assembled.read_bytes() == b"".join(chunks[:3])
        assert assembled.stat().st_size > 0

    def test_assembling_nothing_is_an_error_rather_than_an_empty_file(
        self, settings: Settings
    ) -> None:
        ingest.start_upload(settings, "empty", {"question_id": "q012"})
        with pytest.raises(ingest.IngestError):
            ingest.assemble_chunks(settings, "empty", ".webm")

    def test_writing_to_an_unknown_session_is_refused(self, settings: Settings) -> None:
        with pytest.raises(ingest.IngestError):
            ingest.write_chunk(settings, "never-started", 0, b"data")


class TestIngestPipeline:
    def test_both_paths_produce_the_same_shape_of_result(
        self, settings: Settings, sample_m4a, sample_wav
    ) -> None:
        with closing_connection(settings.db_path) as connection:
            from_upload = ingest.ingest_recording(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_m4a, "a.m4a"),
                original_suffix=".m4a",
                source="upload",
            )
            from_recorder = ingest.ingest_recording(
                settings,
                connection,
                question_id="q013",
                source_path=_staged(settings, sample_wav, "b.wav"),
                original_suffix=".wav",
                source="recorder",
            )

        for recording in (from_upload, from_recorder):
            assert recording.sha256_original and recording.sha256_flac and recording.sha256_opus
            assert recording.duration_seconds > 0
        assert from_upload.source == "upload"
        assert from_recorder.source == "recorder"

    def test_the_original_is_kept_untouched(self, settings: Settings, sample_m4a) -> None:
        original_digest = sha256_file(sample_m4a)
        with closing_connection(settings.db_path) as connection:
            recording = ingest.ingest_recording(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_m4a, "c.m4a"),
                original_suffix=".m4a",
            )
        assert recording.sha256_original == original_digest

    def test_a_file_that_is_not_audio_is_refused_cleanly(self, settings: Settings) -> None:
        junk = settings.data_dir / "notaudio.m4a"
        junk.write_bytes(b"this is definitely not audio" * 100)
        with closing_connection(settings.db_path) as connection:
            with pytest.raises(ingest.IngestError) as caught:
                ingest.ingest_recording(
                    settings,
                    connection,
                    question_id="q012",
                    source_path=junk,
                    original_suffix=".m4a",
                )
        assert "audio" in str(caught.value).lower()
        assert not list(settings.audio_dir.rglob("*.flac"))

    def test_an_empty_file_is_refused(self, settings: Settings) -> None:
        empty = settings.data_dir / "empty.m4a"
        empty.write_bytes(b"")
        with closing_connection(settings.db_path) as connection:
            with pytest.raises(ingest.IngestError):
                ingest.ingest_recording(
                    settings,
                    connection,
                    question_id="q012",
                    source_path=empty,
                    original_suffix=".m4a",
                )

    def test_ingest_queues_the_recording_for_transcription(
        self, settings: Settings, sample_m4a
    ) -> None:
        from veillee.queue import depth

        with closing_connection(settings.db_path) as connection:
            ingest.ingest_recording(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_m4a, "d.m4a"),
                original_suffix=".m4a",
            )
            assert depth(connection)["pending"] == 1

    def test_an_abandoned_upload_goes_to_trash_not_oblivion(self, settings: Settings) -> None:
        ingest.start_upload(settings, "abandoned", {"question_id": "q012"})
        ingest.write_chunk(settings, "abandoned", 0, b"some audio bytes")

        ingest.discard_upload(settings, "abandoned")

        assert not ingest.upload_dir(settings, "abandoned").exists()
        recovered = list(settings.trash_dir.rglob("00000.part"))
        assert len(recovered) == 1
        assert recovered[0].read_bytes() == b"some audio bytes"


def _staged(settings: Settings, source, name: str):
    destination = settings.data_dir / name
    shutil.copy2(source, destination)
    return destination
