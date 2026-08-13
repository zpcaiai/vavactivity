from scripts.testing.role_function_matrix import build_report


def test_every_role_permission_decision_and_admin_route_gate() -> None:
    report = build_report()

    assert report["status"] == "PASS", report["findings"]
    assert report["summary"]["role_count"] == 81
    assert report["summary"]["permission_count"] == 808
    assert report["summary"]["admin_web_permission_reference_count"] > 0
    assert (
        report["summary"]["route_bound_permission_count"]
        + report["summary"]["policy_only_permission_count"]
        == 808
    )
    assert report["functional_coverage_complete"] is False
    assert report["summary"]["total_decisions_executed"] == 81 * 808


def test_global_administrator_and_member_boundaries() -> None:
    report = build_report()
    roles = {row["role"]: row for row in report["roles"]}

    assert roles["super_admin"]["permission_count"] == 808
    assert roles["platform_admin"]["permission_count"] == 807
    assert roles["member"]["permission_count"] == 0
    assert roles["member"]["policy_only_permission_count"] == 0
    assert roles["member"]["bound_route_operation_count"] == 0
