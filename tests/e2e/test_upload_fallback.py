"""Path B, driven through the actual browser UI.

This is the path that saves the morning if MediaRecorder turns out to be broken
on his iPad. It is tested through the real file input, not by posting to the API.
"""

from __future__ import annotations

import pytest

from tests.conftest import FIXTURES, LiveServer


@pytest.fixture
def page(browser: object, live_server: LiveServer):
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    yield page
    context.close()


class TestUploadFromAPhone:
    def test_the_upload_control_is_offered_on_the_question_page(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        label = page.locator("label[for='audio-file']")
        assert label.is_visible()
        assert "upload a recording from your phone" in label.inner_text().lower()
        assert page.locator("#audio-file").is_visible()

    def test_an_m4a_from_voice_memos_round_trips(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]

        page.set_input_files("#audio-file", str(FIXTURES / "sample.m4a"))
        page.click("button:has-text('Send this recording')")

        page.wait_for_selector(".recording-item", timeout=60_000)

        audio = list((live_server.data_dir / "audio").rglob("*.flac"))
        assert len(audio) == 1, "no archival FLAC was produced from the upload"
        assert list((live_server.data_dir / "audio").rglob("*.opus"))
        assert list((live_server.data_dir / "audio").rglob("*.orig.m4a"))

    def test_the_uploaded_recording_is_playable_on_the_page(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        page.set_input_files("#audio-file", str(FIXTURES / "sample.m4a"))
        page.click("button:has-text('Send this recording')")
        page.wait_for_selector(".recording-item", timeout=60_000)

        player = page.locator(".recording-item audio").first
        assert player.is_visible()
        assert ".opus" in (player.get_attribute("src") or "")

        # The browser can actually decode it.
        duration = page.evaluate(
            """async () => {
                const el = document.querySelector('.recording-item audio');
                el.load();
                await new Promise(r => { el.onloadedmetadata = r; setTimeout(r, 8000); });
                return el.duration;
            }"""
        )
        assert duration and duration > 0

    def test_removing_a_recording_needs_the_word_typed(
        self, page: object, live_server: LiveServer
    ) -> None:
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        page.set_input_files("#audio-file", str(FIXTURES / "sample.m4a"))
        page.click("button:has-text('Send this recording')")
        page.wait_for_selector(".recording-item", timeout=60_000)

        # First: the wrong word. Nothing may be removed.
        page.once("dialog", lambda dialog: dialog.accept("no"))
        page.click("button:has-text('Remove this')")
        page.wait_for_timeout(1500)
        assert list((live_server.data_dir / "audio").rglob("*.flac"))

        # Then the right one.
        page.once("dialog", lambda dialog: dialog.accept("delete"))
        page.click("button:has-text('Remove this')")
        page.wait_for_timeout(3000)

        assert not list((live_server.data_dir / "audio").rglob("*.flac"))
        assert list((live_server.data_dir / ".trash").rglob("*.flac")), "files must go to trash"

    def test_a_file_that_is_not_audio_is_refused_kindly(
        self, page: object, live_server: LiveServer, tmp_path
    ) -> None:
        junk = tmp_path / "shopping-list.m4a"
        junk.write_bytes(b"bread, milk, turf" * 300)

        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        page.set_input_files("#audio-file", str(junk))
        page.click("button:has-text('Send this recording')")

        message = page.locator(".notice.problem")
        message.wait_for(state="visible", timeout=30_000)
        text = message.inner_text().lower()
        assert "couldn't save" in text or "does not appear to be audio" in text
        # He is told what to do next, not just that it failed.
        assert "m4a" in text or "phone" in text
