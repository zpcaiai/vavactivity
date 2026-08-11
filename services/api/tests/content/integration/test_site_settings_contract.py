from __future__ import annotations

import pytest
from pydantic import ValidationError

from vav.modules.content.schemas import SiteSettingRequest


def test_site_setting_history_and_rollback_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/admin/site-settings/{setting_key}/history" in paths
    assert "/api/v1/admin/site-settings/{setting_key}/rollback" in paths
    assert "get" in paths["/api/v1/admin/site-settings/{setting_key}/history"]
    assert "post" in paths["/api/v1/admin/site-settings/{setting_key}/rollback"]


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("string", True),
        ("boolean", "true"),
        ("array", {}),
        ("object", []),
    ],
)
def test_site_setting_value_must_match_declared_type(value_type: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SiteSettingRequest.model_validate(
            {
                "value_type": value_type,
                "value": value,
                "reason": "Contract mismatch regression test",
            }
        )
