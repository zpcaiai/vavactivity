"""Regression tests for the last-four backfill worker (CHK-002).

Every case below corresponds to a defect that only appeared when the job was
run against real rows, so each one is a guard against a specific way the
backfill can look like it worked while leaving the lookup broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import text

from vav.cli import backfill_last_four_hmac as worker
from vav.core.database import session_factory
from vav.modules.checkin_operations.domain import last_four_hmac
from vav.modules.privacy.crypto import encrypt_private, searchable_hmac

TEST_KEY = "backfill-regression-key-3f19c8"
SALT_VERSION = "tv1"


@dataclass(frozen=True)
class _StubSettings:
    """Only the two attributes the worker reads."""

    checkin_last_four_hmac_key: object
    checkin_last_four_salt_version: str = SALT_VERSION


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        worker, "get_settings", lambda: _StubSettings(checkin_last_four_hmac_key=_Secret(TEST_KEY))
    )
    # ``run`` disposes the process-wide engine when it finishes, which would
    # tear the pool out from under the rest of the session.
    monkeypatch.setattr(worker, "get_engine", lambda: _NullEngine())


class _NullEngine:
    async def dispose(self) -> None:
        return None


async def _seed(rows: list[tuple[str, str]]) -> list[str]:
    """Insert phone contact points with ``last_four_hmac`` left NULL.

    ``rows`` is a list of ``(label, ciphertext)``. Returns the created ids.
    """

    created: list[str] = []
    async with session_factory() as session:
        for label, ciphertext in rows:
            suffix = uuid4().hex
            email = f"backfill-{label}-{suffix}@example.invalid"
            user_id = await session.scalar(
                text(
                    "INSERT INTO users (email, display_email, status, email_verified_at) "
                    "VALUES (CAST(:email AS citext), CAST(:email AS varchar), 'active', now()) "
                    "RETURNING id"
                ),
                {"email": email},
            )
            contact_id = await session.scalar(
                text(
                    "INSERT INTO user_contact_points "
                    "  (user_id, contact_type, value_encrypted, value_hmac, status, is_primary) "
                    "VALUES (:user_id, 'phone', :encrypted, :hmac, 'verified', true) "
                    "RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "encrypted": ciphertext,
                    "hmac": searchable_hmac(f"{label}-{suffix}"),
                },
            )
            created.append(str(contact_id))
        await session.commit()
    return created


async def _digests(ids: list[str]) -> dict[str, str | None]:
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, last_four_hmac FROM user_contact_points "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": ids},
        )
        return {str(row.id): row.last_four_hmac for row in result}


@pytest.mark.asyncio
async def test_unreadable_ciphertext_is_skipped_rather_than_aborting_the_run(
    configured: None,
) -> None:
    """A corrupt row must not stop the rows behind it from being fixed.

    ``decrypt_private`` raises ``VavError``. When that was missing from the
    worker's except clause, one unreadable row aborted the whole job and every
    row after it silently stayed unfindable by last-four lookup.
    """

    ids = await _seed(
        [
            ("corrupt", "not-a-valid-fernet-token"),
            ("good", encrypt_private("+8613500001234")),
        ]
    )

    written = await worker.run(batch_size=50, apply=True, limit=None)

    assert written >= 1
    digests = await _digests(ids)
    corrupt_id, good_id = ids
    assert digests[corrupt_id] is None, "an unreadable row must be left untouched"
    assert digests[good_id] == last_four_hmac(
        "1234", key=TEST_KEY.encode(), salt_version=SALT_VERSION
    ), "the row behind the corrupt one must still be backfilled"


@pytest.mark.asyncio
async def test_a_full_batch_of_unfixable_rows_still_terminates(configured: None) -> None:
    """The loop must page forward, not re-select the same unfixable rows.

    Unfixable rows never stop matching the "still pending" predicate. Selecting
    by that predicate alone meant a batch made entirely of them was re-read
    forever; paging by ``id > cursor`` visits each row exactly once.
    """

    ids = await _seed(
        [("corrupt-a", "bad-token-a"), ("corrupt-b", "bad-token-b"), ("corrupt-c", "bad-token-c")]
    )

    # batch_size 1 forces at least one page that yields nothing writable while
    # more rows remain — the exact shape that used to spin.
    written = await worker.run(batch_size=1, apply=True, limit=None)

    assert written == 0
    assert all(value is None for value in (await _digests(ids)).values())


@pytest.mark.asyncio
async def test_rerun_is_idempotent_and_rotation_rewrites_every_row(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Digests carry their salt version so a key rotation is detectable."""

    ids = await _seed([("rotate", encrypt_private("+8613500009876"))])

    assert await worker.run(batch_size=50, apply=True, limit=None) >= 1
    first = (await _digests(ids))[ids[0]]
    assert first is not None and first.startswith(f"{SALT_VERSION}:")

    # A second pass has nothing left to do for this row.
    await worker.run(batch_size=50, apply=True, limit=None)
    assert (await _digests(ids))[ids[0]] == first

    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: _StubSettings(
            checkin_last_four_hmac_key=_Secret(TEST_KEY),
            checkin_last_four_salt_version="tv2",
        ),
    )
    assert await worker.run(batch_size=50, apply=True, limit=None) >= 1
    rotated = (await _digests(ids))[ids[0]]
    assert rotated is not None and rotated.startswith("tv2:")
    assert rotated != first


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(configured: None) -> None:
    ids = await _seed([("dry", encrypt_private("+8613500005555"))])

    await worker.run(batch_size=50, apply=False, limit=None)

    assert (await _digests(ids))[ids[0]] is None


def test_refuses_the_development_default_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped default is public, so it must be rejected like an empty key.

    Without this the "refuse to run unsalted" guard was decorative: the setting
    has a non-empty default, so the falsiness check could never fire.
    """

    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: _StubSettings(
            checkin_last_four_hmac_key=_Secret("local-checkin-last-four-key-change-me")
        ),
    )
    with pytest.raises(SystemExit):
        worker._lookup_key()

    monkeypatch.setattr(
        worker, "get_settings", lambda: _StubSettings(checkin_last_four_hmac_key=_Secret("  "))
    )
    with pytest.raises(SystemExit):
        worker._lookup_key()
