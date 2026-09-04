"""Getting around. Everything must be one click from home."""

from __future__ import annotations

import pytest

from tests.conftest import LiveServer
from tests.e2e.helpers import editor_locator


@pytest.fixture
def page(browser: object, live_server: LiveServer):
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    yield page
    context.close()


class TestGettingAround:
    def test_home_offers_a_question_and_a_way_to_browse(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/"), wait_until="load")  # type: ignore[attr-defined]
        assert page.locator("a.card").count() >= 1  # type: ignore[attr-defined]
        assert page.locator("a:has-text('Browse by chapter')").count() == 1
        assert page.locator('a:has-text("Everything you\'ve answered")').count() >= 1

    def test_home_to_chapter_to_question_in_two_clicks(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/"), wait_until="load")  # type: ignore[attr-defined]
        page.click("a:has-text('Browse by chapter')")
        page.click("a.card >> nth=0")
        page.click("a.card >> nth=0")
        assert "/question/" in page.url
        assert page.locator("h1.question-text").count() == 1

    def test_all_fourteen_chapters_are_listed(self, page: object, live_server: LiveServer) -> None:
        page.goto(live_server.url("/chapters"), wait_until="load")  # type: ignore[attr-defined]
        assert page.locator("a.card").count() == 14

    def test_progress_is_a_warm_count_and_never_a_percentage(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        editor_locator(page).click()
        page.keyboard.type("An answer so there is progress to report.")
        page.wait_for_function(
            "() => document.getElementById('save-state').textContent.includes('Saved')",
            timeout=15_000,
        )

        page.goto(live_server.url("/"), wait_until="load")
        body = page.locator("main").inner_text()
        assert "You've answered 1 question" in body
        assert "%" not in body
        assert page.locator("progress").count() == 0

    def test_the_editor_that_shipped_is_recorded(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Which editor loaded is a fact the handover needs to state truthfully."""
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        editor_locator(page)
        milkdown = page.locator(".ProseMirror").count() > 0
        fallback_visible = page.locator("#editor-fallback").is_visible()
        assert milkdown or fallback_visible
        # Exactly one of them is in use, never both.
        assert milkdown != fallback_visible


class TestSkippingAndPuttingOff:
    def test_skip_moves_to_the_next_question(self, page: object, live_server: LiveServer) -> None:
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        page.click("button:has-text('Skip for now')")
        page.wait_for_load_state("load")
        assert "/question/q013" in page.url

    def test_come_back_to_this_is_the_same_weight_as_next(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Putting a question off must not look like the lesser choice."""
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        next_box = page.locator("a.button:has-text('Next question')").bounding_box()
        skip_box = page.locator("button:has-text('Skip for now')").bounding_box()
        later_box = page.locator("button:has-text('Come back to this')").bounding_box()

        assert next_box and skip_box and later_box
        for box in (next_box, skip_box, later_box):
            assert box["height"] >= 56, "touch targets must stay large"
        assert abs(skip_box["height"] - next_box["height"]) < 2
        assert abs(later_box["height"] - next_box["height"]) < 2

    def test_a_question_put_off_is_offered_first_from_home(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q030"), wait_until="load")  # type: ignore[attr-defined]
        page.click("button:has-text('Come back to this')")
        page.goto(live_server.url("/"), wait_until="load")
        assert "You said you would come back to this one" in page.locator("main").inner_text()


class TestHisOwnQuestion:
    def test_he_can_add_one_from_the_home_page(self, page: object, live_server: LiveServer) -> None:
        page.goto(live_server.url("/"), wait_until="load")  # type: ignore[attr-defined]
        page.fill("#own-question", "What became of the forge?")
        page.click("button:has-text('Add it')")
        page.wait_for_load_state("load")

        assert "/question/c001" in page.url
        assert "What became of the forge?" in page.locator("h1.question-text").inner_text()


def test_body_text_is_never_below_eighteen_pixels(page: object, live_server: LiveServer) -> None:
    for path in ("/", "/chapters", "/answers", "/question/q001"):
        page.goto(live_server.url(path), wait_until="load")  # type: ignore[attr-defined]
        size = page.evaluate("() => parseFloat(getComputedStyle(document.body).fontSize)")
        assert size >= 18, f"{path} renders body text at {size}px"
