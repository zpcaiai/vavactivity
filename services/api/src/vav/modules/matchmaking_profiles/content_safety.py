"""Narrative content screening for dating-profile free text.

Detection is advisory: findings route text to human review rather than
silently asserting fraud. Contact details are the one category that is
rejected outright, because the platform must not let users bypass the
consent-gated contact-exchange flow.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
from typing import Any

CONTACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "email_address": re.compile(
        r"[\w.+-]+\s*(?:@|＠|\(at\)|\[at\])\s*[\w-]+\s*\.\s*[a-z]{2,}", re.I
    ),
    "phone_number": re.compile(r"(?<!\d)(?:\+?\d[\s\-()]?){8,15}(?!\d)"),
    "messaging_handle": re.compile(
        r"(?:微信|weixin|wechat|whatsapp|telegram|line\s*id|qq|instagram|ig)\s*[:：=]?\s*[\w.\-]{3,}",
        re.I,
    ),
    "external_link": re.compile(r"(?:https?://|www\.)\S+", re.I),
}

RISK_PATTERNS: dict[str, re.Pattern[str]] = {
    "external_payment_request": re.compile(
        r"(?:转账|汇款|打款|红包|付款给我|send\s+money|wire\s+transfer|gift\s+card)", re.I
    ),
    "investment_solicitation": re.compile(
        r"(?:投资|理财|炒币|数字货币|虚拟货币|crypto|bitcoin|forex|guaranteed\s+returns)", re.I
    ),
    "off_platform_redirect": re.compile(
        r"(?:加我|私聊我|站外联系|contact\s+me\s+(?:off|outside)|add\s+me\s+on)", re.I
    ),
    "credential_disclosure": re.compile(
        r"(?:身份证号|护照号|银行卡号|passport\s+number|id\s+number)", re.I
    ),
}

NARRATIVE_FIELDS: tuple[str, ...] = (
    "self_introduction",
    "faith_journey",
    "relationship_values",
    "marriage_vision",
    "family_vision",
    "strengths_and_growth",
    "interests_and_lifestyle",
    "hoped_for_relationship",
)


def scan_text(value: str | None) -> list[dict[str, Any]]:
    """Return findings for a single narrative value."""
    if not value:
        return []
    findings: list[dict[str, Any]] = []
    for code, pattern in CONTACT_PATTERNS.items():
        if pattern.search(value):
            findings.append({"code": code, "category": "contact_information", "severity": "block"})
    for code, pattern in RISK_PATTERNS.items():
        if pattern.search(value):
            findings.append({"code": code, "category": "risk", "severity": "review"})
    return findings


def scan_narratives(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return findings across every narrative field, tagged with the field code."""
    findings: list[dict[str, Any]] = []
    for field in NARRATIVE_FIELDS:
        for finding in scan_text(payload.get(field)):
            findings.append({**finding, "field_code": field})
    return findings


def blocking_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finding for finding in findings if finding["severity"] == "block"]


def moderation_status_for(findings: list[dict[str, Any]]) -> str:
    """Narratives always require review; findings only raise the priority."""
    return "review_required"
