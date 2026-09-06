"""Photographs.

He photographs framed prints with his phone and emails them. This is the same
thing without the email: the file he took is kept untouched, a screen-sized copy
is derived, and a caption in his own words travels with both.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .. import ingest, repository
from ..config import Settings
from ..questions import QuestionBank
from ..storage import photos as photo_storage
from ..storage.answers import atomic_write, move_to_trash
from ..storage.gitrepo import autocommit
from .deps import get_bank, get_db, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
DELETE_CONFIRMATION = "delete"
MAX_CAPTION = 2000


def _safe_id(value: str) -> str:
    if not SAFE_ID.match(value):
        raise HTTPException(status_code=400, detail="Malformed photograph id")
    return value


def _suffix_for(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ".jpg"
    suffix = "." + filename.rsplit(".", 1)[-1].lower()
    return suffix if suffix in photo_storage.SUPPORTED_SUFFIXES else ".jpg"


@router.post("/api/photo/{question_id}")
async def upload_photograph(
    question_id: str,
    file: UploadFile = File(...),
    caption: str = Form(""),
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if bank.by_id(question_id) is None:
        raise HTTPException(status_code=404, detail="No such question")
    if len(caption) > MAX_CAPTION:
        raise HTTPException(status_code=422, detail="That caption is too long")

    suffix = _suffix_for(file.filename)
    staging_id = uuid.uuid4().hex
    staging_dir = ingest.start_upload(settings, staging_id, {"question_id": question_id})
    staging = staging_dir / f"incoming{suffix}"

    written = 0
    try:
        with staging.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="That photograph is too large")
                output.write(chunk)

        photograph = ingest.ingest_photograph(
            settings,
            connection,
            question_id=question_id,
            source_path=staging,
            original_suffix=suffix,
            caption=caption,
        )
    except ingest.IngestError as exc:
        ingest.discard_upload(settings, staging_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        ingest.discard_upload(settings, staging_id)
        logger.error("photograph upload failed for %s: %s", question_id, exc)
        raise HTTPException(status_code=500, detail=f"Could not save it: {exc}") from exc

    ingest.discard_upload(settings, staging_id)
    return JSONResponse(
        {
            "photo_id": photograph.photo_id,
            "question_id": photograph.question_id,
            "caption": photograph.caption,
            "view_url": f"/photo/{photograph.photo_id}.jpg",
        },
        status_code=201,
    )


@router.get("/photo/{photo_id}.jpg")
def view_photograph(
    photo_id: str, connection: sqlite3.Connection = Depends(get_db)
) -> FileResponse:
    """The screen copy. Paths come from the index, never from the URL."""
    _safe_id(photo_id)
    photograph = repository.get_photograph(connection, photo_id)
    if photograph is None:
        raise HTTPException(status_code=404, detail="No such photograph")
    path = Path(photograph.view_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="That image is missing from disk")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/photo/{photo_id}/original")
def original_photograph(
    photo_id: str, connection: sqlite3.Connection = Depends(get_db)
) -> FileResponse:
    """The file exactly as he gave it, for printing or archiving."""
    _safe_id(photo_id)
    photograph = repository.get_photograph(connection, photo_id)
    if photograph is None:
        raise HTTPException(status_code=404, detail="No such photograph")
    path = Path(photograph.original_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="That image is missing from disk")
    return FileResponse(path, filename=path.name)


@router.post("/api/photo/{photo_id}/caption")
async def set_caption(
    photo_id: str,
    caption: str = Form(...),
    connection: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Captions are the whole value of an old photograph. They must be editable."""
    _safe_id(photo_id)
    if len(caption) > MAX_CAPTION:
        raise HTTPException(status_code=422, detail="That caption is too long")
    photograph = repository.get_photograph(connection, photo_id)
    if photograph is None:
        raise HTTPException(status_code=404, detail="No such photograph")

    sidecar = Path(photograph.sidecar_path)
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["caption"] = caption.strip()
    atomic_write(sidecar, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    connection.execute(
        "UPDATE photographs SET caption = ? WHERE photo_id = ?", (caption.strip(), photo_id)
    )
    autocommit(
        settings.data_dir, f"photograph: {photo_id} caption", enabled=settings.git_autocommit
    )
    return JSONResponse({"photo_id": photo_id, "caption": caption.strip()})


@router.post("/api/photo/{photo_id}/delete")
async def delete_photograph(
    photo_id: str,
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Same rule as recordings: type the word, and nothing is truly deleted."""
    _safe_id(photo_id)
    body = await request.json()
    raw = body.get("confirm", "") if isinstance(body, dict) else ""
    if str(raw).strip().lower() != DELETE_CONFIRMATION:
        raise HTTPException(
            status_code=422,
            detail=f"Type the word '{DELETE_CONFIRMATION}' to remove this photograph",
        )
    photograph = repository.get_photograph(connection, photo_id)
    if photograph is None:
        raise HTTPException(status_code=404, detail="No such photograph")

    moved = []
    for path_text in (
        photograph.original_path,
        photograph.view_path,
        photograph.sidecar_path,
    ):
        destination = move_to_trash(settings, Path(path_text))
        if destination:
            moved.append(str(destination))

    repository.delete_photograph_row(connection, photo_id)
    autocommit(
        settings.data_dir,
        f"photograph: {photo_id} moved to trash",
        enabled=settings.git_autocommit,
    )
    return JSONResponse({"deleted": photo_id, "moved_to_trash": moved})
