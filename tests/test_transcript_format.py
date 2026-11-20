"""The transcript document format has one owner: veillee.storage.transcript."""

from __future__ import annotations

from pathlib import Path

import pytest

from veillee.storage import transcript as fmt
from veillee.storage.audio import _transcript_is_reviewed
from veillee.storage.frontmatter import FrontmatterError, dumps
from veillee.transcribe import Segment, Transcription, render_markdown


def _produced(tmp_path: Path) -> Path:
    transcription = Transcription(
        segments=(Segment(0.0, 1.0, "hello"),), language="en", backend="test", model="m"
    )
    path = tmp_path / "t.md"
    path.write_text(
        render_markdown(transcription, recording_id="r1", question_id="q1", created="now"),
        encoding="utf-8",
    )
    return path


def test_round_trip(tmp_path: Path) -> None:
    metadata = fmt.build_transcript_metadata(
        recording_id="r1",
        question_id="q1",
        created="c",
        transcribed="t",
        backend="b",
        model="m",
        language="en",
    )
    path = tmp_path / "t.md"
    fmt.write_transcript_file(path, fmt.Transcript(metadata=metadata, body="body text"))
    loaded = fmt.read_transcript(path)
    assert loaded.metadata == metadata
    assert loaded.body == "body text"


def test_reviewed_defaults_false() -> None:
    metadata = fmt.build_transcript_metadata(
        recording_id="r", question_id="q", created="c", transcribed="t",
        backend="b", model="m", language="en",
    )  # fmt: skip
    assert metadata[fmt.REVIEWED] is False
    assert fmt.Transcript(metadata={}, body="").reviewed is False


def test_mark_reviewed_is_immutable() -> None:
    original = fmt.Transcript(metadata={"reviewed": False}, body="b")
    marked = fmt.mark_reviewed(original, True)
    assert marked.reviewed is True
    assert original.reviewed is False


def test_malformed_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(FrontmatterError):
        fmt.read_transcript(path)
    assert fmt.read_reviewed(path) is None


def test_read_reviewed_absent_flag(tmp_path: Path) -> None:
    path = tmp_path / "t.md"
    path.write_text(dumps({"recording_id": "r"}, "x"), encoding="utf-8")
    assert fmt.read_reviewed(path) is None


def test_producer_output_reads_unreviewed_everywhere(tmp_path: Path) -> None:
    path = _produced(tmp_path)
    assert fmt.read_reviewed(path) is False
    assert fmt.read_transcript(path).reviewed is False
    # Audio index: the file's flag wins over a sidecar claiming review.
    assert _transcript_is_reviewed(path, {"transcript_reviewed": True}) is False
