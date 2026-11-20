"""The transcript document: the one place its format and `reviewed` flag live.

Producers (transcription), readers (audio indexing, reassign) and the /admin
editor all go through here so the key names and the default can not drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, dumps, loads

REVIEWED = "reviewed"
NOTE = "Machine draft. Not shown to him. Correct it before trusting it."


@dataclass(frozen=True)
class Transcript:
    metadata: dict[str, Any]
    body: str

    @property
    def reviewed(self) -> bool:
        return bool(self.metadata.get(REVIEWED, False))


def build_transcript_metadata(
    *,
    recording_id: str,
    question_id: str,
    created: str,
    transcribed: str,
    backend: str,
    model: str,
    language: str,
    reviewed: bool = False,
) -> dict[str, Any]:
    """Frontmatter for a freshly transcribed (unreviewed) machine draft."""
    return {
        "recording_id": recording_id,
        "question_id": question_id,
        "created": created,
        "transcribed": transcribed,
        "backend": backend,
        "model": model,
        "language": language,
        REVIEWED: reviewed,
        "note": NOTE,
    }


def parse_transcript(text: str) -> Transcript:
    """Raises FrontmatterError if the text is not a well-formed document."""
    metadata, body = loads(text)
    return Transcript(metadata=metadata, body=body)


def read_transcript(path: Path) -> Transcript:
    """Raises FrontmatterError (malformed) or OSError (unreadable)."""
    return parse_transcript(path.read_text(encoding="utf-8"))


def render_transcript(transcript: Transcript) -> str:
    return dumps(dict(transcript.metadata), transcript.body)


def mark_reviewed(transcript: Transcript, reviewed: bool) -> Transcript:
    return Transcript(
        metadata={**transcript.metadata, REVIEWED: bool(reviewed)}, body=transcript.body
    )


def read_reviewed(path: Path) -> bool | None:
    """The file's recorded review state, or None if unreadable or never recorded."""
    try:
        metadata = read_transcript(path).metadata
    except (FrontmatterError, OSError):
        return None
    if REVIEWED not in metadata:
        return None
    return bool(metadata[REVIEWED])
