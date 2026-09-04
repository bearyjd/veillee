"""Optional single passcode.

Off by default: the tailnet is the security boundary. When it is on, the cookie
is signed and long-lived, because asking an eighty-year-old for a password twice
on the same iPad is a way to lose a user.
"""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeSerializer

from ..config import Settings

COOKIE_NAME = "veillee_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 5
_SALT = "veillee-passcode-v1"
OPEN_PATHS = frozenset({"/healthz", "/enter"})


def _serializer(settings: Settings) -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt=_SALT)


def issue_cookie(response: Response, settings: Settings) -> None:
    """Mark this device as known, for a long time."""
    token = _serializer(settings).dumps({"ok": True})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Served over HTTPS by `tailscale serve`, but the app itself listens on
        # plain HTTP on 127.0.0.1, so this cannot be marked Secure.
        secure=False,
    )


def has_valid_cookie(request: Request, settings: Settings) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    try:
        payload = _serializer(settings).loads(token)
    except BadSignature:
        return False
    return bool(isinstance(payload, dict) and payload.get("ok"))


def passcode_matches(candidate: str, settings: Settings) -> bool:
    """Constant-time comparison, so the passcode cannot be guessed by timing."""
    if not settings.passcode:
        return True
    return hmac.compare_digest(candidate.strip(), settings.passcode)


def is_authorised(request: Request, settings: Settings) -> bool:
    if not settings.passcode:
        return True
    if request.url.path in OPEN_PATHS or request.url.path.startswith("/static/"):
        return True
    return has_valid_cookie(request, settings)


def redirect_to_entry(request: Request) -> RedirectResponse:
    destination = request.url.path
    suffix = f"?next={destination}" if destination and destination != "/" else ""
    return RedirectResponse(f"/enter{suffix}", status_code=303)
