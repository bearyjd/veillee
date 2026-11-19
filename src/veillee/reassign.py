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

    # Validate everything that can fail before the first rename.
    for kind, entry in payload.get("files", {}).items():
        if not (directory / str(entry["name"])).exists():
            raise ReassignError(f"{kind} file is missing: {entry['name']}")
    parsed = _read_transcripts(settings, recording_id)

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

    moved.extend(
        _move_transcripts(settings, recording_id, new_recording_id, new_question_id, parsed)
    )
    _move_transcript_revisions(settings, recording_id, new_recording_id, moved)

    logger.info("refiled %s as %s", recording_id, new_recording_id)
    return Reassignment(recording_id, new_recording_id, tuple(moved))


def _read_transcripts(settings: Settings, recording_id: str) -> dict[str, object]:
    """Parse every transcript file up front, so a bad one fails before anything moves."""
    paths = audio_storage.transcript_paths(settings, recording_id)
    parsed: dict[str, object] = {}
    for key, label in (("markdown", "transcript"), ("machine", "machine draft")):
        if paths[key].exists():
            try:
                parsed[key] = loads(paths[key].read_text(encoding="utf-8"))
            except FrontmatterError as exc:
                raise ReassignError(f"{label} is unreadable, nothing moved: {exc}") from exc
    if paths["json"].exists():
        try:
            parsed["json"] = json.loads(paths["json"].read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReassignError(f"machine transcript is unreadable, nothing moved: {exc}") from exc
    return parsed


def _move_transcripts(
    settings: Settings,
    recording_id: str,
    new_recording_id: str,
    new_question_id: str,
    parsed: dict[str, object],
) -> list[str]:
    """Carry the transcript across, keeping any review already done on it."""
    moved: list[str] = []
    paths = audio_storage.transcript_paths(settings, recording_id)
    new_paths = audio_storage.transcript_paths(settings, new_recording_id)

    for key in ("markdown", "machine"):
        if key not in parsed:
            continue
        metadata, body = parsed[key]  # type: ignore[misc]
        metadata = {**metadata, "recording_id": new_recording_id, "question_id": new_question_id}
        new_paths[key].parent.mkdir(parents=True, exist_ok=True)
        atomic_write(new_paths[key], dumps(metadata, body))
        paths[key].unlink()
        moved.append(f"{paths[key].name} -> {new_paths[key].name}")

    if "json" in parsed:
        payload = parsed["json"]
        if isinstance(payload, dict):
            payload = {**payload, "recording_id": new_recording_id, "question_id": new_question_id}
        atomic_write(new_paths["json"], json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        paths["json"].unlink()
        moved.append(f"{paths['json'].name} -> {new_paths['json'].name}")
    return moved


def _move_transcript_revisions(
    settings: Settings, recording_id: str, new_recording_id: str, moved: list[str]
) -> None:
    old = settings.revisions_dir / f"transcript-{recording_id}"
    if old.is_dir():
        new = settings.revisions_dir / f"transcript-{new_recording_id}"
        shutil.move(str(old), str(new))
        moved.append(f"{old.name}/ -> {new.name}/")
