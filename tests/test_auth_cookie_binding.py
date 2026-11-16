"""A session cookie must not outlive the passcode that earned it."""

from __future__ import annotations

import dataclasses
import time
from unittest import mock

from fastapi import Request
from fastapi.responses import Response
from itsdangerous import URLSafeSerializer

from veillee import config
from veillee.web import auth


def _settings(passcode: str | None = "seanchai", family: str | None = "cousins") -> config.Settings:
    return dataclasses.replace(
        config.load_settings(),
        passcode=passcode,
        family_passcode=family,
        secret_key="test-key-not-a-secret-but-32-chars-long",
    )


def _request(token: str | None) -> Request:
    headers = [(b"cookie", f"{auth.COOKIE_NAME}={token}".encode())] if token else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _token(settings: config.Settings, role: str = auth.ROLE_WRITER) -> str:
    response = Response()
    auth.issue_cookie(response, settings, role)
    cookie = response.headers["set-cookie"]
    return cookie.split("=", 1)[1].split(";", 1)[0]


def test_a_fresh_cookie_is_accepted() -> None:
    settings = _settings()
    assert auth.role_from_cookie(_request(_token(settings)), settings) == auth.ROLE_WRITER
    family = _token(settings, auth.ROLE_FAMILY)
    assert auth.role_from_cookie(_request(family), settings) == auth.ROLE_FAMILY


def test_an_old_cookie_is_rejected_after_the_writer_passcode_changes() -> None:
    old = _token(_settings(passcode="seanchai"))
    changed = _settings(passcode="a-new-word")
    assert auth.role_from_cookie(_request(old), changed) is None


def test_an_old_cookie_is_rejected_after_the_family_passcode_changes() -> None:
    old = _token(_settings(family="cousins"), auth.ROLE_FAMILY)
    changed = _settings(family="someone-else")
    assert auth.role_from_cookie(_request(old), changed) is None


def test_a_cookie_is_rejected_once_its_passcode_is_removed() -> None:
    old = _token(_settings(family="cousins"), auth.ROLE_FAMILY)
    assert auth.role_from_cookie(_request(old), _settings(family=None)) is None


def test_a_cookie_without_a_passcode_fingerprint_is_rejected() -> None:
    """Cookies minted before the binding existed must not keep working."""
    settings = _settings()
    legacy = URLSafeSerializer(settings.secret_key, salt=auth._SALT).dumps(
        {"ok": True, "role": auth.ROLE_WRITER}
    )
    assert auth.role_from_cookie(_request(legacy), settings) is None


def test_a_cookie_past_its_max_age_is_rejected() -> None:
    settings = _settings()
    token = _token(settings)
    expired_at = time.time() + auth.COOKIE_MAX_AGE + 60
    with mock.patch("time.time", return_value=expired_at):
        assert auth.role_from_cookie(_request(token), settings) is None
