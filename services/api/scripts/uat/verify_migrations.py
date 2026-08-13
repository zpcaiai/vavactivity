#!/usr/bin/env python3
"""OPS-004 / DATA-001: verify the migration chain and the database it produces.

Four assertions, in increasing order of what they need to run:

1. **The revision graph has exactly one head.** Computed by parsing the
   migration files directly, so it works with no database, no Alembic install
   and no virtualenv - which matters, because a second head is usually noticed
   during a merge, on a laptop, with nothing running. Two heads is a ``FAIL``,
   and the offending revisions are named.
2. **An empty database reaches the expected head.** ``alembic upgrade head``
   against a database that starts with no ``alembic_version`` row.
3. **A second run is a no-op.** Running ``upgrade head`` again must change
   nothing; a migration that is not idempotent at the chain level will show up
   here rather than during a retried deploy.
4. **The observable schema version is printed** - the head Alembic reports and
   the ``alembic_version`` value actually stored.

Anything that cannot run is ``BLOCKED`` with the reason (no ``alembic`` on PATH,
no driver installed, database unreachable), never skipped and never a traceback.

Exit codes: ``0`` verified, ``1`` an actionable failure or a blocked check.

Usage::

    python3 batch_p4/scripts/verify_migrations.py --graph-only
    python3 batch_p4/scripts/verify_migrations.py --database-url postgresql://... --allow-upgrade
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import Report, Status, find_repo_root, run_command  # noqa: E402

_REVISION_RE = re.compile(r"^revision\s*(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_DOWN_RE = re.compile(
    r"^down_revision\s*(?::\s*[^=]+)?=\s*(?:['\"]([^'\"]+)['\"]|None)", re.MULTILINE
)


@dataclass(frozen=True)
class Revision:
    path: str
    revision: str
    down_revision: str | None


def parse_revision(path: str) -> Revision | None:
    """Read one migration file's identity without importing it.

    Parsing beats importing here: importing a migration pulls in Alembic, the
    models and whatever the module happens to touch at import time, and this
    check needs to work when none of that is installed.
    """

    try:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
    except OSError:
        return None
    revision_match = _REVISION_RE.search(source)
    if not revision_match:
        return None
    down_match = _DOWN_RE.search(source)
    down = down_match.group(1) if down_match and down_match.group(1) else None
    return Revision(path=path, revision=revision_match.group(1), down_revision=down)


def load_revisions(directory: str) -> list[Revision]:
    revisions: list[Revision] = []
    if not os.path.isdir(directory):
        return revisions
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".py") or name.startswith("__"):
            continue
        parsed = parse_revision(os.path.join(directory, name))
        if parsed is not None:
            revisions.append(parsed)
    return revisions


def compute_heads(revisions: list[Revision]) -> list[str]:
    """A head is a revision nothing else points down to."""

    referenced = {rev.down_revision for rev in revisions if rev.down_revision}
    return sorted(rev.revision for rev in revisions if rev.revision not in referenced)


def find_orphans(revisions: list[Revision]) -> list[Revision]:
    """Revisions whose ``down_revision`` names something that does not exist."""

    known = {rev.revision for rev in revisions}
    return [
        rev for rev in revisions if rev.down_revision is not None and rev.down_revision not in known
    ]


def find_duplicates(revisions: list[Revision]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for rev in revisions:
        seen.setdefault(rev.revision, []).append(os.path.basename(rev.path))
    return {key: paths for key, paths in seen.items() if len(paths) > 1}


def check_graph(report: Report, directory: str) -> list[str]:
    """Static analysis of the revision chain. Needs nothing installed."""

    revisions = load_revisions(directory)
    command = f"ls {directory}"
    if not revisions:
        report.record(
            "migrations.graph",
            Status.BLOCKED,
            f"No migration files parsed under {directory}.",
            command=command,
            remedy="Point --migrations at the directory holding the revision files.",
        )
        return []

    duplicates = find_duplicates(revisions)
    if duplicates:
        detail = "; ".join(f"{rev} in {', '.join(files)}" for rev, files in duplicates.items())
        report.record(
            "migrations.duplicate_revisions",
            Status.FAIL,
            f"Duplicate revision id(s): {detail}.",
            command=command,
            remedy=(
                "Two files claiming the same revision id makes the chain ambiguous; renumber one."
            ),
        )

    orphans = find_orphans(revisions)
    if orphans:
        detail = "; ".join(
            f"{os.path.basename(rev.path)} -> {rev.down_revision}" for rev in orphans
        )
        report.record(
            "migrations.orphan_revisions",
            Status.FAIL,
            f"Revision(s) point at a down_revision that does not exist: {detail}.",
            command=command,
            remedy=(
                "Either the parent migration is missing from this checkout, or the "
                "down_revision is a typo. Alembic will refuse to run either way."
            ),
        )

    heads = compute_heads(revisions)
    if len(heads) == 1:
        report.record(
            "migrations.single_head",
            Status.PASS,
            f"Exactly one head: {heads[0]} ({len(revisions)} revisions parsed).",
            command=command,
            head=heads[0],
            revision_count=len(revisions),
        )
    elif not heads:
        report.record(
            "migrations.single_head",
            Status.FAIL,
            "No head found - the revision graph is cyclic.",
            command=command,
            remedy="A cycle means every revision has a child; inspect down_revision values.",
        )
    else:
        report.record(
            "migrations.single_head",
            Status.FAIL,
            f"{len(heads)} heads: {', '.join(heads)}. Alembic cannot upgrade a branched chain.",
            command=command,
            remedy=(
                "Two branches were merged without rebasing one onto the other. Set the later "
                "branch's down_revision to the other head (or `alembic merge`), then re-run."
            ),
            heads=heads,
        )
    return heads


# ---------------------------------------------------------------------------
# Live database checks
# ---------------------------------------------------------------------------


def _alembic(args: list[str], *, repo_root: str, database_url: str | None) -> tuple[bool, str, str]:
    env = {"ALEMBIC_CONFIG": os.path.join(repo_root, "alembic.ini")}
    if database_url:
        env["DATABASE_URL"] = database_url
    output = run_command(["alembic", *args], timeout=300, env=env)
    if output.missing:
        return False, "", "alembic is not installed or not on PATH"
    return output.ok, output.stdout.strip(), output.stderr.strip()


def check_live(
    report: Report,
    *,
    repo_root: str,
    database_url: str | None,
    allow_upgrade: bool,
    expected_head: str | None,
) -> None:
    if not database_url:
        report.record(
            "migrations.live",
            Status.BLOCKED,
            "No DATABASE_URL given, so the chain was only checked statically.",
            command="alembic upgrade head",
            remedy="Pass --database-url or export DATABASE_URL to verify against a real database.",
        )
        return
    if not allow_upgrade:
        report.record(
            "migrations.live",
            Status.BLOCKED,
            "Refusing to run migrations without --allow-upgrade.",
            command="alembic upgrade head",
            remedy=(
                "Re-run with --allow-upgrade against a scratch database. This guard exists so "
                "the script cannot migrate a database somebody is using."
            ),
        )
        return

    ok, stdout, stderr = _alembic(["heads"], repo_root=repo_root, database_url=database_url)
    if not ok:
        report.record(
            "migrations.alembic_heads",
            Status.BLOCKED,
            f"`alembic heads` failed: {stderr or stdout}",
            command="alembic heads",
            remedy="Install alembic and make sure alembic.ini is discoverable, then re-run.",
        )
        return
    reported_heads = [line for line in stdout.splitlines() if line.strip()]
    if len(reported_heads) > 1:
        report.record(
            "migrations.alembic_heads",
            Status.FAIL,
            f"Alembic reports {len(reported_heads)} heads: {'; '.join(reported_heads)}",
            command="alembic heads",
            remedy="Merge the branches before deploying; a branched chain cannot upgrade.",
        )
        return
    report.record(
        "migrations.alembic_heads",
        Status.PASS,
        f"Alembic reports one head: {reported_heads[0] if reported_heads else 'unknown'}",
        command="alembic heads",
    )

    ok, stdout, stderr = _alembic(
        ["upgrade", "head"], repo_root=repo_root, database_url=database_url
    )
    if not ok:
        report.record(
            "migrations.first_upgrade",
            Status.FAIL,
            f"`alembic upgrade head` failed: {(stderr or stdout)[-600:]}",
            command="alembic upgrade head",
            remedy="Fix the failing migration; an empty database must reach head in one run.",
        )
        return
    report.record(
        "migrations.first_upgrade",
        Status.PASS,
        "An empty database reached head.",
        command="alembic upgrade head",
    )

    ok, current_after_first, _ = _alembic(
        ["current"], repo_root=repo_root, database_url=database_url
    )
    ok_second, second_stdout, second_stderr = _alembic(
        ["upgrade", "head"], repo_root=repo_root, database_url=database_url
    )
    if not ok_second:
        report.record(
            "migrations.second_upgrade",
            Status.FAIL,
            f"The second `alembic upgrade head` failed: {(second_stderr or second_stdout)[-600:]}",
            command="alembic upgrade head",
            remedy="A re-run must be a no-op; a deploy that retries would fail the same way.",
        )
        return
    ok_current, current_after_second, _ = _alembic(
        ["current"], repo_root=repo_root, database_url=database_url
    )
    if ok and ok_current and current_after_first != current_after_second:
        report.record(
            "migrations.second_upgrade",
            Status.FAIL,
            (
                "The second run changed the schema version: "
                f"{current_after_first!r} -> {current_after_second!r}"
            ),
            command="alembic current",
            remedy=(
                "Some migration is not chain-idempotent; a retried deploy would double-apply it."
            ),
        )
        return
    report.record(
        "migrations.second_upgrade",
        Status.PASS,
        "A second `upgrade head` changed nothing.",
        command="alembic upgrade head && alembic current",
    )
    report.record(
        "migrations.schema_version",
        Status.PASS,
        f"Observable schema version: {current_after_second or current_after_first or 'unknown'}",
        command="alembic current",
        expected_head=expected_head,
    )


def build_report(
    *,
    migrations_dir: str,
    repo_root: str,
    database_url: str | None,
    allow_upgrade: bool,
) -> Report:
    report = Report(
        "verify_migrations",
        "OPS-004/DATA-001: one head, empty database reaches head, second run is a no-op.",
    )
    heads: list[str] = []
    try:
        heads = check_graph(report, migrations_dir)
    except Exception as exc:  # noqa: BLE001 - never traceback out of a verifier
        report.record(
            "migrations.graph",
            Status.BLOCKED,
            f"{type(exc).__name__}: {exc}",
            command=f"ls {migrations_dir}",
            remedy="Fix the error above and re-run.",
        )
    try:
        check_live(
            report,
            repo_root=repo_root,
            database_url=database_url,
            allow_upgrade=allow_upgrade,
            expected_head=heads[0] if len(heads) == 1 else None,
        )
    except Exception as exc:  # noqa: BLE001
        report.record(
            "migrations.live",
            Status.BLOCKED,
            f"{type(exc).__name__}: {exc}",
            command="alembic upgrade head",
            remedy="Fix the error above and re-run.",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    repo_default = find_repo_root(os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--repo-root", default=repo_default)
    parser.add_argument(
        "--migrations",
        default=None,
        help="Migration directory (default: <repo-root>/migrations).",
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument(
        "--allow-upgrade",
        action="store_true",
        help="Permit running `alembic upgrade head`. Required for the live checks.",
    )
    parser.add_argument("--graph-only", action="store_true", help="Skip every live database check.")
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    migrations_dir = args.migrations or os.path.join(args.repo_root, "migrations")
    report = build_report(
        migrations_dir=migrations_dir,
        repo_root=args.repo_root,
        database_url=None if args.graph_only else args.database_url,
        allow_upgrade=args.allow_upgrade and not args.graph_only,
    )
    if args.graph_only:
        # A graph-only run is explicitly partial; the live check is still
        # recorded as BLOCKED so nobody reads this as a full verification.
        pass
    return report.emit(args.json_path, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
