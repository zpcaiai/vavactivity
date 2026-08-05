import pytest

from vav.modules.relationships.domain import STAGES, other_participant, validate_transition


def test_stage_progress_is_adjacent_by_default() -> None:
    validate_transition("introduction_accepted", "initial_contact")
    with pytest.raises(ValueError, match="skipping"):
        validate_transition("introduction_accepted", "dating")


def test_backward_proposal_and_confirmed_stage_are_in_registry() -> None:
    validate_transition("dating", "getting_to_know")
    assert STAGES[-1] == "relationship_confirmed"


def test_only_a_participant_has_a_partner() -> None:
    assert other_participant(user_low_id="a", user_high_id="b", actor_id="a") == "b"
    with pytest.raises(ValueError, match="not a relationship participant"):
        other_participant(user_low_id="a", user_high_id="b", actor_id="c")
