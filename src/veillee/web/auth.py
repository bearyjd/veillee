"""Who may write, and who may only read.

Two passcodes, both optional and both off by default. The tailnet remains the
security boundary; these exist so that relatives can be given the address
without being able to change a word of what he wrote.

* `VEILLEE_PASSCODE` — his. Full access.
* `VEILLEE_FAMILY_PASSCODE` — theirs. Read-only, and no transcripts.

Read-only is enforced on the server by method and path, not by hiding buttons.
Hidden buttons are a courtesy; the middleware is the rule.
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

ROLE_WRITER = "writer"
ROLE_FAMILY = "family"

OPEN_PATHS = frozenset({"/healthz", "/enter"})

# Everything a reader may see. Anything else is his alone - most importantly
# /admin, where the machine transcripts live.
FAMILY_DENIED_PREFIXES = ("/admin", "/api/answer", "/api/recording", "/api/photo", "/questions")


def _serializer(settings: Settings) -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt=_SALT)


def issue_cookie(response: Response, settings: Settings, role: str = ROLE_WRITER) -> None:
    """Mark this device as known, and as what, for a long time."""
    token = _serializer(settings).dumps({"ok": True, "role": role})
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


def role_from_cookie(request: Request, settings: Settings) -> str | None:
    """The role this device signed in as, or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = _serializer(settings).loads(token)
    except BadSignature:
        return None
    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    role = str(payload.get("role", ROLE_WRITER))
    return role if role in {ROLE_WRITER, ROLE_FAMILY} else ROLE_WRITER


def has_valid_cookie(request: Request, settings: Settings) -> bool:
    return role_from_cookie(request, settings) is not None


def passcode_matches(candidate: str, settings: Settings) -> bool:
    """Constant-time comparison, so the passcode cannot be guessed by timing."""
    if not settings.passcode:
        return True
    return hmac.compare_digest(candidate.strip(), settings.passcode)


def role_for_passcode(candidate: str, settings: Settings) -> str | None:
    """Which role a typed word earns, or None if it earns nothing.

    Both are compared every time, so a wrong word takes the same path as a
    right one.
    """
    typed = candidate.strip()
    writer = settings.passcode or ""
    family = settings.family_passcode or ""
    writer_ok = bool(writer) and hmac.compare_digest(typed, writer)
    family_ok = bool(family) and hmac.compare_digest(typed, family)
    if writer_ok:
        return ROLE_WRITER
    if family_ok:
        return ROLE_FAMILY
    return None


def passcodes_enabled(settings: Settings) -> bool:
    return bool(settings.passcode or settings.family_passcode)


def is_open_path(path: str) -> bool:
    return path in OPEN_PATHS or path.startswith("/static/")


def is_authorised(request: Request, settings: Settings) -> bool:
    if not passcodes_enabled(settings):
        return True
    if is_open_path(request.url.path):
        return True
    return has_valid_cookie(request, settings)


def family_may(request: Request) -> bool:
    """Whether a read-only visitor is allowed to make this request."""
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        return False
    return not any(request.url.path.startswith(prefix) for prefix in FAMILY_DENIED_PREFIXES)


def redirect_to_entry(request: Request) -> RedirectResponse:
    destination = request.url.path
    suffix = f"?next={destination}" if destination and destination != "/" else ""
    return RedirectResponse(f"/enter{suffix}", status_code=303)
