"""The remote transcription backend.

This shipped with no test of any kind and had never been run against anything -
the one piece of the project whose behaviour was pure assertion. These tests
stand up a real HTTP server that speaks the OpenAI-compatible
`/v1/audio/transcriptions` shape, so the code makes genuine requests over a
genuine socket rather than talking to a mock.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from veillee.config import Settings, load_settings
from veillee.transcribe import TranscriptionError, transcribe, transcribe_remote

RECEIVED: list[dict] = []
RESPONSE: dict = {}
STATUS: list[int] = [200]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        RECEIVED.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type", ""),
                "body": body,
            }
        )
        payload = json.dumps(RESPONSE).encode()
        self.send_response(STATUS[0])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def remote_server() -> Iterator[str]:
    RECEIVED.clear()
    RESPONSE.clear()
    STATUS[0] = 200
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _settings(monkeypatch: pytest.MonkeyPatch, base_url: str, **extra: str) -> Settings:
    monkeypatch.setenv("VEILLEE_TRANSCRIPTION_BACKEND", "remote")
    monkeypatch.setenv("VEILLEE_REMOTE_BASE_URL", base_url)
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    return load_settings()


class TestASuccessfulTranscription:
    def test_it_posts_to_the_openai_compatible_path(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        RESPONSE.update({"text": "She baked on a Saturday night.", "language": "en"})
        transcribe_remote(_settings(monkeypatch, remote_server), sample_wav)

        assert RECEIVED[0]["path"] == "/v1/audio/transcriptions"

    def test_a_trailing_slash_does_not_double_up(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        RESPONSE.update({"text": "words"})
        transcribe_remote(_settings(monkeypatch, remote_server + "/"), sample_wav)

        assert RECEIVED[0]["path"] == "/v1/audio/transcriptions"

    def test_it_sends_the_audio_as_multipart(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        RESPONSE.update({"text": "words"})
        transcribe_remote(_settings(monkeypatch, remote_server), sample_wav)

        request = RECEIVED[0]
        assert request["content_type"].startswith("multipart/form-data")
        assert b"sample.wav" in request["body"]
        assert b'name="model"' in request["body"]
        assert b"verbose_json" in request["body"]
        # The actual bytes have to arrive, not just the field name.
        assert sample_wav.read_bytes()[:16] in request["body"]

    def test_segments_become_timestamped_output(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        RESPONSE.update(
            {
                "language": "en",
                "segments": [
                    {"start": 0.0, "end": 2.5, "text": " She baked on a Saturday night."},
                    {"start": 2.5, "end": 5.0, "text": " The turf was always going."},
                ],
            }
        )
        result = transcribe_remote(_settings(monkeypatch, remote_server), sample_wav)

        assert len(result.segments) == 2
        assert result.segments[0].start == 0.0
        assert result.segments[1].text == "The turf was always going."
        assert result.language == "en"
        assert result.backend == "remote"
        assert "Saturday night" in result.text

    def test_a_plain_text_reply_still_works(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        """Not every server returns segments; it must not lose the words."""
        RESPONSE.update({"text": "She baked on a Saturday night."})
        result = transcribe_remote(_settings(monkeypatch, remote_server), sample_wav)

        assert len(result.segments) == 1
        assert result.text == "She baked on a Saturday night."

    def test_the_configured_model_is_sent(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        RESPONSE.update({"text": "words"})
        settings = _settings(monkeypatch, remote_server, VEILLEE_REMOTE_MODEL="whisper-large-v3")
        result = transcribe_remote(settings, sample_wav)

        assert b"whisper-large-v3" in RECEIVED[0]["body"]
        assert result.model == "whisper-large-v3"


class TestAuthentication:
    def test_an_api_key_is_sent_as_a_bearer_token(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        RESPONSE.update({"text": "words"})
        settings = _settings(monkeypatch, remote_server, VEILLEE_REMOTE_API_KEY="sk-test-123")
        transcribe_remote(settings, sample_wav)

        assert RECEIVED[0]["authorization"] == "Bearer sk-test-123"

    def test_no_header_is_sent_when_no_key_is_configured(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        """A local endpoint on the tailnet needs no key."""
        RESPONSE.update({"text": "words"})
        transcribe_remote(_settings(monkeypatch, remote_server), sample_wav)

        assert RECEIVED[0]["authorization"] is None


class TestWhenItGoesWrong:
    def test_a_server_error_is_a_retryable_failure(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        STATUS[0] = 500
        RESPONSE.update({"error": "model overloaded"})

        with pytest.raises(TranscriptionError) as caught:
            transcribe_remote(_settings(monkeypatch, remote_server), sample_wav)
        assert "remote transcription failed" in str(caught.value)

    def test_an_unauthorised_reply_is_reported_clearly(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        STATUS[0] = 401
        with pytest.raises(TranscriptionError):
            transcribe_remote(_settings(monkeypatch, remote_server), sample_wav)

    def test_an_unreachable_endpoint_does_not_hang_or_crash(
        self, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        from tests.conftest import free_port

        settings = _settings(monkeypatch, f"http://127.0.0.1:{free_port()}")
        with pytest.raises(TranscriptionError):
            transcribe_remote(settings, sample_wav)

    def test_no_base_url_is_refused_with_the_variable_named(
        self, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
    ) -> None:
        monkeypatch.setenv("VEILLEE_TRANSCRIPTION_BACKEND", "remote")
        monkeypatch.delenv("VEILLEE_REMOTE_BASE_URL", raising=False)

        with pytest.raises(TranscriptionError) as caught:
            transcribe_remote(load_settings(), sample_wav)
        assert "VEILLEE_REMOTE_BASE_URL" in str(caught.value)

    def test_a_missing_audio_file_is_refused_before_any_request(
        self, remote_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        settings = _settings(monkeypatch, remote_server)
        with pytest.raises(TranscriptionError):
            transcribe(settings, tmp_path / "gone.flac")
        assert RECEIVED == [], "it sent a request for a file that does not exist"


def test_the_backend_switch_actually_selects_remote(
    remote_server: str, monkeypatch: pytest.MonkeyPatch, sample_wav: Path
) -> None:
    """`transcribe()` must route on the setting, or the switch is decorative."""
    RESPONSE.update({"text": "routed to the remote endpoint"})
    result = transcribe(_settings(monkeypatch, remote_server), sample_wav)

    assert len(RECEIVED) == 1
    assert result.backend == "remote"
    assert result.text == "routed to the remote endpoint"
