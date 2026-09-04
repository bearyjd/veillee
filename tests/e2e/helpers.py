"""Shared browser helpers."""

from __future__ import annotations

from typing import Any

EDITOR_READY_MS = 15_000


def editor_locator(page: Any) -> Any:
    """Whichever editor is actually live: Milkdown, or the plain fallback.

    Autosave is identical either way, which is the point: the test does not
    care which one loaded, only that the words survive.
    """
    milkdown = page.locator(".ProseMirror").first
    try:
        milkdown.wait_for(state="visible", timeout=EDITOR_READY_MS)
        return milkdown
    except Exception:
        fallback = page.locator("#editor-fallback")
        fallback.wait_for(state="visible", timeout=EDITOR_READY_MS)
        return fallback


def type_answer(page: Any, text: str) -> None:
    """Type into the editor the way a person does, one key at a time."""
    target = editor_locator(page)
    target.click()
    page.keyboard.type(text, delay=8)


def read_answer_from_disk(data_dir: Any, pattern: str) -> str:
    matches = list(data_dir.rglob(pattern))
    if not matches:
        return ""
    return matches[0].read_text(encoding="utf-8")
