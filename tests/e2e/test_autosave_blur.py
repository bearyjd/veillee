"""Autosave on blur.

The specification asks for autosave every five seconds *and on blur*. These
tests never wait for the timer: each one asserts the words reached the disk
faster than the five-second interval could have written them.
"""

from __future__ import annotations

import time

import pytest

from tests.conftest import LiveServer
from tests.e2e.helpers import editor_locator

AUTOSAVE_INTERVAL_SECONDS = 5


def _wait_for_disk(live_server: LiveServer, needle: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for path in live_server.data_dir.rglob("012-*.md"):
            if needle in path.read_text(encoding="utf-8"):
                return True
        time.sleep(0.15)
    return False


@pytest.fixture
def page(browser: object, live_server: LiveServer):
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url("/question/q012"), wait_until="load")
    editor_locator(page)
    yield page
    context.close()


class TestAutosaveOnBlur:
    def test_clicking_out_of_the_editor_saves_at_once(
        self, page: object, live_server: LiveServer
    ) -> None:
        """He clicks from the text onto the page. That must save.

        window's blur event does not fire for this - it only fires when the
        whole browser loses focus - so this is the case that actually happens
        and the one most likely to be missed.
        """
        editor = editor_locator(page)
        editor.click()
        page.keyboard.type("He clicked away before the timer ran.", delay=8)  # type: ignore

        started = time.time()
        page.locator("h1.question-text").click()  # type: ignore[attr-defined]

        landed = _wait_for_disk(live_server, "clicked away", timeout=3.0)
        elapsed = time.time() - started

        assert landed, "leaving the editor did not save"
        assert elapsed < AUTOSAVE_INTERVAL_SECONDS, (
            f"took {elapsed:.1f}s - that is the interval timer, not the blur handler"
        )

    def test_escape_leaves_the_writing_box_and_saves(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Tab indents inside a rich editor, so Escape is the way out.

        Without it the editor is a keyboard trap - WCAG 2.1.2 - which axe-core
        cannot detect, so it needs a test of its own.
        """
        inside = "() => document.getElementById('editor-frame').contains(document.activeElement)"
        editor = editor_locator(page)
        editor.click()
        page.keyboard.type("He pressed escape.", delay=8)  # type: ignore[attr-defined]
        assert page.evaluate(inside)  # type: ignore[attr-defined]

        started = time.time()
        page.keyboard.press("Escape")  # type: ignore[attr-defined]

        assert not page.evaluate(inside), "Escape did not move focus out of the editor"
        assert _wait_for_disk(live_server, "pressed escape", timeout=3.0)
        assert time.time() - started < AUTOSAVE_INTERVAL_SECONDS

    def test_the_way_out_is_advertised(self, page: object, live_server: LiveServer) -> None:
        """WCAG requires the user be told the method when Tab will not do it."""
        hint = page.locator("#editor-escape-hint")  # type: ignore[attr-defined]
        assert "Esc" in hint.inner_text()
        assert page.get_attribute("#editor-frame", "aria-describedby") == "editor-escape-hint"

        editor_locator(page).click()
        page.wait_for_timeout(300)
        opacity = page.evaluate(
            "() => getComputedStyle(document.getElementById('editor-escape-hint')).opacity"
        )
        assert float(opacity) > 0.9, "the hint is not shown while he is in the box"

    def test_tab_stays_inside_the_editor_for_list_indenting(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Documents the behaviour that Escape exists to compensate for."""
        editor = editor_locator(page)
        editor.click()
        page.keyboard.type("an item", delay=8)  # type: ignore[attr-defined]
        page.keyboard.press("Tab")
        page.wait_for_timeout(300)
        assert page.evaluate(
            "() => document.getElementById('editor-frame').contains(document.activeElement)"
        )

    def test_moving_around_inside_the_editor_does_not_thrash_the_disk(
        self, page: object, live_server: LiveServer
    ) -> None:
        """focusout bubbles, so it must not fire for focus moves within."""
        editor = editor_locator(page)
        editor.click()
        page.keyboard.type("First line.", delay=8)  # type: ignore[attr-defined]
        page.keyboard.press("Enter")
        page.keyboard.type("Second line.", delay=8)
        assert _wait_for_disk(live_server, "Second line", timeout=8.0)

        before = len(list((live_server.data_dir / ".revisions" / "q012").glob("*.md")))
        for _ in range(4):
            editor.click()
            page.wait_for_timeout(120)
        page.wait_for_timeout(800)
        after = len(list((live_server.data_dir / ".revisions" / "q012").glob("*.md")))

        assert after == before, "clicking within the editor wrote extra revisions"

    def test_the_fallback_textarea_also_saves_on_blur(
        self, browser: object, live_server: LiveServer
    ) -> None:
        context = browser.new_context()  # type: ignore[attr-defined]
        context.route("**/vendor/editor.js", lambda route: route.abort())
        fallback = context.new_page()
        fallback.goto(live_server.url("/question/q012"), wait_until="load")
        fallback.wait_for_selector("#editor-fallback", state="visible", timeout=15_000)

        fallback.click("#editor-fallback")
        fallback.keyboard.type("Typed into the plain box.", delay=8)
        started = time.time()
        fallback.locator("h1.question-text").click()

        assert _wait_for_disk(live_server, "plain box", timeout=3.0)
        assert time.time() - started < AUTOSAVE_INTERVAL_SECONDS
        context.close()
