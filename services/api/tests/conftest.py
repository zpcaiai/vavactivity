import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "test"
if not Path("/.dockerenv").exists():
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://vav:vav_local_development_only@localhost:5432/vav"
    )
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["AUTH_PRIVATE_KEY_FILE"] = ".dev-secrets/auth-private.pem"
    os.environ["AUTH_PUBLIC_KEY_FILE"] = ".dev-secrets/auth-public.pem"

from vav.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
