"""Path A, with a real fake microphone.

Chromium is launched with a wav file standing in for a microphone, so the page
genuinely captures audio, genuinely uploads it in chunks, and the server
genuinely produces FLAC. Nothing here is mocked.
"""

from __future__ import annotations

from tests.conftest import LiveServer


class TestMediaRecorderRoundTrip:
    def test_a_recording_reaches_disk_as_flac(
        self, fake_audio_browser: object, live_server: LiveServer
    ) -> None:
        context = fake_audio_browser.new_context(permissions=["microphone"])  # type: ignore
        page = context.new_page()
        page.goto(live_server.url("/question/q015"), wait_until="load")

        page.wait_for_selector("#record-button", timeout=20_000)
        page.click("#record-button")

        # Long enough for several chunks to be uploaded while still recording.
        page.wait_for_timeout(7000)
        assert page.locator("#record-button").get_attribute("data-recording") == "true"

        page.click("#record-button")
        page.wait_for_selector(".recording-item", timeout=90_000)
        context.close()

        flac = list((live_server.data_dir / "audio").rglob("*.flac"))
        assert len(flac) == 1, "the recording did not become an archival FLAC"
        assert flac[0].stat().st_size > 0
        assert list((live_server.data_dir / "audio").rglob("*.opus"))
        assert list((live_server.data_dir / "audio").rglob("*.json"))

    def test_chunks_arrive_while_he_is_still_talking(
        self, fake_audio_browser: object, live_server: LiveServer
    ) -> None:
        """The whole point of chunking: a crash costs seconds, not the story."""
        context = fake_audio_browser.new_context(permissions=["microphone"])  # type: ignore
        page = context.new_page()
        page.goto(live_server.url("/question/q015"), wait_until="load")

        page.wait_for_selector("#record-button", timeout=20_000)
        page.click("#record-button")
        page.wait_for_timeout(8000)

        # Still recording — nothing has been finished — yet audio is already
        # durable on the server.
        assert page.locator("#record-button").get_attribute("data-recording") == "true"
        partial = list((live_server.data_dir / ".uploads").rglob("*.part"))
        assert partial, "no audio had reached the disk mid-recording"
        assert sum(chunk.stat().st_size for chunk in partial) > 0

        context.close()

    def test_the_timer_and_meter_appear_while_recording(
        self, fake_audio_browser: object, live_server: LiveServer
    ) -> None:
        context = fake_audio_browser.new_context(permissions=["microphone"])  # type: ignore
        page = context.new_page()
        page.goto(live_server.url("/question/q015"), wait_until="load")

        page.wait_for_selector("#record-button", timeout=20_000)
        page.click("#record-button")
        page.wait_for_timeout(3500)

        assert page.locator(".level-meter").is_visible()
        assert page.locator(".elapsed").is_visible()
        assert "0:0" in page.locator(".elapsed").inner_text()
        assert "Stop recording" in page.locator("#record-button").inner_text()

        context.close()

    def test_a_browser_without_mediarecorder_still_offers_the_upload(
        self, browser: object, live_server: LiveServer
    ) -> None:
        """This is the iPad Safari case, simulated by removing the API."""
        context = browser.new_context()  # type: ignore[attr-defined]
        context.add_init_script("delete window.MediaRecorder;")
        page = context.new_page()
        page.goto(live_server.url("/question/q015"), wait_until="load")

        page.wait_for_selector("#audio-file", timeout=20_000)
        assert page.locator("#record-button").count() == 0
        assert page.locator("#audio-file").is_visible()
        guidance = page.locator(".recorder .notice", has_text="works just as well")
        assert guidance.is_visible()

        context.close()


class TestPauseAndResume:
    def test_he_can_pause_and_carry_on_without_starting_a_second_file(
        self, fake_audio_browser: object, live_server: LiveServer
    ) -> None:
        """Stopping for a cup of tea must not end the recording."""
        context = fake_audio_browser.new_context(permissions=["microphone"])  # type: ignore
        page = context.new_page()
        page.goto(live_server.url("/question/q015"), wait_until="load")

        page.wait_for_selector("#record-button", timeout=20_000)
        page.click("#record-button")
        page.wait_for_timeout(4000)

        page.click("#pause-button")
        page.wait_for_timeout(500)
        assert "Carry on" in page.locator("#pause-button").inner_text()
        assert "paused" in page.locator(".elapsed").inner_text().lower()
        assert "Nothing has been lost" in page.locator(".elapsed").inner_text()

        # The clock must not advance while paused.
        paused_at = page.locator(".elapsed").inner_text()
        page.wait_for_timeout(2500)
        assert page.locator(".elapsed").inner_text() == paused_at

        page.click("#pause-button")
        page.wait_for_timeout(3500)
        assert "Pause" in page.locator("#pause-button").inner_text()
        assert page.locator(".elapsed").inner_text() != paused_at

        page.click("#record-button")
        page.wait_for_selector(".recording-item", timeout=90_000)
        context.close()

        # One recording, not two.
        assert len(list((live_server.data_dir / "audio").rglob("*.flac"))) == 1

    def test_the_pause_button_is_hidden_until_he_is_recording(
        self, fake_audio_browser: object, live_server: LiveServer
    ) -> None:
        context = fake_audio_browser.new_context(permissions=["microphone"])  # type: ignore
        page = context.new_page()
        page.goto(live_server.url("/question/q015"), wait_until="load")
        page.wait_for_selector("#record-button", timeout=20_000)

        assert not page.locator("#pause-button").is_visible()
        page.click("#record-button")
        page.wait_for_timeout(1500)
        assert page.locator("#pause-button").is_visible()

        context.close()
