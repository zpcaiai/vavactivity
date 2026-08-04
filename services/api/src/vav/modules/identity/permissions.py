# ruff: noqa: B008

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends

from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal

IDENTITY_PERMISSIONS = {
    "users.read",
    "users.update",
    "users.suspend",
    "users.restore",
    "users.sessions.revoke",
    "roles.read",
    "roles.create",
    "roles.update",
    "roles.assign",
    "roles.revoke",
    "admins.read",
    "admins.invite",
    "admins.disable",
    "admins.restore",
    "audit.read",
    "audit.export",
}

CMS_PERMISSIONS = {
    "content.pages.read",
    "content.pages.create",
    "content.pages.update",
    "content.pages.review",
    "content.pages.publish",
    "content.pages.archive",
    "content.articles.read",
    "content.articles.create",
    "content.articles.update",
    "content.articles.publish",
    "content.testimonials.read",
    "content.testimonials.create",
    "content.testimonials.update",
    "content.testimonials.publish",
    "content.media.read",
    "content.media.upload",
    "content.media.update",
    "content.media.delete",
    "content.navigation.read",
    "content.navigation.manage",
    "content.settings.read",
    "content.settings.manage",
    "contact.submissions.read",
    "contact.submissions.assign",
    "contact.submissions.resolve",
    "contact.submissions.export",
}

CATALOG_PERMISSIONS = {
    "catalog.products.read",
    "catalog.products.create",
    "catalog.products.update",
    "catalog.products.review",
    "catalog.products.publish",
    "catalog.products.archive",
    "catalog.skus.read",
    "catalog.skus.create",
    "catalog.skus.update",
    "catalog.skus.activate",
    "catalog.prices.read",
    "catalog.prices.create",
    "catalog.prices.activate",
    "catalog.prices.expire",
    "catalog.price_books.read",
    "catalog.price_books.manage",
    "catalog.inventory.read",
    "catalog.inventory.adjust",
    "catalog.inventory.export",
    "catalog.promotions.read",
    "catalog.promotions.create",
    "catalog.promotions.update",
    "catalog.promotions.activate",
    "catalog.coupons.read",
    "catalog.coupons.create",
    "catalog.coupons.disable",
    "catalog.coupons.export",
    "catalog.pricing.simulate",
    "catalog.audit.read",
}

COMMERCE_PERMISSIONS = {
    "commerce.orders.read",
    "commerce.orders.cancel",
    "commerce.orders.manual_review",
    "commerce.orders.export",
    "commerce.payments.read",
    "commerce.payments.retry",
    "commerce.payments.reconcile",
    "commerce.subscriptions.read",
    "commerce.subscriptions.cancel",
    "commerce.subscriptions.resume",
    "commerce.refunds.read",
    "commerce.refunds.request",
    "commerce.refunds.approve",
    "commerce.refunds.submit",
    "commerce.entitlements.read",
    "commerce.entitlements.retry",
    "commerce.entitlements.suspend",
    "commerce.entitlements.revoke",
    "commerce.webhooks.read",
    "commerce.webhooks.replay",
    "commerce.reconciliation.read",
    "commerce.reconciliation.assign",
    "commerce.reconciliation.resolve",
    "commerce.reconciliation.export",
}

ACTIVITY_PERMISSIONS = {
    "activities.read",
    "activities.create",
    "activities.update",
    "activities.review",
    "activities.publish",
    "activities.cancel",
    "activities.archive",
    "activities.tickets.read",
    "activities.tickets.manage",
    "activities.registrations.read",
    "activities.registrations.review",
    "activities.registrations.cancel",
    "activities.registrations.export",
    "activities.registrations.sensitive.read",
    "activities.waitlist.read",
    "activities.waitlist.manage",
    "activities.waitlist.reorder",
    "activities.checkin.read",
    "activities.checkin.perform",
    "activities.checkin.revoke",
    "activities.groups.read",
    "activities.groups.manage",
    "activities.groups.lock",
    "activities.post_event.read",
    "activities.post_event.manage",
    "activities.post_event.aggregate.read",
    "activities.post_event.sensitive.read",
    "activities.post_event.suspend_match",
    "activities.analytics.read",
    "activities.audit.read",
}

COURSE_PERMISSIONS = {
    "courses.read",
    "courses.create",
    "courses.update",
    "courses.review",
    "courses.publish",
    "courses.unpublish",
    "courses.archive",
    "courses.structure.read",
    "courses.structure.manage",
    "courses.structure.publish_version",
    "courses.instructors.read",
    "courses.instructors.manage",
    "courses.resources.read",
    "courses.resources.upload",
    "courses.resources.manage",
    "courses.video.manage",
    "courses.catalog.read",
    "courses.catalog.manage",
    "courses.enrollments.read",
    "courses.enrollments.grant",
    "courses.enrollments.suspend",
    "courses.enrollments.revoke",
    "courses.enrollments.export",
    "courses.progress.read",
    "courses.progress.reset",
    "courses.progress.export",
    "courses.exercises.read",
    "courses.exercises.manage",
    "courses.exercises.grade",
    "courses.exercises.sensitive.read",
    "courses.certificates.read",
    "courses.certificates.issue",
    "courses.certificates.revoke",
    "courses.certificates.regenerate",
    "courses.analytics.read",
    "courses.audit.read",
}

COUNSELING_PERMISSIONS = {
    "counseling.mentors.read",
    "counseling.mentors.manage",
    "counseling.services.read",
    "counseling.services.manage",
    "counseling.schedules.manage",
    "counseling.appointments.read",
    "counseling.appointments.manage",
    "counseling.sessions.manage",
    "counseling.records.manage",
    "counseling.records.private",
    "counseling.followups.manage",
    "counseling.safety.manage",
}

KNOWLEDGE_PERMISSIONS = {
    "knowledge.spaces.read",
    "knowledge.spaces.manage",
    "knowledge.sources.read",
    "knowledge.sources.manage",
    "knowledge.authorizations.read",
    "knowledge.authorizations.manage",
    "knowledge.authorizations.approve",
    "knowledge.documents.read",
    "knowledge.documents.ingest",
    "knowledge.documents.review",
    "knowledge.documents.publish",
    "knowledge.findings.sensitive.read",
    "knowledge.indexes.read",
    "knowledge.indexes.manage",
    "knowledge.retrieval.debug",
    "knowledge.evaluations.read",
    "knowledge.evaluations.run",
    "knowledge.audit.read",
}

AI_PERMISSIONS = {
    "ai.conversations.read",
    "ai.conversations.sensitive.read",
    "ai.conversations.export",
    "ai.conversations.delete",
    "ai.referrals.read",
    "ai.referrals.assign",
    "ai.referrals.resolve",
    "ai.referrals.safety.read",
    "ai.prompts.read",
    "ai.prompts.create",
    "ai.prompts.update",
    "ai.prompts.approve",
    "ai.prompts.activate",
    "ai.prompts.rollback",
    "ai.models.read",
    "ai.models.manage",
    "ai.model_routes.manage",
    "ai.tools.read",
    "ai.tools.manage",
    "ai.tool_executions.read",
    "ai.tool_executions.replay",
    "ai.evaluations.read",
    "ai.evaluations.manage",
    "ai.evaluations.run",
    "ai.evaluations.approve",
    "ai.feedback.read",
    "ai.feedback.resolve",
    "ai.incidents.read",
    "ai.incidents.manage",
    "ai.audit.read",
}

NOTIFICATION_PERMISSIONS = {
    "notifications.templates.read",
    "notifications.templates.create",
    "notifications.templates.update",
    "notifications.templates.approve",
    "notifications.templates.activate",
    "notifications.templates.rollback",
    "notifications.templates.test_send",
    "notifications.subscriptions.read",
    "notifications.subscriptions.manage",
    "notifications.deliveries.read",
    "notifications.deliveries.content.read",
    "notifications.deliveries.retry",
    "notifications.deliveries.cancel",
    "notifications.reminders.read",
    "notifications.reminders.manage",
    "notifications.reminders.cancel",
    "notifications.campaigns.read",
    "notifications.campaigns.create",
    "notifications.campaigns.update",
    "notifications.campaigns.approve",
    "notifications.campaigns.schedule",
    "notifications.campaigns.start",
    "notifications.campaigns.pause",
    "notifications.campaigns.cancel",
    "notifications.providers.read",
    "notifications.providers.manage",
    "notifications.suppressions.read",
    "notifications.suppressions.create",
    "notifications.suppressions.lift",
    "notifications.dead_letters.read",
    "notifications.dead_letters.resolve",
    "notifications.analytics.read",
    "notifications.audit.read",
}

PRIVACY_PERMISSIONS = {
    "privacy.profile.read",
    "privacy.profile.update",
    "privacy.consents.read",
    "privacy.consents.manage",
    "privacy.consent_releases.create",
    "privacy.consent_releases.approve",
    "privacy.consent_releases.activate",
    "privacy.requests.read",
    "privacy.requests.assign",
    "privacy.requests.verify_identity",
    "privacy.requests.approve",
    "privacy.requests.reject",
    "privacy.exports.read",
    "privacy.exports.generate",
    "privacy.exports.download",
    "privacy.corrections.read",
    "privacy.corrections.review",
    "privacy.corrections.execute",
    "privacy.erasures.read",
    "privacy.erasures.plan",
    "privacy.erasures.approve",
    "privacy.erasures.execute",
    "privacy.erasures.verify",
    "privacy.inventory.read",
    "privacy.inventory.manage",
    "privacy.classifications.read",
    "privacy.classifications.manage",
    "privacy.retention.read",
    "privacy.retention.manage",
    "privacy.retention.execute",
    "privacy.holds.read",
    "privacy.holds.create",
    "privacy.holds.release",
    "privacy.break_glass.read",
    "privacy.break_glass.request",
    "privacy.break_glass.approve",
    "privacy.break_glass.use",
    "privacy.sensitive_access.read",
    "privacy.incidents.read",
    "privacy.incidents.manage",
    "privacy.audit.read",
}

MATCHMAKING_PROFILE_PERMISSIONS = {
    "matchmaking.profiles.read",
    "matchmaking.profiles.sensitive.read",
    "matchmaking.profiles.update",
    "matchmaking.profiles.suspend",
    "matchmaking.profiles.restore",
    "matchmaking.reviews.read",
    "matchmaking.reviews.assign",
    "matchmaking.reviews.decide",
    "matchmaking.reviews.escalate",
    "matchmaking.photos.read",
    "matchmaking.photos.original.read",
    "matchmaking.photos.review",
    "matchmaking.preferences.read",
    "matchmaking.preferences.sensitive.read",
    "matchmaking.schemas.read",
    "matchmaking.schemas.manage",
    "matchmaking.schemas.activate",
    "matchmaking.taxonomies.read",
    "matchmaking.taxonomies.manage",
    "matchmaking.completeness.read",
    "matchmaking.completeness.manage",
    "matchmaking.projections.read",
    "matchmaking.projections.rebuild",
    "matchmaking.analytics.read",
    "matchmaking.audit.read",
}

RECOMMENDATION_PERMISSIONS = {
    "recommendations.strategies.read",
    "recommendations.strategies.create",
    "recommendations.strategies.update",
    "recommendations.strategies.approve",
    "recommendations.strategies.activate",
    "recommendations.strategies.rollback",
    "recommendations.features.read",
    "recommendations.features.manage",
    "recommendations.constraints.read",
    "recommendations.constraints.manage",
    "recommendations.batches.read",
    "recommendations.batches.rebuild",
    "recommendations.batches.invalidate",
    "recommendations.candidates.read",
    "recommendations.candidates.sensitive.read",
    "recommendations.diagnostics.run",
    "recommendations.exposures.read",
    "recommendations.exposures.manage",
    "recommendations.feedback.read",
    "recommendations.feedback.sensitive.read",
    "recommendations.evaluations.read",
    "recommendations.evaluations.manage",
    "recommendations.evaluations.run",
    "recommendations.evaluations.approve",
    "recommendations.experiments.read",
    "recommendations.experiments.create",
    "recommendations.experiments.approve",
    "recommendations.experiments.start",
    "recommendations.experiments.stop",
    "recommendations.analytics.read",
    "recommendations.incidents.read",
    "recommendations.incidents.manage",
    "recommendations.audit.read",
}

ALL_PERMISSIONS = (
    IDENTITY_PERMISSIONS
    | CMS_PERMISSIONS
    | CATALOG_PERMISSIONS
    | COMMERCE_PERMISSIONS
    | ACTIVITY_PERMISSIONS
    | COURSE_PERMISSIONS
    | COUNSELING_PERMISSIONS
    | KNOWLEDGE_PERMISSIONS
    | AI_PERMISSIONS
    | NOTIFICATION_PERMISSIONS
    | PRIVACY_PERMISSIONS
    | MATCHMAKING_PROFILE_PERMISSIONS
    | RECOMMENDATION_PERMISSIONS
)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "super_admin": ALL_PERMISSIONS,
    "platform_admin": ALL_PERMISSIONS - {"admins.restore"},
    "user_manager": {
        "users.read",
        "users.update",
        "users.suspend",
        "users.restore",
        "users.sessions.revoke",
        "roles.read",
    },
    "content_manager": {
        permission
        for permission in CMS_PERMISSIONS
        if not permission.endswith(".publish")
        and permission not in {"content.settings.manage", "contact.submissions.export"}
    },
    "catalog_manager": {
        permission
        for permission in CATALOG_PERMISSIONS
        if permission not in {"catalog.inventory.adjust", "catalog.coupons.export"}
    },
    "order_manager": {
        "catalog.products.read",
        "catalog.skus.read",
        "catalog.prices.read",
        "catalog.inventory.read",
        "catalog.promotions.read",
        "catalog.coupons.read",
        "commerce.orders.read",
        "commerce.orders.cancel",
        "commerce.payments.read",
        "commerce.refunds.read",
        "commerce.refunds.request",
        "commerce.entitlements.read",
    },
    "payment_auditor": {
        "audit.read",
        "commerce.orders.read",
        "commerce.payments.read",
        "commerce.refunds.read",
        "commerce.webhooks.read",
        "commerce.reconciliation.read",
    },
    "finance_manager": {
        permission
        for permission in COMMERCE_PERMISSIONS
        if permission.startswith(
            ("commerce.payments.", "commerce.refunds.", "commerce.reconciliation.")
        )
    }
    | {"commerce.orders.read"},
    "activity_manager": {
        permission
        for permission in ACTIVITY_PERMISSIONS
        if permission
        not in {
            "activities.registrations.sensitive.read",
            "activities.post_event.sensitive.read",
            "activities.registrations.export",
            "activities.checkin.revoke",
        }
    },
    "activity_checkin_staff": {
        "activities.read",
        "activities.registrations.read",
        "activities.checkin.read",
        "activities.checkin.perform",
        "activities.groups.read",
    },
    "course_manager": {
        permission
        for permission in COURSE_PERMISSIONS
        if permission
        not in {
            "courses.enrollments.revoke",
            "courses.enrollments.export",
            "courses.progress.reset",
            "courses.progress.export",
            "courses.exercises.sensitive.read",
            "courses.certificates.revoke",
        }
    },
    "course_grader": {
        "courses.read",
        "courses.enrollments.read",
        "courses.exercises.read",
        "courses.exercises.grade",
    },
    "counseling_manager": COUNSELING_PERMISSIONS - {"counseling.records.private"},
    "counseling_mentor": {
        "counseling.mentors.read",
        "counseling.services.read",
        "counseling.appointments.read",
        "counseling.appointments.manage",
        "counseling.sessions.manage",
        "counseling.records.manage",
        "counseling.records.private",
        "counseling.followups.manage",
        "counseling.safety.manage",
    },
    "counseling_scheduler": {
        "counseling.mentors.read",
        "counseling.services.read",
        "counseling.schedules.manage",
        "counseling.appointments.read",
        "counseling.appointments.manage",
    },
    "ai_knowledge_manager": KNOWLEDGE_PERMISSIONS
    - {"knowledge.authorizations.approve", "knowledge.findings.sensitive.read"}
    | {"ai.evaluations.read"},
    "ai_operations_manager": {
        "ai.conversations.read",
        "ai.referrals.read",
        "ai.referrals.assign",
        "ai.prompts.read",
        "ai.models.read",
        "ai.tools.read",
        "ai.tool_executions.read",
        "ai.evaluations.read",
        "ai.feedback.read",
        "ai.feedback.resolve",
        "ai.audit.read",
    },
    "ai_safety_reviewer": {
        "ai.conversations.read",
        "ai.conversations.sensitive.read",
        "ai.referrals.read",
        "ai.referrals.assign",
        "ai.referrals.resolve",
        "ai.referrals.safety.read",
        "ai.incidents.read",
        "ai.incidents.manage",
        "ai.evaluations.read",
    },
    "ai_release_manager": {
        permission
        for permission in AI_PERMISSIONS
        if permission.startswith("ai.prompts.") or permission.startswith("ai.evaluations.")
    }
    | {
        "ai.models.read",
        "ai.model_routes.manage",
        "ai.tools.read",
        "ai.audit.read",
    },
    "notification_manager": (
        {
            permission
            for permission in NOTIFICATION_PERMISSIONS
            if permission.startswith("notifications.templates.")
            or permission.startswith("notifications.subscriptions.")
            or permission.startswith("notifications.reminders.")
            or permission.startswith("notifications.dead_letters.")
        }
        - {"notifications.templates.approve"}
    )
    | {
        "notifications.deliveries.read",
        "notifications.deliveries.retry",
        "notifications.campaigns.read",
        "notifications.campaigns.create",
        "notifications.campaigns.update",
        "notifications.campaigns.schedule",
        "notifications.campaigns.start",
        "notifications.campaigns.pause",
        "notifications.campaigns.cancel",
        "notifications.providers.read",
        "notifications.suppressions.read",
        "notifications.analytics.read",
        "notifications.audit.read",
    },
    "campaign_editor": {
        "notifications.templates.read",
        "notifications.campaigns.read",
        "notifications.campaigns.create",
        "notifications.campaigns.update",
        "notifications.analytics.read",
    },
    "notification_support": {
        "notifications.deliveries.read",
        "notifications.dead_letters.read",
        "notifications.dead_letters.resolve",
        "notifications.suppressions.read",
    },
    "privacy_manager": {
        permission
        for permission in PRIVACY_PERMISSIONS
        if permission.startswith(("privacy.requests.", "privacy.exports.", "privacy.corrections."))
    }
    | {
        "privacy.erasures.read",
        "privacy.erasures.plan",
        "privacy.inventory.read",
        "privacy.retention.read",
        "privacy.consents.read",
        "privacy.audit.read",
    },
    "privacy_rights_reviewer": {
        "privacy.requests.read",
        "privacy.requests.assign",
        "privacy.requests.verify_identity",
        "privacy.requests.approve",
        "privacy.requests.reject",
        "privacy.exports.read",
        "privacy.corrections.read",
        "privacy.corrections.review",
        "privacy.corrections.execute",
        "privacy.audit.read",
    },
    "privacy_security_officer": {
        permission
        for permission in PRIVACY_PERMISSIONS
        if permission.startswith(
            (
                "privacy.holds.",
                "privacy.break_glass.",
                "privacy.incidents.",
            )
        )
    }
    | {"privacy.sensitive_access.read", "privacy.audit.read"},
    "privacy_data_steward": {
        permission
        for permission in PRIVACY_PERMISSIONS
        if permission.startswith(
            ("privacy.inventory.", "privacy.classifications.", "privacy.retention.")
        )
    }
    | {"privacy.audit.read"},
    "knowledge_rights_approver": {
        "knowledge.sources.read",
        "knowledge.authorizations.read",
        "knowledge.authorizations.approve",
        "knowledge.audit.read",
    },
    "knowledge_reviewer": {
        "knowledge.spaces.read",
        "knowledge.sources.read",
        "knowledge.documents.read",
        "knowledge.documents.review",
        "knowledge.findings.sensitive.read",
        "knowledge.indexes.read",
        "knowledge.retrieval.debug",
        "knowledge.evaluations.read",
    },
    "profile_reviewer": {
        "matchmaking.profiles.read",
        "matchmaking.reviews.read",
        "matchmaking.reviews.assign",
        "matchmaking.reviews.decide",
        "matchmaking.photos.read",
        "matchmaking.photos.review",
        "matchmaking.audit.read",
    },
    "profile_review_lead": {
        "matchmaking.profiles.read",
        "matchmaking.profiles.sensitive.read",
        "matchmaking.profiles.suspend",
        "matchmaking.profiles.restore",
        "matchmaking.reviews.read",
        "matchmaking.reviews.assign",
        "matchmaking.reviews.decide",
        "matchmaking.reviews.escalate",
        "matchmaking.photos.read",
        "matchmaking.photos.review",
        "matchmaking.audit.read",
    },
    "matchmaking_data_steward": {
        permission
        for permission in MATCHMAKING_PROFILE_PERMISSIONS
        if permission.startswith(
            (
                "matchmaking.schemas.",
                "matchmaking.taxonomies.",
                "matchmaking.completeness.",
                "matchmaking.projections.",
            )
        )
    }
    | {"matchmaking.audit.read"},
    "recommendation_operator": {
        "recommendations.strategies.read",
        "recommendations.features.read",
        "recommendations.constraints.read",
        "recommendations.batches.read",
        "recommendations.batches.rebuild",
        "recommendations.candidates.read",
        "recommendations.diagnostics.run",
        "recommendations.exposures.read",
        "recommendations.feedback.read",
        "recommendations.evaluations.read",
        "recommendations.analytics.read",
        "recommendations.audit.read",
    },
    "recommendation_data_scientist": {
        "recommendations.strategies.read",
        "recommendations.strategies.create",
        "recommendations.strategies.update",
        "recommendations.features.read",
        "recommendations.features.manage",
        "recommendations.constraints.read",
        "recommendations.evaluations.read",
        "recommendations.evaluations.manage",
        "recommendations.evaluations.run",
        "recommendations.experiments.read",
        "recommendations.experiments.create",
        "recommendations.analytics.read",
    },
    "recommendation_release_manager": {
        permission
        for permission in RECOMMENDATION_PERMISSIONS
        if permission.startswith(("recommendations.strategies.", "recommendations.experiments."))
    }
    | {
        "recommendations.evaluations.read",
        "recommendations.evaluations.approve",
        "recommendations.audit.read",
    },
    "analyst": {"audit.read", "catalog.audit.read"},
    "support_agent": {"users.read", "catalog.products.read"},
    "member": set(),
}


def require_permission(
    permission: str,
) -> Callable[..., Coroutine[Any, Any, AuthenticatedPrincipal]]:
    async def dependency(
        principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    ) -> AuthenticatedPrincipal:
        principal.require(permission)
        return principal

    return dependency
