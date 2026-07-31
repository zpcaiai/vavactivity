from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    version: str = Field(default="0.1.0", validation_alias="APP_VERSION")
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    display_timezone: str = Field(default="Asia/Shanghai", validation_alias="APP_DISPLAY_TIMEZONE")
    cors_origins: list[AnyHttpUrl] = Field(
        default_factory=lambda: [
            AnyHttpUrl("http://localhost:5173"),
            AnyHttpUrl("http://localhost:5174"),
        ],
        validation_alias="APP_CORS_ORIGINS",
    )
    database_url: str = Field(
        default=("postgresql+asyncpg://vav:vav_local_development_only@localhost:5432/vav"),
        validation_alias="DATABASE_URL",
        repr=False,
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
        repr=False,
    )
    otel_endpoint: str | None = Field(default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    ai_enabled: bool = Field(default=False, validation_alias="AI_ENABLED")

    auth_issuer: str = Field(default="vav-platform", validation_alias="AUTH_ISSUER")
    auth_user_audience: str = Field(default="vav-user", validation_alias="AUTH_USER_AUDIENCE")
    auth_admin_audience: str = Field(default="vav-admin", validation_alias="AUTH_ADMIN_AUDIENCE")
    auth_access_token_ttl_seconds: int = Field(
        default=900, validation_alias="AUTH_ACCESS_TOKEN_TTL_SECONDS"
    )
    auth_clock_skew_seconds: int = Field(default=30, validation_alias="AUTH_CLOCK_SKEW_SECONDS")
    auth_private_key_file: str = Field(
        default=".dev-secrets/auth-private.pem", validation_alias="AUTH_PRIVATE_KEY_FILE"
    )
    auth_public_key_file: str = Field(
        default=".dev-secrets/auth-public.pem", validation_alias="AUTH_PUBLIC_KEY_FILE"
    )
    auth_active_key_id: str = Field(default="dev-key-1", validation_alias="AUTH_ACTIVE_KEY_ID")
    auth_refresh_token_pepper: SecretStr = Field(
        default=SecretStr("local-refresh-pepper-change-me"),
        validation_alias="AUTH_REFRESH_TOKEN_PEPPER",
    )
    auth_refresh_token_ttl_days: int = Field(
        default=30, validation_alias="AUTH_REFRESH_TOKEN_TTL_DAYS"
    )
    auth_admin_refresh_token_ttl_hours: int = Field(
        default=12, validation_alias="AUTH_ADMIN_REFRESH_TOKEN_TTL_HOURS"
    )
    auth_password_min_length: int = Field(default=12, validation_alias="AUTH_PASSWORD_MIN_LENGTH")
    auth_password_max_length: int = Field(default=128, validation_alias="AUTH_PASSWORD_MAX_LENGTH")
    auth_argon2_time_cost: int = Field(default=3, validation_alias="AUTH_ARGON2_TIME_COST")
    auth_argon2_memory_cost: int = Field(default=65536, validation_alias="AUTH_ARGON2_MEMORY_COST")
    auth_argon2_parallelism: int = Field(default=4, validation_alias="AUTH_ARGON2_PARALLELISM")
    auth_max_failed_attempts: int = Field(default=5, validation_alias="AUTH_MAX_FAILED_ATTEMPTS")
    auth_lockout_minutes: int = Field(default=15, validation_alias="AUTH_LOCKOUT_MINUTES")
    auth_email_verification_ttl_hours: int = Field(
        default=24, validation_alias="AUTH_EMAIL_VERIFICATION_TTL_HOURS"
    )
    auth_password_reset_ttl_minutes: int = Field(
        default=30, validation_alias="AUTH_PASSWORD_RESET_TTL_MINUTES"
    )
    auth_email_resend_cooldown_seconds: int = Field(
        default=60, validation_alias="AUTH_EMAIL_RESEND_COOLDOWN_SECONDS"
    )
    auth_cookie_secure: bool = Field(default=False, validation_alias="AUTH_COOKIE_SECURE")
    auth_cookie_domain: str | None = Field(default=None, validation_alias="AUTH_COOKIE_DOMAIN")
    auth_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:5174"],
        validation_alias="AUTH_ALLOWED_ORIGINS",
    )
    user_web_url: str = Field(default="http://localhost:5173", validation_alias="USER_WEB_URL")
    admin_web_url: str = Field(default="http://localhost:5174", validation_alias="ADMIN_WEB_URL")
    public_web_base_url: str = Field(
        default="http://localhost:5173", validation_alias="PUBLIC_WEB_BASE_URL"
    )
    public_api_base_url: str = Field(
        default="http://localhost:8000", validation_alias="PUBLIC_API_BASE_URL"
    )
    public_site_indexing_enabled: bool = Field(
        default=False, validation_alias="PUBLIC_SITE_INDEXING_ENABLED"
    )
    smtp_host: str = Field(default="localhost", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, validation_alias="SMTP_PORT")
    email_from: str = Field(default="no-reply@vav.local", validation_alias="EMAIL_FROM")

    cms_default_locale: str = Field(default="zh-CN", validation_alias="CMS_DEFAULT_LOCALE")
    cms_supported_locales: list[str] = Field(
        default_factory=lambda: ["zh-CN", "zh-TW", "en"],
        validation_alias="CMS_SUPPORTED_LOCALES",
    )
    cms_fallback_locale: str = Field(default="zh-CN", validation_alias="CMS_FALLBACK_LOCALE")
    cms_allow_locale_fallback: bool = Field(
        default=True, validation_alias="CMS_ALLOW_LOCALE_FALLBACK"
    )
    cms_require_review_for_publish: bool = Field(
        default=True, validation_alias="CMS_REQUIRE_REVIEW_FOR_PUBLISH"
    )
    cms_preview_token_ttl_minutes: int = Field(
        default=30, validation_alias="CMS_PREVIEW_TOKEN_TTL_MINUTES"
    )
    media_s3_endpoint: str = Field(
        default="http://localhost:9000", validation_alias="MEDIA_S3_ENDPOINT"
    )
    media_s3_public_endpoint: str = Field(
        default="http://localhost:9000",
        validation_alias="MEDIA_S3_PUBLIC_ENDPOINT",
    )
    media_s3_region: str = Field(default="us-east-1", validation_alias="MEDIA_S3_REGION")
    media_s3_access_key: SecretStr = Field(
        default=SecretStr("vav_minio_local"), validation_alias="MEDIA_S3_ACCESS_KEY"
    )
    media_s3_secret_key: SecretStr = Field(
        default=SecretStr("vav_minio_local_development_only"),
        validation_alias="MEDIA_S3_SECRET_KEY",
    )
    media_bucket_public: str = Field(
        default="vav-public", validation_alias="MEDIA_S3_BUCKET_PUBLIC"
    )
    media_bucket_private: str = Field(
        default="vav-private", validation_alias="MEDIA_S3_BUCKET_PRIVATE"
    )
    media_max_image_size_mb: int = Field(default=10, validation_alias="MEDIA_MAX_IMAGE_SIZE_MB")
    contact_form_max_message_length: int = Field(
        default=5000, validation_alias="CONTACT_FORM_MAX_MESSAGE_LENGTH"
    )

    catalog_default_currency: str = Field(
        default="USD", validation_alias="CATALOG_DEFAULT_CURRENCY"
    )
    catalog_supported_currencies: list[str] = Field(
        default_factory=lambda: ["CNY", "USD", "TWD", "HKD"],
        validation_alias="CATALOG_SUPPORTED_CURRENCIES",
    )
    catalog_require_review_for_publish: bool = Field(
        default=True, validation_alias="CATALOG_REQUIRE_REVIEW_FOR_PUBLISH"
    )
    catalog_public_cache_ttl_seconds: int = Field(
        default=300, validation_alias="CATALOG_PUBLIC_CACHE_TTL_SECONDS"
    )
    pricing_quote_ttl_minutes: int = Field(default=15, validation_alias="PRICING_QUOTE_TTL_MINUTES")
    pricing_allow_locale_fallback: bool = Field(
        default=True, validation_alias="PRICING_ALLOW_LOCALE_FALLBACK"
    )
    pricing_fail_on_configuration_conflict: bool = Field(
        default=True, validation_alias="PRICING_FAIL_ON_CONFIGURATION_CONFLICT"
    )
    pricing_discount_rounding_mode: Literal["half_up"] = Field(
        default="half_up", validation_alias="PRICING_DISCOUNT_ROUNDING_MODE"
    )
    pricing_max_quantity_per_quote: int = Field(
        default=100, validation_alias="PRICING_MAX_QUANTITY_PER_QUOTE"
    )
    inventory_reservation_ttl_minutes: int = Field(
        default=15, validation_alias="INVENTORY_RESERVATION_TTL_MINUTES"
    )
    inventory_low_stock_threshold: int = Field(
        default=5, validation_alias="INVENTORY_LOW_STOCK_THRESHOLD"
    )
    inventory_allow_negative: bool = Field(
        default=False, validation_alias="INVENTORY_ALLOW_NEGATIVE"
    )
    inventory_expiration_job_interval_seconds: int = Field(
        default=60, validation_alias="INVENTORY_EXPIRATION_JOB_INTERVAL_SECONDS"
    )
    promotion_max_stacked_count: int = Field(
        default=3, validation_alias="PROMOTION_MAX_STACKED_COUNT"
    )
    promotion_default_stackability: str = Field(
        default="exclusive", validation_alias="PROMOTION_DEFAULT_STACKABILITY"
    )
    exchange_rate_provider: str = Field(default="manual", validation_alias="EXCHANGE_RATE_PROVIDER")
    exchange_rate_reference_only: bool = Field(
        default=True, validation_alias="EXCHANGE_RATE_REFERENCE_ONLY"
    )

    commerce_order_expiration_minutes: int = Field(
        default=30, validation_alias="COMMERCE_ORDER_EXPIRATION_MINUTES"
    )
    commerce_cart_expiration_days: int = Field(
        default=30, validation_alias="COMMERCE_CART_EXPIRATION_DAYS"
    )
    commerce_checkout_idempotency_ttl_hours: int = Field(
        default=24, validation_alias="COMMERCE_CHECKOUT_IDEMPOTENCY_TTL_HOURS"
    )
    commerce_require_billing_email: bool = Field(
        default=True, validation_alias="COMMERCE_REQUIRE_BILLING_EMAIL"
    )
    payment_enabled_providers: list[str] = Field(
        default_factory=lambda: ["stripe", "paypal"],
        validation_alias="PAYMENT_ENABLED_PROVIDERS",
    )
    payment_default_provider: str = Field(
        default="stripe", validation_alias="PAYMENT_DEFAULT_PROVIDER"
    )
    payment_environment: Literal["test", "live"] = Field(
        default="test", validation_alias="PAYMENT_ENVIRONMENT"
    )
    payment_test_fake_enabled: bool = Field(
        default=True, validation_alias="PAYMENT_TEST_FAKE_ENABLED"
    )
    payment_test_webhook_secret: SecretStr = Field(
        default=SecretStr("local-commerce-webhook-change-me"),
        validation_alias="PAYMENT_TEST_WEBHOOK_SECRET",
    )
    stripe_secret_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="STRIPE_SECRET_KEY"
    )
    stripe_publishable_key: str = Field(default="", validation_alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias="STRIPE_WEBHOOK_SECRET"
    )
    stripe_api_version: str = Field(default="", validation_alias="STRIPE_API_VERSION")
    stripe_success_url: str = Field(
        default="http://localhost:5173/zh-CN/checkout/processing",
        validation_alias="STRIPE_SUCCESS_URL",
    )
    stripe_cancel_url: str = Field(
        default="http://localhost:5173/zh-CN/checkout/cancelled",
        validation_alias="STRIPE_CANCEL_URL",
    )
    paypal_client_id: SecretStr = Field(default=SecretStr(""), validation_alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias="PAYPAL_CLIENT_SECRET"
    )
    paypal_webhook_id: SecretStr = Field(
        default=SecretStr(""), validation_alias="PAYPAL_WEBHOOK_ID"
    )
    paypal_environment: Literal["sandbox", "live"] = Field(
        default="sandbox", validation_alias="PAYPAL_ENVIRONMENT"
    )
    paypal_return_url: str = Field(
        default="http://localhost:5173/zh-CN/checkout/processing",
        validation_alias="PAYPAL_RETURN_URL",
    )
    paypal_cancel_url: str = Field(
        default="http://localhost:5173/zh-CN/checkout/cancelled",
        validation_alias="PAYPAL_CANCEL_URL",
    )
    subscription_grace_period_days: int = Field(
        default=3, validation_alias="SUBSCRIPTION_GRACE_PERIOD_DAYS"
    )
    subscription_cancel_at_period_end_default: bool = Field(
        default=True, validation_alias="SUBSCRIPTION_CANCEL_AT_PERIOD_END_DEFAULT"
    )
    subscription_immediate_cancellation_enabled: bool = Field(
        default=False, validation_alias="SUBSCRIPTION_IMMEDIATE_CANCELLATION_ENABLED"
    )
    refund_approval_required: bool = Field(
        default=True, validation_alias="REFUND_APPROVAL_REQUIRED"
    )
    refund_auto_approval_max_minor: int = Field(
        default=0, validation_alias="REFUND_AUTO_APPROVAL_MAX_MINOR"
    )
    entitlement_activation_max_attempts: int = Field(
        default=10, validation_alias="ENTITLEMENT_ACTIVATION_MAX_ATTEMPTS"
    )
    entitlement_activation_retry_seconds: int = Field(
        default=60, validation_alias="ENTITLEMENT_ACTIVATION_RETRY_SECONDS"
    )
    reconciliation_lookback_days: int = Field(
        default=7, validation_alias="RECONCILIATION_LOOKBACK_DAYS"
    )
    reconciliation_job_interval_minutes: int = Field(
        default=30, validation_alias="RECONCILIATION_JOB_INTERVAL_MINUTES"
    )
    activity_require_review_for_publish: bool = Field(
        default=True, validation_alias="ACTIVITY_REQUIRE_REVIEW_FOR_PUBLISH"
    )
    activity_default_timezone: str = Field(
        default="Asia/Taipei", validation_alias="ACTIVITY_DEFAULT_TIMEZONE"
    )
    activity_public_cache_ttl_seconds: int = Field(
        default=300, validation_alias="ACTIVITY_PUBLIC_CACHE_TTL_SECONDS"
    )
    activity_allow_guest_registration: bool = Field(
        default=False, validation_alias="ACTIVITY_ALLOW_GUEST_REGISTRATION"
    )
    activity_registration_max_active_per_user: int = Field(
        default=1, validation_alias="ACTIVITY_REGISTRATION_MAX_ACTIVE_PER_USER"
    )
    activity_registration_form_max_fields: int = Field(
        default=30, validation_alias="ACTIVITY_REGISTRATION_FORM_MAX_FIELDS"
    )
    activity_registration_payment_invitation_ttl_minutes: int = Field(
        default=30,
        validation_alias="ACTIVITY_REGISTRATION_PAYMENT_INVITATION_TTL_MINUTES",
    )
    activity_waitlist_promotion_ttl_minutes: int = Field(
        default=30, validation_alias="ACTIVITY_WAITLIST_PROMOTION_TTL_MINUTES"
    )
    activity_waitlist_auto_promotion_enabled: bool = Field(
        default=True, validation_alias="ACTIVITY_WAITLIST_AUTO_PROMOTION_ENABLED"
    )
    activity_waitlist_job_interval_seconds: int = Field(
        default=60, validation_alias="ACTIVITY_WAITLIST_JOB_INTERVAL_SECONDS"
    )
    activity_checkin_qr_ttl_seconds: int = Field(
        default=60, validation_alias="ACTIVITY_CHECKIN_QR_TTL_SECONDS"
    )
    activity_checkin_allow_early_minutes: int = Field(
        default=60, validation_alias="ACTIVITY_CHECKIN_ALLOW_EARLY_MINUTES"
    )
    activity_checkin_allow_late_minutes: int = Field(
        default=120, validation_alias="ACTIVITY_CHECKIN_ALLOW_LATE_MINUTES"
    )
    activity_grouping_max_group_size: int = Field(
        default=20, validation_alias="ACTIVITY_GROUPING_MAX_GROUP_SIZE"
    )
    activity_grouping_require_checkin: bool = Field(
        default=False, validation_alias="ACTIVITY_GROUPING_REQUIRE_CHECKIN"
    )
    activity_post_event_max_interested_choices: int = Field(
        default=5, validation_alias="ACTIVITY_POST_EVENT_MAX_INTERESTED_CHOICES"
    )
    activity_post_event_require_checkin: bool = Field(
        default=True, validation_alias="ACTIVITY_POST_EVENT_REQUIRE_CHECKIN"
    )
    activity_post_event_contact_exchange_mode: Literal["mutual_confirmation_required"] = Field(
        default="mutual_confirmation_required",
        validation_alias="ACTIVITY_POST_EVENT_CONTACT_EXCHANGE_MODE",
    )
    activity_post_event_default_window_hours: int = Field(
        default=72, validation_alias="ACTIVITY_POST_EVENT_DEFAULT_WINDOW_HOURS"
    )
    course_require_review_for_publish: bool = Field(
        default=True, validation_alias="COURSE_REQUIRE_REVIEW_FOR_PUBLISH"
    )
    course_default_locale: str = Field(default="zh-CN", validation_alias="COURSE_DEFAULT_LOCALE")
    course_public_cache_ttl_seconds: int = Field(
        default=300, validation_alias="COURSE_PUBLIC_CACHE_TTL_SECONDS"
    )
    course_default_version_policy: Literal["pin_at_enrollment"] = Field(
        default="pin_at_enrollment", validation_alias="COURSE_DEFAULT_VERSION_POLICY"
    )
    course_allow_free_enrollment: bool = Field(
        default=True, validation_alias="COURSE_ALLOW_FREE_ENROLLMENT"
    )
    course_release_job_interval_seconds: int = Field(
        default=60, validation_alias="COURSE_RELEASE_JOB_INTERVAL_SECONDS"
    )
    course_default_release_policy: str = Field(
        default="all_at_once", validation_alias="COURSE_DEFAULT_RELEASE_POLICY"
    )
    course_video_provider: str = Field(
        default="fake_private", validation_alias="COURSE_VIDEO_PROVIDER"
    )
    course_video_playback_url_ttl_seconds: int = Field(
        default=300, validation_alias="COURSE_VIDEO_PLAYBACK_URL_TTL_SECONDS"
    )
    course_video_session_ttl_minutes: int = Field(
        default=120, validation_alias="COURSE_VIDEO_SESSION_TTL_MINUTES"
    )
    course_video_heartbeat_interval_seconds: int = Field(
        default=20, validation_alias="COURSE_VIDEO_HEARTBEAT_INTERVAL_SECONDS"
    )
    course_video_heartbeat_tolerance_seconds: int = Field(
        default=10, validation_alias="COURSE_VIDEO_HEARTBEAT_TOLERANCE_SECONDS"
    )
    course_video_max_concurrent_sessions: int = Field(
        default=3, validation_alias="COURSE_VIDEO_MAX_CONCURRENT_SESSIONS"
    )
    course_video_download_enabled: bool = Field(
        default=False, validation_alias="COURSE_VIDEO_DOWNLOAD_ENABLED"
    )
    course_video_default_required_watch_bps: int = Field(
        default=9000, validation_alias="COURSE_VIDEO_DEFAULT_REQUIRED_WATCH_BPS"
    )
    course_progress_event_max_batch_size: int = Field(
        default=50, validation_alias="COURSE_PROGRESS_EVENT_MAX_BATCH_SIZE"
    )
    course_progress_allow_manual_completion: bool = Field(
        default=True, validation_alias="COURSE_PROGRESS_ALLOW_MANUAL_COMPLETION"
    )
    course_progress_conflict_policy: Literal["monotonic_completion"] = Field(
        default="monotonic_completion", validation_alias="COURSE_PROGRESS_CONFLICT_POLICY"
    )
    course_exercise_max_questions: int = Field(
        default=200, validation_alias="COURSE_EXERCISE_MAX_QUESTIONS"
    )
    course_assignment_max_file_size_mb: int = Field(
        default=25, validation_alias="COURSE_ASSIGNMENT_MAX_FILE_SIZE_MB"
    )
    course_completion_job_interval_seconds: int = Field(
        default=60, validation_alias="COURSE_COMPLETION_JOB_INTERVAL_SECONDS"
    )
    course_certificate_enabled: bool = Field(
        default=True, validation_alias="COURSE_CERTIFICATE_ENABLED"
    )
    course_certificate_public_name_mode: Literal["masked"] = Field(
        default="masked", validation_alias="COURSE_CERTIFICATE_PUBLIC_NAME_MODE"
    )
    counseling_default_booking_mode: str = Field(
        default="request_and_confirm", validation_alias="COUNSELING_DEFAULT_BOOKING_MODE"
    )
    counseling_default_approval_policy: str = Field(
        default="manual", validation_alias="COUNSELING_DEFAULT_APPROVAL_POLICY"
    )
    counseling_default_payment_timing: str = Field(
        default="after_time_approval", validation_alias="COUNSELING_DEFAULT_PAYMENT_TIMING"
    )
    counseling_default_timezone: str = Field(
        default="Asia/Taipei", validation_alias="COUNSELING_DEFAULT_TIMEZONE"
    )
    counseling_slot_interval_minutes: int = Field(
        default=15, validation_alias="COUNSELING_SLOT_INTERVAL_MINUTES"
    )
    counseling_slot_hold_ttl_minutes: int = Field(
        default=15, validation_alias="COUNSELING_SLOT_HOLD_TTL_MINUTES"
    )
    counseling_default_minimum_notice_minutes: int = Field(
        default=1440, validation_alias="COUNSELING_DEFAULT_MINIMUM_NOTICE_MINUTES"
    )
    counseling_default_maximum_advance_days: int = Field(
        default=60, validation_alias="COUNSELING_DEFAULT_MAXIMUM_ADVANCE_DAYS"
    )
    counseling_availability_cache_ttl_seconds: int = Field(
        default=60, validation_alias="COUNSELING_AVAILABILITY_CACHE_TTL_SECONDS"
    )
    counseling_availability_max_range_days: int = Field(
        default=90, validation_alias="COUNSELING_AVAILABILITY_MAX_RANGE_DAYS"
    )
    counseling_payment_invitation_ttl_minutes: int = Field(
        default=30, validation_alias="COUNSELING_PAYMENT_INVITATION_TTL_MINUTES"
    )
    counseling_max_active_appointments_per_user: int = Field(
        default=5, validation_alias="COUNSELING_MAX_ACTIVE_APPOINTMENTS_PER_USER"
    )
    counseling_reschedule_max_count: int = Field(
        default=3, validation_alias="COUNSELING_RESCHEDULE_MAX_COUNT"
    )
    counseling_checkin_open_minutes_before: int = Field(
        default=15, validation_alias="COUNSELING_CHECKIN_OPEN_MINUTES_BEFORE"
    )
    counseling_join_open_minutes_before: int = Field(
        default=10, validation_alias="COUNSELING_JOIN_OPEN_MINUTES_BEFORE"
    )
    counseling_join_close_minutes_after: int = Field(
        default=30, validation_alias="COUNSELING_JOIN_CLOSE_MINUTES_AFTER"
    )
    counseling_meeting_provider: str = Field(
        default="fake", validation_alias="COUNSELING_MEETING_PROVIDER"
    )
    counseling_meeting_join_url_ttl_seconds: int = Field(
        default=300, validation_alias="COUNSELING_MEETING_JOIN_URL_TTL_SECONDS"
    )
    counseling_recording_enabled: bool = Field(
        default=False, validation_alias="COUNSELING_RECORDING_ENABLED"
    )
    counseling_transcription_enabled: bool = Field(
        default=False, validation_alias="COUNSELING_TRANSCRIPTION_ENABLED"
    )
    counseling_credit_reservation_ttl_hours: int = Field(
        default=24, validation_alias="COUNSELING_CREDIT_RESERVATION_TTL_HOURS"
    )
    counseling_default_no_show_credit_policy: str = Field(
        default="manual_review", validation_alias="COUNSELING_DEFAULT_NO_SHOW_CREDIT_POLICY"
    )
    counseling_client_summary_retention_days: int = Field(
        default=0, validation_alias="COUNSELING_CLIENT_SUMMARY_RETENTION_DAYS"
    )
    counseling_mentor_note_retention_days: int = Field(
        default=0, validation_alias="COUNSELING_MENTOR_NOTE_RETENTION_DAYS"
    )
    counseling_safety_record_retention_days: int = Field(
        default=0, validation_alias="COUNSELING_SAFETY_RECORD_RETENTION_DAYS"
    )
    counseling_safety_escalation_enabled: bool = Field(
        default=True, validation_alias="COUNSELING_SAFETY_ESCALATION_ENABLED"
    )
    counseling_immediate_risk_auto_pause_general_advice: bool = Field(
        default=True,
        validation_alias="COUNSELING_IMMEDIATE_RISK_AUTO_PAUSE_GENERAL_ADVICE",
    )

    @model_validator(mode="after")
    def reject_development_credentials_in_production(self) -> Settings:
        if self.environment == "production" and (
            "local_development_only" in self.database_url or "localhost" in self.database_url
        ):
            raise ValueError("production cannot use development database credentials")
        if self.environment == "production" and (
            "change-me" in self.auth_refresh_token_pepper.get_secret_value()
            or not self.auth_cookie_secure
        ):
            raise ValueError("production requires a strong token pepper and secure cookies")
        if self.environment == "production" and self.payment_test_fake_enabled:
            raise ValueError("production cannot enable the local payment fake")
        if self.payment_environment == "live" and self.environment != "production":
            raise ValueError("live payments require the production application environment")
        if self.environment == "production" and self.course_video_provider == "fake_private":
            raise ValueError("production must configure a real private course video provider")
        if self.environment == "production" and self.counseling_meeting_provider == "fake":
            raise ValueError("production must configure a real counseling meeting provider")
        return self

    def public_summary(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "version": self.version,
            "display_timezone": self.display_timezone,
            "features": {"ai_assistant": self.ai_enabled},
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
