from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from vav.common.exceptions import VavError
from vav.modules.quality import design_service
from vav.modules.quality.design_schemas import AuditRunCreate, ComponentUpsert
from vav.modules.quality.design_service import _validate_release_evidence


def test_component_contract_requires_an_owned_ui_package_and_states() -> None:
    item = ComponentUpsert(
        component_code="VStatusBadge",
        package_name="@vav/ui-core",
        source_location="packages/ui-core/src/components/VStatusBadge.vue",
        owner_team="design_system",
        accessibility_contract={"color_alone": False, "accessible_name": True},
        supported_states=["success", "warning", "danger", "info"],
    )
    assert item.status == "active"
    with pytest.raises(ValidationError):
        ComponentUpsert(
            component_code="VUnsafe",
            package_name="third-party-ui",
            source_location="unsafe.vue",
            owner_team="design_system",
            accessibility_contract={},
            supported_states=[],
        )


def test_passing_audit_is_checksum_bound() -> None:
    with pytest.raises(ValidationError):
        AuditRunCreate(
            audit_code="A11Y.TEST.001",
            audit_type="accessibility",
            application_code="design-system",
            git_commit="a" * 40,
            environment="ci",
            status="approved",  # type: ignore[arg-type]
        )


def test_release_manifest_fails_closed() -> None:
    with pytest.raises(VavError, match="missing"):
        _validate_release_evidence(
            {"token_build": {"status": "accepted", "checksum_sha256": "a" * 64}}
        )
    with pytest.raises(VavError, match="not accepted"):
        _validate_release_evidence(
            {
                name: {"status": "technical_pass", "checksum_sha256": "a" * 64}
                for name in (
                    "token_build",
                    "component_tests",
                    "accessibility_review",
                    "visual_baseline_review",
                )
            }
        )


def _session_with_audit_rows(rows: list[dict[str, object]]) -> AsyncMock:
    result = MagicMock()
    result.mappings.return_value = rows
    session = AsyncMock()
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_list_audits_omits_untyped_null_parameter() -> None:
    session = _session_with_audit_rows([])

    assert await design_service.list_audits(session) == []

    statement, parameters = session.execute.await_args.args
    assert "WHERE" not in str(statement)
    assert parameters == {}


@pytest.mark.asyncio
async def test_list_audits_filters_non_null_type() -> None:
    session = _session_with_audit_rows([{"audit_type": "accessibility"}])

    assert await design_service.list_audits(session, "accessibility") == [
        {"audit_type": "accessibility"}
    ]

    statement, parameters = session.execute.await_args.args
    assert "WHERE audit_type=:audit_type" in str(statement)
    assert parameters == {"audit_type": "accessibility"}
