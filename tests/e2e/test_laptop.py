"""He uses a laptop, so keyboard and mouse are the primary paths.

Everything here was originally designed around an iPad. These tests check the
assumptions that changed: real keyboard navigation, a comfortable line length on
a wide screen, and being able to simply start typing.
"""

from __future__ import annotations

import pytest

from tests.conftest import LiveServer
from tests.e2e.helpers import editor_locator

LAPTOP = {"width": 1366, "height": 768}
SIZES = [(1280, 800), (1366, 768), (1440, 900), (1920, 1080)]


@pytest.fixture
def page(browser: object, live_server: LiveServer):
    context = browser.new_context(viewport=LAPTOP)  # type: ignore[attr-defined]
    page = context.new_page()
    yield page
    context.close()


class TestStartingToWrite:
    def test_the_cursor_is_already_in_the_box_on_a_blank_question(
        self, page: object, live_server: LiveServer
    ) -> None:
        """He opens a question and types. No hunting for where to click."""
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        editor_locator(page)
        page.wait_for_timeout(800)

        assert page.evaluate(
            "() => document.getElementById('editor-frame').contains(document.activeElement)"
        ), "he would have to find the box himself"

    def test_the_question_is_still_on_screen(self, page: object, live_server: LiveServer) -> None:
        """Landing in the box is no use if it scrolled the question away."""
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        editor_locator(page)
        page.wait_for_timeout(800)

        assert page.evaluate("() => window.scrollY") == 0
        assert page.locator("h1.question-text").is_visible()

    def test_typing_immediately_reaches_the_disk(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        editor_locator(page)
        page.wait_for_timeout(800)
        page.keyboard.type("Typed without touching the mouse.", delay=6)
        page.evaluate("() => window.veilleeSaveNow && window.veilleeSaveNow()")
        page.wait_for_timeout(1500)

        files = list(live_server.data_dir.rglob("040-*.md"))
        assert files and "without touching the mouse" in files[0].read_text(encoding="utf-8")

    def test_focus_is_not_stolen_from_an_answer_he_already_wrote(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Typing into the middle of last week's answer would be unforgivable."""
        page.goto(live_server.url("/question/q041"), wait_until="load")  # type: ignore
        editor_locator(page)
        page.wait_for_timeout(800)
        page.keyboard.type("Something written earlier.", delay=6)
        page.evaluate("() => window.veilleeSaveNow && window.veilleeSaveNow()")
        page.wait_for_timeout(1500)

        page.reload(wait_until="load")
        editor_locator(page)
        page.wait_for_timeout(1200)

        assert not page.evaluate(
            "() => document.getElementById('editor-frame').contains(document.activeElement)"
        ), "focus was taken into an answer that already had words in it"
        assert "written earlier" in page.locator(".ProseMirror").inner_text()


class TestKeyboardOnly:
    def test_he_can_reach_and_leave_the_box_without_a_mouse(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q042"), wait_until="load")  # type: ignore
        editor_locator(page)
        page.wait_for_timeout(800)

        page.keyboard.type("Keyboard only.", delay=6)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        assert not page.evaluate(
            "() => document.getElementById('editor-frame').contains(document.activeElement)"
        )
        # Escape must land somewhere useful, not nowhere.
        landed = page.evaluate("() => document.activeElement.textContent.trim().slice(0, 30)")
        assert landed, "focus went to the body; there is nothing to tab from"

    def test_the_skip_link_works(self, page: object, live_server: LiveServer) -> None:
        page.goto(live_server.url("/"), wait_until="load")  # type: ignore
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.activeElement.className") == "skip-link"
        assert page.locator("a.skip-link").is_visible(), "the skip link never becomes visible"

    def test_every_control_shows_where_the_keyboard_is(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Without a visible focus ring, keyboard use is guesswork."""
        page.goto(live_server.url("/question/q043"), wait_until="load")  # type: ignore
        page.wait_for_timeout(600)
        outline = page.evaluate("""() => {
            const b = document.querySelector('.button-row a.button');
            b.focus();
            const s = getComputedStyle(b);
            return s.outlineStyle + ' ' + s.outlineWidth;
        }""")
        assert "none" not in outline, f"no focus indicator: {outline}"


@pytest.mark.parametrize(("width", "height"), SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_the_page_is_comfortable_at_laptop_sizes(
    browser: object, live_server: LiveServer, width: int, height: int
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})  # type: ignore
    page = context.new_page()
    page.goto(live_server.url("/question/q012"), wait_until="load")
    page.wait_for_timeout(900)

    assert not page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    ), "the page scrolls sideways"
    assert page.evaluate("() => parseFloat(getComputedStyle(document.body).fontSize)") >= 18

    # A line that runs the whole width of a 1920px screen is unreadable.
    measure = page.evaluate("""() => {
        const e = document.querySelector('.ProseMirror')
            || document.querySelector('#editor-fallback');
        return e ? e.getBoundingClientRect().width : 0;
    }""")
    assert 400 < measure < 900, f"line length is {measure}px"
    context.close()
