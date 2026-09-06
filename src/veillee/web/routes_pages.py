"""The pages he actually looks at. Everything is one click from home."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import repository
from ..config import Settings
from ..models import Question
from ..questions import QuestionBank
from ..storage.answers import load_answer
from . import auth
from .deps import get_bank, get_db, get_settings
from .templating import build_templates

router = APIRouter()
templates = build_templates()


def _require_question(bank: QuestionBank, question_id: str) -> Question:
    question = bank.by_id(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="No such question")
    return question


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
) -> HTMLResponse:
    """Continue, a random question, browse by chapter, everything so far."""
    resume, resume_reason = repository.continue_where_left_off(connection, bank)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "progress": repository.progress(connection, bank),
            "resume": resume,
            "resume_reason": resume_reason,
            "random_question": repository.random_unanswered(connection, bank),
            "chapters": repository.chapter_summaries(connection, bank),
        },
    )


@router.get("/chapters", response_class=HTMLResponse)
def chapters(
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "chapters.html",
        {"chapters": repository.chapter_summaries(connection, bank)},
    )


@router.get("/chapter/{slug}", response_class=HTMLResponse)
def chapter(
    request: Request,
    slug: str,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
) -> HTMLResponse:
    chapter_meta = bank.chapter_by_slug(slug)
    if chapter_meta is None:
        raise HTTPException(status_code=404, detail="No such chapter")
    return templates.TemplateResponse(
        request,
        "chapter.html",
        {
            "chapter": chapter_meta,
            "questions": bank.in_chapter(slug),
            "answers": repository.answers_for_chapter(connection, slug),
            "answered": repository.answered_ids(connection),
        },
    )


@router.get("/question/{question_id}", response_class=HTMLResponse)
def question_page(
    request: Request,
    question_id: str,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    """One question per page. The body is read from disk, not the index."""
    question = _require_question(bank, question_id)
    answer = load_answer(settings, question)
    return templates.TemplateResponse(
        request,
        "question.html",
        {
            "question": question,
            "answer": answer,
            "recordings": repository.recordings_for(connection, question_id),
            "photographs": repository.photographs_for(connection, question_id),
            "next_question": _next_question(bank, question_id),
        },
    )


def _next_question(bank: QuestionBank, question_id: str) -> Question | None:
    ids = [q.id for q in bank.questions]
    try:
        position = ids.index(question_id)
    except ValueError:
        return None
    return bank.questions[position + 1] if position + 1 < len(bank.questions) else None


@router.get("/random")
def random_question(
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
) -> RedirectResponse:
    question = repository.random_unanswered(connection, bank)
    if question is None:
        return RedirectResponse("/answers", status_code=303)
    return RedirectResponse(f"/question/{question.id}", status_code=303)


@router.get("/answers", response_class=HTMLResponse)
def answers_page(
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
) -> HTMLResponse:
    """Everything answered so far, in chapter order."""
    return templates.TemplateResponse(
        request,
        "answers.html",
        {
            "answers": repository.all_written_answers(connection),
            "progress": repository.progress(connection, bank),
            "later": repository.marked_later_ids(connection),
            "bank": bank,
        },
    )


@router.get("/book", response_class=HTMLResponse)
def book(
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
    bank: QuestionBank = Depends(get_bank),
) -> HTMLResponse:
    """Everything he has written, in reading order, laid out to be printed.

    One page, chapter by chapter, with the photographs in place and a note
    where there is a recording. Print it and you have the book.
    """
    answers = {a.question_id: a for a in repository.all_written_answers(connection)}
    photographs: dict[str, list] = {}
    for photo in repository.all_photographs(connection):
        photographs.setdefault(photo.question_id, []).append(photo)
    recordings: dict[str, list] = {}
    for recording in repository.all_recordings(connection):
        recordings.setdefault(recording.question_id, []).append(recording)

    chapters = []
    for chapter in bank.chapters:
        entries = []
        for question in bank.in_chapter(chapter.slug):
            answer = answers.get(question.id)
            pictures = photographs.get(question.id, [])
            spoken = recordings.get(question.id, [])
            if answer or pictures or spoken:
                entries.append(
                    {
                        "question": question,
                        "answer": answer,
                        "photographs": pictures,
                        "recordings": spoken,
                    }
                )
        if entries:
            chapters.append({"chapter": chapter, "entries": entries})

    return templates.TemplateResponse(
        request,
        "book.html",
        {
            "chapters": chapters,
            "progress": repository.progress(connection, bank),
        },
    )


@router.get("/enter", response_class=HTMLResponse, response_model=None)
def enter_form(
    request: Request, settings: Settings = Depends(get_settings)
) -> HTMLResponse | RedirectResponse:
    if not auth.passcodes_enabled(settings):
        return RedirectResponse("/", status_code=303)
    next_path = request.query_params.get("next", "/")
    return templates.TemplateResponse(
        request, "enter.html", {"next_path": next_path, "failed": False}
    )


@router.post("/enter", response_class=HTMLResponse, response_model=None)
def enter_submit(
    request: Request,
    passcode: str = Form(""),
    next_path: str = Form("/"),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse | RedirectResponse:
    role = auth.role_for_passcode(passcode, settings)
    if role is None:
        return templates.TemplateResponse(
            request,
            "enter.html",
            {"next_path": next_path, "failed": True},
            status_code=401,
        )
    safe_next = next_path if next_path.startswith("/") and "//" not in next_path else "/"
    response = RedirectResponse(safe_next, status_code=303)
    auth.issue_cookie(response, settings, role)
    return response
