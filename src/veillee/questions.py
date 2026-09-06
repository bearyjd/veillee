"""The question bank: YAML on disk, loaded at startup, editable without code changes.

Custom questions he adds himself live in `data/custom_questions.yaml` rather than
in `questions/`, so they are part of the archive and survive a reindex.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import (
    CUSTOM_CHAPTER_ORDER,
    CUSTOM_CHAPTER_SLUG,
    CUSTOM_CHAPTER_TITLE,
    Chapter,
    Question,
)
from .storage.answers import atomic_write
from .storage.paths import parse_question_id

logger = logging.getLogger(__name__)


class QuestionBankError(ValueError):
    """The question bank on disk is malformed."""


@dataclass(frozen=True)
class QuestionBank:
    """An immutable snapshot of every question the site knows about."""

    questions: tuple[Question, ...]
    chapters: tuple[Chapter, ...]

    def by_id(self, question_id: str) -> Question | None:
        for question in self.questions:
            if question.id == question_id:
                return question
        return None

    def in_chapter(self, chapter_slug: str) -> tuple[Question, ...]:
        return tuple(q for q in self.questions if q.chapter_slug == chapter_slug)

    def chapter_by_slug(self, slug: str) -> Chapter | None:
        for chapter in self.chapters:
            if chapter.slug == slug:
                return chapter
        return None

    def next_custom_id(self) -> str:
        """Next free id in the 'c' series used for his own questions."""
        used = [parse_question_id(q.id)[1] for q in self.questions if q.id.startswith("c")]
        return f"c{(max(used) + 1) if used else 1:03d}"


def _parse_question(raw: Any, chapter: Chapter, *, custom: bool, source: Path) -> Question:
    if not isinstance(raw, dict):
        raise QuestionBankError(f"{source}: each question must be a mapping, got {type(raw)}")
    for key in ("id", "text"):
        if not raw.get(key):
            raise QuestionBankError(f"{source}: question is missing required key {key!r}")
    parse_question_id(str(raw["id"]))
    follow_ups = raw.get("follow_ups") or []
    if not isinstance(follow_ups, list):
        raise QuestionBankError(f"{source}: follow_ups must be a list for {raw['id']}")
    return Question(
        id=str(raw["id"]),
        chapter_slug=chapter.slug,
        chapter_order=chapter.order,
        chapter_title=chapter.title,
        text=str(raw["text"]).strip(),
        hint=str(raw["hint"]).strip() if raw.get("hint") else None,
        follow_ups=tuple(str(item).strip() for item in follow_ups),
        custom=custom,
        pinned=bool(raw.get("pinned", False)),
        note=str(raw["note"]).strip() if raw.get("note") else None,
    )


def _parse_chapter_file(path: Path) -> tuple[Chapter, list[Question]]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise QuestionBankError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise QuestionBankError(f"{path}: file must contain a YAML mapping")

    raw_chapter = document.get("chapter")
    if not isinstance(raw_chapter, dict):
        raise QuestionBankError(f"{path}: missing a 'chapter' mapping")
    for key in ("order", "slug", "title"):
        if raw_chapter.get(key) in (None, ""):
            raise QuestionBankError(f"{path}: chapter is missing {key!r}")

    chapter = Chapter(
        order=int(raw_chapter["order"]),
        slug=str(raw_chapter["slug"]),
        title=str(raw_chapter["title"]),
    )
    raw_questions = document.get("questions") or []
    if not isinstance(raw_questions, list):
        raise QuestionBankError(f"{path}: 'questions' must be a list")
    questions = [
        _parse_question(item, chapter, custom=False, source=path) for item in raw_questions
    ]
    return chapter, questions


def custom_chapter() -> Chapter:
    """The chapter that holds questions he wrote himself."""
    return Chapter(CUSTOM_CHAPTER_ORDER, CUSTOM_CHAPTER_SLUG, CUSTOM_CHAPTER_TITLE)


def load_custom_questions(path: Path) -> list[Question]:
    """Read his own questions from the archive. A missing file simply means none yet."""
    if not path.exists():
        return []
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise QuestionBankError(f"{path}: not valid YAML: {exc}") from exc
    raw_questions = document.get("questions") or []
    if not isinstance(raw_questions, list):
        raise QuestionBankError(f"{path}: 'questions' must be a list")
    chapter = custom_chapter()
    return [_parse_question(item, chapter, custom=True, source=path) for item in raw_questions]


def append_custom_question(
    path: Path,
    question_id: str,
    text: str,
    *,
    pinned: bool = False,
    note: str | None = None,
) -> None:
    """Add a question to the archive file, atomically.

    `pinned` puts it at the top of the home page until he has answered it, which
    is how someone in the family asks him something specific.
    """
    existing: list[dict[str, object]] = []
    if path.exists():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        existing = list(document.get("questions") or [])
    entry: dict[str, object] = {"id": question_id, "text": text}
    if pinned:
        entry["pinned"] = True
    if note:
        entry["note"] = note
    existing.append(entry)
    payload = yaml.safe_dump(
        {"questions": existing}, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    header = "# Questions he added himself. Part of the archive; safe to edit by hand.\n"
    atomic_write(path, header + payload)


def load_bank(questions_dir: Path, custom_questions_path: Path | None = None) -> QuestionBank:
    """Load the whole bank. Raises QuestionBankError rather than starting up half-loaded."""
    if not questions_dir.is_dir():
        raise QuestionBankError(f"question directory does not exist: {questions_dir}")

    chapters: list[Chapter] = []
    questions: list[Question] = []
    for path in sorted(questions_dir.glob("*.yaml")):
        chapter, chapter_questions = _parse_chapter_file(path)
        chapters.append(chapter)
        questions.extend(chapter_questions)

    if custom_questions_path is not None:
        custom = load_custom_questions(custom_questions_path)
        if custom:
            chapters.append(custom_chapter())
            questions.extend(custom)

    seen: set[str] = set()
    for question in questions:
        if question.id in seen:
            raise QuestionBankError(f"duplicate question id: {question.id}")
        seen.add(question.id)

    if not questions:
        raise QuestionBankError(f"no questions found in {questions_dir}")

    logger.info("loaded %d questions across %d chapters", len(questions), len(chapters))
    return QuestionBank(
        questions=tuple(questions),
        chapters=tuple(sorted(chapters, key=lambda c: c.order)),
    )
