"""Delete and autosave routes must refuse oversized or malformed JSON bodies."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from veillee.web.json_body import JSON_BODY_LIMIT_BYTES, read_capped_json


def _request(parts: list[bytes], headers: dict[str, str]) -> tuple[Request, list[int]]:
    consumed: list[int] = []
    queue = list(parts)

    async def receive() -> dict:
        if not queue:
            return {"type": "http.request", "body": b"", "more_body": False}
        part = queue.pop(0)
        consumed.append(len(part))
        return {"type": "http.request", "body": part, "more_body": bool(queue)}

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope, receive), consumed


def test_limit_is_64_kb() -> None:
    assert JSON_BODY_LIMIT_BYTES == 64 * 1024


async def test_declared_oversize_is_refused_unread() -> None:
    request, consumed = _request([b"{}"], {"content-length": str(JSON_BODY_LIMIT_BYTES + 1)})
    with pytest.raises(HTTPException) as exc:
        await read_capped_json(request)
    assert exc.value.status_code == 413
    assert consumed == []


async def test_undeclared_oversize_stops_streaming() -> None:
    request, consumed = _request([b"x" * 40_000] * 50, {})
    with pytest.raises(HTTPException) as exc:
        await read_capped_json(request)
    assert exc.value.status_code == 413
    assert len(consumed) == 2


async def test_malformed_json_is_400() -> None:
    request, _ = _request([b"{not json"], {})
    with pytest.raises(HTTPException) as exc:
        await read_capped_json(request)
    assert exc.value.status_code == 400


async def test_small_json_is_parsed() -> None:
    request, _ = _request([b'{"confirm": "delete"}'], {})
    assert await read_capped_json(request) == {"confirm": "delete"}
