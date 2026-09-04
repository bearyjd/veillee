"""The application. Binds 127.0.0.1; reached over Tailscale, never Funnel."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from ..config import Settings, load_settings
from ..db import initialise
from ..index import reindex
from ..questions import load_bank
from ..storage.gitrepo import ensure_repo
from . import auth, routes_admin, routes_answers, routes_audio, routes_health, routes_pages
from .deps import AppState
from .templating import STATIC_DIR, build_templates

logger = logging.getLogger(__name__)
templates = build_templates()


def _startup(app: FastAPI, settings: Settings) -> None:
    """Everything that must be true before the first request is served."""
    settings.ensure_dirs()
    initialise(settings.db_path)
    if settings.git_autocommit:
        ensure_repo(settings.data_dir)
    bank = load_bank(settings.questions_dir, settings.custom_questions_path)
    app.state.veillee = AppState(settings=settings, bank=bank)
    # The index is a cache of the disk; reconcile it at every boot so a crash or
    # an out-of-band edit can never leave the site showing stale answers.
    report = reindex(settings)
    for problem in report.problems:
        logger.error("reindex problem: %s", problem)
    logger.info(
        "veillee ready: %d questions, %d answers, %d recordings",
        len(bank.questions), report.answers, report.recordings,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _startup(app, resolved)
        yield

    app = FastAPI(
        title="Veillée",
        description="A private oral history site.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def passcode_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        state = getattr(request.app.state, "veillee", None)
        active = state.settings if state else resolved
        if not auth.is_authorised(request, active):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Not signed in"}, status_code=401)
            return auth.redirect_to_entry(request)
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(routes_health.router)
    app.include_router(routes_pages.router)
    app.include_router(routes_answers.router)
    app.include_router(routes_audio.router)
    app.include_router(routes_admin.router)

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> Response:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if request.url.path.startswith("/static/"):
            return Response(status_code=404)
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> RedirectResponse:
        return RedirectResponse("/static/favicon.svg", status_code=301)

    return app


app_singleton: FastAPI | None = None


def get_app() -> FastAPI:
    """Entry point for `uvicorn veillee.web.app:get_app`."""
    global app_singleton
    if app_singleton is None:
        app_singleton = create_app()
    return app_singleton


__all__ = ["create_app", "get_app", "HTMLResponse"]
