"""Where things live on disk, and how their names are built.

Every name is derived deterministically from stable inputs, so a rebuild from
`data/` alone lands on exactly the same paths.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_QUESTION_ID = re.compile(r"^(?P<prefix>[a-z])(?P<number>\d{3,})$")
MAX_SLUG_LENGTH = 60


def slugify(text: str, *, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Turn free text into a stable, filesystem-safe slug."""
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("-", ascii_text).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0] or slug[:max_length]
    return slug or "untitled"


def parse_question_id(question_id: str) -> tuple[str, int]:
    """Split a question id such as 'q012' into ('q', 12)."""
    match = _QUESTION_ID.match(question_id)
    if not match:
        raise ValueError(f"malformed question id: {question_id!r}")
    return match.group("prefix"), int(match.group("number"))


def chapter_dirname(chapter_order: int, chapter_slug: str) -> str:
    """Directory name for a chapter, e.g. '02-childhood-and-home'."""
    return f"{chapter_order:02d}-{chapter_slug}"


def answer_relpath(chapter_order: int, chapter_slug: str, question_id: str, text: str) -> Path:
    """Relative path of an answer file inside data/answers/."""
    _, number = parse_question_id(question_id)
    return Path(chapter_dirname(chapter_order, chapter_slug)) / f"{number:03d}-{slugify(text)}.md"


def recording_id(question_id: str, when: datetime | None = None) -> str:
    """Build a recording id such as '20260903-141207-q012'."""
    moment = (when or datetime.now(UTC)).astimezone(UTC)
    return f"{moment:%Y%m%d-%H%M%S}-{question_id}"


def recording_dir_for(recording_id_value: str) -> Path:
    """Year/month directory a recording belongs in, derived from its own id."""
    stamp = recording_id_value.split("-", 1)[0]
    return Path(stamp[:4]) / stamp[4:6]


def utc_now_iso() -> str:
    """Current UTC time as a stable, sortable ISO-8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def revision_stamp(when: datetime | None = None) -> str:
    """Sub-second timestamp used to name revision files."""
    moment = (when or datetime.now(UTC)).astimezone(UTC)
    return moment.strftime("%Y%m%d-%H%M%S-%f")


def count_words(body: str) -> int:
    """Word count as a person would understand it."""
    return len(body.split())
