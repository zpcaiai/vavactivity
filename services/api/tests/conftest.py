import asyncio
import atexit
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

os.environ["APP_ENV"] = "test"
# Keep the production Argon2 policy in application configuration while making
# integration fixtures practical. Dedicated hasher tests still exercise hash
# and verify behavior; deployment configuration tests cover production floors.
os.environ.setdefault("AUTH_ARGON2_TIME_COST", "1")
os.environ.setdefault("AUTH_ARGON2_MEMORY_COST", "8192")
os.environ.setdefault("AUTH_ARGON2_PARALLELISM", "1")
os.environ.setdefault("AI_ENABLED", "true")
for proxy_key in ("NO_PROXY", "no_proxy"):
    bypasses = [item for item in os.environ.get(proxy_key, "").split(",") if item]
    for host in ("localhost", "127.0.0.1", "postgres", "minio"):
        if host not in bypasses:
            bypasses.append(host)
    os.environ[proxy_key] = ",".join(bypasses)
if not Path("/.dockerenv").exists():
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://vav:vav_local_development_only@localhost:5432/vav"
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("AUTH_PRIVATE_KEY_FILE", ".dev-secrets/auth-private.pem")
    os.environ.setdefault("AUTH_PUBLIC_KEY_FILE", ".dev-secrets/auth-public.pem")


_SEED_MODULES = (
    "seed_permissions",
    "seed_cms",
    "seed_catalog",
    "seed_courses",
    "seed_counseling",
    "seed_knowledge",
    "seed_ai_assistant",
    "seed_notification_templates",
    "seed_notifications",
    "seed_privacy",
    "seed_privacy_inventory",
    "seed_quality",
    "seed_experience",
    "seed_process_governance",
    "seed_data_governance",
    "seed_admin_platform",
    "seed_memberships",
    "seed_trust_safety",
)
_LOCAL_DATABASE_CLEANUP = None


def _run_database_admin(database_url: str, statement: str) -> None:
    url = make_url(database_url)

    async def execute() -> None:
        connection = await asyncpg.connect(
            host=url.host or "localhost",
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            database=url.database or "postgres",
        )
        try:
            await connection.execute(statement)
        finally:
            await connection.close()

    asyncio.run(execute())


def _prepare_isolated_local_database() -> None:
    global _LOCAL_DATABASE_CLEANUP
    if os.environ.get("CI", "").casefold() == "true":
        return
    explicit_test_url = os.environ.get("VAV_TEST_DATABASE_URL", "").strip()
    source_url = explicit_test_url or os.environ["DATABASE_URL"]
    parsed = make_url(source_url)
    if explicit_test_url:
        os.environ["DATABASE_URL"] = explicit_test_url
        return
    if parsed.drivername != "postgresql+asyncpg":
        raise RuntimeError("Local API tests require a PostgreSQL asyncpg test database.")
    if (parsed.host or "localhost") not in {"localhost", "127.0.0.1", "postgres"}:
        raise RuntimeError(
            "Refusing to run destructive integration tests against a remote database. "
            "Set VAV_TEST_DATABASE_URL to an explicitly managed test database."
        )

    test_database = f"vav_test_{os.getpid()}_{uuid4().hex[:8]}"
    quoted_database = '"' + test_database.replace('"', '""') + '"'
    test_url = parsed.set(database=test_database).render_as_string(hide_password=False)
    project_root = Path(__file__).resolve().parents[3]
    _run_database_admin(source_url, f"CREATE DATABASE {quoted_database}")
    os.environ["DATABASE_URL"] = test_url

    def cleanup() -> None:
        try:
            _run_database_admin(
                source_url,
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{test_database}' AND pid <> pg_backend_pid()",
            )
            _run_database_admin(source_url, f"DROP DATABASE IF EXISTS {quoted_database}")
        except Exception:
            pass

    atexit.register(cleanup)
    _LOCAL_DATABASE_CLEANUP = cleanup
    commands = [
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "services/api/alembic.ini",
            "upgrade",
            "head",
        ],
        *[[sys.executable, "-m", f"vav.cli.{module}"] for module in _SEED_MODULES],
    ]
    try:
        for command in commands:
            subprocess.run(
                command,
                cwd=project_root,
                env=os.environ,
                check=True,
                capture_output=True,
                text=True,
            )
    except subprocess.CalledProcessError as exc:
        cleanup()
        raise RuntimeError(
            f"Failed to prepare isolated test database: {exc.stdout}{exc.stderr}"
        ) from exc


_prepare_isolated_local_database()

from vav.main import app  # noqa: E402


def pytest_sessionfinish() -> None:
    if _LOCAL_DATABASE_CLEANUP is not None:
        _LOCAL_DATABASE_CLEANUP()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
