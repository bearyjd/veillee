"""Writing, autosaving, skipping, and adding his own questions.

Autosave is the only save. There is no button, so these endpoints are the last
line between what he typed and losing it: every one writes a revision first and
reports a real result rather than swallowing an error.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import Settings
from ..index import upsert_answer
from ..models import STATUS_ANSWERED, STATUS_LATER, STATUS_SKIPPED, Question
from ..questions import QuestionBank, append_custom_question
from ..storage.answers import load_answer, write_answer
from ..storage.gitrepo import autocommit
from .deps import app_state, get_bank, get_db, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_BODY_CHARS = 2_000_000
MAX_QUESTION_CHARS = 500


def _require_question(bank: QuestionBank, question_id: str) -> Question:
    question = bank.by_id(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="No such question")
    return question


def _persist(
    settings: Settings,
    connection: sqlite3.Connection,
    question: Question,
    body: str,
    status: str,
) -> dict[str, object]:
    """Write to disk, update the index, then commit. Disk first, always."""
    answer = write_answer(settings, question, body, status=status)
    upsert_answer(connection, answer)
    autocommit(
        settings.data_dir,
        f"answer: {question.id} updated",
        enabled=settings.git_autocommit,
    )
    return {
        "saved": True,
        "question_id": answer.question_id,
        "updated": answer.updated,
        "word_count": answer.word_count,
        "status": answer.status,
    }


@router.post("/api/answer/{question_id}")
async def save_answer(
    question_id: str,
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Autosave. Called every five seconds and on blur."""
    question = _require_question(bank, question_id)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Expected a JSON object")

    body = payload.get("body", "")
    if not isinstance(body, str):
        raise HTTPException(status_code=422, detail="'body' must be text")
    if len(body) > MAX_BODY_CHARS:
        raise HTTPException(status_code=413, detail="That answer is too long to save")

    try:
        result = _persist(settings, connection, question, body, STATUS_ANSWERED)
    except OSError as exc:
        # He must be told, loudly, rather than shown a false "Saved".
        logger.error("could not save %s: %s", question_id, exc)
        raise HTTPException(status_code=500, detail=f"Could not write to disk: {exc}") from exc
    return JSONResponse(result)


@router.post("/question/{question_id}/skip")
def skip_question(
    question_id: str,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Skip for now. Equal in weight to Next, and completely reversible."""
    question = _require_question(bank, question_id)
    _mark(settings, connection, question, STATUS_SKIPPED)
    return RedirectResponse(_after(bank, question_id), status_code=303)


@router.post("/question/{question_id}/later")
def come_back_later(
    question_id: str,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Come back to this. The home page will offer it first next time."""
    question = _require_question(bank, question_id)
    _mark(settings, connection, question, STATUS_LATER)
    return RedirectResponse(_after(bank, question_id), status_code=303)


def _mark(
    settings: Settings, connection: sqlite3.Connection, question: Question, status: str
) -> None:
    """Record a status without disturbing anything already written."""
    existing = load_answer(settings, question)
    body = existing.body if existing else ""
    try:
        _persist(settings, connection, question, body, status)
    except OSError as exc:
        logger.error("could not mark %s as %s: %s", question.id, status, exc)
        raise HTTPException(status_code=500, detail=f"Could not write to disk: {exc}") from exc


def _after(bank: QuestionBank, question_id: str) -> str:
    ids = [q.id for q in bank.questions]
    try:
        position = ids.index(question_id)
    except ValueError:
        return "/"
    if position + 1 < len(bank.questions):
        return f"/question/{bank.questions[position + 1].id}"
    return "/"


@router.post("/questions/new")
def add_own_question(
    request: Request,
    text: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """He can ask himself a question at any time."""
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="A question needs some words in it")
    if len(cleaned) > MAX_QUESTION_CHARS:
        raise HTTPException(status_code=422, detail="That question is too long")

    state = app_state(request)
    question_id = state.bank.next_custom_id()
    append_custom_question(settings.custom_questions_path, question_id, cleaned)
    state.reload_bank()
    autocommit(
        settings.data_dir,
        f"question: {question_id} added",
        enabled=settings.git_autocommit,
    )
    return RedirectResponse(f"/question/{question_id}", status_code=303)


@router.get("/api/answer/{question_id}")
def read_answer_api(
    question_id: str,
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Read back what is on disk. Used by the crash-recovery test."""
    question = _require_question(bank, question_id)
    answer = load_answer(settings, question)
    if answer is None:
        return JSONResponse({"body": "", "word_count": 0, "status": None, "updated": None})
    return JSONResponse(
        {
            "body": answer.body,
            "word_count": answer.word_count,
            "status": answer.status,
            "updated": answer.updated,
        }
    )
