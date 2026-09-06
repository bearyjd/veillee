"""Jinja environment and the small filters the templates need."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def friendly_time(value: str) -> str:
    """'2026-09-03T14:12:07Z' -> '2:14pm'. Quiet, not clinical."""
    try:
        moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return ""
    hour = moment.hour % 12 or 12
    meridiem = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d}{meridiem}"


def friendly_date(value: str) -> str:
    """'2026-09-03T14:12:07Z' -> '3 September 2026'."""
    try:
        moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return ""
    return f"{moment.day} {moment:%B %Y}"


def friendly_duration(seconds: float) -> str:
    """Durations a person reads at a glance: '4 minutes 12 seconds'."""
    total = int(round(seconds))
    minutes, remainder = divmod(total, 60)
    if minutes and remainder:
        return f"{minutes} minute{'s' if minutes != 1 else ''} {remainder} seconds"
    if minutes:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{remainder} second{'s' if remainder != 1 else ''}"


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR), context_processors=[role_context])
    templates.env.filters["friendly_time"] = friendly_time
    templates.env.filters["friendly_date"] = friendly_date
    templates.env.filters["friendly_duration"] = friendly_duration
    templates.env.globals["site_name"] = "Veillée"
    return templates


def role_context(request: Request) -> dict[str, object]:
    """Give every template the viewer's role, so write controls can be hidden.

    Hiding them is only a courtesy - the middleware refuses the request anyway -
    but showing a reader a Save button he cannot use is its own small unkindness.
    """
    role = str(getattr(request.state, "role", "writer"))
    return {"role": role, "read_only": role == "family"}
