"""Render the bilingual email templates (HTML + plain-text alternative)."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_officer_dispatch(context: dict) -> tuple[str, str]:
    html = _env.get_template("officer_dispatch.html").render(**context)
    text = _env.get_template("officer_dispatch.txt").render(**context)
    return html, text


def render_citizen_notice(context: dict) -> tuple[str, str]:
    html = _env.get_template("citizen_notice.html").render(**context)
    text = _env.get_template("citizen_notice.txt").render(**context)
    return html, text
