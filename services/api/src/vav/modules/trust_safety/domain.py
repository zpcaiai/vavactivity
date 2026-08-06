"""Pure Trust & Safety policies.

These functions intentionally have no database or model-provider dependency so the
release-blocking invariants can be tested deterministically.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class SafetyReportCategory(StrEnum):
    HARASSMENT = "harassment"
    THREAT = "threat"
    ABUSE = "abuse"
    COERCIVE_CONTROL = "coercive_control"
    STALKING = "stalking"
    HATE_OR_DEGRADING_CONTENT = "hate_or_degrading_content"
    SEXUAL_CONTENT = "sexual_content"
    IMPERSONATION = "impersonation"
    FRAUD_OR_SCAM = "fraud_or_scam"
    MONEY_REQUEST = "money_request"
    OFF_PLATFORM_PAYMENT = "off_platform_payment"
    SPAM = "spam"
    FALSE_PROFILE = "false_profile"
    UNDERAGE_CONCERN = "underage_concern"
    PRIVACY_VIOLATION = "privacy_violation"
    SAFETY_CONCERN = "safety_concern"
    OTHER = "other"


class ModerationTargetType(StrEnum):
    DATING_PROFILE_FIELD = "dating_profile_field"
    DATING_PROFILE_PHOTO = "dating_profile_photo"
    DATING_PROFILE_NARRATIVE = "dating_profile_narrative"
    ACTIVITY_CONTENT = "activity_content"
    INVITATION_MESSAGE = "invitation_message"
    RELATIONSHIP_SHARED_CONTENT = "relationship_shared_content"
    TESTIMONIAL = "testimonial"
    AI_RESPONSE = "ai_response"
    CAMPAIGN_CONTENT = "campaign_content"


class SafetyRiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class AccountRestrictionType(StrEnum):
    PROFILE_HIDDEN = "profile_hidden"
    PROFILE_EDIT_REVIEW_REQUIRED = "profile_edit_review_required"
    RECOMMENDATION_DISABLED = "recommendation_disabled"
    LIKE_DISABLED = "like_disabled"
    INVITATION_DISABLED = "invitation_disabled"
    CONTACT_EXCHANGE_DISABLED = "contact_exchange_disabled"
    RELATIONSHIP_INTERACTION_FROZEN = "relationship_interaction_frozen"
    ACTIVITY_REGISTRATION_DISABLED = "activity_registration_disabled"
    AI_WRITE_ACTIONS_DISABLED = "ai_write_actions_disabled"
    COMMUNICATION_RATE_LIMITED = "communication_rate_limited"
    REVERIFICATION_REQUIRED = "reverification_required"
    ACCOUNT_TEMPORARILY_SUSPENDED = "account_temporarily_suspended"
    ACCOUNT_PERMANENTLY_DISABLED = "account_permanently_disabled"


REPORT_TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"triaged", "withdrawn"}),
    "triaged": frozenset({"in_review", "action_taken", "closed", "withdrawn"}),
    "in_review": frozenset({"action_taken", "closed", "withdrawn"}),
    "action_taken": frozenset({"closed"}),
    "closed": frozenset(),
    "withdrawn": frozenset(),
}

CASE_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"triaged", "assigned", "closed"}),
    "triaged": frozenset({"assigned", "investigating", "closed"}),
    "assigned": frozenset({"investigating", "pending_action", "resolved"}),
    "investigating": frozenset({"pending_action", "resolved"}),
    "pending_action": frozenset({"investigating", "resolved"}),
    "resolved": frozenset({"closed", "reopened"}),
    "closed": frozenset({"reopened"}),
    "reopened": frozenset({"assigned", "investigating"}),
}

HIGH_IMPACT_RESTRICTIONS = frozenset(
    {
        AccountRestrictionType.ACCOUNT_PERMANENTLY_DISABLED.value,
        AccountRestrictionType.ACCOUNT_TEMPORARILY_SUSPENDED.value,
        AccountRestrictionType.REVERIFICATION_REQUIRED.value,
    }
)

REGISTERED_SIGNALS = frozenset(
    {
        "pair_blocked",
        "active_restriction_count",
        "like_rate",
        "invitation_rate",
        "repeated_contact_count",
        "post_decline_contact_count",
        "distinct_target_count",
        "money_request_detected",
        "external_payment_link_detected",
        "threat_detected",
        "staff_impersonation_detected",
        "account_takeover_signal",
        "classifier_confidence_bps",
    }
)

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_CONTACT_PATTERNS = (
    re.compile(r"(?:\+?\d[\s()\-.]*){7,}"),
    re.compile(r"[\w.+-]+\s*@\s*[\w.-]+\s*\.\s*[a-z]{2,}", re.I),
    re.compile(
        r"[\w.+-]+\s*(?:\(at\)|\[at\]| at )\s*[\w.-]+\s*"
        r"(?:\(dot\)|\[dot\]| dot |\.)\s*[a-z]{2,}",
        re.I,
    ),
    re.compile(r"(?:微\s*信|wechat|whatsapp|telegram|line)\s*[:：]?\s*[\w-]{4,}", re.I),
)
_MONEY_PATTERNS = (
    re.compile(r"(?:转账|汇款|代付|借钱|借款|礼品卡|gift\s*card)", re.I),
    re.compile(r"(?:加密货币|比特币|虚拟币|crypto|bitcoin).{0,24}(?:投资|稳赚|回报|收益)", re.I),
    re.compile(r"(?:紧急|医疗|包裹|账户冻结).{0,32}(?:付款|转钱|借款|费用)", re.I),
)
_THREAT_PATTERNS = (
    re.compile(r"(?:杀了你|伤害你|跟踪你|让你后悔)", re.I),
    re.compile(r"\b(?:kill|hurt|stalk)\s+you\b", re.I),
)
_IMPERSONATION_PATTERNS = (
    re.compile(r"(?:我是|代表).{0,12}(?:VAV|平台|客服|工作人员|导师)", re.I),
    re.compile(r"\b(?:vav|platform)\s+(?:staff|support|mentor)\b", re.I),
)


def canonical_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    if first == second:
        raise ValueError("a safety pair requires two different users")
    return (first, second) if str(first) < str(second) else (second, first)


def validate_transition(current: str, target: str, transitions: dict[str, frozenset[str]]) -> None:
    if target not in transitions.get(current, frozenset()):
        raise ValueError(f"invalid safety transition: {current} -> {target}")


def requires_second_approval(restriction_type: str, duration_hours: int | None) -> bool:
    return restriction_type in HIGH_IMPACT_RESTRICTIONS or (
        duration_hours is not None and duration_hours > 24 * 30
    )


def normalize_adversarial_text(value: str) -> str:
    normalized = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", value))
    original = re.sub(r"\s+", " ", normalized).strip()
    compact = original.casefold()
    for token in re.findall(r"(?<![\w+/])[A-Za-z0-9+/]{16,}={0,2}(?![\w+/])", original):
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        compact = f"{compact} {decoded.casefold()}"
    dense = re.sub(r"[\s._-]+", "", compact)
    return f"{compact} {dense}"


def classify_text(value: str) -> frozenset[str]:
    text = normalize_adversarial_text(value)
    hits: set[str] = set()
    if any(pattern.search(text) for pattern in _CONTACT_PATTERNS):
        hits.add("contact_information_bypass")
    if re.search(r"https?://|www\.|(?:bit\.ly|t\.me|tinyurl\.com)/", text, re.I):
        hits.add("external_link")
    if any(pattern.search(text) for pattern in _MONEY_PATTERNS):
        hits.add("money_request")
    if any(pattern.search(text) for pattern in _THREAT_PATTERNS):
        hits.add("threat")
    if any(pattern.search(text) for pattern in _IMPERSONATION_PATTERNS):
        hits.add("impersonation")
    return frozenset(hits)


def evaluate_condition(condition: dict[str, Any], signals: dict[str, Any]) -> bool:
    """Evaluate the small declarative DSL; arbitrary code and SQL are impossible."""

    signal = condition.get("signal")
    operator = condition.get("operator")
    if signal not in REGISTERED_SIGNALS:
        raise ValueError("rule uses an unregistered signal")
    if operator not in {"eq", "gte", "lte", "in"}:
        raise ValueError("rule uses an unsupported operator")
    actual = signals.get(str(signal))
    expected = condition.get("value")
    if operator == "eq":
        return bool(actual == expected)
    if operator == "gte":
        return bool(actual is not None and actual >= expected)
    if operator == "lte":
        return bool(actual is not None and actual <= expected)
    return bool(actual in expected) if isinstance(expected, list) else False


@dataclass(frozen=True)
class TrustSafetyDecision:
    allowed: bool
    action: str
    safe_reason_code: str | None
    restriction_version: int
    decision_id: UUID
    expires_at: str | None = None
    human_review_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "safe_reason_code": self.safe_reason_code,
            "restriction_version": self.restriction_version,
            "decision_id": str(self.decision_id),
            "expires_at": self.expires_at,
            "human_review_required": self.human_review_required,
        }
