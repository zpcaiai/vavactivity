from __future__ import annotations

import hashlib
import json
import random
import re
from enum import StrEnum
from typing import Any
from uuid import UUID

from vav.common.exceptions import VavError


class ActivityStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class RegistrationStatus(StrEnum):
    STARTED = "started"
    PENDING_APPROVAL = "pending_approval"
    APPROVED_PENDING_PAYMENT = "approved_pending_payment"
    PENDING_PAYMENT = "pending_payment"
    PAYMENT_PROCESSING = "payment_processing"
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AttendanceStatus(StrEnum):
    NOT_CHECKED_IN = "not_checked_in"
    CHECKED_IN = "checked_in"
    CHECKIN_REVOKED = "checkin_revoked"
    NO_SHOW = "no_show"


class WaitlistStatus(StrEnum):
    ACTIVE = "active"
    PROMOTION_OFFERED = "promotion_offered"
    PROMOTED = "promoted"
    DECLINED = "declined"
    OFFER_EXPIRED = "offer_expired"
    CANCELLED = "cancelled"


ACTIVITY_TRANSITIONS: dict[ActivityStatus, frozenset[ActivityStatus]] = {
    ActivityStatus.DRAFT: frozenset({ActivityStatus.IN_REVIEW, ActivityStatus.ARCHIVED}),
    ActivityStatus.IN_REVIEW: frozenset(
        {ActivityStatus.DRAFT, ActivityStatus.SCHEDULED, ActivityStatus.PUBLISHED}
    ),
    ActivityStatus.SCHEDULED: frozenset(
        {ActivityStatus.PUBLISHED, ActivityStatus.CANCELLED, ActivityStatus.DRAFT}
    ),
    ActivityStatus.PUBLISHED: frozenset(
        {
            ActivityStatus.REGISTRATION_OPEN,
            ActivityStatus.REGISTRATION_CLOSED,
            ActivityStatus.CANCELLED,
        }
    ),
    ActivityStatus.REGISTRATION_OPEN: frozenset(
        {ActivityStatus.REGISTRATION_CLOSED, ActivityStatus.CANCELLED}
    ),
    ActivityStatus.REGISTRATION_CLOSED: frozenset(
        {ActivityStatus.IN_PROGRESS, ActivityStatus.CANCELLED}
    ),
    # An event which has already started must use the dedicated incident workflow.
    # The ordinary lifecycle endpoint cannot silently cancel an in-progress event.
    ActivityStatus.IN_PROGRESS: frozenset({ActivityStatus.COMPLETED}),
    ActivityStatus.COMPLETED: frozenset({ActivityStatus.ARCHIVED}),
    ActivityStatus.CANCELLED: frozenset({ActivityStatus.ARCHIVED}),
    ActivityStatus.ARCHIVED: frozenset(),
}


REGISTRATION_TRANSITIONS: dict[RegistrationStatus, frozenset[RegistrationStatus]] = {
    RegistrationStatus.STARTED: frozenset(
        {
            RegistrationStatus.PENDING_APPROVAL,
            RegistrationStatus.PENDING_PAYMENT,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.WAITLISTED,
        }
    ),
    RegistrationStatus.PENDING_APPROVAL: frozenset(
        {
            RegistrationStatus.APPROVED_PENDING_PAYMENT,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.REJECTED,
            RegistrationStatus.CANCELLED,
            RegistrationStatus.WAITLISTED,
        }
    ),
    RegistrationStatus.APPROVED_PENDING_PAYMENT: frozenset(
        {
            RegistrationStatus.PAYMENT_PROCESSING,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.CANCELLED,
            RegistrationStatus.EXPIRED,
        }
    ),
    RegistrationStatus.PENDING_PAYMENT: frozenset(
        {
            RegistrationStatus.PAYMENT_PROCESSING,
            RegistrationStatus.PENDING_APPROVAL,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.CANCELLED,
            RegistrationStatus.EXPIRED,
        }
    ),
    RegistrationStatus.PAYMENT_PROCESSING: frozenset(
        {
            RegistrationStatus.PENDING_APPROVAL,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.CANCELLED,
            RegistrationStatus.EXPIRED,
        }
    ),
    RegistrationStatus.WAITLISTED: frozenset(
        {
            RegistrationStatus.PENDING_APPROVAL,
            RegistrationStatus.PENDING_PAYMENT,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.CANCELLED,
            RegistrationStatus.EXPIRED,
        }
    ),
    RegistrationStatus.CONFIRMED: frozenset({RegistrationStatus.CANCELLED}),
    RegistrationStatus.REJECTED: frozenset(),
    RegistrationStatus.CANCELLED: frozenset(),
    RegistrationStatus.EXPIRED: frozenset(),
}


def ensure_activity_transition(current: str, target: ActivityStatus) -> None:
    try:
        allowed = ACTIVITY_TRANSITIONS[ActivityStatus(current)]
    except ValueError as error:
        raise VavError(
            "ACTIVITY_STATE_INVALID", "Activity state is invalid.", status_code=409
        ) from error
    if target not in allowed:
        raise VavError(
            "ACTIVITY_STATE_TRANSITION_INVALID",
            f"Activity cannot transition from {current} to {target}.",
            status_code=409,
        )


def ensure_registration_transition(current: str, target: RegistrationStatus) -> None:
    try:
        allowed = REGISTRATION_TRANSITIONS[RegistrationStatus(current)]
    except ValueError as error:
        raise VavError(
            "REGISTRATION_STATE_INVALID", "Registration state is invalid.", status_code=409
        ) from error
    if target not in allowed:
        raise VavError(
            "REGISTRATION_STATE_TRANSITION_INVALID",
            f"Registration cannot transition from {current} to {target}.",
            status_code=409,
        )


_SAFE_FIELD_TYPES = {"text", "textarea", "select", "multiselect", "checkbox"}
_SENSITIVE_KEY = re.compile(
    r"(password|passcode|card|cvv|bank|government.?id|passport|medical|diagnosis)",
    re.IGNORECASE,
)
_UNSAFE_TEXT = re.compile(r"<\s*(script|iframe|object)|javascript:", re.IGNORECASE)


def validate_form_schema(schema: dict[str, Any], *, max_fields: int) -> dict[str, Any]:
    fields = schema.get("fields")
    if not isinstance(fields, list) or len(fields) > max_fields:
        raise VavError("ACTIVITY_FORM_SCHEMA_INVALID", "Registration form fields are invalid.")
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            raise VavError("ACTIVITY_FORM_SCHEMA_INVALID", "A form field is invalid.")
        key = str(field.get("key", "")).strip()
        field_type = str(field.get("type", ""))
        if not key or key in seen or _SENSITIVE_KEY.search(key):
            raise VavError("ACTIVITY_FORM_FIELD_FORBIDDEN", "A form field key is not allowed.")
        if field_type not in _SAFE_FIELD_TYPES:
            raise VavError("ACTIVITY_FORM_FIELD_TYPE_INVALID", "A form field type is not allowed.")
        seen.add(key)
    return {"fields": fields}


def validate_form_response(
    schema: dict[str, Any], response: dict[str, Any], *, max_response_chars: int
) -> dict[str, Any]:
    validated_schema = validate_form_schema(schema, max_fields=100)
    definitions = {str(item["key"]): item for item in validated_schema["fields"]}
    if set(response) - set(definitions):
        raise VavError(
            "ACTIVITY_FORM_RESPONSE_INVALID", "Registration response has unknown fields."
        )
    normalized: dict[str, Any] = {}
    for key, definition in definitions.items():
        value = response.get(key)
        if definition.get("required") and (value is None or value == "" or value == []):
            raise VavError("ACTIVITY_FORM_FIELD_REQUIRED", f"{key} is required.")
        if value is None:
            continue
        field_type = str(definition.get("type"))
        if field_type in {"text", "textarea", "select"} and not isinstance(value, str):
            raise VavError("ACTIVITY_FORM_FIELD_TYPE_INVALID", f"{key} has an invalid value type.")
        if field_type == "checkbox" and not isinstance(value, bool):
            raise VavError("ACTIVITY_FORM_FIELD_TYPE_INVALID", f"{key} has an invalid value type.")
        if field_type == "multiselect" and (
            not isinstance(value, list) or any(not isinstance(item, str) for item in value)
        ):
            raise VavError("ACTIVITY_FORM_FIELD_TYPE_INVALID", f"{key} has an invalid value type.")
        option_values = {
            str(option.get("value"))
            for option in definition.get("options", [])
            if isinstance(option, dict) and option.get("value") is not None
        }
        if option_values:
            selected = value if isinstance(value, list) else [value]
            if any(str(item) not in option_values for item in selected):
                raise VavError("ACTIVITY_FORM_OPTION_INVALID", f"{key} contains an invalid option.")
        if isinstance(value, str) and _UNSAFE_TEXT.search(value):
            raise VavError("ACTIVITY_FORM_VALUE_UNSAFE", "HTML or script content is not allowed.")
        normalized[key] = value
    if len(json.dumps(normalized, ensure_ascii=False)) > max_response_chars:
        raise VavError("ACTIVITY_FORM_RESPONSE_TOO_LARGE", "Registration response is too large.")
    return normalized


def deterministic_groups(
    registration_ids: list[UUID], *, target_size: int, seed: str
) -> list[list[UUID]]:
    if target_size < 1:
        raise VavError("GROUP_SIZE_INVALID", "Target group size must be positive.")
    ordered = sorted(registration_ids, key=str)
    random.Random(hashlib.sha256(seed.encode()).digest()).shuffle(ordered)
    return [ordered[index : index + target_size] for index in range(0, len(ordered), target_size)]


def canonical_user_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    if first == second:
        raise VavError("SELF_CHOICE_FORBIDDEN", "A participant cannot choose themselves.")
    return tuple(sorted((first, second), key=str))  # type: ignore[return-value]


def waitlist_order_key(
    *, priority_score: int, manual_order_override: int | None, sequence_number: int
) -> tuple[int, int, int]:
    """Return the public, deterministic ordering used by workers and previews."""
    manual = manual_order_override if manual_order_override is not None else 2**63 - 1
    return (-priority_score, manual, sequence_number)
