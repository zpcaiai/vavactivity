from __future__ import annotations

# ruff: noqa: E501
import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.ai_assistant.crypto import encrypt_ai_data


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: str = "zh-CN"
    limit: int = Field(default=3, ge=1, le=10)


class UserScopedArguments(ToolArguments):
    user_id: UUID | None = None


class WriteToolArguments(UserScopedArguments):
    confirmation_token: str = Field(min_length=16, max_length=512)


class CounselingReferralArguments(WriteToolArguments):
    user_goal_summary: str = Field(min_length=3, max_length=1000)


class AppointmentDraftArguments(CounselingReferralArguments):
    service_id: UUID
    mentor_id: UUID | None = None
    preferred_time_note: str | None = Field(default=None, max_length=500)


class ActionItemArguments(WriteToolArguments):
    content: str = Field(min_length=3, max_length=2000)


@dataclass(frozen=True)
class ToolDefinition:
    code: str
    version: str
    description: str
    input_model: type[BaseModel]
    risk_level: str = "read_only"
    confirmation_required: bool = False
    idempotency_required: bool = False
    timeout_seconds: int = 10

    def public_record(self) -> dict[str, Any]:
        return {
            "tool_code": self.code,
            "semantic_version": self.version,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": {"type": "object"},
            "risk_level": self.risk_level,
            "required_permissions": ["self_scope"],
            "user_confirmation_required": self.confirmation_required,
            "idempotency_required": self.idempotency_required,
            "timeout_seconds": self.timeout_seconds,
            "allowed_agent_profiles": ["hanna_v1"],
        }


READ_TOOLS = (
    "search_published_activities",
    "get_activity_availability",
    "search_published_courses",
    "get_course_price",
    "get_user_course_progress",
    "search_counseling_services",
    "search_available_mentors",
    "get_counseling_availability",
    "get_user_entitlements",
    "get_user_upcoming_appointments",
    "get_platform_safety_guidance",
)
WRITE_TOOLS = (
    "create_counseling_referral",
    "create_counseling_appointment_draft",
    "create_user_action_item",
)

TOOL_REGISTRY: dict[str, ToolDefinition] = {
    code: ToolDefinition(
        code=code,
        version="1.0.0",
        description=code.replace("_", " "),
        input_model=UserScopedArguments,
    )
    for code in READ_TOOLS
}
TOOL_REGISTRY.update(
    {
        code: ToolDefinition(
            code=code,
            version="1.0.0",
            description=code.replace("_", " "),
            input_model=WriteToolArguments,
            risk_level="write",
            confirmation_required=True,
            idempotency_required=True,
        )
        for code in WRITE_TOOLS
    }
)
TOOL_REGISTRY["create_counseling_referral"] = ToolDefinition(
    code="create_counseling_referral",
    version="1.0.0",
    description="Create a user-confirmed counseling referral.",
    input_model=CounselingReferralArguments,
    risk_level="write",
    confirmation_required=True,
    idempotency_required=True,
)
TOOL_REGISTRY["create_counseling_appointment_draft"] = ToolDefinition(
    code="create_counseling_appointment_draft",
    version="1.0.0",
    description="Create a user-confirmed appointment draft without booking a slot.",
    input_model=AppointmentDraftArguments,
    risk_level="write",
    confirmation_required=True,
    idempotency_required=True,
)
TOOL_REGISTRY["create_user_action_item"] = ToolDefinition(
    code="create_user_action_item",
    version="1.0.0",
    description="Create a user-confirmed personal action item.",
    input_model=ActionItemArguments,
    risk_level="write",
    confirmation_required=True,
    idempotency_required=True,
)


def registry_version() -> str:
    return "hanna-tools-1.0.0"


def validate_arguments(
    definition: ToolDefinition, arguments: dict[str, Any], *, current_user_id: UUID
) -> ToolArguments:
    validated = cast(ToolArguments, definition.input_model.model_validate(arguments))
    requested_user = getattr(validated, "user_id", None)
    if requested_user is not None and requested_user != current_user_id:
        raise VavError(
            "AI_TOOL_CROSS_USER_FORBIDDEN",
            "The tool can access only the current user's data.",
            status_code=403,
        )
    return validated


async def _read_rows(
    session: AsyncSession, statement: str, parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = (await session.execute(text(statement), parameters)).mappings().all()

    def json_safe(value: Any) -> Any:
        if isinstance(value, UUID | datetime | date | time | Decimal):
            return str(value)
        if isinstance(value, dict):
            return {key: json_safe(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [json_safe(item) for item in value]
        return value

    return [{key: json_safe(value) for key, value in dict(row).items()} for row in rows]


async def execute_read_tool(
    session: AsyncSession,
    *,
    tool_code: str,
    arguments: dict[str, Any],
    current_user_id: UUID,
    locale: str,
) -> dict[str, Any]:
    definition = TOOL_REGISTRY.get(tool_code)
    if definition is None or tool_code not in READ_TOOLS:
        raise VavError(
            "AI_TOOL_NOT_REGISTERED", "The requested tool is not available.", status_code=400
        )
    parsed = validate_arguments(
        definition, {"locale": locale, **arguments}, current_user_id=current_user_id
    )
    params = {"locale": parsed.locale, "limit": parsed.limit, "user": current_user_id}
    queries = {
        "search_published_activities": (
            "SELECT a.id,a.activity_code,l.title,l.summary,a.starts_at,a.ends_at,a.timezone,a.status "
            "FROM activities a JOIN activity_localizations l ON l.activity_id=a.id AND l.locale=:locale "
            "WHERE a.visibility='public' AND a.status IN "
            "('published','registration_open','registration_closed','in_progress') "
            "AND a.ends_at>now() ORDER BY a.starts_at LIMIT :limit"
        ),
        "get_activity_availability": (
            "SELECT a.id,a.activity_code,a.status,COALESCE(SUM(i.total_capacity-i.reserved_quantity-i.sold_quantity),0) "
            "AS remaining_capacity FROM activities a JOIN activity_ticket_types t ON t.activity_id=a.id "
            "JOIN inventory_items i ON i.sku_id=t.catalog_sku_id "
            "WHERE a.visibility='public' AND a.status IN ('published','registration_open') "
            "GROUP BY a.id ORDER BY a.starts_at LIMIT :limit"
        ),
        "search_published_courses": (
            "SELECT c.id,c.course_code,l.title,l.summary,c.status,c.estimated_duration_minutes "
            "FROM courses c JOIN course_localizations l ON l.course_id=c.id AND l.locale=:locale "
            "WHERE c.visibility='public' AND c.status IN ('published','enrollment_closed') "
            "ORDER BY c.featured DESC,c.sort_order LIMIT :limit"
        ),
        "get_course_price": (
            "SELECT c.id,c.course_code,l.title,p.currency_code,p.unit_amount_minor,p.tax_behavior "
            "FROM courses c JOIN course_localizations l ON l.course_id=c.id AND l.locale=:locale "
            "JOIN prices p ON p.sku_id=c.primary_catalog_sku_id JOIN price_books b ON b.id=p.price_book_id "
            "WHERE c.visibility='public' AND c.status IN ('published','enrollment_closed') "
            "AND p.status='active' AND b.status='active' AND p.valid_from<=now() "
            "AND (p.valid_until IS NULL OR p.valid_until>now()) ORDER BY b.priority DESC LIMIT :limit"
        ),
        "get_user_course_progress": (
            "SELECT e.id,e.course_id,c.course_code,e.status,e.enrolled_at,e.completed_at,"
            "COALESCE(AVG(lp.progress_basis_points),0)::integer AS progress_basis_points "
            "FROM course_enrollments e JOIN courses c ON c.id=e.course_id "
            "LEFT JOIN lesson_progress lp ON lp.enrollment_id=e.id WHERE e.user_id=:user "
            "GROUP BY e.id,c.course_code ORDER BY e.enrolled_at DESC LIMIT :limit"
        ),
        "search_counseling_services": (
            "SELECT s.id,s.service_code,l.name,l.summary,l.scope_notice,s.duration_minutes,s.free_access,s.status "
            "FROM counseling_services s JOIN counseling_service_localizations l "
            "ON l.service_id=s.id AND l.locale=:locale WHERE s.status='published' "
            "ORDER BY s.created_at LIMIT :limit"
        ),
        "search_available_mentors": (
            "SELECT m.id,m.mentor_code,COALESCE(l.public_name,m.display_name) AS name,m.service_languages,m.specialty_topics "
            "FROM counseling_mentors m LEFT JOIN counseling_mentor_localizations l "
            "ON l.mentor_id=m.id AND l.locale=:locale WHERE m.status='active' "
            "ORDER BY m.display_name LIMIT :limit"
        ),
        "get_counseling_availability": (
            "SELECT m.id AS mentor_id,m.display_name,s.id AS service_id,s.service_code,r.timezone,r.weekday,"
            "r.local_start_time,r.local_end_time FROM counseling_availability_rules r "
            "JOIN counseling_mentors m ON m.id=r.mentor_id "
            "LEFT JOIN counseling_services s ON s.id=r.service_id "
            "WHERE r.status='active' AND m.status='active' ORDER BY r.weekday,r.local_start_time LIMIT :limit"
        ),
        "get_user_entitlements": (
            "SELECT id,entitlement_type,status,resource_type,resource_id,quantity_granted,quantity_consumed,expires_at "
            "FROM entitlements WHERE user_id=:user AND status='active' "
            "AND (expires_at IS NULL OR expires_at>now()) ORDER BY created_at DESC LIMIT :limit"
        ),
        "get_user_upcoming_appointments": (
            "SELECT id,appointment_number,service_id,mentor_id,status,scheduled_starts_at,scheduled_ends_at,user_timezone "
            "FROM counseling_appointments WHERE user_id=:user AND status NOT IN ('cancelled','completed','rejected') "
            "ORDER BY scheduled_starts_at NULLS LAST LIMIT :limit"
        ),
    }
    if tool_code == "get_platform_safety_guidance":
        return {
            "items": [
                {
                    "policy": "hanna-safety-1.0.0",
                    "guidance": "Prioritize immediate safety and use local emergency or professional support; AI is not emergency, medical, or legal service.",
                }
            ]
        }
    query = queries[tool_code]
    async with asyncio.timeout(definition.timeout_seconds):
        items = await _read_rows(session, query, params)
    return {"items": items, "authoritative": True, "tool_code": tool_code}


async def execute_confirmed_write_tool(
    session: AsyncSession,
    *,
    tool_code: str,
    arguments: dict[str, Any],
    current_user_id: UUID,
    conversation_id: UUID,
) -> dict[str, Any]:
    definition = TOOL_REGISTRY.get(tool_code)
    if definition is None or tool_code not in WRITE_TOOLS:
        raise VavError(
            "AI_WRITE_TOOL_NOT_REGISTERED", "Write tool is not available.", status_code=400
        )
    parsed = validate_arguments(definition, arguments, current_user_id=current_user_id)
    if tool_code == "create_counseling_referral":
        referral_id = await session.scalar(
            text(
                "INSERT INTO ai_human_referrals "
                "(referral_number,conversation_id,user_id,referral_type,priority,risk_category,"
                "risk_level,status,user_visible_summary_encrypted,internal_context_encrypted,"
                "assigned_team,consent_status,idempotency_key) "
                "VALUES (:number,:conversation,:user,'counseling','normal',NULL,NULL,"
                "'pending_assignment',NULL,NULL,'counseling','user_confirmed',:key) RETURNING id"
            ),
            {
                "number": f"AIR-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}",
                "conversation": conversation_id,
                "user": current_user_id,
                "key": f"confirmed-referral:{conversation_id}:{uuid4().hex}",
            },
        )
        return {"referral_id": str(referral_id), "status": "pending_assignment"}
    content = (
        parsed.content
        if isinstance(parsed, ActionItemArguments)
        else f"Appointment draft: {cast(CounselingReferralArguments, parsed).user_goal_summary}"
    )
    action_item_id = await session.scalar(
        text(
            "INSERT INTO ai_action_items (conversation_id,user_id,content_encrypted,status) "
            "VALUES (:conversation,:user,:content,'open') RETURNING id"
        ),
        {
            "conversation": conversation_id,
            "user": current_user_id,
            "content": encrypt_ai_data({"content": content, "tool_code": tool_code}),
        },
    )
    return {
        "action_item_id": str(action_item_id),
        "status": "draft" if tool_code == "create_counseling_appointment_draft" else "open",
    }
