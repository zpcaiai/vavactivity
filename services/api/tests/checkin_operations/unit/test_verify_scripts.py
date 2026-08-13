"""Tests for the B02/B03 verification scripts.

The scripts are loaded from their path rather than imported as a package,
because that is exactly how they run in anger: ``python3 scripts/verify_*.py``
on a machine that has not installed this repo. If they only worked as installed
modules, these tests would be testing something nobody executes.

Nothing here opens a socket, touches a database or shells out to a service. The
parts under test are the decision functions - which environment variables are
missing, whether a version satisfies a pin, whether a credential looks live,
whether a revision graph has one head, how counts diff - plus the guarantee that
a report never raises.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

# tests/<module>/unit/ -> services/api/, then scripts/uat where the UAT
# verification scripts actually live.
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "uat"

#: A value that is long enough and does not trip the placeholder heuristic
#: (note "xxxxx" would - deliberately, since that is a placeholder people type).
FILLER = "s3cret-value-for-tests-0123456789abcdef"


def _load(name: str) -> ModuleType:
    """Load a script by path, the way the shell does."""

    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load("_common")
env_script = _load("verify_environment")
endpoints_script = _load("verify_service_endpoints")
migrations_script = _load("verify_migrations")
seed_script = _load("verify_seed_idempotency")


# ---------------------------------------------------------------------------
# Shared reporting
# ---------------------------------------------------------------------------


def test_a_blocked_check_is_a_failure_not_a_pass() -> None:
    """The whole point of the three-state model: unverified is not verified."""

    report = common.Report("t")
    report.record("a", common.Status.PASS, "fine")
    report.record("b", common.Status.BLOCKED, "no driver installed")
    assert report.ok is False
    assert report.exit_code() == common.EXIT_ACTIONABLE_FAILURE


def test_warnings_alone_still_pass() -> None:
    report = common.Report("t")
    report.record("a", common.Status.PASS, "fine")
    report.record("b", common.Status.WARN, "feature off")
    assert report.ok is True
    assert report.exit_code() == common.EXIT_OK


def test_guard_turns_an_exploding_check_into_a_blocked_result() -> None:
    report = common.Report("t")

    def boom() -> common.CheckResult:
        raise RuntimeError("psycopg exploded")

    result = report.guard("db", "psql", boom)
    assert result.status is common.Status.BLOCKED
    assert "psycopg exploded" in result.detail
    assert result.remedy
    assert report.exit_code() == 1


def test_a_report_renders_failures_first_and_json_round_trips() -> None:
    import json

    report = common.Report("t", "description")
    report.record("pass-one", common.Status.PASS, "ok")
    report.record("fail-one", common.Status.FAIL, "broken", remedy="fix it")
    rendered = report.render()
    assert rendered.index("fail-one") < rendered.index("pass-one")
    assert "fix it" in rendered
    payload = json.loads(report.to_json())
    assert payload["ok"] is False
    assert payload["counts"]["FAIL"] == 1
    assert len(payload["results"]) == 2


def test_every_result_carries_its_command_and_a_timestamp() -> None:
    report = common.Report("t")
    result = report.record("x", common.Status.FAIL, "d", command="psql -c 'select 1'")
    assert result.command == "psql -c 'select 1'"
    assert result.timestamp.endswith("+00:00")


def test_run_command_reports_a_missing_binary_as_data() -> None:
    output = common.run_command(["definitely-not-a-real-binary-xyz", "--version"])
    assert output.missing is True
    assert output.ok is False


# ---------------------------------------------------------------------------
# verify_environment
# ---------------------------------------------------------------------------


def test_missing_required_variables_fail_with_the_variable_names(tmp_path: Path) -> None:
    report = env_script.build_report({}, repo_root=str(tmp_path), declared_profile="local")
    required = next(item for item in report.results if item.name == "env.required")
    assert required.status is common.Status.FAIL
    assert "DATABASE_URL" in required.detail
    assert "export DATABASE_URL=" in required.remedy


@pytest.mark.parametrize("value", ["", "   ", "changeme", "TODO", "<set me>"])
def test_a_placeholder_counts_as_missing(value: str, tmp_path: Path) -> None:
    environ = {name: value for name, _, _ in env_script.REQUIRED_VARIABLES}
    report = env_script.build_report(environ, repo_root=str(tmp_path), declared_profile="local")
    required = next(item for item in report.results if item.name == "env.required")
    assert required.status is common.Status.FAIL


def test_a_short_key_is_rejected_even_when_present(tmp_path: Path) -> None:
    environ = {name: FILLER for name, _, _ in env_script.REQUIRED_VARIABLES}
    environ["SECRET_KEY"] = "short"
    report = env_script.build_report(environ, repo_root=str(tmp_path), declared_profile="local")
    weak = [item for item in report.results if item.name == "env.strength.SECRET_KEY"]
    assert weak and weak[0].status is common.Status.FAIL


def test_a_live_stripe_key_in_a_local_profile_is_an_actionable_failure(tmp_path: Path) -> None:
    """The check that is about damage rather than convenience."""

    environ = {name: FILLER for name, _, _ in env_script.REQUIRED_VARIABLES}
    environ["VAV_ENV"] = "local"
    # Assemble the synthetic value at runtime so secret scanners do not mistake
    # this negative-path fixture for a committed production credential.
    environ["STRIPE_SECRET_KEY"] = "sk_" + "live_" + "51ABCDEFGHIJKLMNOPQRSTUV"
    report = env_script.build_report(environ, repo_root=str(tmp_path))
    credentials = next(item for item in report.results if item.name == "env.provider_credentials")
    assert credentials.status is common.Status.FAIL
    assert "STRIPE_SECRET_KEY" in credentials.detail
    assert "unset STRIPE_SECRET_KEY" in credentials.remedy
    assert report.exit_code() == 1


def test_a_test_mode_stripe_key_is_not_flagged() -> None:
    assert env_script.detect_live_credentials({"STRIPE_SECRET_KEY": "sk_test_51ABCDEF"}) == []


def test_a_sandbox_named_credential_is_not_flagged() -> None:
    assert (
        env_script.detect_live_credentials({"TWILIO_AUTH_TOKEN": "sandbox-token-value-1234"}) == []
    )


def test_the_same_credentials_are_expected_in_production(tmp_path: Path) -> None:
    environ = {name: FILLER for name, _, _ in env_script.REQUIRED_VARIABLES}
    environ["VAV_ENV"] = "production"
    environ["TWILIO_AUTH_TOKEN"] = "a-real-looking-production-token"
    report = env_script.build_report(environ, repo_root=str(tmp_path))
    credentials = next(item for item in report.results if item.name == "env.provider_credentials")
    assert credentials.status is common.Status.PASS


def test_an_undeclared_profile_is_its_own_failure(tmp_path: Path) -> None:
    report = env_script.build_report({}, repo_root=str(tmp_path))
    profile = next(item for item in report.results if item.name == "env.profile")
    assert profile.status is common.Status.FAIL
    assert "VAV_ENV" in profile.remedy


@pytest.mark.parametrize(
    ("actual", "pin", "expected"),
    [
        ("v20.11.1", ">=20.0.0", True),
        ("v18.19.0", ">=20.0.0", False),
        ("v20.11.1", "^20.10.0", True),
        ("v21.0.0", "^20.10.0", False),
        ("8.15.4", "8.15.4", True),
        ("8.15.4", "~8.15.0", True),
        ("9.0.0", "~8.15.0", False),
        ("v20.11.1", "18.x || >=20.0.0", True),
    ],
)
def test_version_pins_are_compared_not_guessed(actual: str, pin: str, expected: bool) -> None:
    assert env_script.satisfies(actual, pin) is expected


def test_pins_are_read_from_repo_metadata_not_hard_coded(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"engines": {"node": ">=20.0.0", "pnpm": ">=9.0.0"}, "packageManager": "pnpm@9.1.0"}',
        encoding="utf-8",
    )
    (tmp_path / ".nvmrc").write_text("20.11.1\n", encoding="utf-8")
    pins = env_script.read_pinned_versions(str(tmp_path))
    assert pins["node.engines"] == ">=20.0.0"
    assert pins["pnpm.engines"] == ">=9.0.0"
    assert pins["packageManager"] == "pnpm@9.1.0"
    assert pins["node.nvmrc"] == "20.11.1"


def test_a_repo_with_no_pin_blocks_rather_than_passing(tmp_path: Path) -> None:
    report = common.Report("t")
    env_script.check_toolchain(report, str(tmp_path))
    pins = next(item for item in report.results if item.name == "toolchain.pins")
    assert pins.status is common.Status.BLOCKED


def test_the_environment_verifier_never_raises_and_exits_zero_or_one(tmp_path: Path) -> None:
    """The gate: this must print a report, not a traceback, on a bare machine."""

    code = env_script.main(["--repo-root", str(tmp_path), "--quiet"])
    assert code in (0, 1)


def test_a_fully_configured_local_environment_can_pass(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    environ = {name: FILLER for name, _, _ in env_script.REQUIRED_VARIABLES}
    environ["VAV_ENV"] = "local"
    report = env_script.build_report(environ, repo_root=str(tmp_path))
    failures = [item for item in report.results if item.status is common.Status.FAIL]
    assert failures == []


# ---------------------------------------------------------------------------
# verify_service_endpoints
# ---------------------------------------------------------------------------


def test_every_required_port_is_probed() -> None:
    ports = {probe.port for probe in endpoints_script.PROBES}
    assert {5173, 5174, 8000, 8025, 9001, 5432, 6379} <= ports


def test_the_openapi_document_is_its_own_probe() -> None:
    openapi = next(probe for probe in endpoints_script.PROBES if probe.key == "api_openapi")
    assert openapi.path == "/openapi.json"
    assert openapi.expect_json is True


def test_datastores_are_probed_over_tcp_without_pretending_to_authenticate() -> None:
    for key in ("postgres", "redis"):
        probe = next(item for item in endpoints_script.PROBES if item.key == key)
        assert probe.kind == "tcp"
        assert probe.remedy


def test_an_unreachable_service_is_blocked_not_skipped() -> None:
    report = common.Report("t")
    probe = next(item for item in endpoints_script.PROBES if item.key == "postgres")
    # Port 9 (discard) on a documentation-range address: refused or timed out,
    # never accepted, and never a silent skip.
    endpoints_script.run_probe(
        report, probe.__class__(**{**probe.__dict__, "port": 9}), host="127.0.0.1", timeout=0.2
    )
    assert report.results[0].status is common.Status.BLOCKED
    assert report.results[0].command
    assert report.results[0].extra["observed_at"]


def test_an_unknown_only_filter_is_reported_rather_than_ignored() -> None:
    probes, unknown = endpoints_script.select_probes("api_health,not_a_probe")
    assert [probe.key for probe in probes] == ["api_health"]
    assert unknown == ["not_a_probe"]


def test_no_filter_means_every_probe() -> None:
    probes, unknown = endpoints_script.select_probes(None)
    assert len(probes) == len(endpoints_script.PROBES)
    assert unknown == []


# ---------------------------------------------------------------------------
# verify_migrations
# ---------------------------------------------------------------------------


def _write_migration(directory: Path, name: str, revision: str, down: str | None) -> None:
    down_literal = f'"{down}"' if down else "None"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        f'"""m"""\n\nrevision = "{revision}"\ndown_revision = {down_literal}\n',
        encoding="utf-8",
    )


def test_a_linear_chain_has_exactly_one_head(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_a.py", "0001", None)
    _write_migration(tmp_path, "0002_b.py", "0002", "0001")
    _write_migration(tmp_path, "0003_c.py", "0003", "0002")
    report = common.Report("t")
    heads = migrations_script.check_graph(report, str(tmp_path))
    assert heads == ["0003"]
    assert report.results[0].status is common.Status.PASS


def test_multiple_heads_are_detected_and_refused(tmp_path: Path) -> None:
    """Two branches merged without a rebase - the check that needs no database."""

    _write_migration(tmp_path, "0001_a.py", "0001", None)
    _write_migration(tmp_path, "0002_b.py", "0002", "0001")
    _write_migration(tmp_path, "0002_c.py", "0002b", "0001")
    report = common.Report("t")
    heads = migrations_script.check_graph(report, str(tmp_path))
    assert sorted(heads) == ["0002", "0002b"]
    head_check = next(item for item in report.results if item.name == "migrations.single_head")
    assert head_check.status is common.Status.FAIL
    assert "0002b" in head_check.detail
    assert report.exit_code() == 1


def test_a_cycle_has_no_head_and_is_reported(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_a.py", "0001", "0002")
    _write_migration(tmp_path, "0002_b.py", "0002", "0001")
    report = common.Report("t")
    assert migrations_script.check_graph(report, str(tmp_path)) == []
    head_check = next(item for item in report.results if item.name == "migrations.single_head")
    assert head_check.status is common.Status.FAIL
    assert "cyclic" in head_check.detail


def test_a_missing_parent_revision_is_named(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0002_b.py", "0002", "0001")
    report = common.Report("t")
    migrations_script.check_graph(report, str(tmp_path))
    orphans = next(item for item in report.results if item.name == "migrations.orphan_revisions")
    assert orphans.status is common.Status.FAIL
    assert "0001" in orphans.detail


def test_duplicate_revision_ids_are_named(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_a.py", "0001", None)
    _write_migration(tmp_path, "0001_copy.py", "0001", None)
    report = common.Report("t")
    migrations_script.check_graph(report, str(tmp_path))
    duplicates = next(
        item for item in report.results if item.name == "migrations.duplicate_revisions"
    )
    assert duplicates.status is common.Status.FAIL


def test_an_empty_migrations_directory_blocks(tmp_path: Path) -> None:
    report = common.Report("t")
    assert migrations_script.check_graph(report, str(tmp_path)) == []
    assert report.results[0].status is common.Status.BLOCKED


def test_the_real_repo_migrations_have_one_head() -> None:
    """The batch's own chain, parsed the same way CI would parse it."""

    repo_migrations = Path(__file__).resolve().parents[2] / "migrations"
    if not repo_migrations.is_dir():
        pytest.skip("repository migrations directory is not present in this checkout")
    revisions = migrations_script.load_revisions(str(repo_migrations))
    assert revisions
    assert len(migrations_script.compute_heads(revisions)) == 1


def test_the_batch_migrations_chain_onto_each_other() -> None:
    # The migrations live in the real versions directory under their final
    # names, not beside this test under their authoring names.
    versions = Path(__file__).resolve().parents[3] / "migrations" / "versions"
    first = migrations_script.parse_revision(str(versions / "20260812_0105_checkin_operations.py"))
    second = migrations_script.parse_revision(str(versions / "20260812_0106_capacity_guard.py"))
    assert first is not None and second is not None
    assert first.revision == "20260812_0105"
    assert first.down_revision == "20260812_0104"
    assert second.revision == "20260812_0106"
    assert second.down_revision == first.revision

    corrective = migrations_script.parse_revision(
        str(versions / "20260813_0111_explicit_capacity_mode.py")
    )
    assert corrective is not None
    assert corrective.revision == "20260813_0111"
    assert corrective.down_revision == "20260813_0110"

    storage_integrity = migrations_script.parse_revision(
        str(versions / "20260813_0112_profile_media_storage_integrity.py")
    )
    assert storage_integrity is not None
    assert storage_integrity.revision == "20260813_0112"
    assert storage_integrity.down_revision == corrective.revision


def test_capacity_migrations_keep_inventory_mode_separate_from_zero_capacity() -> None:
    versions = Path(__file__).resolve().parents[3] / "migrations" / "versions"
    fresh = (versions / "20260812_0106_capacity_guard.py").read_text(encoding="utf-8")
    corrective = (versions / "20260813_0111_explicit_capacity_mode.py").read_text(encoding="utf-8")

    assert "is_unlimited BOOLEAN NOT NULL DEFAULT false" in fresh
    assert "JOIN product_skus sku ON sku.id = t.catalog_sku_id" in fresh
    assert "LEFT JOIN inventory_items inv ON inv.sku_id = sku.id" in fresh
    assert "CASE WHEN derived.is_unlimited THEN 0" in fresh
    assert "WHERE NOT c.is_unlimited AND c.capacity > derived.cap" in fresh

    assert "ADD COLUMN IF NOT EXISTS is_unlimited BOOLEAN NOT NULL DEFAULT false" in corrective
    assert "WHEN target_is_unlimited THEN 0" in corrective
    assert "GREATEST(catalogue_capacity, confirmed_seats + held_seats)" in corrective
    assert "'migration', '20260813_0111'" in corrective


def test_ai_escalation_partial_downgrade_restores_queue_index_and_keeps_quarantine() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "versions"
        / "20260812_0107_merge_ai_escalation_queue.py"
    ).read_text(encoding="utf-8")

    assert "CREATE INDEX IF NOT EXISTS ai_human_escalations_queue_idx" in migration
    assert "ai_human_escalation_orphans is deliberately retained" in migration


def test_profile_media_migration_preserves_physical_deletion_obligations() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "versions"
        / "20260813_0112_profile_media_storage_integrity.py"
    ).read_text(encoding="utf-8")

    assert "profile_media_storage_deletions" in migration
    assert "DROP TABLE" not in migration
    assert "CREATE TABLE IF NOT EXISTS profile_media_storage_deletions" in migration


def test_the_live_check_refuses_to_migrate_without_an_explicit_flag() -> None:
    report = common.Report("t")
    migrations_script.check_live(
        report,
        repo_root=os.getcwd(),
        database_url="postgresql://localhost/x",
        allow_upgrade=False,
        expected_head="0003",
    )
    assert report.results[0].status is common.Status.BLOCKED
    assert "--allow-upgrade" in report.results[0].detail


def test_no_database_url_blocks_the_live_check_rather_than_passing() -> None:
    report = common.Report("t")
    migrations_script.check_live(
        report, repo_root=os.getcwd(), database_url=None, allow_upgrade=True, expected_head=None
    )
    assert report.results[0].status is common.Status.BLOCKED


# ---------------------------------------------------------------------------
# verify_seed_idempotency
# ---------------------------------------------------------------------------


def test_a_table_that_grew_on_the_second_run_is_reported() -> None:
    grew = seed_script.diff_counts({"users": 3, "roles": 2}, {"users": 6, "roles": 2})
    assert grew == {"users": (3, 6)}


def test_a_stable_second_run_diffs_to_nothing() -> None:
    assert seed_script.diff_counts({"users": 3}, {"users": 3}) == {}


def test_a_new_table_counts_as_growth_from_zero() -> None:
    assert seed_script.diff_counts({}, {"users": 2}) == {"users": (0, 2)}


def test_shrinkage_is_tracked_separately_from_growth() -> None:
    assert seed_script.find_shrinkage({"users": 5}, {"users": 2}) == {"users": (5, 2)}
    assert seed_script.find_shrinkage({"users": 5}, {"users": 5}) == {}


def test_append_only_log_tables_are_allowed_to_grow() -> None:
    assert "outbox_events" in seed_script.EXPECTED_GROWTH_TABLES
    assert "users" not in seed_script.EXPECTED_GROWTH_TABLES


def test_the_seed_verifier_refuses_to_write_without_an_explicit_flag() -> None:
    report = seed_script.build_report(
        database_url="postgresql://localhost/x",
        seed_command="true",
        repo_root=os.getcwd(),
        allow_writes=False,
    )
    assert report.results[0].status is common.Status.BLOCKED
    assert report.exit_code() == 1


def test_no_database_url_blocks_the_seed_verifier() -> None:
    report = seed_script.build_report(
        database_url=None, seed_command="true", repo_root=os.getcwd(), allow_writes=True
    )
    assert report.results[0].status is common.Status.BLOCKED


def test_a_missing_driver_is_blocked_with_an_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The graceful-degradation requirement: no traceback when psycopg is absent."""

    def _no_driver(_database_url: str) -> dict[str, int]:
        raise ImportError("neither psycopg nor psycopg2 is installed; install one to count rows")

    monkeypatch.setattr(seed_script, "count_rows", _no_driver)
    report = seed_script.build_report(
        database_url="postgresql://localhost/x",
        seed_command="true",
        repo_root=os.getcwd(),
        allow_writes=True,
    )
    driver = next(item for item in report.results if item.name == "seed.driver")
    assert driver.status is common.Status.BLOCKED
    assert "psycopg" in driver.remedy


def test_an_unreachable_database_is_blocked_not_crashed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_database_url: str) -> dict[str, int]:
        raise OSError("connection refused")

    monkeypatch.setattr(seed_script, "count_rows", _boom)
    report = seed_script.build_report(
        database_url="postgresql://localhost/x",
        seed_command="true",
        repo_root=os.getcwd(),
        allow_writes=True,
    )
    assert report.results[0].status is common.Status.BLOCKED
    assert "connection refused" in report.results[0].detail
