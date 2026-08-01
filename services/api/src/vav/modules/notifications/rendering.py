from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

from vav.common.exceptions import VavError

VARIABLE = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*}}")
UNSAFE_TEMPLATE = re.compile(
    r"<\s*(script|iframe|form)|\bon[a-z]+\s*=|javascript\s*:|data\s*:|{%|{#|__",
    re.IGNORECASE,
)
CONTROLLED_ROUTES = {
    "account-order": "/account/orders/{orderId}",
    "account-activity": "/account/activities/{registrationId}",
    "account-course": "/account/courses/{enrollmentId}",
    "account-counseling-appointment": "/account/counseling/appointments/{appointmentId}",
    "account-ai-assistant": "/ai-assistant/{conversationId}",
    "account-security": "/account/security",
    "account-notifications": "/account/notifications",
}


@dataclass(frozen=True)
class RenderedTemplate:
    subject: str | None
    title: str | None
    body_html: str | None
    body_text: str
    action_label: str | None
    action_url: str | None


def validate_variable_schema(schema: dict[str, Any], variables: dict[str, Any]) -> None:
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise VavError(
            "NOTIFICATION_TEMPLATE_SCHEMA_UNSAFE",
            "Template schemas must be closed object schemas.",
            status_code=422,
        )
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise VavError(
            "NOTIFICATION_TEMPLATE_SCHEMA_INVALID", "Invalid variable schema.", status_code=422
        )
    required = schema.get("required", [])
    missing = sorted(set(required) - set(variables))
    extra = sorted(set(variables) - set(properties))
    if missing or extra:
        raise VavError(
            "NOTIFICATION_TEMPLATE_VARIABLES_INVALID",
            "Template variables do not match the release schema.",
            details=[{"missing": missing, "extra": extra}],
            status_code=422,
        )
    for key, value in variables.items():
        rule = properties[key]
        expected = rule.get("type")
        valid = (
            (expected == "string" and isinstance(value, str))
            or (expected == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (expected == "boolean" and isinstance(value, bool))
        )
        if not valid:
            raise VavError(
                "NOTIFICATION_TEMPLATE_VARIABLE_TYPE_INVALID",
                f"Template variable {key} has an invalid type.",
                status_code=422,
            )
        if isinstance(value, str) and len(value) > int(rule.get("maxLength", 2000)):
            raise VavError(
                "NOTIFICATION_TEMPLATE_VARIABLE_TOO_LONG",
                f"Template variable {key} is too long.",
                status_code=422,
            )


def validate_template_source(source: str | None) -> None:
    if source is None:
        return
    if UNSAFE_TEMPLATE.search(source):
        raise VavError(
            "NOTIFICATION_TEMPLATE_UNSAFE",
            "Template source contains an unsafe construct.",
            status_code=422,
        )
    if "{{" in VARIABLE.sub("", source) or "}}" in VARIABLE.sub("", source):
        raise VavError(
            "NOTIFICATION_TEMPLATE_EXPRESSION_FORBIDDEN",
            "Only declared simple variables are allowed.",
            status_code=422,
        )


def _render(source: str | None, variables: dict[str, Any]) -> str | None:
    if source is None:
        return None
    validate_template_source(source)

    def replacement(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            raise VavError(
                "NOTIFICATION_TEMPLATE_VARIABLE_MISSING",
                f"Template variable {key} is missing.",
                status_code=422,
            )
        return html.escape(str(variables[key]), quote=True)

    return VARIABLE.sub(replacement, source)


def render_template(
    *,
    schema: dict[str, Any],
    variables: dict[str, Any],
    subject_template: str | None,
    title_template: str | None,
    body_html_template: str | None,
    body_text_template: str,
    action_label_template: str | None,
    action_url_template: str | None,
) -> RenderedTemplate:
    validate_variable_schema(schema, variables)
    rendered = RenderedTemplate(
        subject=_render(subject_template, variables),
        title=_render(title_template, variables),
        body_html=_render(body_html_template, variables),
        body_text=_render(body_text_template, variables) or "",
        action_label=_render(action_label_template, variables),
        action_url=_render(action_url_template, variables),
    )
    if rendered.action_url and (
        not rendered.action_url.startswith("/") or rendered.action_url.startswith("//")
    ):
        raise VavError(
            "NOTIFICATION_ACTION_URL_UNSAFE",
            "Notification action URLs must be local routes.",
            status_code=422,
        )
    if body_html_template is not None and rendered.body_html is None:
        raise VavError("NOTIFICATION_TEMPLATE_INVALID", "HTML rendering failed.", status_code=422)
    return rendered


def route_from_reference(reference: dict[str, Any] | None) -> str | None:
    if reference is None:
        return None
    route_name = reference.get("route_name")
    params = reference.get("params", {})
    template = CONTROLLED_ROUTES.get(str(route_name))
    if template is None or not isinstance(params, dict):
        raise VavError(
            "NOTIFICATION_ACTION_ROUTE_FORBIDDEN",
            "Notification action route is not registered.",
            status_code=422,
        )
    try:
        url = template.format(**{key: str(value) for key, value in params.items()})
    except KeyError as exc:
        raise VavError(
            "NOTIFICATION_ACTION_ROUTE_INVALID",
            "Notification action parameters are incomplete.",
            status_code=422,
        ) from exc
    if ".." in url or "//" in url:
        raise VavError(
            "NOTIFICATION_ACTION_ROUTE_INVALID", "Unsafe route parameters.", status_code=422
        )
    return url
