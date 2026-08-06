from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from vav.common.exceptions import VavError
from vav.modules.notifications.rendering import render_template, route_from_reference
from vav.modules.notifications.schemas import NotificationPreferenceItem
from vav.modules.notifications.service import (
    quiet_hours_end,
    retry_delay,
    validate_campaign_audience,
)

SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {"name": {"type": "string", "maxLength": 20}},
    "additionalProperties": False,
}


def test_template_renders_declared_values_with_html_escape() -> None:
    value = render_template(
        schema=SCHEMA,
        variables={"name": "<Stephen>"},
        subject_template="Hello {{ name }}",
        title_template="通知",
        body_html_template="<p>{{ name }}</p>",
        body_text_template="{{ name }}",
        action_label_template="Open",
        action_url_template="/account/notifications",
    )
    assert value.body_html == "<p>&lt;Stephen&gt;</p>"
    assert value.body_text == "&lt;Stephen&gt;"


@pytest.mark.parametrize(
    "source",
    ["<script>alert(1)</script>", '<a href="javascript:alert(1)">x</a>', "{% import os %}"],
)
def test_template_rejects_executable_sources(source: str) -> None:
    with pytest.raises(VavError) as error:
        render_template(
            schema=SCHEMA,
            variables={"name": "safe"},
            subject_template="safe",
            title_template="safe",
            body_html_template=source,
            body_text_template="safe",
            action_label_template=None,
            action_url_template=None,
        )
    assert error.value.code.startswith("NOTIFICATION_TEMPLATE_")


def test_template_rejects_missing_and_extra_variables() -> None:
    with pytest.raises(VavError) as error:
        render_template(
            schema=SCHEMA,
            variables={"other": "value"},
            subject_template="safe",
            title_template=None,
            body_html_template=None,
            body_text_template="safe",
            action_label_template=None,
            action_url_template=None,
        )
    assert error.value.code == "NOTIFICATION_TEMPLATE_VARIABLES_INVALID"


def test_controlled_route_registry_rejects_open_redirects() -> None:
    assert (
        route_from_reference({"route_name": "account-order", "params": {"orderId": "123"}})
        == "/account/orders/123"
    )
    with pytest.raises(VavError) as error:
        route_from_reference({"route_name": "https://attacker.example", "params": {}})
    assert error.value.code == "NOTIFICATION_ACTION_ROUTE_FORBIDDEN"


def test_cross_midnight_quiet_hours_use_iana_timezone() -> None:
    delayed_until = quiet_hours_end(
        now=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
        start=time(22, 0),
        end=time(8, 0),
        timezone_name="Asia/Shanghai",
    )
    assert delayed_until == datetime(2026, 8, 2, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("timezone_name", ["UTC", "Etc/UTC", "Asia/Shanghai"])
def test_notification_preference_accepts_real_iana_timezones(timezone_name: str) -> None:
    preference = NotificationPreferenceItem(
        category="activity",
        channel="email",
        enabled=True,
        quiet_hours_timezone=timezone_name,
    )
    assert preference.quiet_hours_timezone == timezone_name


def test_notification_preference_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="must be an IANA timezone"):
        NotificationPreferenceItem(
            category="activity",
            channel="email",
            enabled=True,
            quiet_hours_timezone="Mars/Olympus_Mons",
        )


def test_retry_policy_is_bounded_and_deterministic_for_test_jitter() -> None:
    assert retry_delay(1, jitter=1.0) == 0
    assert retry_delay(2, jitter=1.0) == 60
    assert retry_delay(6, jitter=1.0) == 43200
    assert retry_delay(99, jitter=1.0) == 43200


def test_campaign_audience_rejects_sensitive_and_unknown_fields() -> None:
    validate_campaign_audience({"locale": "zh-CN", "marketing_consent": True})
    with pytest.raises(VavError) as error:
        validate_campaign_audience({"ai_conversation": "sad", "arbitrary_sql": "select"})
    assert error.value.code == "NOTIFICATION_CAMPAIGN_AUDIENCE_UNSAFE"
