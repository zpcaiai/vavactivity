# ruff: noqa: B008

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.models.identity import (
    AdminInvitation,
    AuthSession,
    Permission,
    Role,
    RolePermission,
    SecurityAuditEvent,
    User,
    UserRole,
)
from vav.modules.identity.abuse import enforce_rate_limit
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.dependencies import (
    AuthenticatedPrincipal,
    ensure_not_self,
    request_fingerprint,
    require_admin_principal,
    require_authenticated_user,
    require_csrf,
)
from vav.modules.identity.domain import SessionStatus, UserStatus
from vav.modules.identity.email import EmailService
from vav.modules.identity.permissions import require_permission
from vav.modules.identity.schemas import (
    AdminInvitationAcceptRequest,
    AdminInvitationRequest,
    EmailRequest,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    ReasonRequest,
    RegisterRequest,
    RoleChangeRequest,
    TokenConfirmRequest,
)
from vav.modules.identity.security import opaque_token, privacy_hash, sha256_token
from vav.modules.identity.service import AuthResult, IdentityService

router = APIRouter()
identity_service = IdentityService()
email_service = EmailService()


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _set_session_cookies(
    response: Response, result: AuthResult, *, audience: Literal["user", "admin"]
) -> None:
    settings = get_settings()
    cookie_name = "vav_admin_refresh" if audience == "admin" else "vav_user_refresh"
    path = "/api/v1/admin/auth" if audience == "admin" else "/api/v1/auth"
    same_site: Literal["lax", "strict"] = "strict" if audience == "admin" else "lax"
    response.set_cookie(
        cookie_name,
        result.refresh_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=same_site,
        path=path,
        domain=settings.auth_cookie_domain,
        max_age=(
            settings.auth_admin_refresh_token_ttl_hours * 3600
            if audience == "admin"
            else settings.auth_refresh_token_ttl_days * 86400
        ),
    )
    csrf_cookie_name = "vav_admin_csrf" if audience == "admin" else "vav_user_csrf"
    response.set_cookie(
        csrf_cookie_name,
        result.csrf_token,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite=same_site,
        path="/",
        domain=settings.auth_cookie_domain,
    )


def _clear_session_cookies(response: Response, *, audience: Literal["user", "admin"]) -> None:
    settings = get_settings()
    cookie_name = "vav_admin_refresh" if audience == "admin" else "vav_user_refresh"
    path = "/api/v1/admin/auth" if audience == "admin" else "/api/v1/auth"
    response.delete_cookie(cookie_name, path=path, domain=settings.auth_cookie_domain)
    csrf_cookie_name = "vav_admin_csrf" if audience == "admin" else "vav_user_csrf"
    response.delete_cookie(csrf_cookie_name, path="/", domain=settings.auth_cookie_domain)


def _auth_payload(result: AuthResult) -> dict[str, Any]:
    return {
        "access_token": result.access_token,
        "token_type": "Bearer",
        "expires_in": result.expires_in,
        "user": {
            "id": str(result.user.id),
            "email": result.user.display_email,
            "status": result.user.status,
            "email_verified": result.user.email_verified_at is not None,
            "preferred_locale": result.user.preferred_locale,
            "timezone": result.user.timezone,
            "permissions": result.permissions,
        },
    }


async def _send_verification(user: User, raw_token: str) -> None:
    settings = get_settings()
    link = f"{settings.user_web_url}/{user.preferred_locale}/auth/verify-email?token={raw_token}"
    await email_service.send_link(
        recipient=user.display_email,
        subject="Verify your VAV email",
        title="Verify your VAV email",
        link=link,
    )


@router.post("/auth/register", status_code=status.HTTP_202_ACCEPTED)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    ip_hash, _ = request_fingerprint(request)
    await enforce_rate_limit(f"rate:register:ip:{ip_hash}", limit=5, window_seconds=3600)
    user, raw_token = await identity_service.register(
        session,
        email=str(payload.email),
        password=payload.password,
        preferred_locale=payload.preferred_locale,
        timezone=payload.timezone,
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
    )
    if raw_token:
        await _send_verification(user, raw_token)
    return success(
        {
            "registration_status": (
                "verification_required" if user.email_verified_at is None else "active"
            ),
            "email": _mask_email(str(payload.email)),
        },
        request_id_from_request(request),
    )


@router.post("/auth/email-verification/send", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    payload: EmailRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    email_hash = privacy_hash(str(payload.email))
    await enforce_rate_limit(f"rate:verify-email:email:{email_hash}", limit=1, window_seconds=60)
    created = await identity_service.create_verification_token(session, str(payload.email))
    if created:
        await _send_verification(*created)
    return success(
        {"message": "If the account is eligible, a verification email will be sent."},
        request_id_from_request(request),
    )


@router.post("/auth/email-verification/confirm")
async def confirm_verification(
    payload: TokenConfirmRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    user = await identity_service.confirm_email(session, payload.token)
    return success(
        {"status": "verified", "email": _mask_email(user.display_email)},
        request_id_from_request(request),
    )


async def _login(
    *,
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession,
    audience: Literal["user", "admin"],
) -> dict[str, Any]:
    settings = get_settings()
    ip_hash, user_agent_hash = request_fingerprint(request)
    ip_limit = 5 if audience == "admin" else 10
    ip_window = 900 if audience == "admin" else 60
    await enforce_rate_limit(
        f"rate:{'admin-' if audience == 'admin' else ''}login:ip:{ip_hash}",
        limit=ip_limit,
        window_seconds=ip_window,
    )
    await enforce_rate_limit(
        f"rate:login:email:{privacy_hash(str(payload.email))}",
        limit=5,
        window_seconds=900,
    )
    result = await identity_service.login(
        session,
        email=str(payload.email),
        password=payload.password,
        device_name=payload.device_name,
        audience=(
            settings.auth_admin_audience if audience == "admin" else settings.auth_user_audience
        ),
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    _set_session_cookies(response, result, audience=audience)
    return success(_auth_payload(result), request_id_from_request(request))


@router.post("/auth/login")
async def user_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _login(
        payload=payload,
        request=request,
        response=response,
        session=session,
        audience="user",
    )


@router.post("/admin/auth/login")
async def admin_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _login(
        payload=payload,
        request=request,
        response=response,
        session=session,
        audience="admin",
    )


async def _refresh(
    *,
    request: Request,
    response: Response,
    session: AsyncSession,
    audience: Literal["user", "admin"],
) -> dict[str, Any]:
    require_csrf(request, audience=audience)
    settings = get_settings()
    cookie_name = "vav_admin_refresh" if audience == "admin" else "vav_user_refresh"
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        raise VavError("AUTH_SESSION_INVALID", "Session is invalid.", status_code=401)
    await enforce_rate_limit(
        f"rate:refresh:token:{privacy_hash(raw_token)}", limit=30, window_seconds=60
    )
    result = await identity_service.refresh(
        session,
        raw_refresh_token=raw_token,
        audience=(
            settings.auth_admin_audience if audience == "admin" else settings.auth_user_audience
        ),
    )
    _set_session_cookies(response, result, audience=audience)
    return success(_auth_payload(result), request_id_from_request(request))


@router.post("/auth/refresh")
async def user_refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _refresh(request=request, response=response, session=session, audience="user")


@router.post("/admin/auth/refresh")
async def admin_refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _refresh(request=request, response=response, session=session, audience="admin")


async def _me(principal: AuthenticatedPrincipal, request: Request) -> dict[str, Any]:
    return success(
        {
            "id": str(principal.user.id),
            "email": principal.user.display_email,
            "status": principal.user.status,
            "email_verified": principal.user.email_verified_at is not None,
            "preferred_locale": principal.user.preferred_locale,
            "timezone": principal.user.timezone,
            "permissions": sorted(principal.permissions),
        },
        request_id_from_request(request),
    )


@router.get("/auth/me")
async def user_me(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
) -> dict[str, Any]:
    return await _me(principal, request)


@router.get("/admin/auth/me")
async def admin_me(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
) -> dict[str, Any]:
    return await _me(principal, request)


async def _list_sessions(
    principal: AuthenticatedPrincipal,
    request: Request,
    session: AsyncSession,
) -> dict[str, Any]:
    items = (
        await session.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == principal.user.id,
                AuthSession.audience == principal.audience,
                AuthSession.status == SessionStatus.ACTIVE,
            )
            .order_by(AuthSession.issued_at.desc())
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "device_name": item.device_name,
                    "issued_at": item.issued_at.isoformat(),
                    "last_used_at": (item.last_used_at.isoformat() if item.last_used_at else None),
                    "expires_at": item.expires_at.isoformat(),
                    "current": item.id == principal.session.id,
                }
                for item in items
            ]
        },
        request_id_from_request(request),
    )


@router.get("/auth/sessions")
async def user_sessions(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _list_sessions(principal, request, session)


@router.get("/admin/auth/sessions")
async def admin_sessions(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _list_sessions(principal, request, session)


async def _revoke_session(
    session_id: UUID,
    principal: AuthenticatedPrincipal,
    request: Request,
    session: AsyncSession,
) -> dict[str, Any]:
    target = await session.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == principal.user.id,
            AuthSession.audience == principal.audience,
        )
        .with_for_update()
    )
    if target is None:
        raise VavError("SESSION_NOT_FOUND", "Session was not found.", status_code=404)
    if target.status == SessionStatus.ACTIVE:
        target.status = SessionStatus.REVOKED
        target.revoked_at = datetime.now(UTC)
        target.revoke_reason = "user_revoked"
        record_security_event(
            session,
            event_type="auth.session.revoked",
            actor_type="user",
            actor_user_id=principal.user.id,
            actor_session_id=principal.session.id,
            target_type="session",
            target_id=target.id,
        )
        await session.commit()
    return success({"status": "revoked"}, request_id_from_request(request))


@router.delete("/auth/sessions/{session_id}")
async def revoke_user_session(
    session_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _revoke_session(session_id, principal, request, session)


@router.delete("/admin/auth/sessions/{session_id}")
async def revoke_admin_session(
    session_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _revoke_session(session_id, principal, request, session)


async def _logout(
    *,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
    audience: Literal["user", "admin"],
) -> dict[str, Any]:
    require_csrf(request, audience=audience)
    principal.session.status = SessionStatus.REVOKED
    principal.session.revoked_at = datetime.now(UTC)
    principal.session.revoke_reason = "logout"
    record_security_event(
        session,
        event_type="auth.session.revoked",
        actor_type="user",
        actor_user_id=principal.user.id,
        actor_session_id=principal.session.id,
        target_type="session",
        target_id=principal.session.id,
    )
    await session.commit()
    _clear_session_cookies(response, audience=audience)
    return success({"status": "logged_out"}, request_id_from_request(request))


@router.post("/auth/logout")
async def user_logout(
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _logout(
        request=request,
        response=response,
        principal=principal,
        session=session,
        audience="user",
    )


@router.post("/admin/auth/logout")
async def admin_logout(
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _logout(
        request=request,
        response=response,
        principal=principal,
        session=session,
        audience="admin",
    )


@router.post("/auth/logout-all")
async def logout_all(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await identity_service.revoke_all(session, principal.user.id, "logout_all")
    return success({"status": "all_sessions_revoked"}, request_id_from_request(request))


@router.post("/auth/password/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    payload: EmailRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    email_hash = privacy_hash(str(payload.email))
    await enforce_rate_limit(
        f"rate:forgot-password:email:{email_hash}", limit=5, window_seconds=3600
    )
    created = await identity_service.request_password_reset(session, str(payload.email))
    if created:
        user, raw_token = created
        link = (
            f"{get_settings().user_web_url}/{user.preferred_locale}"
            f"/auth/reset-password?token={raw_token}"
        )
        await email_service.send_link(
            recipient=user.display_email,
            subject="Reset your VAV password",
            title="Reset your VAV password",
            link=link,
        )
    return success(
        {"message": "If the account is eligible, a reset email will be sent."},
        request_id_from_request(request),
    )


@router.post("/auth/password/reset")
async def reset_password(
    payload: PasswordResetRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await identity_service.reset_password(
        session, raw_token=payload.token, new_password=payload.new_password
    )
    return success({"status": "password_reset"}, request_id_from_request(request))


@router.post("/auth/password/change")
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await identity_service.change_password(
        session,
        user=principal.user,
        current_session_id=principal.session.id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return success({"status": "password_changed"}, request_id_from_request(request))


@router.get(
    "/admin/users",
    dependencies=[Depends(require_permission("users.read"))],
)
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    users = (
        await session.scalars(
            select(User)
            .order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(user.id),
                    "email": user.display_email,
                    "status": user.status,
                    "email_verified": user.email_verified_at is not None,
                    "created_at": user.created_at.isoformat(),
                }
                for user in users
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
        request_id_from_request(request),
    )


async def _change_user_status(
    *,
    target_id: UUID,
    target_status: UserStatus,
    event_type: str,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    ensure_not_self(principal, target_id)
    target = await session.get(User, target_id, with_for_update=True)
    if target is None:
        raise VavError("USER_NOT_FOUND", "User was not found.", status_code=404)
    before = target.status
    target.status = target_status
    target.auth_version += 1
    if target_status == UserStatus.ACTIVE:
        target.locked_until = None
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == target.id, AuthSession.status == SessionStatus.ACTIVE)
        .values(
            status=SessionStatus.REVOKED,
            revoked_at=datetime.now(UTC),
            revoke_reason=event_type,
        )
    )
    record_security_event(
        session,
        event_type=event_type,
        severity="warning",
        actor_type="admin",
        actor_user_id=principal.user.id,
        actor_session_id=principal.session.id,
        target_type="user",
        target_id=target.id,
        reason=payload.reason,
        before_state={"status": before},
        after_state={"status": target.status},
    )
    await session.commit()
    return success({"status": target.status}, request_id_from_request(request))


@router.post("/admin/users/{user_id}/suspend")
async def suspend_user(
    user_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("users.suspend")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _change_user_status(
        target_id=user_id,
        target_status=UserStatus.SUSPENDED,
        event_type="user.account.suspended",
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/users/{user_id}/restore")
async def restore_user(
    user_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("users.restore")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _change_user_status(
        target_id=user_id,
        target_status=UserStatus.ACTIVE,
        event_type="user.account.restored",
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/admin/roles")
async def list_roles(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("roles.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    roles = (await session.scalars(select(Role).order_by(Role.code))).all()
    return success(
        {
            "items": [
                {
                    "id": str(role.id),
                    "code": role.code,
                    "name": role.name,
                    "is_system": role.is_system,
                    "is_active": role.is_active,
                }
                for role in roles
            ]
        },
        request_id_from_request(request),
    )


async def _role_permission_codes(session: AsyncSession, role_id: UUID) -> set[str]:
    return set(
        (
            await session.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id)
            )
        ).all()
    )


@router.post("/admin/users/{user_id}/roles")
async def assign_role(
    user_id: UUID,
    payload: RoleChangeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("roles.assign")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    role = await session.scalar(select(Role).where(Role.code == payload.role_code))
    target = await session.get(User, user_id, with_for_update=True)
    if role is None or target is None or not role.is_active:
        raise VavError("ROLE_OR_USER_NOT_FOUND", "Role or user was not found.", status_code=404)
    role_permissions = await _role_permission_codes(session, role.id)
    if not role_permissions.issubset(principal.permissions):
        raise VavError(
            "PRIVILEGE_ESCALATION_BLOCKED",
            "You cannot grant permissions you do not hold.",
            status_code=403,
        )
    assignment = await session.get(UserRole, (user_id, role.id), with_for_update=True)
    if assignment is None:
        assignment = UserRole(
            user_id=user_id,
            role_id=role.id,
            granted_by=principal.user.id,
            grant_reason=payload.reason,
            expires_at=payload.expires_at,
        )
        session.add(assignment)
    else:
        assignment.revoked_at = None
        assignment.revoked_by = None
        assignment.revoke_reason = None
        assignment.granted_by = principal.user.id
        assignment.grant_reason = payload.reason
        assignment.granted_at = datetime.now(UTC)
        assignment.expires_at = payload.expires_at
    target.rbac_version += 1
    record_security_event(
        session,
        event_type="rbac.role.assigned",
        actor_type="admin",
        actor_user_id=principal.user.id,
        actor_session_id=principal.session.id,
        target_type="user",
        target_id=user_id,
        reason=payload.reason,
        after_state={"role": role.code},
    )
    await session.commit()
    return success({"status": "assigned"}, request_id_from_request(request))


@router.delete("/admin/users/{user_id}/roles/{role_code}")
async def revoke_role(
    user_id: UUID,
    role_code: str,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("roles.revoke")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if user_id == principal.user.id:
        raise VavError(
            "SELF_ROLE_REVOCATION_FORBIDDEN",
            "Administrators cannot revoke their own role.",
            status_code=409,
        )
    role = await session.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        raise VavError("ROLE_NOT_FOUND", "Role was not found.", status_code=404)
    assignment = await session.get(UserRole, (user_id, role.id), with_for_update=True)
    if assignment is None or assignment.revoked_at is not None:
        raise VavError(
            "ROLE_ASSIGNMENT_NOT_FOUND", "Role assignment was not found.", status_code=404
        )
    if role.code == "super_admin":
        active_count = await session.scalar(
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(
                UserRole.role_id == role.id,
                UserRole.revoked_at.is_(None),
                User.status == UserStatus.ACTIVE,
            )
        )
        if int(active_count or 0) <= 1:
            raise VavError(
                "LAST_SUPER_ADMIN_PROTECTED",
                "The last active super administrator cannot be removed.",
                status_code=409,
            )
    assignment.revoked_at = datetime.now(UTC)
    assignment.revoked_by = principal.user.id
    assignment.revoke_reason = payload.reason
    target = await session.get(User, user_id, with_for_update=True)
    if target is not None:
        target.rbac_version += 1
    record_security_event(
        session,
        event_type="rbac.role.revoked",
        actor_type="admin",
        actor_user_id=principal.user.id,
        actor_session_id=principal.session.id,
        target_type="user",
        target_id=user_id,
        reason=payload.reason,
        before_state={"role": role.code},
    )
    await session.commit()
    return success({"status": "revoked"}, request_id_from_request(request))


@router.post("/admin/admins/invitations", status_code=201)
async def invite_admin(
    payload: AdminInvitationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admins.invite")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    roles = (
        await session.scalars(
            select(Role).where(Role.code.in_(payload.role_codes), Role.is_active.is_(True))
        )
    ).all()
    if len(roles) != len(set(payload.role_codes)):
        raise VavError("ROLE_NOT_FOUND", "One or more roles were not found.", status_code=404)
    requested_permissions: set[str] = set()
    for role in roles:
        requested_permissions |= await _role_permission_codes(session, role.id)
    if not requested_permissions.issubset(principal.permissions):
        raise VavError(
            "PRIVILEGE_ESCALATION_BLOCKED",
            "You cannot invite an administrator with permissions you do not hold.",
            status_code=403,
        )
    raw_token = opaque_token()
    invitation = AdminInvitation(
        id=uuid4(),
        email=str(payload.email).strip().casefold(),
        token_hash=sha256_token(raw_token),
        proposed_role_ids=[str(role.id) for role in roles],
        invited_by=principal.user.id,
        reason=payload.reason,
        expires_at=datetime.now(UTC) + timedelta(hours=48),
    )
    session.add(invitation)
    record_security_event(
        session,
        event_type="admin.invitation.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        actor_session_id=principal.session.id,
        target_type="admin_invitation",
        target_id=invitation.id,
        reason=payload.reason,
        metadata={"roles": sorted(payload.role_codes)},
    )
    await session.commit()
    link = f"{get_settings().admin_web_url}/admin/accept-invitation?token={raw_token}"
    await email_service.send_link(
        recipient=str(payload.email),
        subject="VAV administrator invitation",
        title="Accept your VAV administrator invitation",
        link=link,
    )
    return success(
        {"id": str(invitation.id), "status": "pending"},
        request_id_from_request(request),
    )


@router.get("/admin/admins/invitations")
async def list_invitations(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AuthenticatedPrincipal = Depends(require_permission("admins.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count()).select_from(AdminInvitation)) or 0)
    invitations = (
        await session.scalars(
            select(AdminInvitation)
            .order_by(AdminInvitation.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "email": _mask_email(item.email),
                    "expires_at": item.expires_at.isoformat(),
                    "accepted_at": item.accepted_at.isoformat() if item.accepted_at else None,
                    "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
                }
                for item in invitations
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
        request_id_from_request(request),
    )


@router.post("/admin/admins/invitations/{invitation_id}/revoke")
async def revoke_invitation(
    invitation_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admins.invite")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    invitation = await session.get(AdminInvitation, invitation_id, with_for_update=True)
    if invitation is None:
        raise VavError("INVITATION_NOT_FOUND", "Invitation was not found.", status_code=404)
    if invitation.accepted_at is not None:
        raise VavError(
            "INVITATION_ALREADY_ACCEPTED", "Invitation is already accepted.", status_code=409
        )
    invitation.revoked_at = datetime.now(UTC)
    record_security_event(
        session,
        event_type="admin.invitation.revoked",
        actor_type="admin",
        actor_user_id=principal.user.id,
        actor_session_id=principal.session.id,
        target_type="admin_invitation",
        target_id=invitation.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": "revoked"}, request_id_from_request(request))


@router.post("/admin/admins/invitations/accept")
async def accept_invitation(
    payload: AdminInvitationAcceptRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    invitation = await session.scalar(
        select(AdminInvitation)
        .where(AdminInvitation.token_hash == sha256_token(payload.token))
        .with_for_update()
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
    ):
        raise VavError("INVITATION_INVALID", "Invitation is invalid.", status_code=400)
    identity_service.password_policy.validate(payload.password, invitation.email)
    user = await session.scalar(
        select(User).where(User.email == invitation.email).with_for_update()
    )
    if user is None:
        user = User(
            id=uuid4(),
            email=invitation.email,
            display_email=invitation.email,
            password_hash=identity_service.password_hasher.hash(payload.password),
            status=UserStatus.ACTIVE,
            email_verified_at=now,
            preferred_locale=payload.preferred_locale,
            timezone=payload.timezone,
            terms_version=payload.terms_version,
            terms_accepted_at=now,
            privacy_version=payload.privacy_version,
            privacy_accepted_at=now,
        )
        session.add(user)
    elif user.status in {UserStatus.SUSPENDED, UserStatus.DELETED}:
        raise VavError("INVITATION_INVALID", "Invitation is invalid.", status_code=400)
    else:
        user.email_verified_at = user.email_verified_at or now
        user.status = UserStatus.ACTIVE
    await session.flush()
    for role_id_text in invitation.proposed_role_ids:
        role_id = UUID(role_id_text)
        existing = await session.get(UserRole, (user.id, role_id))
        if existing is None:
            session.add(
                UserRole(
                    user_id=user.id,
                    role_id=role_id,
                    granted_by=invitation.invited_by,
                    grant_reason=f"Accepted administrator invitation {invitation.id}",
                )
            )
        else:
            existing.revoked_at = None
            existing.revoked_by = None
            existing.revoke_reason = None
    user.rbac_version += 1
    invitation.accepted_at = now
    record_security_event(
        session,
        event_type="admin.invitation.accepted",
        actor_type="user",
        actor_user_id=user.id,
        target_type="admin_invitation",
        target_id=invitation.id,
    )
    await session.commit()
    return success({"status": "accepted"}, request_id_from_request(request))


@router.get("/admin/admins")
async def list_admins(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AuthenticatedPrincipal = Depends(require_permission("admins.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    filters = (UserRole.revoked_at.is_(None), Role.code != "member")
    total = int(
        await session.scalar(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(*filters)
        )
        or 0
    )
    statement = (
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(*filters)
        .distinct()
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    admins = (await session.scalars(statement)).all()
    return success(
        {
            "items": [
                {"id": str(admin.id), "email": admin.display_email, "status": admin.status}
                for admin in admins
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
        request_id_from_request(request),
    )


@router.post("/admin/admins/{user_id}/disable")
async def disable_admin(
    user_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admins.disable")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _change_user_status(
        target_id=user_id,
        target_status=UserStatus.SUSPENDED,
        event_type="admin.account.disabled",
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/admins/{user_id}/restore")
async def restore_admin(
    user_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("admins.restore")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _change_user_status(
        target_id=user_id,
        target_status=UserStatus.ACTIVE,
        event_type="admin.account.restored",
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/admin/audit/security-events")
async def list_security_events(
    request: Request,
    event_type: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    statement = select(SecurityAuditEvent)
    count_statement = select(func.count()).select_from(SecurityAuditEvent)
    if event_type:
        statement = statement.where(SecurityAuditEvent.event_type == event_type)
        count_statement = count_statement.where(SecurityAuditEvent.event_type == event_type)
    total = int(await session.scalar(count_statement) or 0)
    events = (
        await session.scalars(
            statement.order_by(SecurityAuditEvent.occurred_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "actor_type": event.actor_type,
                    "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
                    "target_type": event.target_type,
                    "target_id": str(event.target_id) if event.target_id else None,
                    "reason": event.reason,
                    "metadata": event.event_metadata,
                    "occurred_at": event.occurred_at.isoformat(),
                }
                for event in events
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
        request_id_from_request(request),
    )
