from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.models.activities import Activity, ActivityLocalization
from vav.models.content import ContentEntry, ContentLocalization
from vav.models.counseling import CounselingServiceDefinition, CounselingServiceLocalization
from vav.models.courses import Course, CourseLocalization
from vav.models.knowledge import KnowledgeDocumentVersion, KnowledgeSource
from vav.modules.knowledge.service import knowledge_service


@dataclass(frozen=True)
class ConnectorDocument:
    code: str
    title: str
    locale: str
    body: str
    reference_type: str
    reference_id: str
    version: int


def _public_text(*values: object) -> str:
    rendered: list[str] = []

    def append(value: object) -> None:
        if isinstance(value, str) and value.strip():
            rendered.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                append(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key.casefold() not in {
                    "answer",
                    "submission",
                    "private_note",
                    "email",
                    "phone",
                    "address",
                }:
                    append(item)

    for candidate in values:
        append(candidate)
    return "\n\n".join(rendered)


async def _cms(session: AsyncSession) -> list[ConnectorDocument]:
    rows = (
        await session.execute(
            select(ContentEntry, ContentLocalization)
            .join(ContentLocalization, ContentLocalization.entry_id == ContentEntry.id)
            .where(ContentEntry.status == "published", ContentEntry.visibility == "public")
        )
    ).all()
    return [
        ConnectorDocument(
            code=f"cms-{entry.canonical_slug}-{localization.locale}",
            title=localization.title,
            locale=localization.locale,
            body=_public_text(
                localization.title,
                localization.subtitle,
                localization.excerpt,
                localization.plain_text,
                localization.content_blocks,
            ),
            reference_type="content_entry",
            reference_id=str(entry.id),
            version=entry.current_version,
        )
        for entry, localization in rows
        if localization.translation_status in {"ready", "published"}
    ]


async def _courses(session: AsyncSession) -> list[ConnectorDocument]:
    rows = (
        await session.execute(
            select(Course, CourseLocalization)
            .join(CourseLocalization, CourseLocalization.course_id == Course.id)
            .where(Course.status == "published", Course.visibility == "public")
        )
    ).all()
    return [
        ConnectorDocument(
            code=f"course-{course.course_code}-{localization.locale}",
            title=localization.title,
            locale=localization.locale,
            body=_public_text(
                localization.title,
                localization.subtitle,
                localization.summary,
                localization.description_blocks,
                localization.learning_outcomes,
                localization.target_audience,
                localization.prerequisites,
            ),
            reference_type="course",
            reference_id=str(course.id),
            version=course.version,
        )
        for course, localization in rows
        if localization.translation_status in {"ready", "published"}
    ]


async def _activities(session: AsyncSession) -> list[ConnectorDocument]:
    rows = (
        await session.execute(
            select(Activity, ActivityLocalization)
            .join(ActivityLocalization, ActivityLocalization.activity_id == Activity.id)
            .where(Activity.status == "published", Activity.visibility == "public")
        )
    ).all()
    return [
        ConnectorDocument(
            code=f"activity-{activity.activity_code}-{localization.locale}",
            title=localization.title,
            locale=localization.locale,
            body=_public_text(
                localization.title,
                localization.summary,
                localization.description_blocks,
                localization.participation_notes,
                localization.cancellation_notice,
            ),
            reference_type="activity",
            reference_id=str(activity.id),
            version=activity.version,
        )
        for activity, localization in rows
        if localization.translation_status in {"ready", "published"}
    ]


async def _counseling(session: AsyncSession) -> list[ConnectorDocument]:
    rows = (
        await session.execute(
            select(CounselingServiceDefinition, CounselingServiceLocalization)
            .join(
                CounselingServiceLocalization,
                CounselingServiceLocalization.service_id == CounselingServiceDefinition.id,
            )
            .where(CounselingServiceDefinition.status == "published")
        )
    ).all()
    return [
        ConnectorDocument(
            code=f"counseling-{service.service_code}-{localization.locale}",
            title=localization.name,
            locale=localization.locale,
            body=_public_text(
                localization.name,
                localization.summary,
                localization.description_blocks,
                localization.scope_notice,
                service.scope_policy,
            ),
            reference_type="counseling_service",
            reference_id=str(service.id),
            version=service.version,
        )
        for service, localization in rows
        if localization.translation_status in {"ready", "published"}
    ]


CONNECTORS = {
    "cms": _cms,
    "course": _courses,
    "activity": _activities,
    "counseling": _counseling,
}


async def sync_source(
    session: AsyncSession, source: KnowledgeSource
) -> list[KnowledgeDocumentVersion]:
    connector = CONNECTORS.get(source.source_type)
    if connector is None:
        raise VavError(
            "KNOWLEDGE_CONNECTOR_UNSUPPORTED",
            "This source does not support business synchronization.",
            status_code=409,
        )
    candidates = await connector(session)
    versions: list[KnowledgeDocumentVersion] = []
    for item in candidates:
        if not item.body.strip():
            continue
        version = await knowledge_service.ingest(
            session,
            source=source,
            document_code=item.code,
            title=item.title,
            locale=item.locale,
            mime_type="text/markdown",
            raw_text=item.body,
            source_locator={
                "reference_type": item.reference_type,
                "reference_id": item.reference_id,
                "source_version": item.version,
            },
        )
        versions.append(version)
    source.last_synced_at = datetime.now(UTC)
    source.last_sync_version = json.dumps(
        {"documents": len(versions), "at": source.last_synced_at.isoformat()},
        separators=(",", ":"),
    )
    await session.commit()
    return versions
