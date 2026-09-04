"""Core value objects. All frozen: we build new ones rather than mutating."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

STATUS_ANSWERED = "answered"
STATUS_SKIPPED = "skipped"
STATUS_LATER = "later"
VALID_STATUSES = frozenset({STATUS_ANSWERED, STATUS_SKIPPED, STATUS_LATER})

CUSTOM_CHAPTER_ORDER = 15
CUSTOM_CHAPTER_SLUG = "questions-he-asked-himself"
CUSTOM_CHAPTER_TITLE = "Questions he asked himself"


@dataclass(frozen=True)
class Chapter:
    order: int
    slug: str
    title: str


@dataclass(frozen=True)
class Question:
    id: str
    chapter_slug: str
    chapter_order: int
    chapter_title: str
    text: str
    hint: str | None = None
    follow_ups: tuple[str, ...] = ()
    custom: bool = False

    @property
    def chapter(self) -> Chapter:
        return Chapter(self.chapter_order, self.chapter_slug, self.chapter_title)


@dataclass(frozen=True)
class Answer:
    question_id: str
    question_text: str
    chapter_slug: str
    chapter_order: int
    body: str
    status: str
    created: str
    updated: str
    word_count: int
    custom: bool
    path: Path

    def with_body(self, body: str, *, updated: str, word_count: int) -> Answer:
        """Return a new Answer carrying the given body. Never mutates."""
        return replace(self, body=body, updated=updated, word_count=word_count)

    @property
    def is_written(self) -> bool:
        return self.status == STATUS_ANSWERED and bool(self.body.strip())


@dataclass(frozen=True)
class Recording:
    recording_id: str
    question_id: str
    created: str
    duration_seconds: float
    device: str
    original_path: str
    flac_path: str
    opus_path: str
    sidecar_path: str
    sha256_original: str
    sha256_flac: str
    sha256_opus: str
    source: str
    transcript_path: str | None = None
    transcript_reviewed: bool = False


@dataclass(frozen=True)
class QueueJob:
    id: int
    recording_id: str
    state: str
    attempts: int
    next_attempt_at: str
    last_error: str | None
