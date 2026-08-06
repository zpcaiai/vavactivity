import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

SENSITIVE_KEY_PARTS = {
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "email",
    "phone",
    "contact",
    "conversation",
    "counseling",
    "profile_body",
    "evidence",
    "card",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(part in str(key).casefold() for part in SENSITIVE_KEY_PARTS)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redact_sensitive(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    return cast(dict[str, Any], _redact(dict(event_dict)))


def add_service_identity(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    event_dict.setdefault("service", "api")
    return dict(event_dict)


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_service_identity,
            redact_sensitive,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
