"""The Path B upload must refuse an oversized body before multipart parsing spools it."""

from __future__ import annotations

import socket

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from starlette.requests import Request

from tests.conftest import LiveServer, _start_server
from veillee.web.routes_audio import _read_capped_form

LIMIT = 1024
BOUNDARY = "veilleeboundary"


def _multipart(payload: bytes) -> bytes:
    return (
        (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.m4a"\r\n'
            "Content-Type: audio/m4a\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{BOUNDARY}--\r\n".encode()
    )


def _request(parts: list[bytes], headers: dict[str, str]) -> tuple[Request, list[int]]:
    consumed: list[int] = []
    queue = list(parts)

    async def receive() -> dict:
        if not queue:
            return {"type": "http.request", "body": b"", "more_body": False}
        part = queue.pop(0)
        consumed.append(len(part))
        return {"type": "http.request", "body": part, "more_body": bool(queue)}

    all_headers = {"content-type": f"multipart/form-data; boundary={BOUNDARY}", **headers}
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(k.lower().encode(), v.encode()) for k, v in all_headers.items()],
    }
    return Request(scope, receive), consumed


async def test_declared_oversize_is_refused_without_reading_the_body() -> None:
    request, consumed = _request([b"x" * 600, b"x" * 600], {"content-length": "1200"})
    with pytest.raises(HTTPException) as exc:
        await _read_capped_form(request, LIMIT)
    assert exc.value.status_code == 413
    assert consumed == []


async def test_undeclared_oversize_stops_streaming_at_the_cap() -> None:
    body = _multipart(b"x" * 30_000)
    parts = [body[i : i + 600] for i in range(0, len(body), 600)]
    request, consumed = _request(parts, {})
    with pytest.raises(HTTPException) as exc:
        await _read_capped_form(request, LIMIT)
    assert exc.value.status_code == 413
    assert sum(consumed) <= LIMIT + 600


async def test_body_within_the_cap_is_parsed() -> None:
    body = _multipart(b"abcd")
    request, _ = _request([body], {"content-length": str(len(body))})
    form = await _read_capped_form(request, LIMIT)
    try:
        upload = form.get("file")
        assert isinstance(upload, UploadFile)
        assert await upload.read() == b"abcd"
    finally:
        await form.close()


async def test_malformed_content_length_is_a_400() -> None:
    request, _ = _request([b"a"], {"content-length": "abc"})
    with pytest.raises(HTTPException) as exc:
        await _read_capped_form(request, LIMIT)
    assert exc.value.status_code == 400


@pytest.fixture
def small_cap_server(tmp_path):  # type: ignore[no-untyped-def]
    yield from _start_server(tmp_path, {"VEILLEE_MAX_UPLOAD_BYTES": str(LIMIT)})


def test_upload_endpoint_answers_413_without_waiting_for_the_body(
    small_cap_server: LiveServer,
) -> None:
    """Declare a huge body, send a few bytes: the server must refuse at once.

    Before the cap, the endpoint waited for the whole body to be parsed (and
    spooled to disk) before checking its size, so this read would time out.
    """
    host, port = small_cap_server.base_url.removeprefix("http://").split(":")
    head = (
        "POST /api/upload/q012 HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Type: multipart/form-data; boundary={BOUNDARY}\r\n"
        f"Content-Length: {10**10}\r\n\r\n"
    ).encode()
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        sock.sendall(head + _multipart(b"x" * 16)[:64])
        response = sock.recv(4096)
    assert response.startswith(b"HTTP/1.1 413"), response[:200]
