from enum import StrEnum


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    LOCKED = "locked"
    SUSPENDED = "suspended"
    DELETION_PENDING = "deletion_pending"
    DELETED = "deleted"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    REPLACED = "replaced"
    REVOKED = "revoked"
    EXPIRED = "expired"


class Audience(StrEnum):
    USER = "vav-user"
    ADMIN = "vav-admin"


ADMIN_PERMISSION_PREFIXES = (
    "users.",
    "roles.",
    "admins.",
    "audit.",
    "content.",
    "contact.",
    "catalog.",
)
