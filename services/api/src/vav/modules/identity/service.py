from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import Settings, get_settings
from vav.models.identity import (
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.domain import SessionStatus, UserStatus
from vav.modules.identity.security import (
    AccessTokenService,
    PasswordHasher,
    PasswordPolicy,
    hmac_token,
    opaque_token,
    sha256_token,
)


@dataclass(frozen=True)
class AuthResult:
    access_token: str
    refresh_token: str
    csrf_token: str
    expires_in: int
    user: User
    session: AuthSession
    permissions: list[str]


async def permissions_for_user(session: AsyncSession, user_id: UUID) -> list[str]:
    now = datetime.now(UTC)
    statement = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > now),
            Role.is_active.is_(True),
        )
        .distinct()
        .order_by(Permission.code)
    )
    return list((await session.scalars(statement)).all())


async def roles_for_user(session: AsyncSession, user_id: UUID) -> list[str]:
    now = datetime.now(UTC)
    statement = (
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > now),
            Role.is_active.is_(True),
        )
        .distinct()
        .order_by(Role.code)
    )
    return list((await session.scalars(statement)).all())


class IdentityService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.password_policy = PasswordPolicy(self.settings)
        self.password_hasher = PasswordHasher(self.settings)
        self.token_service = AccessTokenService(self.settings)

    async def register(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        preferred_locale: str,
        timezone: str,
        terms_version: str,
        privacy_version: str,
    ) -> tuple[User, str | None]:
        normalized_email = email.strip().casefold()
        self.password_policy.validate(password, normalized_email)
        existing = await session.scalar(select(User).where(User.email == normalized_email))
        if existing is not None:
            return existing, None
        now = datetime.now(UTC)
        user = User(
            id=uuid4(),
            email=normalized_email,
            display_email=email.strip(),
            password_hash=self.password_hasher.hash(password),
            status=UserStatus.PENDING_VERIFICATION,
            preferred_locale=preferred_locale,
            timezone=timezone,
            terms_version=terms_version,
            terms_accepted_at=now,
            privacy_version=privacy_version,
            privacy_accepted_at=now,
        )
        session.add(user)
        await session.flush()
        raw_token = opaque_token()
        session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=sha256_token(raw_token),
                expires_at=now + timedelta(hours=self.settings.auth_email_verification_ttl_hours),
            )
        )
        member_role = await session.scalar(select(Role).where(Role.code == "member"))
        if member_role is not None:
            session.add(
                UserRole(
                    user_id=user.id,
                    role_id=member_role.id,
                    granted_by=user.id,
                    grant_reason="Automatic member role on registration",
                )
            )
        record_security_event(
            session,
            event_type="auth.registration.created",
            actor_type="user",
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
        )
        await session.commit()
        return user, raw_token

    async def create_verification_token(
        self, session: AsyncSession, email: str
    ) -> tuple[User, str] | None:
        user = await session.scalar(select(User).where(User.email == email.strip().casefold()))
        if user is None or user.email_verified_at is not None:
            return None
        now = datetime.now(UTC)
        await session.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.consumed_at.is_(None),
                EmailVerificationToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        raw_token = opaque_token()
        session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=sha256_token(raw_token),
                expires_at=now + timedelta(hours=self.settings.auth_email_verification_ttl_hours),
            )
        )
        record_security_event(
            session,
            event_type="auth.email_verification.sent",
            actor_type="user",
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
        )
        await session.commit()
        return user, raw_token

    async def confirm_email(self, session: AsyncSession, raw_token: str) -> User:
        now = datetime.now(UTC)
        token = await session.scalar(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == sha256_token(raw_token))
            .with_for_update()
        )
        if (
            token is None
            or token.consumed_at is not None
            or token.invalidated_at is not None
            or token.expires_at <= now
        ):
            raise VavError("VERIFICATION_TOKEN_INVALID", "Verification token is invalid.")
        user = await session.get(User, token.user_id, with_for_update=True)
        if user is None:
            raise VavError("VERIFICATION_TOKEN_INVALID", "Verification token is invalid.")
        token.consumed_at = now
        user.email_verified_at = now
        user.status = UserStatus.ACTIVE
        record_security_event(
            session,
            event_type="auth.email_verification.completed",
            actor_type="user",
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
        )
        await session.commit()
        return user

    async def login(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        device_name: str,
        audience: str,
        ip_hash: str,
        user_agent_hash: str,
    ) -> AuthResult:
        now = datetime.now(UTC)
        user = await session.scalar(
            select(User).where(User.email == email.strip().casefold()).with_for_update()
        )
        valid_password = user is not None and self.password_hasher.verify(
            user.password_hash, password
        )
        if user is None or not valid_password:
            if user is not None:
                user.failed_login_count += 1
                if user.failed_login_count >= self.settings.auth_max_failed_attempts:
                    user.status = UserStatus.LOCKED
                    user.locked_until = now + timedelta(minutes=self.settings.auth_lockout_minutes)
                    record_security_event(
                        session,
                        event_type="auth.account.locked",
                        severity="warning",
                        actor_type="anonymous",
                        target_type="user",
                        target_id=user.id,
                        ip_address_hash=ip_hash,
                    )
                await session.commit()
            raise VavError(
                "INVALID_CREDENTIALS",
                "Email or password is incorrect.",
                status_code=401,
            )
        if user.status == UserStatus.LOCKED and user.locked_until and user.locked_until <= now:
            user.status = (
                UserStatus.ACTIVE
                if user.email_verified_at is not None
                else UserStatus.PENDING_VERIFICATION
            )
            user.locked_until = None
        if user.status != UserStatus.ACTIVE:
            record_security_event(
                session,
                event_type="auth.login.failed",
                severity="warning",
                actor_type="user",
                actor_user_id=user.id,
                target_type="user",
                target_id=user.id,
                metadata={"reason": "account_not_active"},
                ip_address_hash=ip_hash,
            )
            await session.commit()
            raise VavError(
                "INVALID_CREDENTIALS",
                "Email or password is incorrect.",
                status_code=401,
            )
        permissions = await permissions_for_user(session, user.id)
        if audience == self.settings.auth_admin_audience and not permissions:
            raise VavError(
                "INVALID_CREDENTIALS",
                "Email or password is incorrect.",
                status_code=401,
            )
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        result = self._new_session(
            user=user,
            permissions=permissions,
            audience=audience,
            device_name=device_name,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        session.add(result.session)
        record_security_event(
            session,
            event_type="auth.login.succeeded",
            actor_type="user",
            actor_user_id=user.id,
            actor_session_id=result.session.id,
            target_type="user",
            target_id=user.id,
            ip_address_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        await session.commit()
        return result

    def _new_session(
        self,
        *,
        user: User,
        permissions: list[str],
        audience: str,
        device_name: str,
        ip_hash: str,
        user_agent_hash: str,
        family_id: UUID | None = None,
    ) -> AuthResult:
        now = datetime.now(UTC)
        raw_refresh = opaque_token("vav_rt_")
        csrf_token = opaque_token("vav_csrf_")
        session_id = uuid4()
        ttl = (
            timedelta(hours=self.settings.auth_admin_refresh_token_ttl_hours)
            if audience == self.settings.auth_admin_audience
            else timedelta(days=self.settings.auth_refresh_token_ttl_days)
        )
        auth_session = AuthSession(
            id=session_id,
            user_id=user.id,
            session_family_id=family_id or uuid4(),
            refresh_token_hash=hmac_token(raw_refresh, self.settings),
            audience=audience,
            status=SessionStatus.ACTIVE,
            issued_at=now,
            expires_at=now + ttl,
            device_name=device_name,
            ip_address_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        access = self.token_service.issue(
            user_id=user.id,
            session_id=session_id,
            audience=audience,
            auth_version=user.auth_version,
            rbac_version=user.rbac_version,
        )
        return AuthResult(
            access_token=access,
            refresh_token=raw_refresh,
            csrf_token=csrf_token,
            expires_in=self.settings.auth_access_token_ttl_seconds,
            user=user,
            session=auth_session,
            permissions=permissions,
        )

    async def refresh(
        self,
        session: AsyncSession,
        *,
        raw_refresh_token: str,
        audience: str,
    ) -> AuthResult:
        now = datetime.now(UTC)
        existing = await session.scalar(
            select(AuthSession)
            .where(AuthSession.refresh_token_hash == hmac_token(raw_refresh_token, self.settings))
            .with_for_update()
        )
        if existing is None or existing.audience != audience:
            raise VavError("AUTH_SESSION_INVALID", "Session is invalid.", status_code=401)
        user = await session.get(User, existing.user_id, with_for_update=True)
        if user is None:
            raise VavError("AUTH_SESSION_INVALID", "Session is invalid.", status_code=401)
        if existing.status == SessionStatus.REPLACED:
            await session.execute(
                update(AuthSession)
                .where(AuthSession.session_family_id == existing.session_family_id)
                .values(
                    status=SessionStatus.REVOKED,
                    revoked_at=now,
                    revoke_reason="refresh_token_reuse",
                )
            )
            user.auth_version += 1
            record_security_event(
                session,
                event_type="auth.refresh_token.reuse_detected",
                severity="critical",
                actor_type="anonymous",
                target_type="session_family",
                target_id=existing.session_family_id,
            )
            await session.commit()
            raise VavError(
                "AUTH_SESSION_COMPROMISED",
                "Session family was revoked.",
                status_code=401,
            )
        if existing.status != SessionStatus.ACTIVE or existing.expires_at <= now:
            existing.status = SessionStatus.EXPIRED
            await session.commit()
            raise VavError("AUTH_SESSION_INVALID", "Session is invalid.", status_code=401)
        if user.status != UserStatus.ACTIVE:
            raise VavError("AUTH_SESSION_INVALID", "Session is invalid.", status_code=401)
        permissions = await permissions_for_user(session, user.id)
        replacement = self._new_session(
            user=user,
            permissions=permissions,
            audience=audience,
            device_name=existing.device_name or "Browser",
            ip_hash=existing.ip_address_hash or "",
            user_agent_hash=existing.user_agent_hash or "",
            family_id=existing.session_family_id,
        )
        session.add(replacement.session)
        existing.status = SessionStatus.REPLACED
        existing.last_used_at = now
        existing.replaced_by_session_id = replacement.session.id
        record_security_event(
            session,
            event_type="auth.session.refreshed",
            actor_type="user",
            actor_user_id=user.id,
            actor_session_id=existing.id,
            target_type="session",
            target_id=replacement.session.id,
        )
        await session.commit()
        return replacement

    async def request_password_reset(
        self, session: AsyncSession, email: str
    ) -> tuple[User, str] | None:
        user = await session.scalar(select(User).where(User.email == email.strip().casefold()))
        if user is None or user.status in {UserStatus.DELETED, UserStatus.SUSPENDED}:
            return None
        now = datetime.now(UTC)
        await session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
                PasswordResetToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        raw_token = opaque_token()
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=sha256_token(raw_token),
                expires_at=now + timedelta(minutes=self.settings.auth_password_reset_ttl_minutes),
            )
        )
        record_security_event(
            session,
            event_type="auth.password.reset.requested",
            actor_type="anonymous",
            target_type="user",
            target_id=user.id,
        )
        await session.commit()
        return user, raw_token

    async def reset_password(
        self, session: AsyncSession, *, raw_token: str, new_password: str
    ) -> User:
        now = datetime.now(UTC)
        token = await session.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == sha256_token(raw_token))
            .with_for_update()
        )
        if (
            token is None
            or token.consumed_at is not None
            or token.invalidated_at is not None
            or token.expires_at <= now
        ):
            raise VavError("PASSWORD_RESET_TOKEN_INVALID", "Reset token is invalid.")
        user = await session.get(User, token.user_id, with_for_update=True)
        if user is None:
            raise VavError("PASSWORD_RESET_TOKEN_INVALID", "Reset token is invalid.")
        self.password_policy.validate(new_password, user.email)
        user.password_hash = self.password_hasher.hash(new_password)
        user.password_changed_at = now
        user.auth_version += 1
        token.consumed_at = now
        await session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.id != token.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        await self.revoke_all(session, user.id, "password_reset", commit=False)
        record_security_event(
            session,
            event_type="auth.password.reset.completed",
            actor_type="user",
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
        )
        await session.commit()
        return user

    async def change_password(
        self,
        session: AsyncSession,
        *,
        user: User,
        current_session_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        if not self.password_hasher.verify(user.password_hash, current_password):
            raise VavError("CURRENT_PASSWORD_INVALID", "Current password is incorrect.")
        self.password_policy.validate(new_password, user.email)
        now = datetime.now(UTC)
        user.password_hash = self.password_hasher.hash(new_password)
        user.password_changed_at = now
        user.auth_version += 1
        await session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.id != current_session_id,
                AuthSession.status == SessionStatus.ACTIVE,
            )
            .values(
                status=SessionStatus.REVOKED,
                revoked_at=now,
                revoke_reason="password_changed",
            )
        )
        record_security_event(
            session,
            event_type="auth.password.changed",
            actor_type="user",
            actor_user_id=user.id,
            actor_session_id=current_session_id,
            target_type="user",
            target_id=user.id,
        )
        await session.commit()

    async def revoke_all(
        self,
        session: AsyncSession,
        user_id: UUID,
        reason: str,
        *,
        commit: bool = True,
    ) -> None:
        now = datetime.now(UTC)
        await session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.status.in_([SessionStatus.ACTIVE, SessionStatus.REPLACED]),
            )
            .values(status=SessionStatus.REVOKED, revoked_at=now, revoke_reason=reason)
        )
        user = await session.get(User, user_id, with_for_update=True)
        if user is not None:
            user.auth_version += 1
        record_security_event(
            session,
            event_type="auth.session.family_revoked",
            actor_type="user",
            actor_user_id=user_id,
            target_type="user",
            target_id=user_id,
            reason=reason,
        )
        if commit:
            await session.commit()
