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
    knowledge_default_locale: str = Field(
        default="zh-CN", validation_alias="KNOWLEDGE_DEFAULT_LOCALE"
    )
    knowledge_supported_locales: str = Field(
        default="zh-CN,zh-TW,en", validation_alias="KNOWLEDGE_SUPPORTED_LOCALES"
    )
    knowledge_require_authorization: bool = Field(
        default=True, validation_alias="KNOWLEDGE_REQUIRE_AUTHORIZATION"
    )
    knowledge_require_review_before_publish: bool = Field(
        default=True, validation_alias="KNOWLEDGE_REQUIRE_REVIEW_BEFORE_PUBLISH"
    )
    knowledge_max_upload_size_mb: int = Field(
        default=100, validation_alias="KNOWLEDGE_MAX_UPLOAD_SIZE_MB"
    )
    knowledge_parser_timeout_seconds: int = Field(
        default=120, validation_alias="KNOWLEDGE_PARSER_TIMEOUT_SECONDS"
    )
    knowledge_min_parse_quality_bps: int = Field(
        default=8000, validation_alias="KNOWLEDGE_MIN_PARSE_QUALITY_BPS"
    )
    knowledge_block_low_quality_autopublish: bool = Field(
        default=True, validation_alias="KNOWLEDGE_BLOCK_LOW_QUALITY_AUTOPUBLISH"
    )
    knowledge_chunk_strategy: str = Field(
        default="heading_aware_v1", validation_alias="KNOWLEDGE_CHUNK_STRATEGY"
    )
    knowledge_chunk_target_tokens: int = Field(
        default=500, validation_alias="KNOWLEDGE_CHUNK_TARGET_TOKENS"
    )
    knowledge_chunk_max_tokens: int = Field(
        default=800, validation_alias="KNOWLEDGE_CHUNK_MAX_TOKENS"
    )
    knowledge_chunk_min_tokens: int = Field(
        default=100, validation_alias="KNOWLEDGE_CHUNK_MIN_TOKENS"
    )
    knowledge_chunk_overlap_tokens: int = Field(
        default=80, validation_alias="KNOWLEDGE_CHUNK_OVERLAP_TOKENS"
    )
    knowledge_parent_chunk_max_tokens: int = Field(
        default=1600, validation_alias="KNOWLEDGE_PARENT_CHUNK_MAX_TOKENS"
    )
    knowledge_embedding_provider: str = Field(
        default="fake", validation_alias="KNOWLEDGE_EMBEDDING_PROVIDER"
    )
    knowledge_embedding_profile: str = Field(
        default="default-multilingual", validation_alias="KNOWLEDGE_EMBEDDING_PROFILE"
    )
    knowledge_embedding_batch_token_limit: int = Field(
        default=20000, validation_alias="KNOWLEDGE_EMBEDDING_BATCH_TOKEN_LIMIT"
    )
    knowledge_embedding_max_retries: int = Field(
        default=5, validation_alias="KNOWLEDGE_EMBEDDING_MAX_RETRIES"
    )
    knowledge_retrieval_top_k: int = Field(default=8, validation_alias="KNOWLEDGE_RETRIEVAL_TOP_K")
    knowledge_retrieval_candidate_count: int = Field(
        default=40, validation_alias="KNOWLEDGE_RETRIEVAL_CANDIDATE_COUNT"
    )
    knowledge_retrieval_fusion: str = Field(
        default="reciprocal_rank_fusion", validation_alias="KNOWLEDGE_RETRIEVAL_FUSION"
    )
    knowledge_retrieval_rerank_enabled: bool = Field(
        default=True, validation_alias="KNOWLEDGE_RETRIEVAL_RERANK_ENABLED"
    )
    knowledge_retrieval_query_max_length: int = Field(
        default=2000, validation_alias="KNOWLEDGE_RETRIEVAL_QUERY_MAX_LENGTH"
    )
    knowledge_retrieval_cache_ttl_seconds: int = Field(
        default=300, validation_alias="KNOWLEDGE_RETRIEVAL_CACHE_TTL_SECONDS"
    )
    knowledge_evaluation_min_cases: int = Field(
        default=30, validation_alias="KNOWLEDGE_EVALUATION_MIN_CASES"
    )
    knowledge_evaluation_require_zero_acl_leakage: bool = Field(
        default=True, validation_alias="KNOWLEDGE_EVALUATION_REQUIRE_ZERO_ACL_LEAKAGE"
    )
    knowledge_evaluation_require_zero_authorization_violations: bool = Field(
        default=True, validation_alias="KNOWLEDGE_EVALUATION_REQUIRE_ZERO_AUTHORIZATION_VIOLATIONS"
    )
    knowledge_query_log_retention_days: int = Field(
        default=30, validation_alias="KNOWLEDGE_QUERY_LOG_RETENTION_DAYS"
    )
    knowledge_store_raw_query_text: bool = Field(
        default=True, validation_alias="KNOWLEDGE_STORE_RAW_QUERY_TEXT"
    )
    knowledge_sensitive_query_encryption: bool = Field(
        default=True, validation_alias="KNOWLEDGE_SENSITIVE_QUERY_ENCRYPTION"
    )

    ai_agent_profile: str = Field(default="hanna_v1", validation_alias="AI_AGENT_PROFILE")
    ai_agent_graph_version: str = Field(default="1.0.0", validation_alias="AI_AGENT_GRAPH_VERSION")
    ai_agent_default_locale: str = Field(
        default="zh-CN", validation_alias="AI_AGENT_DEFAULT_LOCALE"
    )
    ai_agent_max_recent_turns: int = Field(default=12, validation_alias="AI_AGENT_MAX_RECENT_TURNS")
    ai_agent_summary_trigger_turns: int = Field(
        default=10, validation_alias="AI_AGENT_SUMMARY_TRIGGER_TURNS"
    )
    ai_agent_max_clarifying_questions_per_turn: int = Field(
        default=2, validation_alias="AI_AGENT_MAX_CLARIFYING_QUESTIONS_PER_TURN"
    )
    ai_turn_timeout_seconds: int = Field(default=45, validation_alias="AI_TURN_TIMEOUT_SECONDS")
    ai_turn_max_model_calls: int = Field(default=8, validation_alias="AI_TURN_MAX_MODEL_CALLS")
    ai_turn_max_tool_calls: int = Field(default=6, validation_alias="AI_TURN_MAX_TOOL_CALLS")
    ai_turn_max_input_tokens: int = Field(
        default=30000, validation_alias="AI_TURN_MAX_INPUT_TOKENS"
    )
    ai_turn_max_output_tokens: int = Field(
        default=2000, validation_alias="AI_TURN_MAX_OUTPUT_TOKENS"
    )
    ai_turn_max_cost_minor: int = Field(default=100, validation_alias="AI_TURN_MAX_COST_MINOR")
    ai_safety_prescreen_enabled: bool = Field(
        default=True, validation_alias="AI_SAFETY_PRESCREEN_ENABLED"
    )
    ai_safety_postcheck_enabled: bool = Field(
        default=True, validation_alias="AI_SAFETY_POSTCHECK_ENABLED"
    )
    ai_safety_high_risk_auto_referral: bool = Field(
        default=True, validation_alias="AI_SAFETY_HIGH_RISK_AUTO_REFERRAL"
    )
    ai_safety_immediate_risk_pause_conversation: bool = Field(
        default=True, validation_alias="AI_SAFETY_IMMEDIATE_RISK_PAUSE_CONVERSATION"
    )
    ai_safety_policy_version: str = Field(
        default="1.0.0", validation_alias="AI_SAFETY_POLICY_VERSION"
    )
    ai_rag_enabled: bool = Field(default=True, validation_alias="AI_RAG_ENABLED")
    ai_rag_top_k: int = Field(default=8, validation_alias="AI_RAG_TOP_K")
    ai_rag_require_citations: bool = Field(
        default=True, validation_alias="AI_RAG_REQUIRE_CITATIONS"
    )
    ai_rag_allow_unsourced_general_guidance: bool = Field(
        default=True, validation_alias="AI_RAG_ALLOW_UNSOURCED_GENERAL_GUIDANCE"
    )
    ai_rag_block_unsupported_core_claims: bool = Field(
        default=True, validation_alias="AI_RAG_BLOCK_UNSUPPORTED_CORE_CLAIMS"
    )
    ai_tool_calling_enabled: bool = Field(default=True, validation_alias="AI_TOOL_CALLING_ENABLED")
    ai_tool_default_timeout_seconds: int = Field(
        default=10, validation_alias="AI_TOOL_DEFAULT_TIMEOUT_SECONDS"
    )
    ai_tool_write_confirmation_required: bool = Field(
        default=True, validation_alias="AI_TOOL_WRITE_CONFIRMATION_REQUIRED"
    )
    ai_tool_max_parallel_calls: int = Field(
        default=3, validation_alias="AI_TOOL_MAX_PARALLEL_CALLS"
    )
    ai_max_service_recommendations: int = Field(
        default=3, validation_alias="AI_MAX_SERVICE_RECOMMENDATIONS"
    )
    ai_max_recommendations_per_type: int = Field(
        default=2, validation_alias="AI_MAX_RECOMMENDATIONS_PER_TYPE"
    )
    ai_recommend_only_currently_available: bool = Field(
        default=True, validation_alias="AI_RECOMMEND_ONLY_CURRENTLY_AVAILABLE"
    )
    ai_long_term_memory_enabled: bool = Field(
        default=True, validation_alias="AI_LONG_TERM_MEMORY_ENABLED"
    )
    ai_long_term_memory_opt_in_required: bool = Field(
        default=True, validation_alias="AI_LONG_TERM_MEMORY_OPT_IN_REQUIRED"
    )
    ai_long_term_memory_default: bool = Field(
        default=False, validation_alias="AI_LONG_TERM_MEMORY_DEFAULT"
    )
    ai_conversation_retention_days: int = Field(
        default=365, validation_alias="AI_CONVERSATION_RETENTION_DAYS"
    )
    ai_conversation_store_raw_content: bool = Field(
        default=True, validation_alias="AI_CONVERSATION_STORE_RAW_CONTENT"
    )
    ai_conversation_encryption_enabled: bool = Field(
        default=True, validation_alias="AI_CONVERSATION_ENCRYPTION_ENABLED"
    )
    ai_external_training_opt_in_required: bool = Field(
        default=True, validation_alias="AI_EXTERNAL_TRAINING_OPT_IN_REQUIRED"
    )
    ai_external_training_default: bool = Field(
        default=False, validation_alias="AI_EXTERNAL_TRAINING_DEFAULT"
    )
    ai_model_provider: str = Field(
        default="deterministic_local", validation_alias="AI_MODEL_PROVIDER"
    )
    ai_evaluation_min_cases: int = Field(default=30, validation_alias="AI_EVALUATION_MIN_CASES")
    ai_evaluation_require_zero_privacy_leakage: bool = Field(
        default=True, validation_alias="AI_EVALUATION_REQUIRE_ZERO_PRIVACY_LEAKAGE"
    )
    ai_evaluation_require_zero_unauthorized_tool_calls: bool = Field(
        default=True, validation_alias="AI_EVALUATION_REQUIRE_ZERO_UNAUTHORIZED_TOOL_CALLS"
    )
    ai_evaluation_require_zero_cross_user_access: bool = Field(
        default=True, validation_alias="AI_EVALUATION_REQUIRE_ZERO_CROSS_USER_ACCESS"
    )

    notification_enabled: bool = Field(default=True, validation_alias="NOTIFICATION_ENABLED")
    notification_default_locale: str = Field(
        default="zh-CN", validation_alias="NOTIFICATION_DEFAULT_LOCALE"
    )
    notification_supported_locales: str = Field(
        default="zh-CN,zh-TW,en", validation_alias="NOTIFICATION_SUPPORTED_LOCALES"
    )
    notification_default_timezone: str = Field(
        default="Asia/Shanghai", validation_alias="NOTIFICATION_DEFAULT_TIMEZONE"
    )
    notification_worker_batch_size: int = Field(
        default=100, validation_alias="NOTIFICATION_WORKER_BATCH_SIZE"
    )
    notification_max_delivery_attempts: int = Field(
        default=6, validation_alias="NOTIFICATION_MAX_DELIVERY_ATTEMPTS"
    )
    notification_delivery_timeout_seconds: int = Field(
        default=15, validation_alias="NOTIFICATION_DELIVERY_TIMEOUT_SECONDS"
    )
    notification_retry_base_seconds: int = Field(
        default=60, validation_alias="NOTIFICATION_RETRY_BASE_SECONDS"
    )
    notification_retry_max_seconds: int = Field(
        default=43200, validation_alias="NOTIFICATION_RETRY_MAX_SECONDS"
    )
    notification_dedup_ttl_days: int = Field(
        default=30, validation_alias="NOTIFICATION_DEDUP_TTL_DAYS"
    )
    notification_in_app_enabled: bool = Field(
        default=True, validation_alias="NOTIFICATION_IN_APP_ENABLED"
    )
    notification_in_app_retention_days: int = Field(
        default=365, validation_alias="NOTIFICATION_IN_APP_RETENTION_DAYS"
    )
    notification_unread_cache_ttl_seconds: int = Field(
        default=60, validation_alias="NOTIFICATION_UNREAD_CACHE_TTL_SECONDS"
    )
    notification_email_enabled: bool = Field(
        default=True, validation_alias="NOTIFICATION_EMAIL_ENABLED"
    )
    notification_email_provider: str = Field(
        default="mailpit", validation_alias="NOTIFICATION_EMAIL_PROVIDER"
    )
    notification_email_from_address: str = Field(
        default="no-reply@example.local", validation_alias="NOTIFICATION_EMAIL_FROM_ADDRESS"
    )
    notification_email_from_name: str = Field(
        default="VAV", validation_alias="NOTIFICATION_EMAIL_FROM_NAME"
    )
    notification_email_reply_to: str = Field(
        default="", validation_alias="NOTIFICATION_EMAIL_REPLY_TO"
    )
    notification_email_provider_webhook_secret: SecretStr = Field(
        default=SecretStr("change-me-notification-webhook"),
        validation_alias="NOTIFICATION_EMAIL_PROVIDER_WEBHOOK_SECRET",
    )
    notification_email_max_recipients_per_request: int = Field(
        default=1, validation_alias="NOTIFICATION_EMAIL_MAX_RECIPIENTS_PER_REQUEST"
    )
    mailpit_smtp_host: str = Field(default="localhost", validation_alias="MAILPIT_SMTP_HOST")
    mailpit_smtp_port: int = Field(default=1025, validation_alias="MAILPIT_SMTP_PORT")
    notification_quiet_hours_enabled: bool = Field(
        default=True, validation_alias="NOTIFICATION_QUIET_HOURS_ENABLED"
    )
    notification_marketing_opt_in_required: bool = Field(
        default=True, validation_alias="NOTIFICATION_MARKETING_OPT_IN_REQUIRED"
    )
    notification_default_marketing_enabled: bool = Field(
        default=False, validation_alias="NOTIFICATION_DEFAULT_MARKETING_ENABLED"
    )
    notification_digest_enabled: bool = Field(
        default=True, validation_alias="NOTIFICATION_DIGEST_ENABLED"
    )
    notification_reminder_job_interval_seconds: int = Field(
        default=60, validation_alias="NOTIFICATION_REMINDER_JOB_INTERVAL_SECONDS"
    )
    notification_reminder_lookahead_minutes: int = Field(
        default=10, validation_alias="NOTIFICATION_REMINDER_LOOKAHEAD_MINUTES"
    )
    notification_stale_reminder_recheck: bool = Field(
        default=True, validation_alias="NOTIFICATION_STALE_REMINDER_RECHECK"
    )
    notification_campaigns_enabled: bool = Field(
        default=True, validation_alias="NOTIFICATION_CAMPAIGNS_ENABLED"
    )
    notification_campaign_default_batch_size: int = Field(
        default=100, validation_alias="NOTIFICATION_CAMPAIGN_DEFAULT_BATCH_SIZE"
    )
    notification_campaign_default_rate_per_minute: int = Field(
        default=500, validation_alias="NOTIFICATION_CAMPAIGN_DEFAULT_RATE_PER_MINUTE"
    )
    notification_campaign_approval_required: bool = Field(
        default=True, validation_alias="NOTIFICATION_CAMPAIGN_APPROVAL_REQUIRED"
    )
    notification_campaign_test_recipient_allowlist: str = Field(
        default="", validation_alias="NOTIFICATION_CAMPAIGN_TEST_RECIPIENT_ALLOWLIST"
    )
    notification_soft_bounce_threshold: int = Field(
        default=3, validation_alias="NOTIFICATION_SOFT_BOUNCE_THRESHOLD"
    )
    notification_suppression_enabled: bool = Field(
        default=True, validation_alias="NOTIFICATION_SUPPRESSION_ENABLED"
    )
    notification_event_retention_days: int = Field(
        default=90, validation_alias="NOTIFICATION_EVENT_RETENTION_DAYS"
    )
    notification_delivery_retention_days: int = Field(
        default=365, validation_alias="NOTIFICATION_DELIVERY_RETENTION_DAYS"
    )
    notification_attempt_retention_days: int = Field(
        default=180, validation_alias="NOTIFICATION_ATTEMPT_RETENTION_DAYS"
    )

    privacy_enabled: bool = Field(default=True, validation_alias="PRIVACY_ENABLED")
    privacy_default_mode: Literal["strict", "balanced", "custom"] = Field(
        default="strict", validation_alias="PRIVACY_DEFAULT_MODE"
    )
    privacy_require_reauth_for_export: bool = Field(
        default=True, validation_alias="PRIVACY_REQUIRE_REAUTH_FOR_EXPORT"
    )
    privacy_require_reauth_for_erasure: bool = Field(
        default=True, validation_alias="PRIVACY_REQUIRE_REAUTH_FOR_ERASURE"
    )
    privacy_request_default_due_days: int = Field(
        default=30, validation_alias="PRIVACY_REQUEST_DEFAULT_DUE_DAYS"
    )
    privacy_request_identity_verification_ttl_minutes: int = Field(
        default=30, validation_alias="PRIVACY_REQUEST_IDENTITY_VERIFICATION_TTL_MINUTES"
    )
    privacy_request_max_active_per_user: int = Field(
        default=3, validation_alias="PRIVACY_REQUEST_MAX_ACTIVE_PER_USER"
    )
    privacy_export_formats: str = Field(
        default="json,csv,html", validation_alias="PRIVACY_EXPORT_FORMATS"
    )
    privacy_export_download_ttl_hours: int = Field(
        default=24, validation_alias="PRIVACY_EXPORT_DOWNLOAD_TTL_HOURS"
    )
    privacy_export_archive_retention_days: int = Field(
        default=7, validation_alias="PRIVACY_EXPORT_ARCHIVE_RETENTION_DAYS"
    )
    privacy_export_max_size_mb: int = Field(
        default=1024, validation_alias="PRIVACY_EXPORT_MAX_SIZE_MB"
    )
    privacy_export_encryption_enabled: bool = Field(
        default=True, validation_alias="PRIVACY_EXPORT_ENCRYPTION_ENABLED"
    )
    privacy_erasure_confirmation_required: bool = Field(
        default=True, validation_alias="PRIVACY_ERASURE_CONFIRMATION_REQUIRED"
    )
    privacy_erasure_cooling_off_days: int = Field(
        default=7, validation_alias="PRIVACY_ERASURE_COOLING_OFF_DAYS"
    )
    privacy_erasure_max_attempts: int = Field(
        default=10, validation_alias="PRIVACY_ERASURE_MAX_ATTEMPTS"
    )
    privacy_erasure_retry_seconds: int = Field(
        default=300, validation_alias="PRIVACY_ERASURE_RETRY_SECONDS"
    )
    privacy_erasure_fail_closed: bool = Field(
        default=True, validation_alias="PRIVACY_ERASURE_FAIL_CLOSED"
    )
    privacy_retention_job_interval_hours: int = Field(
        default=24, validation_alias="PRIVACY_RETENTION_JOB_INTERVAL_HOURS"
    )
    privacy_retention_policy_required: bool = Field(
        default=True, validation_alias="PRIVACY_RETENTION_POLICY_REQUIRED"
    )
    privacy_allow_unbounded_retention: bool = Field(
        default=False, validation_alias="PRIVACY_ALLOW_UNBOUNDED_RETENTION"
    )
    privacy_field_encryption_enabled: bool = Field(
        default=True, validation_alias="PRIVACY_FIELD_ENCRYPTION_ENABLED"
    )
    privacy_search_hmac_pepper: SecretStr = Field(
        default=SecretStr("change-me-privacy-search-hmac"),
        validation_alias="PRIVACY_SEARCH_HMAC_PEPPER",
    )
    privacy_break_glass_default_ttl_minutes: int = Field(
        default=30, validation_alias="PRIVACY_BREAK_GLASS_DEFAULT_TTL_MINUTES"
    )
    privacy_break_glass_approval_required: bool = Field(
        default=True, validation_alias="PRIVACY_BREAK_GLASS_APPROVAL_REQUIRED"
    )
    ai_memory_default_ttl_days: int = Field(
        default=365, validation_alias="AI_MEMORY_DEFAULT_TTL_DAYS"
    )
    ai_memory_inferred_item_user_approval_required: bool = Field(
        default=True, validation_alias="AI_MEMORY_INFERRED_ITEM_USER_APPROVAL_REQUIRED"
    )
    privacy_sensitive_access_audit_enabled: bool = Field(
        default=True, validation_alias="PRIVACY_SENSITIVE_ACCESS_AUDIT_ENABLED"
    )
    privacy_audit_retention_days: int = Field(
        default=730, validation_alias="PRIVACY_AUDIT_RETENTION_DAYS"
    )

    dating_profile_enabled: bool = Field(default=True, validation_alias="DATING_PROFILE_ENABLED")
    dating_minimum_age: int = Field(default=18, validation_alias="DATING_MINIMUM_AGE")
    dating_profile_default_locale: str = Field(
        default="zh-CN", validation_alias="DATING_PROFILE_DEFAULT_LOCALE"
    )
    dating_profile_default_privacy_mode: Literal["strict", "balanced", "custom"] = Field(
        default="strict", validation_alias="DATING_PROFILE_DEFAULT_PRIVACY_MODE"
    )
    dating_profile_submission_min_completeness_bps: int = Field(
        default=8000, validation_alias="DATING_PROFILE_SUBMISSION_MIN_COMPLETENESS_BPS"
    )
    dating_profile_recommendation_min_completeness_bps: int = Field(
        default=9000, validation_alias="DATING_PROFILE_RECOMMENDATION_MIN_COMPLETENESS_BPS"
    )
    dating_profile_require_primary_photo: bool = Field(
        default=True, validation_alias="DATING_PROFILE_REQUIRE_PRIMARY_PHOTO"
    )
    dating_profile_require_review: bool = Field(
        default=True, validation_alias="DATING_PROFILE_REQUIRE_REVIEW"
    )
    dating_self_intro_min_chars: int = Field(
        default=80, validation_alias="DATING_SELF_INTRO_MIN_CHARS"
    )
    dating_self_intro_max_chars: int = Field(
        default=3000, validation_alias="DATING_SELF_INTRO_MAX_CHARS"
    )
    dating_narrative_max_chars: int = Field(
        default=4000, validation_alias="DATING_NARRATIVE_MAX_CHARS"
    )
    dating_photo_min_count_for_submission: int = Field(
        default=1, validation_alias="DATING_PHOTO_MIN_COUNT_FOR_SUBMISSION"
    )
    dating_photo_max_count: int = Field(default=8, validation_alias="DATING_PHOTO_MAX_COUNT")
    dating_photo_max_size_mb: int = Field(default=10, validation_alias="DATING_PHOTO_MAX_SIZE_MB")
    dating_photo_allowed_types: str = Field(
        default="image/jpeg,image/png,image/webp", validation_alias="DATING_PHOTO_ALLOWED_TYPES"
    )
    dating_photo_view_token_ttl_seconds: int = Field(
        default=300, validation_alias="DATING_PHOTO_VIEW_TOKEN_TTL_SECONDS"
    )
    dating_photo_strip_exif: bool = Field(default=True, validation_alias="DATING_PHOTO_STRIP_EXIF")
    dating_photo_biometric_identification_enabled: bool = Field(
        default=False, validation_alias="DATING_PHOTO_BIOMETRIC_IDENTIFICATION_ENABLED"
    )
    dating_review_assignment_enabled: bool = Field(
        default=True, validation_alias="DATING_REVIEW_ASSIGNMENT_ENABLED"
    )
    dating_review_auto_approve_enabled: bool = Field(
        default=False, validation_alias="DATING_REVIEW_AUTO_APPROVE_ENABLED"
    )
    dating_review_require_reason_for_rejection: bool = Field(
        default=True, validation_alias="DATING_REVIEW_REQUIRE_REASON_FOR_REJECTION"
    )
    dating_review_require_reason_for_suspension: bool = Field(
        default=True, validation_alias="DATING_REVIEW_REQUIRE_REASON_FOR_SUSPENSION"
    )
    dating_preferences_max_criteria: int = Field(
        default=50, validation_alias="DATING_PREFERENCES_MAX_CRITERIA"
    )
    dating_allow_hard_constraints: bool = Field(
        default=True, validation_alias="DATING_ALLOW_HARD_CONSTRAINTS"
    )
    dating_allow_automatic_relaxation_default: bool = Field(
        default=False, validation_alias="DATING_ALLOW_AUTOMATIC_RELAXATION_DEFAULT"
    )
    dating_projection_job_max_attempts: int = Field(
        default=10, validation_alias="DATING_PROJECTION_JOB_MAX_ATTEMPTS"
    )
    dating_projection_cache_ttl_seconds: int = Field(
        default=300, validation_alias="DATING_PROJECTION_CACHE_TTL_SECONDS"
    )

    # ------------------------------------------------------------------
    # Recommendations (Batch 14)
    # ------------------------------------------------------------------
    recommendation_enabled: bool = Field(default=True, validation_alias="RECOMMENDATION_ENABLED")
    recommendation_default_strategy: str = Field(
        default="baseline-bidirectional-v1", validation_alias="RECOMMENDATION_DEFAULT_STRATEGY"
    )
    recommendation_batch_job_interval_hours: int = Field(
        default=24, validation_alias="RECOMMENDATION_BATCH_JOB_INTERVAL_HOURS"
    )
    recommendation_max_candidates_per_user: int = Field(
        default=1000, validation_alias="RECOMMENDATION_MAX_CANDIDATES_PER_USER"
    )
    recommendation_candidate_validity_days: int = Field(
        default=7, validation_alias="RECOMMENDATION_CANDIDATE_VALIDITY_DAYS"
    )
    recommendation_require_active_approved_profile: bool = Field(
        default=True, validation_alias="RECOMMENDATION_REQUIRE_ACTIVE_APPROVED_PROFILE"
    )
    recommendation_hard_constraint_auto_relax: bool = Field(
        default=False, validation_alias="RECOMMENDATION_HARD_CONSTRAINT_AUTO_RELAX"
    )
    recommendation_allow_user_relaxation: bool = Field(
        default=True, validation_alias="RECOMMENDATION_ALLOW_USER_RELAXATION"
    )
    recommendation_unknown_value_policy: Literal["lower_confidence", "exclude", "neutral"] = Field(
        default="lower_confidence", validation_alias="RECOMMENDATION_UNKNOWN_VALUE_POLICY"
    )
    recommendation_missingness_policy: Literal[
        "ignore_and_lower_confidence", "neutral_score", "configured_penalty"
    ] = Field(
        default="ignore_and_lower_confidence",
        validation_alias="RECOMMENDATION_MISSINGNESS_POLICY",
    )
    recommendation_missing_penalty_bps: int = Field(
        default=0, validation_alias="RECOMMENDATION_MISSING_PENALTY_BPS"
    )
    recommendation_min_directional_score_bps: int = Field(
        default=4000, validation_alias="RECOMMENDATION_MIN_DIRECTIONAL_SCORE_BPS"
    )
    recommendation_min_bidirectional_score_bps: int = Field(
        default=5000, validation_alias="RECOMMENDATION_MIN_BIDIRECTIONAL_SCORE_BPS"
    )
    recommendation_min_confidence_bps: int = Field(
        default=5000, validation_alias="RECOMMENDATION_MIN_CONFIDENCE_BPS"
    )
    recommendation_daily_batch_size: int = Field(
        default=10, validation_alias="RECOMMENDATION_DAILY_BATCH_SIZE"
    )
    recommendation_batch_ttl_days: int = Field(
        default=7, validation_alias="RECOMMENDATION_BATCH_TTL_DAYS"
    )
    recommendation_supplemental_batch_enabled: bool = Field(
        default=True, validation_alias="RECOMMENDATION_SUPPLEMENTAL_BATCH_ENABLED"
    )
    recommendation_max_daily_received: int = Field(
        default=20, validation_alias="RECOMMENDATION_MAX_DAILY_RECEIVED"
    )
    recommendation_max_daily_shown_per_profile: int = Field(
        default=50, validation_alias="RECOMMENDATION_MAX_DAILY_SHOWN_PER_PROFILE"
    )
    recommendation_repeat_exposure_cooldown_days: int = Field(
        default=30, validation_alias="RECOMMENDATION_REPEAT_EXPOSURE_COOLDOWN_DAYS"
    )
    recommendation_exposure_visible_min_ms: int = Field(
        default=1000, validation_alias="RECOMMENDATION_EXPOSURE_VISIBLE_MIN_MS"
    )
    recommendation_skip_cooldown_days: int = Field(
        default=30, validation_alias="RECOMMENDATION_SKIP_COOLDOWN_DAYS"
    )
    recommendation_exploration_slot_count: int = Field(
        default=2, validation_alias="RECOMMENDATION_EXPLORATION_SLOT_COUNT"
    )
    recommendation_cold_start_min_exposures: int = Field(
        default=5, validation_alias="RECOMMENDATION_COLD_START_MIN_EXPOSURES"
    )
    recommendation_feedback_personalization_default: bool = Field(
        default=True, validation_alias="RECOMMENDATION_FEEDBACK_PERSONALIZATION_DEFAULT"
    )
    recommendation_experiments_enabled: bool = Field(
        default=False, validation_alias="RECOMMENDATION_EXPERIMENTS_ENABLED"
    )
    recommendation_experiment_approval_required: bool = Field(
        default=True, validation_alias="RECOMMENDATION_EXPERIMENT_APPROVAL_REQUIRED"
    )
    recommendation_fail_closed_on_moderation_error: bool = Field(
        default=True, validation_alias="RECOMMENDATION_FAIL_CLOSED_ON_MODERATION_ERROR"
    )
    recommendation_require_zero_blocked_pair_leakage: bool = Field(
        default=True, validation_alias="RECOMMENDATION_REQUIRE_ZERO_BLOCKED_PAIR_LEAKAGE"
    )

    matchmaking_interactions_enabled: bool = Field(
        default=True, validation_alias="MATCHMAKING_INTERACTIONS_ENABLED"
    )
    matchmaking_allow_direct_profile_like: bool = Field(
        default=False, validation_alias="MATCHMAKING_ALLOW_DIRECT_PROFILE_LIKE"
    )
    matchmaking_require_valid_recommendation_item: bool = Field(
        default=True, validation_alias="MATCHMAKING_REQUIRE_VALID_RECOMMENDATION_ITEM"
    )
    matchmaking_like_ttl_days: int = Field(
        default=180, ge=1, validation_alias="MATCHMAKING_LIKE_TTL_DAYS"
    )
    matchmaking_skip_not_now_cooldown_days: int = Field(
        default=30, ge=1, validation_alias="MATCHMAKING_SKIP_NOT_NOW_COOLDOWN_DAYS"
    )
    matchmaking_skip_not_interested_cooldown_days: int = Field(
        default=180, ge=1, validation_alias="MATCHMAKING_SKIP_NOT_INTERESTED_COOLDOWN_DAYS"
    )
    matchmaking_allow_skip_undo: bool = Field(
        default=True, validation_alias="MATCHMAKING_ALLOW_SKIP_UNDO"
    )
    matchmaking_skip_undo_window_seconds: int = Field(
        default=300, ge=0, validation_alias="MATCHMAKING_SKIP_UNDO_WINDOW_SECONDS"
    )
    matchmaking_mutual_match_enabled: bool = Field(
        default=True, validation_alias="MATCHMAKING_MUTUAL_MATCH_ENABLED"
    )
    matchmaking_single_like_notification_enabled: bool = Field(
        default=False, validation_alias="MATCHMAKING_SINGLE_LIKE_NOTIFICATION_ENABLED"
    )
    matchmaking_mutual_match_notification_enabled: bool = Field(
        default=True, validation_alias="MATCHMAKING_MUTUAL_MATCH_NOTIFICATION_ENABLED"
    )
    matchmaking_invitation_enabled: bool = Field(
        default=True, validation_alias="MATCHMAKING_INVITATION_ENABLED"
    )
    matchmaking_invitation_ttl_days: int = Field(
        default=7, ge=1, validation_alias="MATCHMAKING_INVITATION_TTL_DAYS"
    )
    matchmaking_declined_pair_cooldown_days: int = Field(
        default=180, ge=1, validation_alias="MATCHMAKING_DECLINED_PAIR_COOLDOWN_DAYS"
    )
    matchmaking_expired_invitation_cooldown_days: int = Field(
        default=30, ge=1, validation_alias="MATCHMAKING_EXPIRED_INVITATION_COOLDOWN_DAYS"
    )
    matchmaking_invitation_message_max_chars: int = Field(
        default=500, ge=1, validation_alias="MATCHMAKING_INVITATION_MESSAGE_MAX_CHARS"
    )
    matchmaking_invitation_contact_info_blocking: bool = Field(
        default=True, validation_alias="MATCHMAKING_INVITATION_CONTACT_INFO_BLOCKING"
    )
    matchmaking_expired_invitation_reopens_match: bool = Field(
        default=True, validation_alias="MATCHMAKING_EXPIRED_INVITATION_REOPENS_MATCH"
    )
    matchmaking_contact_exchange_policy: Literal[
        "platform_only",
        "mutual_confirmation_required",
        "automatic_after_invitation_accepted",
    ] = Field(
        default="mutual_confirmation_required",
        validation_alias="MATCHMAKING_CONTACT_EXCHANGE_POLICY",
    )
    matchmaking_contact_exchange_require_verified_contact: bool = Field(
        default=True, validation_alias="MATCHMAKING_CONTACT_EXCHANGE_REQUIRE_VERIFIED_CONTACT"
    )
    matchmaking_contact_reveal_token_ttl_seconds: int = Field(
        default=300, ge=30, validation_alias="MATCHMAKING_CONTACT_REVEAL_TOKEN_TTL_SECONDS"
    )
    matchmaking_contact_grant_default_ttl_days: int = Field(
        default=0, ge=0, validation_alias="MATCHMAKING_CONTACT_GRANT_DEFAULT_TTL_DAYS"
    )
    matchmaking_fail_closed_on_moderation_error: bool = Field(
        default=True, validation_alias="MATCHMAKING_FAIL_CLOSED_ON_MODERATION_ERROR"
    )
    matchmaking_block_invalidates_contact_grants: bool = Field(
        default=True, validation_alias="MATCHMAKING_BLOCK_INVALIDATES_CONTACT_GRANTS"
    )
    matchmaking_idempotency_ttl_hours: int = Field(
        default=24, ge=1, validation_alias="MATCHMAKING_IDEMPOTENCY_TTL_HOURS"
    )

    @property
    def dating_photo_allowed_type_set(self) -> frozenset[str]:
        return frozenset(
            item.strip().casefold()
            for item in self.dating_photo_allowed_types.split(",")
            if item.strip()
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
        if self.environment == "production" and self.knowledge_embedding_provider == "fake":
            raise ValueError("production must configure a real knowledge embedding provider")
        if self.environment == "production" and self.ai_model_provider == "deterministic_local":
            raise ValueError("production must configure an approved AI model provider")
        if self.environment == "production" and not self.ai_conversation_encryption_enabled:
            raise ValueError("production must encrypt AI conversation content")
        if self.ai_external_training_default:
            raise ValueError("external AI training cannot be enabled by default")
        if self.notification_default_marketing_enabled:
            raise ValueError("marketing notifications cannot be enabled by default")
        if self.notification_email_max_recipients_per_request != 1:
            raise ValueError("notification email delivery must use one recipient per request")
        if self.environment == "production" and self.notification_email_provider in {
            "mailpit",
            "fake",
        }:
            raise ValueError("production must configure an approved notification email provider")
        if self.environment == "production" and (
            "change-me" in self.notification_email_provider_webhook_secret.get_secret_value()
            or not self.notification_email_provider_webhook_secret.get_secret_value()
        ):
            raise ValueError("production requires a notification webhook secret")
        if self.ai_long_term_memory_default:
            raise ValueError("AI long-term memory cannot be enabled by default")
        if not self.ai_long_term_memory_opt_in_required:
            raise ValueError("AI long-term memory requires explicit opt-in")
        if self.privacy_allow_unbounded_retention:
            raise ValueError("unbounded privacy retention cannot be enabled")
        if self.dating_minimum_age < 18:
            raise ValueError("dating profiles require an adult minimum age of at least 18")
        if self.dating_photo_biometric_identification_enabled:
            raise ValueError("biometric identification cannot be enabled for dating photos")
        if self.dating_allow_automatic_relaxation_default:
            raise ValueError("hard partner criteria cannot be relaxed by default")
        if self.dating_review_auto_approve_enabled and self.environment == "production":
            raise ValueError("production dating profiles require human review")
        if self.dating_profile_recommendation_min_completeness_bps < (
            self.dating_profile_submission_min_completeness_bps
        ):
            raise ValueError(
                "recommendation completeness threshold cannot be lower than submission threshold"
            )
        if self.recommendation_hard_constraint_auto_relax:
            raise ValueError("recommendation hard constraints cannot be relaxed automatically")
        if not self.recommendation_fail_closed_on_moderation_error:
            raise ValueError("recommendation safety checks must fail closed")
        if not self.recommendation_require_zero_blocked_pair_leakage:
            raise ValueError("blocked pairs can never be recommended")
        if not self.matchmaking_fail_closed_on_moderation_error:
            raise ValueError("interaction safety checks must fail closed")
        if not self.matchmaking_block_invalidates_contact_grants:
            raise ValueError("a block must revoke contact access")
        if self.matchmaking_single_like_notification_enabled:
            raise ValueError("a one-sided like can never notify its target")
        if (
            self.environment == "production"
            and self.matchmaking_contact_exchange_policy
            == "automatic_after_invitation_accepted"
        ):
            raise ValueError(
                "automatic contact exchange requires an approved product and privacy decision"
            )
        if self.environment == "production" and (
            not self.matchmaking_contact_exchange_require_verified_contact
        ):
            raise ValueError("only verified contact points can be exchanged")
        if self.environment == "production" and self.matchmaking_allow_direct_profile_like:
            raise ValueError("liking an arbitrary profile requires an approved product decision")
        if (
            self.environment == "production"
            and self.recommendation_experiments_enabled
            and (not self.recommendation_experiment_approval_required)
        ):
            raise ValueError("production recommendation experiments require approval")
        if self.recommendation_min_bidirectional_score_bps < 0 or (
            self.recommendation_min_bidirectional_score_bps > 10_000
        ):
            raise ValueError("bidirectional score thresholds are basis points between 0 and 10000")
        if self.environment == "production" and (
            not self.privacy_field_encryption_enabled
            or not self.privacy_export_encryption_enabled
            or "change-me" in self.privacy_search_hmac_pepper.get_secret_value()
        ):
            raise ValueError("production requires privacy encryption and a strong HMAC pepper")
        return self

    def public_summary(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "version": self.version,
            "display_timezone": self.display_timezone,
            "features": {
                "ai_assistant": self.ai_enabled,
                "notifications": self.notification_enabled,
                "privacy": self.privacy_enabled,
                "dating_profile": self.dating_profile_enabled,
                "recommendations": self.recommendation_enabled,
            },
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
