from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any
from uuid import UUID

from vav.common.exceptions import VavError


class CourseStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ENROLLMENT_CLOSED = "enrollment_closed"
    UNPUBLISHED = "unpublished"
    ARCHIVED = "archived"


COURSE_TRANSITIONS = {
    CourseStatus.DRAFT: {CourseStatus.IN_REVIEW, CourseStatus.ARCHIVED},
    CourseStatus.IN_REVIEW: {CourseStatus.DRAFT, CourseStatus.PUBLISHED, CourseStatus.SCHEDULED},
    CourseStatus.SCHEDULED: {CourseStatus.PUBLISHED, CourseStatus.DRAFT},
    CourseStatus.PUBLISHED: {
        CourseStatus.ENROLLMENT_CLOSED,
        CourseStatus.UNPUBLISHED,
        CourseStatus.ARCHIVED,
    },
    CourseStatus.ENROLLMENT_CLOSED: {
        CourseStatus.PUBLISHED,
        CourseStatus.UNPUBLISHED,
        CourseStatus.ARCHIVED,
    },
    CourseStatus.UNPUBLISHED: {CourseStatus.IN_REVIEW, CourseStatus.ARCHIVED},
    CourseStatus.ARCHIVED: set(),
}


def ensure_course_transition(current: str, target: str) -> None:
    try:
        source = CourseStatus(current)
        destination = CourseStatus(target)
    except ValueError as error:
        raise VavError(
            "COURSE_STATUS_INVALID", "Course status is invalid.", status_code=422
        ) from error
    if destination not in COURSE_TRANSITIONS[source]:
        raise VavError(
            "COURSE_TRANSITION_INVALID",
            f"Course cannot transition from {source.value} to {destination.value}.",
            status_code=409,
        )


def assert_acyclic_prerequisites(edges: Iterable[tuple[UUID, UUID]]) -> None:
    graph: dict[UUID, set[UUID]] = {}
    for lesson_id, prerequisite_id in edges:
        graph.setdefault(lesson_id, set()).add(prerequisite_id)
        graph.setdefault(prerequisite_id, set())
    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(node: UUID) -> None:
        if node in visiting:
            raise VavError(
                "COURSE_PREREQUISITE_CYCLE",
                "Lesson prerequisites contain a cycle.",
                status_code=422,
            )
        if node in visited:
            return
        visiting.add(node)
        for child in graph.get(node, set()):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def score_response(question_type: str, expected: Any, actual: Any) -> bool | None:
    if question_type in {"single_choice", "true_false"}:
        return str(actual) == str(expected)
    if question_type == "multiple_choice":
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False
        return {str(item) for item in actual} == {str(item) for item in expected}
    return None


def monotonic_progress(current: int, candidate: int) -> int:
    return max(current, min(max(candidate, 0), 10_000))


def mask_public_name(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return "V**"
    if "@" in cleaned:
        local, _, domain = cleaned.partition("@")
        return f"{local[:1]}***@{domain}"
    parts = cleaned.split(" ")
    if len(parts) > 1:
        return " ".join(f"{part[:1]}***" for part in parts)
    return f"{cleaned[:1]}***"
