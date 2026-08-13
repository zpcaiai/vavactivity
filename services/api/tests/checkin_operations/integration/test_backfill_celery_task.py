from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.models.identity import User

WORKER_SRC = Path(__file__).resolve().parents[5] / "worker" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from vav_worker import tasks  # noqa: E402


@pytest.mark.asyncio
async def test_celery_worker_claims_and_completes_one_queued_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    suffix = uuid4().hex
    async with session_factory() as session:
        actor = User(
            email=f"backfill-worker-{suffix}@example.com",
            display_email=f"backfill-worker-{suffix}@example.com",
            password_hash=None,
            status="active",
        )
        session.add(actor)
        await session.flush()
        await session.execute(
            text(
                "INSERT INTO checkin_last_four_backfill_runs "
                "(id,requested_by,batch_size,salt_version,dry_run,pending_rows,status) "
                "VALUES (:id,:actor,25,'v1',true,0,'queued')"
            ),
            {"id": str(run_id), "actor": str(actor.id)},
        )
        await session.commit()

    calls: list[tuple[int, bool, int | None]] = []

    async def fake_run(*, batch_size: int, apply: bool, limit: int | None) -> int:
        calls.append((batch_size, apply, limit))
        return 7

    monkeypatch.setattr(tasks, "run_last_four_backfill", fake_run)

    result = await tasks._process_last_four_backfill()

    assert result == {"claimed": 1, "processed": 7, "remaining": 0}
    assert calls == [(25, False, None)]
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status,processed_rows,pending_rows,note,started_at,finished_at "
                    "FROM checkin_last_four_backfill_runs WHERE id=:id"
                ),
                {"id": str(run_id)},
            )
        ).one()
    assert row.status == "completed"
    assert row.processed_rows == 7
    assert row.pending_rows == 0
    assert "dry run completed" in row.note
    assert row.started_at is not None
    assert row.finished_at is not None
