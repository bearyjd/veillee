"""Moving a recording to a different question.

He records against whichever page he happens to be on, so a recording filed
under the wrong question is a normal event rather than an accident. The question
id is baked into the filenames, the sidecar and the transcript, so putting one
right means moving all of them together - which is exactly the sort of thing
that should be a command rather than a careful afternoon with `mv`.

Nothing is re-encoded. The audio bytes and their checksums are untouched.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .storage import audio as audio_storage
from .storage.answers import atomic_write
from .storage.frontmatter import FrontmatterError, dumps, loads
from .storage.paths import parse_question_id

logger = logging.getLogger(__name__)


class ReassignError(RuntimeError):
    """The recording could not be moved. Nothing has been changed."""


@dataclass(frozen=True)
class Reassignment:
    old_recording_id: str
    new_recording_id: str
    moved: tuple[str, ...]


def _sidecar_for(settings: Settings, recording_id: str) -> Path:
    for candidate in audio_storage.iter_sidecars(settings):
        if candidate.stem == recording_id:
            return candidate
    raise ReassignError(f"no recording called {recording_id}")


def move_recording(settings: Settings, recording_id: str, new_question_id: str) -> Reassignment:
    """Refile a recording under a different question."""
    parse_question_id(new_question_id)
    sidecar = _sidecar_for(settings, recording_id)

    stamp, _, old_question = recording_id.rpartition("-")
    if not stamp:
        raise ReassignError(f"malformed recording id: {recording_id}")
    if old_question == new_question_id:
        raise ReassignError(f"{recording_id} is already filed under {new_question_id}")

    new_recording_id = f"{stamp}-{new_question_id}"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    directory = sidecar.parent
    moved: list[str] = []

    # Audio first. Only the names change; the bytes and their checksums do not.
    for kind, entry in payload.get("files", {}).items():
        source = directory / str(entry["name"])
        if not source.exists():
            raise ReassignError(f"{kind} file is missing: {source.name}")
        destination = directory / source.name.replace(recording_id, new_recording_id, 1)
        source.rename(destination)
        entry["name"] = destination.name
        moved.append(f"{source.name} -> {destination.name}")

    payload["recording_id"] = new_recording_id
    payload["question_id"] = new_question_id
    payload["refiled_from"] = old_question
    atomic_write(
        directory / f"{new_recording_id}.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    sidecar.unlink()
    moved.append(f"{sidecar.name} -> {new_recording_id}.json")

    moved.extend(_move_transcripts(settings, recording_id, new_recording_id, new_question_id))
    _move_transcript_revisions(settings, recording_id, new_recording_id, moved)

    logger.info("refiled %s as %s", recording_id, new_recording_id)
    return Reassignment(recording_id, new_recording_id, tuple(moved))


def _move_transcripts(
    settings: Settings, recording_id: str, new_recording_id: str, new_question_id: str
) -> list[str]:
    """Carry the transcript across, keeping any review already done on it."""
    moved: list[str] = []
    paths = audio_storage.transcript_paths(settings, recording_id)
    new_paths = audio_storage.transcript_paths(settings, new_recording_id)

    markdown = paths["markdown"]
    if markdown.exists():
        try:
            metadata, body = loads(markdown.read_text(encoding="utf-8"))
        except FrontmatterError as exc:
            raise ReassignError(f"transcript is unreadable, nothing moved: {exc}") from exc
        metadata["recording_id"] = new_recording_id
        metadata["question_id"] = new_question_id
        new_paths["markdown"].parent.mkdir(parents=True, exist_ok=True)
        atomic_write(new_paths["markdown"], dumps(metadata, body))
        markdown.unlink()
        moved.append(f"{markdown.name} -> {new_paths['markdown'].name}")

    for suffix in (".json", ".machine.md"):
        source = markdown.with_suffix("").with_name(markdown.stem + suffix)
        if source.exists():
            destination = source.with_name(new_recording_id + suffix)
            source.rename(destination)
            moved.append(f"{source.name} -> {destination.name}")
    return moved


def _move_transcript_revisions(
    settings: Settings, recording_id: str, new_recording_id: str, moved: list[str]
) -> None:
    old = settings.revisions_dir / f"transcript-{recording_id}"
    if old.is_dir():
        new = settings.revisions_dir / f"transcript-{new_recording_id}"
        shutil.move(str(old), str(new))
        moved.append(f"{old.name}/ -> {new.name}/")
