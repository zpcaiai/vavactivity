"""Declarative metadata helpers that never mutate execution authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from vav_skill_sdk.permissions import validate_permissions

SkillClass = TypeVar("SkillClass", bound=type[Any])


def skill_definition(
    *, name: str, version: str, permissions: tuple[str, ...] = ()
) -> Callable[[SkillClass], SkillClass]:
    validated = validate_permissions(permissions)

    def decorate(target: SkillClass) -> SkillClass:
        target.skill_name = name
        target.skill_version = version
        target.requested_permissions = validated
        return target

    return decorate
