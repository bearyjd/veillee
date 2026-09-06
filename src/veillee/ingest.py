"""The one audio pipeline, used identically by both capture paths.

Whether audio arrived from MediaRecorder in chunks or from a file the iPad's
Voice Memos produced, it lands here and is treated the same way:

    original (untouched) -> FLAC 48kHz -> Opus 48kbps -> checksums -> queue

The original is never modified and never deleted. Every transcode is a decision
that could turn out to be wrong, and the original is how that stays recoverable.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .index import upsert_photograph, upsert_recording
from .models import Recording
from .queue import enqueue
from .storage import audio as audio_storage
from .storage import photos as photo_storage
from .storage.answers import atomic_write, move_to_trash
from .storage.gitrepo import autocommit
from .storage.paths import recording_id as build_recording_id
from .storage.paths import revision_stamp, utc_now_iso
from .transcode import TranscodeError, is_decodable, probe_duration, to_flac, to_opus

logger = logging.getLogger(__name__)


class IngestError(RuntimeError):
    """The audio could not be taken in. Nothing partial is left behind."""


def _cleanup(paths: dict[str, Path]) -> None:
    """Remove derived files after a failure. The original is kept if it decoded."""
    for key in ("flac", "opus", "sidecar"):
        paths[key].unlink(missing_ok=True)


def ingest_recording(
    settings: Settings,
    connection: sqlite3.Connection,
    *,
    question_id: str,
    source_path: Path,
    original_suffix: str,
    device: str = "",
    source: str = "upload",
    when: datetime | None = None,
) -> Recording:
    """Take one audio file all the way into the archive and the queue."""
    if not source_path.exists() or source_path.stat().st_size == 0:
        raise IngestError("The recording arrived empty. Nothing was saved.")

    if not is_decodable(source_path):
        raise IngestError(
            "That file does not appear to be audio we can read. "
            "If it came from a phone, try sending it as m4a, mp3 or wav."
        )

    recording_id = build_recording_id(question_id, when or datetime.now(UTC))
    paths = audio_storage.recording_paths(settings, recording_id, original_suffix)
    paths["original"].parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(source_path), str(paths["original"]))

    try:
        to_flac(paths["original"], paths["flac"])
        to_opus(paths["original"], paths["opus"])
    except TranscodeError as exc:
        _cleanup(paths)
        logger.error("transcode failed for %s: %s", recording_id, exc)
        raise IngestError(f"The recording was saved but could not be converted: {exc}") from exc

    duration = probe_duration(paths["flac"]) or probe_duration(paths["original"])
    created = utc_now_iso()
    audio_storage.write_sidecar(
        paths["sidecar"],
        recording_id=recording_id,
        question_id=question_id,
        created=created,
        duration_seconds=duration,
        device=device[:300],
        source=source,
        original=paths["original"],
        flac=paths["flac"],
        opus=paths["opus"],
    )

    recording = audio_storage.read_sidecar(paths["sidecar"])
    upsert_recording(connection, recording)
    enqueue(connection, recording_id)
    autocommit(
        settings.data_dir,
        f"recording: {recording_id} added",
        enabled=settings.git_autocommit,
    )
    logger.info("ingested %s (%.1fs, via %s)", recording_id, duration, source)
    return recording


def ingest_photograph(
    settings: Settings,
    connection: sqlite3.Connection,
    *,
    question_id: str,
    source_path: Path,
    original_suffix: str,
    caption: str = "",
    when: datetime | None = None,
) -> photo_storage.Photograph:
    """Take one photograph into the archive: original kept, view copy derived."""
    if not source_path.exists() or source_path.stat().st_size == 0:
        raise IngestError("That photograph arrived empty. Nothing was saved.")

    photo_id = build_recording_id(question_id, when or datetime.now(UTC))
    paths = photo_storage.photo_paths(settings, photo_id, original_suffix)
    paths["original"].parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(paths["original"]))

    try:
        width, height = photo_storage.make_view_copy(paths["original"], paths["view"])
    except photo_storage.PhotoError as exc:
        # Keep the original - he gave it to us - but do not leave a half-made
        # record behind that the index would trip over.
        paths["view"].unlink(missing_ok=True)
        move_to_trash(settings, paths["original"])
        raise IngestError(str(exc)) from exc

    photo_storage.write_sidecar(
        paths["sidecar"],
        photo_id=photo_id,
        question_id=question_id,
        created=utc_now_iso(),
        caption=caption.strip(),
        original=paths["original"],
        view=paths["view"],
        width=width,
        height=height,
    )
    photograph = photo_storage.read_sidecar(paths["sidecar"])
    upsert_photograph(connection, photograph)
    autocommit(settings.data_dir, f"photograph: {photo_id} added", enabled=settings.git_autocommit)
    logger.info("ingested photograph %s for %s", photo_id, question_id)
    return photograph


def upload_dir(settings: Settings, upload_id: str) -> Path:
    """Where a chunked upload accumulates. Chunks are files, never memory."""
    return settings.uploads_dir / upload_id


def start_upload(settings: Settings, upload_id: str, metadata: dict[str, object]) -> Path:
    directory = upload_dir(settings, upload_id)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(directory / "meta.json", json.dumps(metadata, indent=2) + "\n")
    return directory


def write_chunk(settings: Settings, upload_id: str, index: int, payload: bytes) -> Path:
    """Persist one chunk immediately, so a crash costs only what is in flight."""
    directory = upload_dir(settings, upload_id)
    if not directory.is_dir():
        raise IngestError("That recording session is not open. Start a new recording.")
    destination = directory / f"{index:05d}.part"
    temporary = destination.with_suffix(".part.tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return destination


def read_upload_metadata(settings: Settings, upload_id: str) -> dict[str, object]:
    meta_path = upload_dir(settings, upload_id) / "meta.json"
    if not meta_path.exists():
        raise IngestError("That recording session is not open. Start a new recording.")
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def assemble_chunks(settings: Settings, upload_id: str, suffix: str) -> Path:
    """Concatenate every chunk that arrived, in order, into one file.

    Missing trailing chunks are simply absent: a recording cut short by a dead
    battery still assembles into everything that did arrive.
    """
    directory = upload_dir(settings, upload_id)
    chunks = sorted(directory.glob("*.part"))
    if not chunks:
        raise IngestError("No audio arrived for that recording.")

    assembled = directory / f"assembled{suffix}"
    with assembled.open("wb") as output:
        for chunk in chunks:
            output.write(chunk.read_bytes())
    if assembled.stat().st_size == 0:
        raise IngestError("No audio arrived for that recording.")
    return assembled


def discard_upload(settings: Settings, upload_id: str) -> None:
    """Move an abandoned upload to the trash rather than deleting it."""
    directory = upload_dir(settings, upload_id)
    if not directory.is_dir():
        return
    destination = settings.trash_dir / revision_stamp() / "uploads" / upload_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(directory), str(destination))
