"""The formatting toolbar.

The specification asks for five buttons and nothing more: bold, italic,
heading, bullet list, quote. Milkdown ships a toolbar of its own that only
appears once you have already selected text — no use to someone who does not
know it is there — so Veillee renders its own, always visible.

Every test here asserts on the markdown that reached the disk, not on what the
page looked like. A toolbar button that styles the screen but writes nothing is
worse than no button at all.
"""

from __future__ import annotations

import time

import pytest

from tests.conftest import LiveServer
from tests.e2e.helpers import editor_locator

BUTTONS = ["bold", "italic", "heading", "bulletList", "quote"]


@pytest.fixture
def page(browser: object, live_server: LiveServer):
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url("/question/q012"), wait_until="load")
    editor_locator(page)
    page.wait_for_selector("#editor-toolbar:not([hidden])", timeout=20_000)
    yield page
    context.close()


def _answer_on_disk(live_server: LiveServer, timeout: float = 12.0) -> str:
    """Wait for autosave to land, then read the file a person would open."""
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        files = list(live_server.data_dir.rglob("012-*.md"))
        if files:
            text = files[0].read_text(encoding="utf-8")
            if "---" in text and text.split("---", 2)[-1].strip():
                return text
        time.sleep(0.25)
    return text


def _type_and_format(page: object, text: str, action: str, *, select: bool) -> None:
    editor = editor_locator(page)
    editor.click()
    page.keyboard.type(text, delay=10)  # type: ignore[attr-defined]
    if select:
        page.keyboard.press("Shift+Home")  # type: ignore[attr-defined]
    page.click(f"#editor-toolbar button[data-action='{action}']")
    page.wait_for_timeout(400)
    page.evaluate("() => window.veilleeSaveNow && window.veilleeSaveNow()")


class TestTheToolbarExists:
    def test_it_is_visible_without_selecting_anything_first(self, page: object) -> None:
        toolbar = page.locator("#editor-toolbar")  # type: ignore[attr-defined]
        assert toolbar.is_visible()
        assert toolbar.get_attribute("role") == "toolbar"

    def test_it_has_exactly_the_five_buttons_asked_for(self, page: object) -> None:
        actions = page.eval_on_selector_all(  # type: ignore[attr-defined]
            "#editor-toolbar button", "els => els.map(e => e.dataset.action)"
        )
        assert actions == BUTTONS

    def test_every_button_is_a_real_touch_target(self, page: object) -> None:
        for action in BUTTONS:
            box = page.locator(f"#editor-toolbar button[data-action='{action}']").bounding_box()
            assert box and box["height"] >= 44, f"{action} is too small to press"

    def test_every_button_is_labelled_for_a_screen_reader(self, page: object) -> None:
        for action in BUTTONS:
            label = page.get_attribute(
                f"#editor-toolbar button[data-action='{action}']", "aria-label"
            )
            assert label, f"{action} has no accessible name"


class TestTheButtonsWriteMarkdown:
    def test_bold(self, page: object, live_server: LiveServer) -> None:
        _type_and_format(page, "the forge", "bold", select=True)
        assert "**the forge**" in _answer_on_disk(live_server)

    def test_italic(self, page: object, live_server: LiveServer) -> None:
        _type_and_format(page, "the forge", "italic", select=True)
        body = _answer_on_disk(live_server)
        assert "*the forge*" in body and "**the forge**" not in body

    def test_heading(self, page: object, live_server: LiveServer) -> None:
        _type_and_format(page, "The crossroads", "heading", select=False)
        assert "## The crossroads" in _answer_on_disk(live_server)

    def test_bullet_list(self, page: object, live_server: LiveServer) -> None:
        _type_and_format(page, "turf", "bulletList", select=False)
        body = _answer_on_disk(live_server)
        assert "* turf" in body or "- turf" in body

    def test_quote(self, page: object, live_server: LiveServer) -> None:
        _type_and_format(page, "she said it often", "quote", select=False)
        assert "> she said it often" in _answer_on_disk(live_server)

    def test_heading_presses_twice_back_to_plain_text(
        self, page: object, live_server: LiveServer
    ) -> None:
        """The button must never be a one-way door."""
        _type_and_format(page, "Not a heading after all", "heading", select=False)
        assert "## Not a heading after all" in _answer_on_disk(live_server)

        page.click("#editor-toolbar button[data-action='heading']")  # type: ignore[attr-defined]
        page.wait_for_timeout(400)
        page.evaluate("() => window.veilleeSaveNow && window.veilleeSaveNow()")
        page.wait_for_timeout(1200)

        files = list(live_server.data_dir.rglob("012-*.md"))
        body = files[0].read_text(encoding="utf-8")
        assert "Not a heading after all" in body
        assert "## Not a heading after all" not in body


def test_formatting_survives_a_reload(page: object, live_server: LiveServer) -> None:
    """Rich text on screen is worthless if it does not come back."""
    _type_and_format(page, "the forge", "bold", select=True)
    assert "**the forge**" in _answer_on_disk(live_server)

    page.reload(wait_until="load")  # type: ignore[attr-defined]
    editor_locator(page)
    page.wait_for_timeout(1500)
    assert page.locator(".ProseMirror strong").count() == 1
