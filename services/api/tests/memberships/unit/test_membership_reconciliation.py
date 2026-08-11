from unittest.mock import AsyncMock, MagicMock

import pytest

from vav.modules.memberships import service


def _session_with_rows(rows: list[dict[str, object]]) -> AsyncMock:
    result = MagicMock()
    result.mappings.return_value = rows
    session = AsyncMock()
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_list_reconciliation_issues_omits_untyped_null_parameter() -> None:
    session = _session_with_rows([])

    assert await service.list_reconciliation_issues(session) == []

    statement, parameters = session.execute.await_args.args
    assert "WHERE" not in str(statement)
    assert parameters == {}


@pytest.mark.asyncio
async def test_list_reconciliation_issues_filters_non_null_status() -> None:
    session = _session_with_rows([{"status": "open"}])

    assert await service.list_reconciliation_issues(session, "open") == [
        {"status": "open"}
    ]

    statement, parameters = session.execute.await_args.args
    assert "WHERE status=:status" in str(statement)
    assert parameters == {"status": "open"}
