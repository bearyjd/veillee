"""/healthz — the one page meant for the machine and the son, not for him."""

from __future__ import annotations

import shutil
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import queue as queue_module
from ..config import Settings
from ..db import get_meta
from ..questions import QuestionBank
from ..storage.gitrepo import last_status
from ..transcode import ffmpeg_available
from .deps import get_bank, get_db, get_settings

router = APIRouter()

LOW_DISK_BYTES = 1024 * 1024 * 1024


@router.get("/healthz")
def healthz(
    connection: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    bank: QuestionBank = Depends(get_bank),
) -> JSONResponse:
    """Disk free, queue depth, last successful backup. Degrades, never 500s."""
    problems: list[str] = []

    try:
        usage = shutil.disk_usage(settings.data_dir)
        disk = {
            "free_bytes": usage.free,
            "free_human": f"{usage.free / 1_000_000_000:.1f} GB",
            "total_human": f"{usage.total / 1_000_000_000:.1f} GB",
        }
        if usage.free < LOW_DISK_BYTES:
            problems.append("less than 1 GB of disk free")
    except OSError as exc:
        disk = {"error": str(exc)}
        problems.append(f"cannot read disk usage: {exc}")

    try:
        depth = queue_module.depth(connection)
        if depth.get(queue_module.STATE_DEAD):
            problems.append(f"{depth[queue_module.STATE_DEAD]} transcription jobs gave up")
        last_backup = get_meta(connection, "last_backup", "never")
        answers = connection.execute("SELECT COUNT(*) AS n FROM answers").fetchone()["n"]
        recordings = connection.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"]
        photographs = connection.execute("SELECT COUNT(*) AS n FROM photographs").fetchone()["n"]
    except sqlite3.Error as exc:
        depth, last_backup, answers, recordings, photographs = {}, "unknown", -1, -1, -1
        problems.append(f"index unreadable, run `veillee reindex`: {exc}")

    git = last_status()
    if git.enabled and not git.ok:
        problems.append(f"data/ git: {git.detail}")

    if not ffmpeg_available():
        problems.append("ffmpeg is not installed; recordings cannot be processed")

    return JSONResponse(
        {
            "status": "ok" if not problems else "degraded",
            "problems": problems,
            "disk": disk,
            "queue": depth,
            "last_backup": last_backup,
            "counts": {
                "answers": answers,
                "recordings": recordings,
                "photographs": photographs,
                "questions": len(bank.questions),
            },
            "data_dir": str(settings.data_dir.resolve()),
            "git": {"enabled": git.enabled, "ok": git.ok, "detail": git.detail},
            "ffmpeg": ffmpeg_available(),
            "transcription_backend": settings.transcription_backend,
        }
    )
