"""ffmpeg actually runs. These assert on decoded output, not on exit codes."""

from __future__ import annotations

import shutil

import pytest

from veillee.config import Settings
from veillee.db import closing_connection
from veillee.ingest import ingest_recording
from veillee.storage import audio as audio_storage
from veillee.transcode import (
    ARCHIVE_SAMPLE_RATE,
    TranscodeError,
    ffmpeg_available,
    is_decodable,
    probe_codec,
    probe_duration,
    to_flac,
    to_opus,
)

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is not installed")


class TestTranscoding:
    def test_flac_is_real_flac_and_decodes(self, tmp_path, sample_wav) -> None:
        output = to_flac(sample_wav, tmp_path / "out.flac")
        assert probe_codec(output) == "flac"
        assert is_decodable(output)
        assert probe_duration(output) == pytest.approx(probe_duration(sample_wav), abs=0.15)

    def test_opus_is_real_opus_and_decodes(self, tmp_path, sample_wav) -> None:
        output = to_opus(sample_wav, tmp_path / "out.opus")
        assert probe_codec(output) == "opus"
        assert is_decodable(output)

    def test_opus_is_much_smaller_than_flac(self, tmp_path, sample_wav) -> None:
        flac = to_flac(sample_wav, tmp_path / "a.flac")
        opus = to_opus(sample_wav, tmp_path / "a.opus")
        assert opus.stat().st_size < flac.stat().st_size

    def test_m4a_input_converts(self, tmp_path, sample_m4a) -> None:
        assert probe_codec(to_flac(sample_m4a, tmp_path / "b.flac")) == "flac"
        assert probe_codec(to_opus(sample_m4a, tmp_path / "b.opus")) == "opus"

    def test_a_failed_transcode_leaves_no_partial_file(self, tmp_path) -> None:
        junk = tmp_path / "junk.wav"
        junk.write_bytes(b"not audio at all")
        destination = tmp_path / "out.flac"
        with pytest.raises(TranscodeError):
            to_flac(junk, destination)
        assert not destination.exists()
        assert list(tmp_path.glob("*.part")) == []


class TestChecksumsAndSidecar:
    def test_sidecar_records_a_correct_checksum_for_all_three_files(
        self, settings: Settings, sample_m4a
    ) -> None:
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

        # Re-checksum from disk and compare with what the sidecar claims.
        assert audio_storage.verify_recording(recording) == []
        assert (
            audio_storage.sha256_file(__import__("pathlib").Path(recording.flac_path))
            == recording.sha256_flac
        )

    def test_verify_notices_a_corrupted_file(self, settings: Settings, sample_m4a) -> None:
        staged = settings.data_dir / "in2.m4a"
        shutil.copy2(sample_m4a, staged)
        with closing_connection(settings.db_path) as connection:
            recording = ingest_recording(
                settings,
                connection,
                question_id="q012",
                source_path=staged,
                original_suffix=".m4a",
            )
        from pathlib import Path

        Path(recording.opus_path).write_bytes(b"corrupted")

        problems = audio_storage.verify_recording(recording)

        assert len(problems) == 1
        assert "checksum" in problems[0]

    def test_verify_notices_a_missing_file(self, settings: Settings, sample_m4a) -> None:
        staged = settings.data_dir / "in3.m4a"
        shutil.copy2(sample_m4a, staged)
        with closing_connection(settings.db_path) as connection:
            recording = ingest_recording(
                settings,
                connection,
                question_id="q012",
                source_path=staged,
                original_suffix=".m4a",
            )
        from pathlib import Path

        Path(recording.flac_path).unlink()

        assert any("missing" in problem for problem in audio_storage.verify_recording(recording))

    def test_archive_copy_is_at_the_archival_sample_rate(self, tmp_path, sample_wav) -> None:
        import json
        import subprocess

        output = to_flac(sample_wav, tmp_path / "rate.flac")
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate",
                "-of",
                "json",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        rate = int(json.loads(result.stdout)["streams"][0]["sample_rate"])
        assert rate == ARCHIVE_SAMPLE_RATE
