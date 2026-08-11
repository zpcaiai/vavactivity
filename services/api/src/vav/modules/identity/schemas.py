from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, PositiveInt


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    preferred_locale: str = "zh-CN"
    timezone: str = "UTC"
    terms_version: str = Field(min_length=1, max_length=32)
    privacy_version: str = Field(min_length=1, max_length=32)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_name: str = Field(default="Browser", min_length=1, max_length=128)


class EmailRequest(BaseModel):
    email: EmailStr


class TokenConfirmRequest(BaseModel):
    token: str = Field(min_length=24, max_length=256)


class PasswordResetRequest(TokenConfirmRequest):
    new_password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class AdminUserUpdateRequest(ReasonRequest):
    expected_version: int = Field(ge=1)
    email: EmailStr | None = None
    preferred_locale: Literal["zh-CN", "zh-TW", "en"] | None = None
    timezone: str | None = Field(default=None, min_length=3, max_length=64)


class AdminUserDeactivateRequest(ReasonRequest):
    expected_version: int = Field(ge=1)


class RoleChangeRequest(ReasonRequest):
    role_code: str = Field(min_length=2, max_length=128)
    expires_at: datetime | None = None


class AdminInvitationRequest(ReasonRequest):
    email: EmailStr
    role_codes: list[str] = Field(min_length=1)


class AdminInvitationAcceptRequest(TokenConfirmRequest):
    password: str
    preferred_locale: str = "zh-CN"
    timezone: str = "UTC"
    terms_version: str
    privacy_version: str


class ContentPageQuery(BaseModel):
    page: PositiveInt = 1
    page_size: PositiveInt = 20


class CurrentUserResponse(BaseModel):
    id: UUID
    email: str
    status: str
    email_verified: bool
    preferred_locale: str
    timezone: str
    permissions: list[str] = []


class SessionResponse(BaseModel):
    id: UUID
    device_name: str | None
    issued_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    current: bool
