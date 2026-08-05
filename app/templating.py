"""Shared Jinja2 template environment + filters for HTML pages."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from starlette.templating import Jinja2Templates

from app.config import BASE_DIR, get_settings

IST = ZoneInfo("Asia/Kolkata")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _ist(dt: datetime | None, fmt: str = "%d %b %Y, %H:%M") -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime(fmt) + " IST"


def _pct(value, digits: int = 0) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


templates.env.filters["ist"] = _ist
templates.env.filters["pct"] = _pct
templates.env.globals["app_name"] = get_settings().app_name
