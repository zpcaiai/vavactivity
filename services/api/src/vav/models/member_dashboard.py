"""Member dashboard ORM models (B18 / DASH-001).

These models document the schema for metadata and tooling; the service layer
queries through raw SQL. The dashboard owns none of the data it displays, so
the tables here are only the things it genuinely does own: a member's display
preferences, their dismissals, the operator's route overrides, and the log of
which sections degraded.

Anything security-relevant is expressed here *and* as real DDL in migration
``20260812_0102`` - notably the ``task_key LIKE task_type || ':%'`` constraint,
which stops a dismissal being forged against another section's row.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.activities import created_at, updated_at, uuid_pk
from vav.models.base import Base


class MemberDashboardPreference(Base):
    """Per-member display preferences.

    Hiding a section is cosmetic. Authorization is resolved server-side on
    every request, so a member cannot unhide a section they may not see.
    """

    __tablename__ = "member_dashboard_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    hidden_sections: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    page_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class MemberDashboardTaskDismissal(Base):
    """One dismissed card.

    A dismissal never completes the underlying task: the survey is still due,
    it is simply off the home screen.
    """

    __tablename__ = "member_dashboard_task_dismissals"
    __table_args__ = (UniqueConstraint("user_id", "task_key"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Stable key emitted by the dashboard, e.g. ``survey_pending:<uuid>``.
    task_key: Mapped[str] = mapped_column(String(128), nullable=False)
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MemberDashboardSectionIncident(Base):
    """Append-only record of a degraded section.

    Graceful degradation makes a broken section look like an empty one at the
    API. This table is what keeps that from also making it invisible to
    operations.
    """

    __tablename__ = "member_dashboard_section_incidents"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    section_key: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MemberDashboardTaskTypeOverride(Base):
    """Operator override of a task type's route and base priority.

    Ships empty: ``member_dashboard.domain.DEEP_LINK_TEMPLATES`` holds the
    defaults, so a fresh deployment routes correctly with no rows. The
    site-relative constraint is enforced here, in the DDL, and again at render
    time by ``domain.build_deep_link``.
    """

    __tablename__ = "member_dashboard_task_type_overrides"

    task_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    deep_link_template: Mapped[str] = mapped_column(String(255), nullable=False)
    base_priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'normal'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
