"""YAML frontmatter documents.

The file on disk is the archive. This module is deliberately strict about
round-tripping: what we write, we must be able to read back byte-identically
after a no-op load/dump cycle, because `veillee reindex` trusts it completely.
"""

from __future__ import annotations

from typing import Any

import yaml

DELIMITER = "---"


class FrontmatterError(ValueError):
    """Raised when a document on disk is not a well-formed frontmatter file."""


def dumps(metadata: dict[str, Any], body: str) -> str:
    """Serialise metadata + body into a frontmatter document.

    Key order is preserved exactly as given, so the schema stays human-readable.
    """
    front = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    )
    body_text = body.strip("\n")
    trailer = f"{body_text}\n" if body_text else ""
    return f"{DELIMITER}\n{front}{DELIMITER}\n\n{trailer}"


def loads(text: str) -> tuple[dict[str, Any], str]:
    """Parse a frontmatter document into (metadata, body).

    Raises FrontmatterError rather than returning a half-parsed document: a
    silent partial read here would mean a silently truncated answer.
    """
    if not text.startswith(DELIMITER):
        raise FrontmatterError("document does not begin with a '---' frontmatter block")

    rest = text[len(DELIMITER) :]
    if rest.startswith("\n"):
        rest = rest[1:]

    closing = _find_closing_delimiter(rest)
    if closing is None:
        raise FrontmatterError("unterminated frontmatter block: no closing '---' found")

    raw_front, body = rest[:closing], rest[closing:]
    body = body.split("\n", 1)[1] if "\n" in body else ""

    try:
        metadata = yaml.safe_load(raw_front) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"frontmatter is not valid YAML: {exc}") from exc

    if not isinstance(metadata, dict):
        raise FrontmatterError("frontmatter must be a YAML mapping")

    return metadata, body.strip("\n")


def _find_closing_delimiter(text: str) -> int | None:
    """Return the offset of the line that closes the frontmatter block."""
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.rstrip("\r\n") == DELIMITER:
            return offset
        offset += len(line)
    return None
