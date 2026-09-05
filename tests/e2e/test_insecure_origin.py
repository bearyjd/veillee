"""What the page does when it is served over plain http.

Browsers withhold the microphone entirely from a non-localhost page served over
http, so publishing straight onto a tailnet IP silently disables recording. The
page must say so accurately: "this browser won't let the page record" would send
his son off debugging Safari for an hour when the cause is the address.
"""

from __future__ import annotations

import pytest

from tests.conftest import LiveServer

# Make the page believe it is on an insecure origin, before any of its own
# scripts run, and take the microphone away exactly as a browser would.
INSECURE = """
Object.defineProperty(window, 'isSecureContext', { get: () => false });
Object.defineProperty(navigator, 'mediaDevices', { get: () => undefined });
"""


@pytest.fixture
def insecure_page(browser: object, live_server: LiveServer):
    context = browser.new_context()  # type: ignore[attr-defined]
    context.add_init_script(INSECURE)
    page = context.new_page()
    page.goto(live_server.url("/question/q012"), wait_until="load")
    page.wait_for_timeout(1200)
    yield page
    context.close()


class TestOverPlainHttp:
    def test_the_record_button_is_not_offered(self, insecure_page: object) -> None:
        assert insecure_page.locator("#record-button").count() == 0  # type: ignore

    def test_it_blames_the_address_rather_than_the_browser(self, insecure_page: object) -> None:
        notice = insecure_page.locator(  # type: ignore[attr-defined]
            ".recorder .notice", has_text="https"
        )
        assert notice.is_visible()
        text = " ".join(notice.inner_text().split())
        assert "https" in text
        assert "tailscale serve" in text, "it does not say how to fix it"
        assert "browser won't let" not in text, "it blames the browser"

    def test_the_upload_path_is_still_offered(self, insecure_page: object) -> None:
        """Path B needs no secure context, so he is never left with nothing."""
        assert insecure_page.locator("#audio-file").is_visible()  # type: ignore
        label = insecure_page.locator("label[for='audio-file']").inner_text()
        assert "upload a recording" in label.lower()

    def test_writing_is_completely_unaffected(
        self, insecure_page: object, live_server: LiveServer
    ) -> None:
        """Only the microphone is withheld. The archive still works."""
        from tests.e2e.helpers import editor_locator

        editor = editor_locator(insecure_page)
        editor.click()
        insecure_page.keyboard.type("Written over plain http.", delay=8)  # type: ignore
        insecure_page.evaluate("() => window.veilleeSaveNow && window.veilleeSaveNow()")
        insecure_page.wait_for_timeout(1500)

        files = list(live_server.data_dir.rglob("012-*.md"))
        assert files and "plain http" in files[0].read_text(encoding="utf-8")


def test_over_https_the_recorder_is_offered(browser: object, live_server: LiveServer) -> None:
    """The control case: on a secure origin the button is there."""
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url("/question/q012"), wait_until="load")
    page.wait_for_timeout(1200)
    assert page.evaluate("() => window.isSecureContext") is True
    assert page.locator("#record-button").count() == 1
    context.close()
