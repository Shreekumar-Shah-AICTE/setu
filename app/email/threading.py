"""Email threading helpers.

A grievance keeps a stable ``root_message_id``. The first dispatch uses it as
the ``Message-ID``; every subsequent escalation/citizen mail sets
``In-Reply-To`` and ``References`` to it, so the whole grievance stays as one
Gmail thread.
"""
from __future__ import annotations

import email.utils
import secrets
from email.message import EmailMessage
from urllib.parse import urlparse

from app.config import get_settings


def _domain() -> str:
    host = urlparse(get_settings().public_base_url).hostname or "setu.local"
    return host


def new_message_id() -> str:
    return email.utils.make_msgid(idstring=secrets.token_hex(6), domain=_domain())


def build_email_message(
    *,
    to: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    message_id: str,
    from_addr: str,
    in_reply_to: str | None = None,
    references: str | None = None,
    extra_headers: dict | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    msg["Message-ID"] = message_id
    msg["Date"] = email.utils.formatdate(localtime=True)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    for key, value in (extra_headers or {}).items():
        msg[key] = value
    # Plain-text part first, then the HTML alternative.
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg
