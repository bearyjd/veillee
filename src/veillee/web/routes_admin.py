"""The son's view. Transcripts live here and nowhere else.

A machine transcript of an elderly man with an Irish accent will get his own
mother's name wrong. Showing him that is a way of making him feel stupid, so
transcripts are drafts on this page only, marked plainly as unreviewed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import queue as queue_module
from .. import repository
from ..config import Settings
from ..questions import QuestionBank
from ..storage import audio as audio_storage
from ..storage.answers import atomic_write, save_revision
from ..storage.frontmatter import FrontmatterError, dumps, loads
from ..storage.gitrepo import autocommit
from ..storage.paths import utc_now_iso
from .deps import get_bank, get_db, get_settings
from .templating import build_templates

router = APIRouter()
templates = build_templates()


@router.get("/admin", response_class=HTMLResponse)
def admin_home(
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    bank: QuestionBank = Depends(get_bank),
) -> HTMLResponse:
    """Recordings, their transcripts, and whether they have been reviewed."""
    recordings = repository.all_recordings(connection)
    rows = []
    for recording in recordings:
        transcript = audio_storage.transcript_paths(settings, recording.recording_id)["markdown"]
        reviewed = False
        if transcript.exists():
            try:
                metadata, _ = loads(transcript.read_text(encoding="utf-8"))
                reviewed = bool(metadata.get("reviewed", False))
            except (FrontmatterError, OSError):
                reviewed = False
        rows.append(
            {
                "recording": recording,
                "has_transcript": transcript.exists(),
                "reviewed": reviewed,
                "question": bank.by_id(recording.question_id),
            }
        )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"rows": rows, "queue": queue_module.depth(connection)},
    )


def _transcript_or_404(settings: Settings, recording_id: str) -> Path:
    path = audio_storage.transcript_paths(settings, recording_id)["markdown"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="No transcript yet for that recording")
    return path


@router.get("/admin/transcript/{recording_id}", response_class=HTMLResponse)
def view_transcript(
    request: Request,
    recording_id: str,
    connection: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    path = _transcript_or_404(settings, recording_id)
    try:
        metadata, body = loads(path.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise HTTPException(status_code=500, detail=f"Transcript is unreadable: {exc}") from exc
    return templates.TemplateResponse(
        request,
        "admin_transcript.html",
        {
            "recording": repository.get_recording(connection, recording_id),
            "metadata": metadata,
            "body": body,
            "recording_id": recording_id,
        },
    )


@router.post("/admin/transcript/{recording_id}")
def save_transcript(
    recording_id: str,
    body: str = Form(...),
    reviewed: str = Form(""),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Save an edit. The machine original is preserved, never overwritten."""
    path = _transcript_or_404(settings, recording_id)
    try:
        metadata, existing = loads(path.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise HTTPException(status_code=500, detail=f"Transcript is unreadable: {exc}") from exc

    save_revision(settings, f"transcript-{recording_id}", path)

    history = list(metadata.get("history") or [])
    if not any(entry.get("kind") == "machine_original" for entry in history):
        # First edit: keep the machine's words verbatim, forever.
        machine_path = path.with_suffix(".machine.md")
        if not machine_path.exists():
            atomic_write(machine_path, dumps(dict(metadata), existing))
        history.append(
            {
                "kind": "machine_original",
                "saved": utc_now_iso(),
                "file": machine_path.name,
            }
        )
    history.append({"kind": "edit", "saved": utc_now_iso()})

    updated = {**metadata, "reviewed": bool(reviewed), "updated": utc_now_iso(), "history": history}
    atomic_write(path, dumps(updated, body))
    autocommit(
        settings.data_dir,
        f"transcript: {recording_id} reviewed",
        enabled=settings.git_autocommit,
    )
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/requeue/{recording_id}")
def requeue_transcription(
    recording_id: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> RedirectResponse:
    """Give a dead-lettered or missing transcription another go."""
    if repository.get_recording(connection, recording_id) is None:
        raise HTTPException(status_code=404, detail="No such recording")
    queue_module.requeue(connection, recording_id)
    return RedirectResponse("/admin", status_code=303)
