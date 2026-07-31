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

ALL_PERMISSIONS = (
    IDENTITY_PERMISSIONS
    | CMS_PERMISSIONS
    | CATALOG_PERMISSIONS
    | COMMERCE_PERMISSIONS
    | ACTIVITY_PERMISSIONS
    | COURSE_PERMISSIONS
    | COUNSELING_PERMISSIONS
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
