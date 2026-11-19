"""Size-capped JSON request bodies for the small delete and autosave routes."""

from __future__ import annotations

import json

from fastapi import HTTPException, Request

JSON_BODY_LIMIT_BYTES = 64 * 1024
_TOO_LARGE = "Request body too large"


async def read_capped_json(request: Request, limit: int = JSON_BODY_LIMIT_BYTES) -> object:
    """Parse a JSON body, refusing with 413 before buffering more than `limit` bytes."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            too_big = int(declared) > limit
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed Content-Length") from None
        if too_big:
            raise HTTPException(status_code=413, detail=_TOO_LARGE)

    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > limit:
            raise HTTPException(status_code=413, detail=_TOO_LARGE)
    try:
        return json.loads(bytes(body))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Malformed JSON body") from None
