from __future__ import annotations

import asyncio
import html
import smtplib
from email.message import EmailMessage

import structlog

from vav.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class EmailService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_link(self, *, recipient: str, subject: str, title: str, link: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(f"{title}\n\n{link}")
        message.add_alternative(
            (
                "<!doctype html><html><body>"
                f"<h1>{html.escape(title)}</h1>"
                f'<p><a href="{html.escape(link, quote=True)}">Continue</a></p>'
                "<p>If you did not request this action, ignore this message.</p>"
                "</body></html>"
            ),
            subtype="html",
        )
        try:
            await asyncio.to_thread(self._send, message)
        except OSError as exc:
            logger.warning("email_delivery_deferred", error_type=type(exc).__name__)

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=5) as client:
            client.send_message(message)
