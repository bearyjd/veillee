"""The most important test in the suite.

He types. The browser dies without warning — a crash, a flat battery, a closed
lid, a cat on the power strip. He opens the site again. His words are there.

Nothing else in this project matters if this fails.
"""

from __future__ import annotations

import time

import pytest

from tests.conftest import LiveServer
from tests.e2e.helpers import editor_locator, type_answer

SENTENCE = (
    "She baked on a Saturday night so the house smelled of bread on the Sunday, "
    "and the turf was always going by the time we came down."
)


def _crash_the_renderer(page: object) -> None:
    """Kill the renderer outright. No unload handlers, no beacon, no mercy."""
    try:
        page.goto("chrome://crash", timeout=3000)  # type: ignore[attr-defined]
    except Exception:
        # A renderer that has died refuses navigation; that is the success case.
        pass


class TestCrashRecovery:
    def test_words_survive_the_browser_being_killed(
        self, browser: object, live_server: LiveServer
    ) -> None:
        context = browser.new_context()  # type: ignore[attr-defined]
        page = context.new_page()
        page.goto(live_server.url("/question/q012"), wait_until="load")

        type_answer(page, SENTENCE)

        # Autosave runs every five seconds. Wait past one full interval and do
        # nothing else at all: no blur, no navigation, no explicit save.
        time.sleep(6)

        _crash_the_renderer(page)
        context.close()

        # A completely fresh context: new process, no memory, nothing carried over.
        recovered = browser.new_context()  # type: ignore[attr-defined]
        recovered_page = recovered.new_page()
        recovered_page.goto(live_server.url("/question/q012"), wait_until="load")
        text = editor_locator(recovered_page).inner_text()
        recovered.close()

        assert "Saturday night" in text
        assert "turf" in text

    def test_the_words_are_on_disk_as_plain_markdown(
        self, browser: object, live_server: LiveServer
    ) -> None:
        """Recovered from the page is good; recovered from a file is the promise."""
        context = browser.new_context()  # type: ignore[attr-defined]
        page = context.new_page()
        page.goto(live_server.url("/question/q012"), wait_until="load")

        type_answer(page, SENTENCE)
        time.sleep(6)
        _crash_the_renderer(page)
        context.close()

        files = list(live_server.data_dir.rglob("012-*.md"))
        assert len(files) == 1, "the answer was not written to disk at all"
        content = files[0].read_text(encoding="utf-8")
        assert "Saturday night" in content
        assert content.startswith("---"), "the file is not readable frontmatter markdown"

    def test_a_revision_exists_after_repeated_autosaves(
        self, browser: object, live_server: LiveServer
    ) -> None:
        context = browser.new_context()  # type: ignore[attr-defined]
        page = context.new_page()
        page.goto(live_server.url("/question/q012"), wait_until="load")

        type_answer(page, "First thought. ")
        time.sleep(6)
        type_answer(page, "Then a second one.")
        time.sleep(6)
        context.close()

        revisions = list((live_server.data_dir / ".revisions" / "q012").glob("*.md"))
        assert revisions, "no revision was kept between autosaves"

    def test_the_save_line_tells_him_it_is_saved(
        self, browser: object, live_server: LiveServer
    ) -> None:
        """A quiet confirmation, never a button and never a warning."""
        context = browser.new_context()  # type: ignore[attr-defined]
        page = context.new_page()
        page.goto(live_server.url("/question/q012"), wait_until="load")

        type_answer(page, "A few words.")
        page.wait_for_function(
            "() => document.getElementById('save-state').textContent.includes('Saved')",
            timeout=15_000,
        )

        state = page.locator("#save-state")
        assert "Saved" in state.inner_text()
        assert state.get_attribute("data-state") == "saved"
        assert page.locator("button:has-text('Save')").count() == 0
        context.close()

    def test_leaving_the_page_immediately_still_saves(
        self, browser: object, live_server: LiveServer
    ) -> None:
        """He types and clicks Next straight away, inside the autosave window."""
        context = browser.new_context()  # type: ignore[attr-defined]
        page = context.new_page()
        page.goto(live_server.url("/question/q012"), wait_until="load")

        type_answer(page, "Typed and left at once.")
        page.click("a.button:has-text('Next question')")
        page.wait_for_load_state("load")
        context.close()

        deadline = time.time() + 10
        content = ""
        while time.time() < deadline:
            files = list(live_server.data_dir.rglob("012-*.md"))
            if files:
                content = files[0].read_text(encoding="utf-8")
                if "Typed and left" in content:
                    break
            time.sleep(0.25)
        assert "Typed and left" in content


@pytest.mark.parametrize("question_id", ["q001", "q060", "q120"])
def test_autosave_works_on_any_question(
    browser: object, live_server: LiveServer, question_id: str
) -> None:
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url(f"/question/{question_id}"), wait_until="load")
    type_answer(page, f"An answer for {question_id}.")
    time.sleep(6)
    context.close()

    number = question_id[1:]
    files = list(live_server.data_dir.rglob(f"{number}-*.md"))
    assert files, f"nothing written for {question_id}"
    assert question_id in files[0].read_text(encoding="utf-8")
