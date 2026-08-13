#!/usr/bin/env python3
"""DATA-002: prove the seed can be run twice without duplicating anything.

The method is deliberately blunt and hard to fool: count every row in every
table, run the seed, count again, run the seed again, count again. The first
delta is what the seed created; the second delta must be **empty**. Any table
that grew on the second run is named with its before/after counts.

Why counts rather than a smarter comparison: a seed that is "idempotent" via
``ON CONFLICT DO NOTHING`` on some tables and ``INSERT`` on others is the normal
way this breaks, and row counts catch it without knowing anything about the
schema.

Dependencies degrade gracefully. Counting rows needs a PostgreSQL driver
(``psycopg`` or ``psycopg2``); if neither is importable the run is ``BLOCKED``
with that reason rather than crashing on the import.

Exit codes: ``0`` the seed is idempotent, ``1`` it is not, or the check could not
run.

Usage::

    python3 batch_p4/scripts/verify_seed_idempotency.py --allow-writes
    python3 batch_p4/scripts/verify_seed_idempotency.py --seed-command 'python -m vav.scripts.seed'
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import Report, Status, find_repo_root, run_command  # noqa: E402

DEFAULT_SEED_COMMAND = os.environ.get("VAV_SEED_COMMAND", "python3 -m vav.scripts.seed")

#: Tables whose growth on a second run is expected and not a defect: append-only
#: logs that record *that the seed ran*. Everything else must be stable.
EXPECTED_GROWTH_TABLES: frozenset[str] = frozenset(
    {"alembic_version", "audit_logs", "outbox_events", "seed_runs"}
)


def _connect(database_url: str):  # noqa: ANN202 - driver-dependent connection object
    """Open a connection with whichever driver is installed.

    Raises ``ImportError`` when neither driver is present; the caller turns that
    into a ``BLOCKED`` result rather than a traceback.
    """

    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )
    try:
        import psycopg  # type: ignore[import-not-found]

        return psycopg.connect(dsn)
    except ImportError:
        pass
    try:
        import psycopg2  # type: ignore[import-not-found]

        return psycopg2.connect(dsn)
    except ImportError as exc:
        raise ImportError(
            "neither psycopg nor psycopg2 is installed; install one to count rows"
        ) from exc


def count_rows(database_url: str) -> dict[str, int]:
    """Row count per table in the public schema.

    A single query with ``count(*)`` per table would need dynamic SQL per table;
    this builds one UNION ALL instead so the whole snapshot is consistent - taken
    inside one statement, so a background job cannot shift the numbers between
    two tables' counts.
    """

    connection = _connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            if not tables:
                return {}
            union = " UNION ALL ".join(
                f"SELECT '{table}' AS table_name, count(*) AS row_count FROM \"{table}\""
                for table in tables
            )
            cursor.execute(union)
            return {row[0]: int(row[1]) for row in cursor.fetchall()}
    finally:
        connection.close()


def diff_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Tables that grew, as ``{table: (before, after)}``.

    Only growth is reported. A table that *shrank* between runs is a different
    bug (something is deleting), and conflating the two would make both harder
    to read; it is surfaced separately by the caller.
    """

    grew: dict[str, tuple[int, int]] = {}
    for table, count in after.items():
        previous = before.get(table, 0)
        if count > previous:
            grew[table] = (previous, count)
    return grew


def find_shrinkage(before: dict[str, int], after: dict[str, int]) -> dict[str, tuple[int, int]]:
    return {
        table: (before[table], after.get(table, 0))
        for table in before
        if after.get(table, 0) < before[table]
    }


def run_seed(report: Report, command: str, *, repo_root: str, label: str) -> bool:
    argv = shlex.split(command)
    output = run_command(argv, timeout=900, env={"PYTHONPATH": repo_root})
    if output.missing:
        report.record(
            f"seed.{label}",
            Status.BLOCKED,
            f"Seed command not runnable: {output.stderr}",
            command=command,
            remedy="Pass --seed-command with the command this repo actually uses.",
        )
        return False
    if not output.ok:
        report.record(
            f"seed.{label}",
            Status.FAIL,
            f"Seed exited {output.returncode}: {(output.stderr or output.stdout)[-600:]}",
            command=command,
            remedy="Fix the seed before judging its idempotency.",
        )
        return False
    report.record(f"seed.{label}", Status.PASS, f"Seed run '{label}' completed.", command=command)
    return True


def build_report(
    *, database_url: str | None, seed_command: str, repo_root: str, allow_writes: bool
) -> Report:
    report = Report(
        "verify_seed_idempotency",
        "DATA-002: run the seed twice and prove no table grew on the second run.",
    )
    if not database_url:
        report.record(
            "seed.database",
            Status.BLOCKED,
            "No DATABASE_URL given.",
            command="echo $DATABASE_URL",
            remedy="Pass --database-url or export DATABASE_URL pointing at a scratch database.",
        )
        return report
    if not allow_writes:
        report.record(
            "seed.database",
            Status.BLOCKED,
            "Refusing to run the seed without --allow-writes.",
            command=seed_command,
            remedy=(
                "Re-run with --allow-writes against a scratch database. This guard exists so the "
                "script cannot seed a database somebody is using."
            ),
        )
        return report

    try:
        baseline = count_rows(database_url)
    except ImportError as exc:
        report.record(
            "seed.driver",
            Status.BLOCKED,
            str(exc),
            command="python3 -c 'import psycopg'",
            remedy="pip install 'psycopg[binary]' (or psycopg2-binary) and re-run.",
        )
        return report
    except Exception as exc:  # noqa: BLE001 - driver errors are data, not crashes
        report.record(
            "seed.database",
            Status.BLOCKED,
            f"Could not read row counts: {type(exc).__name__}: {exc}",
            command="psql -c '\\dt'",
            remedy="Check DATABASE_URL, that the database exists and that migrations have run.",
        )
        return report

    report.record(
        "seed.baseline",
        Status.PASS,
        f"Baseline captured: {len(baseline)} tables, {sum(baseline.values())} rows.",
        command="SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
        tables=len(baseline),
    )

    if not run_seed(report, seed_command, repo_root=repo_root, label="first"):
        return report
    try:
        after_first = count_rows(database_url)
    except Exception as exc:  # noqa: BLE001
        report.record(
            "seed.count_first",
            Status.BLOCKED,
            f"Could not read row counts after the first seed: {exc}",
            remedy="Check the database is still reachable.",
        )
        return report
    created = diff_counts(baseline, after_first)
    report.record(
        "seed.first_run_effect",
        Status.PASS if created else Status.WARN,
        (
            f"First run created rows in {len(created)} table(s): "
            + ", ".join(
                f"{table} {before}->{after}"
                for table, (before, after) in sorted(created.items())[:10]
            )
            if created
            else "First run created no rows - the seed may already have been applied."
        ),
        command=seed_command,
        created={table: after - before for table, (before, after) in created.items()},
    )

    if not run_seed(report, seed_command, repo_root=repo_root, label="second"):
        return report
    try:
        after_second = count_rows(database_url)
    except Exception as exc:  # noqa: BLE001
        report.record(
            "seed.count_second",
            Status.BLOCKED,
            f"Could not read row counts after the second seed: {exc}",
            remedy="Check the database is still reachable.",
        )
        return report

    grew = diff_counts(after_first, after_second)
    unexpected = {
        table: counts for table, counts in grew.items() if table not in EXPECTED_GROWTH_TABLES
    }
    tolerated = {table: counts for table, counts in grew.items() if table in EXPECTED_GROWTH_TABLES}

    if unexpected:
        detail = ", ".join(
            f"{table}: {before} -> {after} (+{after - before})"
            for table, (before, after) in sorted(unexpected.items())
        )
        report.record(
            "seed.idempotent",
            Status.FAIL,
            f"{len(unexpected)} table(s) grew on the second seed run: {detail}",
            command=f"{seed_command}  # run twice",
            remedy=(
                "Make those inserts conflict-safe (ON CONFLICT DO NOTHING on a natural key, or a "
                "lookup before insert). A seed that duplicates on re-run makes every redeploy "
                "and every restored snapshot a data incident."
            ),
            tables=sorted(unexpected),
        )
    else:
        report.record(
            "seed.idempotent",
            Status.PASS,
            f"No table grew on the second run ({len(after_second)} tables compared).",
            command=f"{seed_command}  # run twice",
        )
    if tolerated:
        report.record(
            "seed.expected_growth",
            Status.WARN,
            "Append-only tables grew, as expected: "
            + ", ".join(
                f"{table} +{after - before}" for table, (before, after) in sorted(tolerated.items())
            ),
            remedy="No action needed; these are logs of the seed having run.",
        )
    shrank = find_shrinkage(after_first, after_second)
    if shrank:
        report.record(
            "seed.shrinkage",
            Status.FAIL,
            "Table(s) lost rows on the second run: "
            + ", ".join(
                f"{table} {before}->{after}" for table, (before, after) in sorted(shrank.items())
            ),
            remedy="A seed that deletes on re-run is destructive; find the truncate or delete.",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--seed-command", default=DEFAULT_SEED_COMMAND)
    parser.add_argument(
        "--repo-root", default=find_repo_root(os.path.dirname(os.path.abspath(__file__)))
    )
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Permit running the seed. Required; the script will not write without it.",
    )
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(
        database_url=args.database_url,
        seed_command=args.seed_command,
        repo_root=args.repo_root,
        allow_writes=args.allow_writes,
    )
    return report.emit(args.json_path, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
