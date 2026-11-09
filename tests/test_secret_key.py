"""The session-signing key must be explicit whenever a passcode is set.

It used to default to a literal published in the repository, so anyone could
sign a `role: writer` cookie offline and walk past the passcode.
"""

from __future__ import annotations

import httpx
import pytest
from itsdangerous import URLSafeSerializer

from tests.conftest import LiveServer
from veillee.config import ConfigError, Settings, load_settings
from veillee.web.app import create_app

OLD_DEFAULT = "veillee-local-tailnet-only"


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name in ("VEILLEE_PASSCODE", "VEILLEE_FAMILY_PASSCODE", "VEILLEE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return load_settings()


class TestStartupRefusesAWeakKey:
    def test_passcode_without_a_key_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolved = _settings(monkeypatch, VEILLEE_PASSCODE="x")
        with pytest.raises(ConfigError, match="VEILLEE_SECRET_KEY"):
            create_app(resolved)

    def test_passcode_with_the_old_default_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolved = _settings(monkeypatch, VEILLEE_PASSCODE="x", VEILLEE_SECRET_KEY=OLD_DEFAULT)
        with pytest.raises(ConfigError, match="VEILLEE_SECRET_KEY"):
            create_app(resolved)

    def test_family_passcode_alone_also_needs_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolved = _settings(monkeypatch, VEILLEE_FAMILY_PASSCODE="x")
        with pytest.raises(ConfigError, match="VEILLEE_SECRET_KEY"):
            create_app(resolved)

    def test_an_explicit_key_starts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolved = _settings(monkeypatch, VEILLEE_PASSCODE="x", VEILLEE_SECRET_KEY="k" * 32)
        create_app(resolved)

    def test_no_passcode_needs_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        create_app(_settings(monkeypatch))


def test_a_cookie_signed_with_the_old_default_is_rejected(
    live_server_with_passcode: LiveServer,
) -> None:
    forged = URLSafeSerializer(OLD_DEFAULT, salt="veillee-passcode-v1").dumps(
        {"ok": True, "role": "writer"}
    )
    response = httpx.get(
        live_server_with_passcode.url("/admin"),
        cookies={"veillee_session": forged},
        timeout=30,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/enter" in response.headers["location"]
