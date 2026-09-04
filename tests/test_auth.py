"""The optional passcode.

Off by default - the tailnet is the security boundary. When it is on, the whole
point is that he is asked once per device and never again, so both halves need
testing: that it actually keeps people out, and that it does not keep asking.
"""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import LiveServer

PASSCODE = "seanchai"


class TestWithNoPasscode:
    def test_everything_is_open(self, live_server: LiveServer) -> None:
        for path in ("/", "/chapters", "/question/q012", "/admin"):
            assert httpx.get(live_server.url(path), timeout=30).status_code == 200

    def test_the_entry_page_sends_you_home(self, live_server: LiveServer) -> None:
        response = httpx.get(live_server.url("/enter"), timeout=30, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"


class TestWithAPasscode:
    def test_a_page_redirects_to_the_entry_form(
        self, live_server_with_passcode: LiveServer
    ) -> None:
        response = httpx.get(
            live_server_with_passcode.url("/question/q012"), timeout=30, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/enter")

    def test_the_api_answers_401_rather_than_redirecting(
        self, live_server_with_passcode: LiveServer
    ) -> None:
        """A redirect to HTML would make autosave look like it succeeded."""
        response = httpx.post(
            live_server_with_passcode.url("/api/answer/q012"),
            json={"body": "should not be saved"},
            timeout=30,
            follow_redirects=False,
        )
        assert response.status_code == 401
        assert not list(live_server_with_passcode.data_dir.rglob("012-*.md"))

    def test_healthz_stays_open_so_the_morning_check_works(
        self, live_server_with_passcode: LiveServer
    ) -> None:
        assert httpx.get(live_server_with_passcode.url("/healthz"), timeout=30).status_code == 200

    def test_static_files_stay_open(self, live_server_with_passcode: LiveServer) -> None:
        response = httpx.get(live_server_with_passcode.url("/static/css/veillee.css"), timeout=30)
        assert response.status_code == 200

    def test_the_wrong_word_is_refused(self, live_server_with_passcode: LiveServer) -> None:
        response = httpx.post(
            live_server_with_passcode.url("/enter"),
            data={"passcode": "wrong", "next_path": "/"},
            timeout=30,
            follow_redirects=False,
        )
        assert response.status_code == 401
        assert "veillee_session" not in response.cookies
        assert "wasn't right" in response.text

    def test_the_right_word_lets_you_in(self, live_server_with_passcode: LiveServer) -> None:
        with httpx.Client(base_url=live_server_with_passcode.base_url, timeout=30) as client:
            response = client.post(
                "/enter", data={"passcode": PASSCODE, "next_path": "/"}, follow_redirects=False
            )
            assert response.status_code == 303
            assert "veillee_session" in client.cookies

            assert client.get("/question/q012", follow_redirects=False).status_code == 200

    def test_he_is_never_asked_twice_on_the_same_device(
        self, live_server_with_passcode: LiveServer
    ) -> None:
        """The cookie must outlast any plausible gap between sittings."""
        with httpx.Client(base_url=live_server_with_passcode.base_url, timeout=30) as client:
            entry = client.post(
                "/enter", data={"passcode": PASSCODE, "next_path": "/"}, follow_redirects=False
            )
            set_cookie = entry.headers["set-cookie"]
            assert "HttpOnly" in set_cookie
            assert "Max-Age=" in set_cookie
            max_age = int(set_cookie.split("Max-Age=")[1].split(";")[0])
            assert max_age > 60 * 60 * 24 * 365, "the cookie expires within a year"

            for _ in range(3):
                assert client.get("/", follow_redirects=False).status_code == 200
                assert (
                    client.post(
                        "/api/answer/q012", json={"body": "written while signed in"}
                    ).status_code
                    == 200
                )

    def test_a_forged_cookie_is_rejected(self, live_server_with_passcode: LiveServer) -> None:
        """It is signed, so making one up must not work."""
        response = httpx.get(
            live_server_with_passcode.url("/"),
            cookies={"veillee_session": "eyJvayI6dHJ1ZX0.forged"},
            timeout=30,
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_you_land_back_where_you_were_going(
        self, live_server_with_passcode: LiveServer
    ) -> None:
        with httpx.Client(base_url=live_server_with_passcode.base_url, timeout=30) as client:
            redirect = client.get("/question/q030", follow_redirects=False)
            next_path = redirect.headers["location"].split("next=")[1]
            entry = client.post(
                "/enter",
                data={"passcode": PASSCODE, "next_path": next_path},
                follow_redirects=False,
            )
            assert entry.headers["location"] == "/question/q030"

    @pytest.mark.parametrize("hostile", ["//evil.example.com", "https://evil.example.com/x", "//x"])
    def test_it_will_not_bounce_you_off_the_tailnet(
        self, live_server_with_passcode: LiveServer, hostile: str
    ) -> None:
        """An open redirect here would be a way out of the private network."""
        with httpx.Client(base_url=live_server_with_passcode.base_url, timeout=30) as client:
            entry = client.post(
                "/enter",
                data={"passcode": PASSCODE, "next_path": hostile},
                follow_redirects=False,
            )
            assert entry.headers["location"] == "/"


def test_the_passcode_comparison_is_constant_time() -> None:
    """Guessing it by timing must not be possible."""
    import inspect

    from veillee.web import auth

    assert "compare_digest" in inspect.getsource(auth.passcode_matches)
