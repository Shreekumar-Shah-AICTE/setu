"""ConsoleEmailProvider — the default, account-free provider.

Writes a valid RFC-822 ``.eml`` file and a rendered ``.html`` preview to
``outbox/`` and logs a one-line summary. The magic-link URLs in the preview are
live and clickable. The DB record of the send is written by the dispatcher as a
grievance event.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.config import get_settings
from app.email.base import OutboundEmail, SendResult
from app.email.threading import build_email_message

logger = logging.getLogger("setu.email")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]


class ConsoleEmailProvider:
    @property
    def name(self) -> str:
        return "console"

    async def send(self, message: OutboundEmail) -> SendResult:
        settings = get_settings()
        from_addr = message.from_addr or settings.email_from
        msg = build_email_message(
            to=message.to, subject=message.subject, html_body=message.html_body,
            text_body=message.text_body, message_id=message.message_id, from_addr=from_addr,
            in_reply_to=message.in_reply_to, references=message.references,
            extra_headers=message.extra_headers,
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        stem = f"{stamp}_{message.kind}_{_safe(message.grievance_id or 'na')}"
        outbox = settings.outbox_path
        eml_path = outbox / f"{stem}.eml"
        html_path = outbox / f"{stem}.html"
        eml_path.write_bytes(msg.as_bytes())
        html_path.write_text(message.html_body, encoding="utf-8")
        logger.info(
            "[console-email] to=%s subject=%r kind=%s -> %s",
            message.to, message.subject, message.kind, eml_path.name,
        )
        return SendResult(
            ok=True, message_id=message.message_id, provider="console",
            path=str(eml_path), detail=f"wrote {eml_path.name}",
        )
