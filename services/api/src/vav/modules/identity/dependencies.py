# ruff: noqa: B008

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.identity import AuthSession, User
from vav.modules.identity.domain import SessionStatus, UserStatus
from vav.modules.identity.security import AccessTokenService
from vav.modules.identity.service import permissions_for_user

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user: User
    session: AuthSession
    audience: str
    permissions: frozenset[str]

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise VavError(
                "PERMISSION_DENIED",
                "You do not have permission to perform this action.",
                status_code=403,
            )


async def _authenticate(
    *,
    credentials: HTTPAuthorizationCredentials | None,
    session: AsyncSession,
    audience: str,
) -> AuthenticatedPrincipal:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise VavError("AUTHENTICATION_REQUIRED", "Authentication is required.", status_code=401)
    claims = AccessTokenService().decode(credentials.credentials, audience)
    auth_session = await session.get(AuthSession, claims.session_id)
    user = await session.get(User, claims.user_id)
    if (
        auth_session is None
        or user is None
        or auth_session.user_id != user.id
        or auth_session.audience != audience
        or auth_session.status != SessionStatus.ACTIVE
        or user.status != UserStatus.ACTIVE
        or user.auth_version != claims.auth_version
        or user.rbac_version != claims.rbac_version
    ):
        raise VavError("AUTH_SESSION_INVALID", "Session is invalid.", status_code=401)
    permissions = frozenset(await permissions_for_user(session, user.id))
    return AuthenticatedPrincipal(
        user=user,
        session=auth_session,
        audience=audience,
        permissions=permissions,
    )


async def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_database_session),
) -> AuthenticatedPrincipal:
    return await _authenticate(
        credentials=credentials,
        session=session,
        audience=get_settings().auth_user_audience,
    )


async def require_admin_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_database_session),
) -> AuthenticatedPrincipal:
    principal = await _authenticate(
        credentials=credentials,
        session=session,
        audience=get_settings().auth_admin_audience,
    )
    if not principal.permissions:
        raise VavError(
            "ADMIN_ACCESS_REQUIRED", "Administrator access is required.", status_code=403
        )
    return principal


def require_csrf(request: Request, *, audience: str) -> None:
    settings = get_settings()
    origin = request.headers.get("origin")
    if origin not in settings.auth_allowed_origins:
        raise VavError("ORIGIN_NOT_ALLOWED", "Request origin is not allowed.", status_code=403)
    cookie_name = "vav_admin_csrf" if audience == "admin" else "vav_user_csrf"
    cookie_token = request.cookies.get(cookie_name)
    header_token = request.headers.get("x-csrf-token")
    if not cookie_token or not header_token or cookie_token != header_token:
        raise VavError("CSRF_VALIDATION_FAILED", "CSRF validation failed.", status_code=403)


def request_fingerprint(request: Request) -> tuple[str, str]:
    from vav.modules.identity.security import privacy_hash

    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return privacy_hash(ip), privacy_hash(user_agent)


def ensure_not_self(principal: AuthenticatedPrincipal, target_user_id: UUID) -> None:
    if principal.user.id == target_user_id:
        raise VavError(
            "SELF_GOVERNANCE_FORBIDDEN",
            "This action cannot be performed on your own administrator account.",
            status_code=409,
        )
