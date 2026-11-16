"""The chunk endpoint must refuse an oversized body before buffering it."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from veillee.web.routes_audio import _read_capped_body

LIMIT = 1024


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


async def test_declared_oversize_is_refused_without_reading_the_body() -> None:
    request, consumed = _request([b"x" * 600, b"x" * 600], {"content-length": "1200"})
    with pytest.raises(HTTPException) as exc:
        await _read_capped_body(request, LIMIT)
    assert exc.value.status_code == 413
    assert consumed == []


async def test_undeclared_oversize_stops_streaming_at_the_cap() -> None:
    parts = [b"x" * 600] * 50
    request, consumed = _request(parts, {})
    with pytest.raises(HTTPException) as exc:
        await _read_capped_body(request, LIMIT)
    assert exc.value.status_code == 413
    assert len(consumed) == 2


async def test_body_within_the_cap_is_returned_whole() -> None:
    request, _ = _request([b"ab", b"cd"], {"content-length": "4"})
    assert await _read_capped_body(request, LIMIT) == b"abcd"


async def test_malformed_content_length_is_a_400() -> None:
    request, _ = _request([b"a"], {"content-length": "abc"})
    with pytest.raises(HTTPException) as exc:
        await _read_capped_body(request, LIMIT)
    assert exc.value.status_code == 400
