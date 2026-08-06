from vav.modules.identity.permissions import DESIGN_SYSTEM_PERMISSIONS, ROLE_PERMISSIONS


def test_design_permissions_and_roles_are_exactly_governed() -> None:
    assert len(DESIGN_SYSTEM_PERMISSIONS) == 21
    assert {
        "design_system_developer",
        "ui_quality_reviewer",
        "design_release_manager",
    } <= set(ROLE_PERMISSIONS)
    assert "design.tokens.release" not in ROLE_PERMISSIONS["design_system_developer"]
    assert "design.tokens.manage" not in ROLE_PERMISSIONS["design_release_manager"]
    assert "design.accessibility.review" in ROLE_PERMISSIONS["ui_quality_reviewer"]
    assert "design.baselines.approve" in ROLE_PERMISSIONS["ui_quality_reviewer"]
