"""Recordings on disk: the untouched original, two derived files, and a sidecar.

The sidecar JSON carries everything the index needs, so a recording found by
walking `data/audio/` can be re-indexed with no other source of information.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..config import Settings
from ..models import Recording
from .answers import atomic_write
from .frontmatter import FrontmatterError, loads
from .paths import recording_dir_for

SIDECAR_VERSION = 1
CHUNK_BYTES = 1024 * 1024

SUPPORTED_UPLOAD_SUFFIXES = frozenset({".m4a", ".mp3", ".wav", ".webm", ".ogg", ".opus", ".flac"})


def sha256_file(path: Path) -> str:
    """Checksum a file without reading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def recording_paths(settings: Settings, recording_id: str, original_suffix: str) -> dict[str, Path]:
    """The four paths that make up one recording."""
    directory = settings.audio_dir / recording_dir_for(recording_id)
    suffix = original_suffix if original_suffix.startswith(".") else f".{original_suffix}"
    return {
        "original": directory / f"{recording_id}.orig{suffix}",
        "flac": directory / f"{recording_id}.flac",
        "opus": directory / f"{recording_id}.opus",
        "sidecar": directory / f"{recording_id}.json",
    }


def transcript_paths(settings: Settings, recording_id: str) -> dict[str, Path]:
    """Where a recording's transcript and raw machine output live."""
    directory = settings.transcripts_dir / recording_dir_for(recording_id)
    return {
        "markdown": directory / f"{recording_id}.md",
        "json": directory / f"{recording_id}.json",
    }


def _file_entry(path: Path) -> dict[str, object]:
    return {"name": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def write_sidecar(
    sidecar_path: Path,
    *,
    recording_id: str,
    question_id: str,
    created: str,
    duration_seconds: float,
    device: str,
    source: str,
    original: Path,
    flac: Path,
    opus: Path,
) -> dict[str, object]:
    """Write the sidecar that makes this recording self-describing on disk."""
    payload: dict[str, object] = {
        "sidecar_version": SIDECAR_VERSION,
        "recording_id": recording_id,
        "question_id": question_id,
        "created": created,
        "duration_seconds": round(float(duration_seconds), 3),
        "device": device,
        "source": source,
        "files": {
            "original": _file_entry(original),
            "flac": _file_entry(flac),
            "opus": _file_entry(opus),
        },
    }
    atomic_write(sidecar_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return payload


def read_sidecar(sidecar_path: Path) -> Recording:
    """Rebuild a Recording from its sidecar alone."""
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    files = payload.get("files", {})
    directory = sidecar_path.parent

    def entry(kind: str, key: str) -> str:
        return str(files.get(kind, {}).get(key, ""))

    recording_id = str(payload["recording_id"])
    transcripts = directory.parent.parent.parent / "transcripts"
    transcript = (
        transcripts / recording_dir_for(recording_id) / f"{recording_id}.md"
        if transcripts.is_dir()
        else None
    )
    return Recording(
        recording_id=recording_id,
        question_id=str(payload["question_id"]),
        created=str(payload.get("created", "")),
        duration_seconds=float(payload.get("duration_seconds", 0.0)),
        device=str(payload.get("device", "")),
        original_path=str(directory / entry("original", "name")),
        flac_path=str(directory / entry("flac", "name")),
        opus_path=str(directory / entry("opus", "name")),
        sidecar_path=str(sidecar_path),
        sha256_original=entry("original", "sha256"),
        sha256_flac=entry("flac", "sha256"),
        sha256_opus=entry("opus", "sha256"),
        source=str(payload.get("source", "upload")),
        transcript_path=str(transcript) if transcript and transcript.exists() else None,
        transcript_reviewed=_transcript_is_reviewed(transcript, payload),
    )


def _transcript_is_reviewed(transcript: Path | None, payload: dict[str, object]) -> bool:
    """Whether a person has checked this transcript against the audio.

    The review is recorded in the transcript's own frontmatter, because that is
    the file the reviewing happens in. It has to be read from there: the sidecar
    beside the audio never learns about it, so an index rebuilt from the sidecar
    alone reported every reviewed transcript as unreviewed for ever, and
    `reindex` - the operation this archive is founded on - confirmed the wrong
    answer instead of correcting it.

    The sidecar is still honoured as a fallback, for recordings written before
    the transcript carried the flag.
    """
    if transcript is not None and transcript.exists():
        try:
            metadata, _ = loads(transcript.read_text(encoding="utf-8"))
        except (FrontmatterError, OSError):
            # An unreadable transcript is a problem for the caller to report,
            # not a reason to lose the rest of the recording.
            pass
        else:
            if "reviewed" in metadata:
                return bool(metadata["reviewed"])
    return bool(payload.get("transcript_reviewed", False))


def iter_sidecars(settings: Settings) -> list[Path]:
    """Every recording sidecar on disk, in a stable order."""
    if not settings.audio_dir.is_dir():
        return []
    return sorted(settings.audio_dir.rglob("*.json"))


def verify_recording(recording: Recording) -> list[str]:
    """Re-checksum a recording's files. Returns a list of problems, empty if sound."""
    problems: list[str] = []
    for label, path_text, expected in (
        ("original", recording.original_path, recording.sha256_original),
        ("flac", recording.flac_path, recording.sha256_flac),
        ("opus", recording.opus_path, recording.sha256_opus),
    ):
        path = Path(path_text)
        if not path.exists():
            problems.append(f"{recording.recording_id}: {label} file is missing ({path.name})")
        elif expected and sha256_file(path) != expected:
            problems.append(f"{recording.recording_id}: {label} checksum does not match")
    return problems
