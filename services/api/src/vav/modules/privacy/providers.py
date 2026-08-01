# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class PrivacyInventoryResult:
    module_code: str
    schema_version: str
    assets: list[dict[str, Any]]


@dataclass(frozen=True)
class ModuleErasurePlan:
    module_code: str
    operation: str
    blockers: list[dict[str, Any]]
    retained_assets: list[str]


class PrivacyDataProvider(Protocol):
    module_code: str
    schema_version: str

    async def inventory(self, session: AsyncSession, user_id: UUID) -> PrivacyInventoryResult: ...

    async def export(self, session: AsyncSession, user_id: UUID) -> dict[str, Any]: ...

    async def plan_erasure(self, session: AsyncSession, user_id: UUID) -> ModuleErasurePlan: ...

    async def execute_erasure(
        self, session: AsyncSession, user_id: UUID, operation: str
    ) -> dict[str, Any]: ...


class FixedModulePrivacyProvider:
    schema_version = "1.0"

    def __init__(
        self,
        *,
        module_code: str,
        inventory_queries: dict[str, str],
        export_queries: dict[str, str],
        erasure_operation: str,
        retained_assets: list[str] | None = None,
        erasure_statements: list[str] | None = None,
    ) -> None:
        self.module_code = module_code
        self.inventory_queries = inventory_queries
        self.export_queries = export_queries
        self.erasure_operation = erasure_operation
        self.retained_assets = retained_assets or []
        self.erasure_statements = erasure_statements or []

    async def inventory(self, session: AsyncSession, user_id: UUID) -> PrivacyInventoryResult:
        assets = []
        for asset_code, query in self.inventory_queries.items():
            count = await session.scalar(text(query), {"user_id": user_id})
            assets.append({"asset_code": asset_code, "record_count": int(count or 0)})
        return PrivacyInventoryResult(self.module_code, self.schema_version, assets)

    async def export(self, session: AsyncSession, user_id: UUID) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for name, query in self.export_queries.items():
            rows = list((await session.execute(text(query), {"user_id": user_id})).mappings().all())
            payload[name] = [dict(row) for row in rows]
        return {
            "module": self.module_code,
            "schema_version": self.schema_version,
            "data": payload,
        }

    async def plan_erasure(self, session: AsyncSession, user_id: UUID) -> ModuleErasurePlan:
        del session, user_id
        return ModuleErasurePlan(
            module_code=self.module_code,
            operation=self.erasure_operation,
            blockers=[],
            retained_assets=list(self.retained_assets),
        )

    async def execute_erasure(
        self, session: AsyncSession, user_id: UUID, operation: str
    ) -> dict[str, Any]:
        if operation != self.erasure_operation:
            return {
                "status": "manual_review",
                "error_code": "PRIVACY_ERASURE_OPERATION_MISMATCH",
                "retained_assets": self.retained_assets,
            }
        affected = 0
        for statement in self.erasure_statements:
            result = await session.execute(text(statement), {"user_id": user_id})
            rowcount = getattr(result, "rowcount", 0)
            affected += max(int(rowcount or 0), 0)
        return {
            "status": "completed",
            "affected_records": affected,
            "retained_assets": self.retained_assets,
        }


PROVIDERS: dict[str, PrivacyDataProvider] = {
    "identity": FixedModulePrivacyProvider(
        module_code="identity",
        inventory_queries={
            "identity.account": "SELECT count(*) FROM users WHERE id=:user_id",
            "identity.profile": "SELECT count(*) FROM user_profiles WHERE user_id=:user_id",
            "identity.contacts": "SELECT count(*) FROM user_contact_points WHERE user_id=:user_id",
            "identity.consents": "SELECT count(*) FROM user_consents WHERE user_id=:user_id",
        },
        export_queries={
            "account": "SELECT id,email,status,email_verified_at,preferred_locale,timezone,created_at FROM users WHERE id=:user_id",
            "profile": "SELECT display_name,gender_code,country_code,region,city,preferred_locale,timezone,public_bio,profile_status,completeness_basis_points,version,created_at,updated_at FROM user_profiles WHERE user_id=:user_id",
            "consents": "SELECT d.consent_code,c.semantic_version,r.status,r.granted_at,r.withdrawn_at,r.expires_at,r.source FROM user_consents r JOIN consent_definitions d ON d.id=r.consent_definition_id JOIN consent_releases c ON c.id=r.consent_release_id WHERE r.user_id=:user_id ORDER BY r.created_at",
        },
        erasure_operation="anonymize",
        retained_assets=["identity.security_audit"],
        erasure_statements=[
            "DELETE FROM user_contact_points WHERE user_id=:user_id",
            "UPDATE user_profiles SET display_name=NULL,legal_name_encrypted=NULL,date_of_birth_encrypted=NULL,gender_code=NULL,country_code=NULL,region=NULL,city=NULL,public_bio=NULL,profile_status='anonymized',version=version+1,updated_at=now() WHERE user_id=:user_id",
        ],
    ),
    "commerce": FixedModulePrivacyProvider(
        module_code="commerce",
        inventory_queries={
            "commerce.orders": "SELECT count(*) FROM orders WHERE user_id=:user_id",
            "commerce.subscriptions": "SELECT count(*) FROM subscriptions WHERE user_id=:user_id",
        },
        export_queries={
            "orders": "SELECT id,order_number,status,currency_code,subtotal_minor,discount_total_minor,tax_total_minor,total_minor,refunded_total_minor,created_at FROM orders WHERE user_id=:user_id ORDER BY created_at",
            "subscriptions": "SELECT id,status,current_period_start,current_period_end,cancel_at_period_end,created_at FROM subscriptions WHERE user_id=:user_id ORDER BY created_at",
        },
        erasure_operation="retain_restricted",
        retained_assets=["commerce.orders", "commerce.payments", "commerce.refunds"],
    ),
    "activities": FixedModulePrivacyProvider(
        module_code="activities",
        inventory_queries={
            "activities.registrations": "SELECT count(*) FROM activity_registrations WHERE user_id=:user_id",
        },
        export_queries={
            "registrations": "SELECT id,registration_number,activity_id,status,attendance_status,confirmed_at,cancelled_at,created_at FROM activity_registrations WHERE user_id=:user_id ORDER BY created_at",
        },
        erasure_operation="anonymize",
        retained_assets=["activities.checkin_audit"],
    ),
    "courses": FixedModulePrivacyProvider(
        module_code="courses",
        inventory_queries={
            "courses.enrollments": "SELECT count(*) FROM course_enrollments WHERE user_id=:user_id",
            "courses.certificates": "SELECT count(*) FROM course_certificates WHERE user_id=:user_id",
        },
        export_queries={
            "enrollments": "SELECT id,course_id,status,enrolled_at,completed_at,access_expires_at FROM course_enrollments WHERE user_id=:user_id ORDER BY enrolled_at",
            "certificates": "SELECT id,certificate_number,status,issued_at,revoked_at FROM course_certificates WHERE user_id=:user_id ORDER BY issued_at",
        },
        erasure_operation="anonymize",
        retained_assets=["courses.certificate_verification"],
    ),
    "counseling": FixedModulePrivacyProvider(
        module_code="counseling",
        inventory_queries={
            "counseling.appointments": "SELECT count(*) FROM counseling_appointments WHERE user_id=:user_id",
            "counseling.records": "SELECT count(*) FROM counseling_records r JOIN counseling_sessions s ON s.id=r.session_id JOIN counseling_appointments a ON a.id=s.appointment_id WHERE a.user_id=:user_id",
        },
        export_queries={
            "appointments": "SELECT id,appointment_number,status,scheduled_starts_at,scheduled_ends_at,payment_status,created_at FROM counseling_appointments WHERE user_id=:user_id ORDER BY created_at",
        },
        erasure_operation="retain_restricted",
        retained_assets=["counseling.private_records", "counseling.safety_records"],
    ),
    "knowledge": FixedModulePrivacyProvider(
        module_code="knowledge",
        inventory_queries={
            "knowledge.queries": "SELECT count(*) FROM knowledge_retrieval_queries WHERE actor_id=:user_id",
        },
        export_queries={},
        erasure_operation="delete",
        erasure_statements=[
            "UPDATE knowledge_retrieval_queries SET actor_id=NULL,query_encrypted='deleted' WHERE actor_id=:user_id"
        ],
    ),
    "ai": FixedModulePrivacyProvider(
        module_code="ai",
        inventory_queries={
            "ai.conversations": "SELECT count(*) FROM ai_conversations WHERE user_id=:user_id",
            "ai.memories": "SELECT count(*) FROM ai_memory_items WHERE user_id=:user_id AND status<>'deleted'",
        },
        export_queries={
            "conversations": "SELECT id,conversation_number,status,locale,created_at,updated_at FROM ai_conversations WHERE user_id=:user_id ORDER BY created_at",
            "memory_manifest": "SELECT id,memory_type,status,source_type,certainty,user_confirmed,valid_from,expires_at,created_at FROM ai_memory_items WHERE user_id=:user_id AND status<>'deleted' ORDER BY created_at",
        },
        erasure_operation="delete",
        erasure_statements=[
            "UPDATE ai_memory_items SET content_encrypted='deleted',status='deleted',deleted_at=now(),updated_at=now() WHERE user_id=:user_id AND status<>'deleted'",
            "UPDATE ai_conversations SET status='deleted',updated_at=now() WHERE user_id=:user_id AND status<>'deleted'",
        ],
    ),
    "notifications": FixedModulePrivacyProvider(
        module_code="notifications",
        inventory_queries={
            "notifications.in_app": "SELECT count(*) FROM user_notifications WHERE user_id=:user_id",
            "notifications.deliveries": "SELECT count(*) FROM notification_deliveries WHERE user_id=:user_id",
            "notifications.preferences": "SELECT count(*) FROM notification_preferences WHERE user_id=:user_id",
        },
        export_queries={
            "in_app": "SELECT id,category,priority,title,body,status,read_at,created_at FROM user_notifications WHERE user_id=:user_id ORDER BY created_at",
            "preferences": "SELECT category,channel,enabled,frequency,quiet_hours_enabled,created_at,updated_at FROM notification_preferences WHERE user_id=:user_id ORDER BY category,channel",
        },
        erasure_operation="delete",
        retained_assets=["notifications.delivery_audit"],
        erasure_statements=[
            "DELETE FROM notification_preferences WHERE user_id=:user_id",
            "DELETE FROM user_notifications WHERE user_id=:user_id",
        ],
    ),
}


def provider_registry() -> dict[str, PrivacyDataProvider]:
    return dict(PROVIDERS)
