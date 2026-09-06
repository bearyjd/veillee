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

    def _upload_one(self, page: object, live_server: LiveServer) -> None:
        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore
        page.set_input_files("#audio-file", str(FIXTURES / "sample.m4a"))
        page.click("button:has-text('Send this recording')")
        page.wait_for_selector(".recording-item", timeout=60_000)

    def test_removing_a_recording_needs_the_word_typed(
        self, page: object, live_server: LiveServer
    ) -> None:
        self._upload_one(page, live_server)
        page.click(".recording-item button:has-text('Remove this')")  # type: ignore[attr-defined]
        page.wait_for_selector("#confirm-remove-recording", state="visible", timeout=10_000)

        # The wrong word leaves the button unpressable, so he cannot fail the
        # way he did with the old browser prompt - where pressing OK with
        # nothing typed silently refused the deletion.
        page.fill("#delete-word", "yes")
        assert page.locator("#confirm-remove-recording button:has-text('Remove it')").is_disabled()
        assert list((live_server.data_dir / "audio").rglob("*.flac"))

        page.fill("#delete-word", "delete")
        page.click("#confirm-remove-recording button:has-text('Remove it')")
        page.wait_for_timeout(3000)

        assert not list((live_server.data_dir / "audio").rglob("*.flac"))
        assert list((live_server.data_dir / ".trash").rglob("*.flac")), "files must go to trash"

    def test_the_word_he_must_type_is_shown_to_him(
        self, page: object, live_server: LiveServer
    ) -> None:
        """He failed at a browser prompt. It must be a copying task, not a memory one."""
        self._upload_one(page, live_server)
        page.click(".recording-item button:has-text('Remove this')")  # type: ignore[attr-defined]
        panel = page.locator("#confirm-remove-recording")
        panel.wait_for(state="visible", timeout=10_000)

        text = " ".join(panel.inner_text().split())
        assert "delete" in text
        assert "trash" in text, "he is not told the files are recoverable"
        assert page.locator("#delete-word").is_visible()

    def test_the_remove_button_stays_disabled_until_the_word_is_right(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Pressing the button with nothing typed is what defeated him."""
        self._upload_one(page, live_server)
        page.click(".recording-item button:has-text('Remove this')")  # type: ignore[attr-defined]
        page.wait_for_selector("#confirm-remove-recording", state="visible", timeout=10_000)

        remove = page.locator("#confirm-remove-recording button:has-text('Remove it')")
        assert remove.is_disabled(), "an empty box must not be submittable"
        page.fill("#delete-word", "Delete  ")
        assert remove.is_enabled(), "capitals and stray spaces must still count"

    def test_removing_a_recording_takes_its_transcript_with_it(
        self, page: object, live_server: LiveServer
    ) -> None:
        """An orphaned machine draft of a recording that no longer exists."""
        self._upload_one(page, live_server)
        recording_id = next((live_server.data_dir / "audio").rglob("*.json")).stem
        year, month = recording_id[:4], recording_id[4:6]
        transcript = live_server.data_dir / "transcripts" / year / month / f"{recording_id}.md"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            f"---\nrecording_id: {recording_id}\nquestion_id: q012\n---\n\n[00:00:00] words\n",
            encoding="utf-8",
        )

        page.click(".recording-item button:has-text('Remove this')")  # type: ignore[attr-defined]
        page.wait_for_selector("#confirm-remove-recording", state="visible", timeout=10_000)
        page.fill("#delete-word", "delete")
        page.click("#confirm-remove-recording button:has-text('Remove it')")
        page.wait_for_timeout(3000)

        assert not transcript.exists(), "the transcript was left behind"
        assert list((live_server.data_dir / ".trash").rglob(f"{recording_id}.md"))

    def test_he_can_change_his_mind(self, page: object, live_server: LiveServer) -> None:
        self._upload_one(page, live_server)
        page.click(".recording-item button:has-text('Remove this')")  # type: ignore[attr-defined]
        page.wait_for_selector("#confirm-remove-recording", state="visible", timeout=10_000)
        page.click("#confirm-remove-recording button:has-text('Keep it')")
        page.wait_for_timeout(600)

        assert not page.locator("#confirm-remove-recording").is_visible()
        assert list((live_server.data_dir / "audio").rglob("*.flac"))

    def test_a_file_that_is_not_audio_is_refused_kindly(
        self, page: object, live_server: LiveServer, tmp_path
    ) -> None:
        junk = tmp_path / "shopping-list.m4a"
        junk.write_bytes(b"bread, milk, turf" * 300)

        page.goto(live_server.url("/question/q012"), wait_until="load")  # type: ignore[attr-defined]
        page.set_input_files("#audio-file", str(junk))
        page.click("button:has-text('Send this recording')")

        message = page.locator(".recorder .notice.problem")
        message.wait_for(state="visible", timeout=30_000)
        text = message.inner_text().lower()
        assert "couldn't save" in text or "does not appear to be audio" in text
        # He is told what to do next, not just that it failed.
        assert "m4a" in text or "phone" in text
