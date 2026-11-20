"""Both audio paths.

Path A is MediaRecorder, uploading chunks while he is still talking. Path B is a
plain file input for a recording made elsewhere — Voice Memos on an iPad, say.
Path B is not a degraded mode; it is a supported way to use the site, and it
exists because Safari's MediaRecorder is the least predictable piece here.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import FormData, UploadFile
from starlette.types import Message

from .. import ingest, repository
from ..config import Settings
from ..questions import QuestionBank
from ..storage import audio as audio_storage
from ..storage.answers import move_to_trash
from ..storage.gitrepo import autocommit
from .deps import get_bank, get_db, get_settings
from .json_body import read_capped_json

logger = logging.getLogger(__name__)
router = APIRouter()

CHUNK_LIMIT_BYTES = 32 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
PLAYABLE = {"opus": ("audio/ogg", "opus_path"), "flac": ("audio/flac", "flac_path")}
DELETE_CONFIRMATION = "delete"


def _safe_id(value: str, label: str) -> str:
    if not SAFE_ID.match(value):
        raise HTTPException(status_code=400, detail=f"Malformed {label}")
    return value


def _require_question_id(bank: QuestionBank, question_id: str) -> str:
    if bank.by_id(question_id) is None:
        raise HTTPException(status_code=404, detail="No such question")
    return question_id


def _refuse_declared_oversize(request: Request, limit: int, detail: str) -> None:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            too_big = int(declared) > limit
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed Content-Length") from None
        if too_big:
            raise HTTPException(status_code=413, detail=detail)


async def _read_capped_body(request: Request, limit: int) -> bytes:
    """Read the request body, refusing with 413 before buffering more than `limit`."""
    _refuse_declared_oversize(request, limit, "Chunk too large")

    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="Chunk too large")
    return bytes(body)


async def _read_capped_form(request: Request, limit: int) -> FormData:
    """Parse a multipart body, refusing with 413 before more than `limit` bytes arrive.

    FastAPI's File()/Form() parameters parse (and spool to disk) the whole body
    before the handler runs, so the cap has to sit in front of the parser.
    """
    detail = "That recording is too large"
    _refuse_declared_oversize(request, limit, detail)

    received = 0

    async def capped_receive() -> Message:
        nonlocal received
        message = await request.receive()
        received += len(message.get("body", b""))
        if received > limit:
            raise HTTPException(status_code=413, detail=detail)
        return message

    return await Request(request.scope, capped_receive).form()


def _suffix_for(filename: str | None, fallback: str) -> str:
    if not filename or "." not in filename:
        return fallback
    suffix = "." + filename.rsplit(".", 1)[-1].lower()
    return suffix if suffix in audio_storage.SUPPORTED_UPLOAD_SUFFIXES else fallback


@router.post("/api/upload/{question_id}")
async def upload_recording(
    question_id: str,
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Path B: a recording made on his phone, uploaded here."""
    _require_question_id(bank, question_id)
    # Allow for the multipart framing around the file itself.
    form = await _read_capped_form(request, settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES)
    try:
        return await _store_upload(question_id, form, request, connection, settings)
    finally:
        await form.close()


async def _store_upload(
    question_id: str,
    form: FormData,
    request: Request,
    connection: sqlite3.Connection,
    settings: Settings,
) -> JSONResponse:
    file = form.get("file")
    if not isinstance(file, UploadFile):
        raise HTTPException(status_code=422, detail="No recording was attached")
    device = form.get("device")
    device = device if isinstance(device, str) else ""
    suffix = _suffix_for(file.filename, ".m4a")

    staging_id = uuid.uuid4().hex
    staging_dir = ingest.start_upload(settings, staging_id, {"question_id": question_id})
    staging = staging_dir / f"incoming{suffix}"

    written = 0
    try:
        with staging.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="That recording is too large")
                output.write(chunk)

        recording = ingest.ingest_recording(
            settings,
            connection,
            question_id=question_id,
            source_path=staging,
            original_suffix=suffix,
            device=device or request.headers.get("user-agent", ""),
            source="upload",
        )
    except HTTPException:
        ingest.discard_upload(settings, staging_id)
        raise
    except ingest.IngestError as exc:
        ingest.discard_upload(settings, staging_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        ingest.discard_upload(settings, staging_id)
        logger.error("upload failed for %s: %s", question_id, exc)
        raise HTTPException(status_code=500, detail=f"Could not save the recording: {exc}") from exc

    ingest.discard_upload(settings, staging_id)
    return JSONResponse(_recording_payload(recording), status_code=201)


@router.post("/api/recording/{question_id}/start")
def start_recording(
    question_id: str,
    request: Request,
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Path A step 1: open a session that chunks will be appended to."""
    _require_question_id(bank, question_id)
    upload_id = uuid.uuid4().hex
    try:
        ingest.start_upload(
            settings,
            upload_id,
            {
                "question_id": question_id,
                "device": request.headers.get("user-agent", ""),
                "started": True,
            },
        )
    except ingest.UploadLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return JSONResponse({"upload_id": upload_id}, status_code=201)


@router.post("/api/recording/{upload_id}/chunk")
async def upload_chunk(
    upload_id: str,
    request: Request,
    index: int = 0,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Path A step 2: one chunk, written to disk the moment it lands."""
    _safe_id(upload_id, "recording session")
    if index < 0:
        raise HTTPException(status_code=400, detail="Malformed chunk index")

    payload = await _read_capped_body(request, CHUNK_LIMIT_BYTES)
    if not payload:
        raise HTTPException(status_code=400, detail="Empty chunk")

    try:
        ingest.write_chunk(settings, upload_id, index, payload)
    except ingest.UploadLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ingest.IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("could not write chunk %d of %s: %s", index, upload_id, exc)
        raise HTTPException(status_code=500, detail=f"Could not save audio: {exc}") from exc
    return JSONResponse({"received": index, "bytes": len(payload)})


@router.post("/api/recording/{upload_id}/finish")
async def finish_recording(
    upload_id: str,
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Path A step 3: assemble whatever arrived and run the pipeline."""
    _safe_id(upload_id, "recording session")
    try:
        metadata = ingest.read_upload_metadata(settings, upload_id)
    except ingest.IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    question_id = str(metadata.get("question_id", ""))
    if not question_id:
        raise HTTPException(status_code=422, detail="That recording session has no question")

    suffix = ".webm"
    try:
        assembled = ingest.assemble_chunks(settings, upload_id, suffix)
        recording = ingest.ingest_recording(
            settings,
            connection,
            question_id=question_id,
            source_path=assembled,
            original_suffix=suffix,
            device=str(metadata.get("device", "")) or request.headers.get("user-agent", ""),
            source="recorder",
        )
    except ingest.IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("could not finish %s: %s", upload_id, exc)
        raise HTTPException(status_code=500, detail=f"Could not save the recording: {exc}") from exc
    finally:
        ingest.discard_upload(settings, upload_id)

    return JSONResponse(_recording_payload(recording), status_code=201)


def _recording_payload(recording: object) -> dict[str, object]:
    return {
        "recording_id": getattr(recording, "recording_id", ""),
        "question_id": getattr(recording, "question_id", ""),
        "duration_seconds": getattr(recording, "duration_seconds", 0.0),
        "playback_url": f"/audio/{getattr(recording, 'recording_id', '')}.opus",
    }


@router.get("/audio/{recording_id}.{extension}")
def play_recording(
    recording_id: str,
    extension: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> FileResponse:
    """Serve a derived file. Paths come from the index, never from the URL."""
    _safe_id(recording_id, "recording")
    if extension not in PLAYABLE:
        raise HTTPException(status_code=404, detail="Not found")

    recording = repository.get_recording(connection, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="No such recording")

    media_type, attribute = PLAYABLE[extension]
    path = Path(str(getattr(recording, attribute)))
    if not path.exists():
        raise HTTPException(status_code=404, detail="That audio file is missing from disk")
    return FileResponse(path, media_type=media_type, filename=f"{recording_id}.{extension}")


@router.post("/api/recording/{recording_id}/delete")
async def delete_recording(
    recording_id: str,
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Deleting needs the word typed out, and still only moves to .trash/."""
    _safe_id(recording_id, "recording")
    payload = await read_capped_json(request)
    raw = payload.get("confirm", "") if isinstance(payload, dict) else ""
    confirmation = str(raw).strip().lower()
    if confirmation != DELETE_CONFIRMATION:
        raise HTTPException(
            status_code=422,
            detail=f"Type the word '{DELETE_CONFIRMATION}' to remove this recording",
        )

    recording = repository.get_recording(connection, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="No such recording")

    doomed = [
        Path(recording.original_path),
        Path(recording.flac_path),
        Path(recording.opus_path),
        Path(recording.sidecar_path),
    ]
    # The transcript is derived from the audio, so it goes with it. Leaving it
    # behind orphans a machine draft of a recording that no longer exists.
    transcripts = audio_storage.transcript_paths(settings, recording_id)
    doomed.extend(transcripts.values())
    # Edits to the transcript are kept under .revisions/, and follow it too.
    doomed.append(audio_storage.transcript_revisions_dir(settings, recording_id))

    moved = []
    for path in doomed:
        destination = move_to_trash(settings, path)
        if destination:
            moved.append(str(destination))

    repository.delete_recording_row(connection, recording_id)
    autocommit(
        settings.data_dir,
        f"recording: {recording_id} moved to trash",
        enabled=settings.git_autocommit,
    )
    return JSONResponse({"deleted": recording_id, "moved_to_trash": moved})
