from uuid import UUID

import pytest

from vav.common.exceptions import VavError
from vav.modules.courses.domain import (
    assert_acyclic_prerequisites,
    ensure_course_transition,
    mask_public_name,
    monotonic_progress,
    score_response,
)


def test_course_publication_state_machine_rejects_skips() -> None:
    ensure_course_transition("draft", "in_review")
    ensure_course_transition("in_review", "published")
    with pytest.raises(VavError) as error:
        ensure_course_transition("draft", "published")
    assert error.value.code == "COURSE_TRANSITION_INVALID"


def test_prerequisite_graph_rejects_cycles() -> None:
    a, b, c = UUID(int=1), UUID(int=2), UUID(int=3)
    assert_acyclic_prerequisites([(b, a), (c, b)])
    with pytest.raises(VavError) as error:
        assert_acyclic_prerequisites([(b, a), (c, b), (a, c)])
    assert error.value.code == "COURSE_PREREQUISITE_CYCLE"


def test_scoring_is_deterministic_and_progress_never_regresses() -> None:
    assert score_response("single_choice", "a", "a") is True
    assert score_response("multiple_choice", ["a", "b"], ["b", "a"]) is True
    assert score_response("text", "expected", "answer") is None
    assert monotonic_progress(8000, 1000) == 8000
    assert monotonic_progress(8000, 12000) == 10000


def test_certificate_public_name_is_masked() -> None:
    assert mask_public_name("Stephen Wang") == "S*** W***"
    assert mask_public_name("learner@example.com") == "l***@example.com"
