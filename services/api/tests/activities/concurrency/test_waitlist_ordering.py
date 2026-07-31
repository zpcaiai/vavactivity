from uuid import UUID

from vav.modules.activities.domain import deterministic_groups


def test_deterministic_grouping_does_not_depend_on_query_order() -> None:
    participants = [UUID(int=value) for value in range(1, 101)]
    expected = deterministic_groups(participants, target_size=8, seed="stable-seed")
    actual = deterministic_groups(
        participants[::2] + participants[1::2], target_size=8, seed="stable-seed"
    )
    assert actual == expected
    assert len({value for group in actual for value in group}) == 100
