from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from vav.common.exceptions import VavError
from vav.core.config import get_settings


@dataclass(frozen=True)
class EmailProviderCapabilities:
    transactional_email: bool = True
    bulk_email: bool = False
    provider_templates: bool = False
    delivery_webhooks: bool = False
    bounce_webhooks: bool = False
    complaint_webhooks: bool = False
    unsubscribe_headers: bool = True
    custom_metadata: bool = True


@dataclass(frozen=True)
class EmailSendRequest:
    from_address: str
    from_name: str
    to_address: str
    reply_to: str | None
    subject: str
    html_body: str
    text_body: str
    headers: dict[str, str]
    tags: dict[str, str]
    idempotency_key: str


@dataclass(frozen=True)
class EmailSendResult:
    provider_message_id: str
    status: str
    response_code: str


class EmailProvider(Protocol):
    name: str
    capabilities: EmailProviderCapabilities

    async def send(self, request: EmailSendRequest) -> EmailSendResult: ...

    async def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool: ...


class FakeEmailProvider:
    name = "fake"
    capabilities = EmailProviderCapabilities(
        delivery_webhooks=True, bounce_webhooks=True, complaint_webhooks=True
    )

    def __init__(self) -> None:
        self.requests: list[EmailSendRequest] = []

    async def send(self, request: EmailSendRequest) -> EmailSendResult:
        self.requests.append(request)
        return EmailSendResult(f"fake-{request.idempotency_key}", "accepted", "250")

    async def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        secret = get_settings().notification_email_provider_webhook_secret.get_secret_value()
        return bool(secret) and headers.get("x-vav-notification-secret") == secret


class MailpitEmailProvider(FakeEmailProvider):
    name = "mailpit"
    capabilities = EmailProviderCapabilities()

    async def send(self, request: EmailSendRequest) -> EmailSendResult:
        message = EmailMessage()
        message["From"] = f"{request.from_name} <{request.from_address}>"
        message["To"] = request.to_address
        message["Subject"] = request.subject
        if request.reply_to:
            message["Reply-To"] = request.reply_to
        for key, value in request.headers.items():
            message[key] = value
        message.set_content(request.text_body)
        message.add_alternative(request.html_body, subtype="html")

        def send_sync() -> None:
            settings = get_settings()
            with smtplib.SMTP(
                settings.mailpit_smtp_host,
                settings.mailpit_smtp_port,
                timeout=settings.notification_delivery_timeout_seconds,
            ) as smtp:
                smtp.send_message(message)

        try:
            await asyncio.wait_for(
                asyncio.to_thread(send_sync),
                timeout=get_settings().notification_delivery_timeout_seconds + 1,
            )
        except (TimeoutError, OSError, smtplib.SMTPException) as exc:
            raise VavError(
                "NOTIFICATION_PROVIDER_TEMPORARY",
                "The development email provider is temporarily unavailable.",
                status_code=503,
            ) from exc
        return EmailSendResult(
            f"mailpit-{request.idempotency_key}",
            "accepted",
            "250",
        )


class ExternalEmailProvider(FakeEmailProvider):
    name = "external"

    async def send(self, request: EmailSendRequest) -> EmailSendResult:
        raise VavError(
            "NOTIFICATION_EXTERNAL_PROVIDER_NOT_CONFIGURED",
            "The external email provider adapter is not configured.",
            status_code=503,
        )


_FAKE_PROVIDER = FakeEmailProvider()


def configured_email_provider() -> EmailProvider:
    provider = get_settings().notification_email_provider
    if provider == "fake":
        return _FAKE_PROVIDER
    if provider == "mailpit":
        return MailpitEmailProvider()
    if provider == "external":
        return ExternalEmailProvider()
    raise VavError(
        "NOTIFICATION_PROVIDER_INVALID",
        "The configured notification provider is not supported.",
        status_code=503,
    )
