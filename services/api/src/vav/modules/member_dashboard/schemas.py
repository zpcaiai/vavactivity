"""Request payloads for the member dashboard module (B18)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


_SECTION = Literal[
    "survey_tasks",
    "result_letters",
    "registrations",
    "mutual_selection",
    "matchmaking",
    "notifications",
]

_TASK_TYPE = Literal[
    "survey_pending",
    "mutual_selection_pending",
    "result_letter_unread",
    "registration_upcoming",
    "matchmaking_attempt_available",
    "notification_unread",
]


class DashboardPreferencesRequest(_Base):
    """Sections a member has chosen to collapse.

    Hiding a section is a display preference only; it never changes what the
    member is authorized to see, which is decided server-side per request.
    """

    hidden_sections: Annotated[list[_SECTION], Field(max_length=6)] = Field(default_factory=list)
    page_size: Annotated[int, Field(ge=1, le=100)] = 20


class TaskDismissRequest(_Base):
    task_type: _TASK_TYPE
    #: The stable key emitted by the dashboard, e.g. ``survey_pending:<uuid>``.
    task_key: Annotated[str, Field(min_length=3, max_length=128)]


class TaskTypeOverrideRequest(_Base):
    """Administrative override of a task type's route and base priority."""

    task_type: _TASK_TYPE
    deep_link_template: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^/[^/].*$")]
    base_priority: Literal["urgent", "high", "normal", "low"] = "normal"
    is_active: bool = True
