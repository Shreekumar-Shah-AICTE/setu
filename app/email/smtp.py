"""SmtpEmailProvider — real SMTP over STARTTLS (Gmail app-password friendly).

Runs the blocking smtplib call in a worker thread so it does not block the event
loop. Credentials come exclusively from the environment.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib

from app.config import get_settings
from app.email.base import OutboundEmail, SendResult
from app.email.threading import build_email_message

logger = logging.getLogger("setu.email")


class SmtpEmailProvider:
    @property
    def name(self) -> str:
        return "smtp"

    def _send_blocking(self, message: OutboundEmail) -> SendResult:
        settings = get_settings()
        from_addr = message.from_addr or settings.email_from
        msg = build_email_message(
            to=message.to, subject=message.subject, html_body=message.html_body,
            text_body=message.text_body, message_id=message.message_id, from_addr=from_addr,
            in_reply_to=message.in_reply_to, references=message.references,
            extra_headers=message.extra_headers,
        )
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.ehlo()
            if settings.smtp_use_tls:
                server.starttls()
                server.ehlo()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        logger.info("[smtp] sent to=%s subject=%r", message.to, message.subject)
        return SendResult(ok=True, message_id=message.message_id, provider="smtp", detail="sent")

    async def send(self, message: OutboundEmail) -> SendResult:
        try:
            return await asyncio.to_thread(self._send_blocking, message)
        except Exception as exc:  # network/auth errors surface but never crash the app
            logger.error("[smtp] send failed: %s", exc)
            return SendResult(
                ok=False, message_id=message.message_id, provider="smtp", detail=str(exc)
            )
