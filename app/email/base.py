"""Email provider interface + selection.

``console`` (default) writes a valid ``.eml`` and an HTML preview to ``outbox/``
and records the send in the database — the entire escalation workflow is
demonstrable with no email account. ``smtp`` sends real mail over STARTTLS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from app.config import get_settings


@dataclass
class OutboundEmail:
    to: list[str]
    subject: str
    html_body: str
    text_body: str
    message_id: str
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    from_addr: Optional[str] = None
    grievance_id: Optional[str] = None
    kind: str = "dispatch"  # dispatch | escalation | citizen | info
    extra_headers: dict = field(default_factory=dict)


@dataclass
class SendResult:
    ok: bool
    message_id: str
    provider: str
    path: Optional[str] = None
    detail: str = ""


class EmailProvider(Protocol):
    async def send(self, message: OutboundEmail) -> SendResult: ...

    @property
    def name(self) -> str: ...


_PROVIDER: EmailProvider | None = None
_PROVIDER_KIND: str | None = None


def get_email_provider() -> EmailProvider:
    global _PROVIDER, _PROVIDER_KIND
    kind = get_settings().email_provider.lower()
    if _PROVIDER is None or _PROVIDER_KIND != kind:
        if kind == "smtp":
            from app.email.smtp import SmtpEmailProvider

            _PROVIDER = SmtpEmailProvider()
        else:
            from app.email.console import ConsoleEmailProvider

            _PROVIDER = ConsoleEmailProvider()
        _PROVIDER_KIND = kind
    return _PROVIDER


def reset_email_provider() -> None:
    global _PROVIDER, _PROVIDER_KIND
    _PROVIDER = None
    _PROVIDER_KIND = None
