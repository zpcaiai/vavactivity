#!/usr/bin/env python3
"""OPS-002: verify the environment before anything else is attempted.

Three jobs, in order of how expensive the mistake is:

1. **Required configuration is present and plausible.** Missing variables fail
   fast, here, with the variable name and an example - not three minutes later
   inside an ORM stack trace.
2. **Pinned toolchain versions match.** Node and pnpm versions come from repo
   metadata (``package.json`` ``engines``/``packageManager``, ``.nvmrc``,
   ``.node-version``), never from a number hard-coded in this file, so the pin
   has exactly one home.
3. **No real provider credential is loaded in a non-production profile.** This
   is the one check here that is about damage rather than convenience: a live
   payment or SMS key sitting in a developer shell is how a test run charges a
   real card or texts a real member.

Exit codes: ``0`` everything verified, ``1`` an actionable failure. A check that
could not run is ``BLOCKED`` and exits ``1`` as well - an unverified environment
is not a verified one.

Usage::

    python3 batch_p4/scripts/verify_environment.py
    python3 batch_p4/scripts/verify_environment.py --profile production --json out.json
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    Report,
    Status,
    find_repo_root,
    read_json,
    read_text,
    run_command,
)

# ---------------------------------------------------------------------------
# Required configuration
# ---------------------------------------------------------------------------

#: ``(name, description, example)``. Kept as data so the failure message can
#: always show what a correct value looks like.
REQUIRED_VARIABLES: tuple[tuple[str, str, str], ...] = (
    (
        "DATABASE_URL",
        "PostgreSQL DSN the API and Alembic use",
        "postgresql+asyncpg://vav:vav@localhost:5432/vav",
    ),
    ("REDIS_URL", "Redis DSN for cache, locks and rate limits", "redis://localhost:6379/0"),
    ("VAV_ENV", "Deployment profile", "local | ci | staging | production"),
    ("SECRET_KEY", "Session and token signing key", "a 32+ character random string"),
    ("PRIVACY_ENCRYPTION_KEY", "Key for vav.modules.privacy.crypto", "base64 32-byte key"),
    ("PRIVACY_HMAC_KEY", "Key behind searchable_hmac()", "base64 32-byte key"),
)

#: Variables the new B08 module needs. Absent means the feature is off, which is
#: a legitimate state (DEC-001), so this is a WARN and not a FAIL.
FEATURE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("CHECKIN_LAST_FOUR_HMAC_KEY", "Deployment salt for the last-four narrowing column (CHK-002)"),
    ("CHECKIN_TOKEN_SIGNING_KEY", "Signs check-in choice and confirmation tokens (CHK-002)"),
)

#: Values that are obviously not real secrets. Anything matching is treated as a
#: placeholder rather than as a loaded credential.
PLACEHOLDER_PATTERN = re.compile(
    r"^(|changeme|change_me|placeholder|dummy|example|test|todo|xxx+|<.*>|\.\.\.|none|null)$",
    re.IGNORECASE,
)

MIN_SECRET_LENGTH = 32

PRODUCTION_PROFILES = frozenset({"production", "prod"})

# ---------------------------------------------------------------------------
# Provider credential detection
# ---------------------------------------------------------------------------

#: ``(env var pattern, value pattern or None, what it is)``. The value pattern
#: is what distinguishes a live key from a sandbox one where the provider makes
#: that visible in the key itself (Stripe does; most do not, which is why the
#: variable name alone is enough to raise the alarm).
PROVIDER_CREDENTIALS: tuple[tuple[str, str | None, str], ...] = (
    (r"^STRIPE_(SECRET|API)_KEY$", r"^sk_live_", "Stripe live secret key"),
    (r"^STRIPE_WEBHOOK_SECRET$", None, "Stripe webhook secret"),
    (r"^ALIPAY_(APP_)?PRIVATE_KEY$", None, "Alipay private key"),
    (r"^WECHAT_PAY_(API_)?KEY$", None, "WeChat Pay merchant key"),
    (r"^WECHAT_PAY_MCH_ID$", None, "WeChat Pay merchant id"),
    (r"^TWILIO_AUTH_TOKEN$", None, "Twilio auth token"),
    (r"^SENDGRID_API_KEY$", r"^SG\.", "SendGrid API key"),
    (r"^AWS_SECRET_ACCESS_KEY$", None, "AWS secret access key"),
    (r"^ALIYUN_ACCESS_KEY_SECRET$", None, "Aliyun access key secret"),
    (r"^ALIYUN_SMS_", None, "Aliyun SMS credential"),
    (r"^APNS_(KEY|CERT)", None, "Apple push credential"),
    (r"^GETUI_(APP_)?SECRET", None, "Getui push secret"),
    (r"^AMAP_(WEB_)?SERVICE_KEY$", None, "AMap server-side key"),
)

#: Names that mean "this is deliberately a sandbox credential".
SANDBOX_HINT = re.compile(r"(sandbox|test|mock|fake|stub|dev)", re.IGNORECASE)


def looks_real(value: str) -> bool:
    """A credential is 'real' when it is set, long enough and not a placeholder."""

    cleaned = (value or "").strip()
    if not cleaned or PLACEHOLDER_PATTERN.match(cleaned):
        return False
    if SANDBOX_HINT.search(cleaned):
        return False
    return len(cleaned) >= 16


def detect_live_credentials(environ: dict[str, str]) -> list[tuple[str, str]]:
    """Return ``(variable, description)`` for every credential that looks live."""

    found: list[tuple[str, str]] = []
    for name_pattern, value_pattern, description in PROVIDER_CREDENTIALS:
        name_re = re.compile(name_pattern)
        for name, value in environ.items():
            if not name_re.match(name):
                continue
            if value_pattern is not None:
                if re.search(value_pattern, value or ""):
                    found.append((name, description))
                continue
            if looks_real(value):
                found.append((name, description))
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Toolchain pins, read from repo metadata
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(value or "")
    if not match:
        return None
    return (
        int(match.group(1)),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
    )


def read_pinned_versions(repo_root: str) -> dict[str, str]:
    """Collect the toolchain pins the repo actually declares.

    Deliberately reads several files: ``.nvmrc`` is what a developer's shell
    honours, ``engines`` is what CI enforces, and ``packageManager`` is what
    corepack activates. A pin that only exists in one of them is a pin half the
    team does not have.
    """

    pins: dict[str, str] = {}
    package_json = read_json(os.path.join(repo_root, "package.json")) or {}
    engines = package_json.get("engines") if isinstance(package_json, dict) else None
    if isinstance(engines, dict):
        if engines.get("node"):
            pins["node.engines"] = str(engines["node"])
        if engines.get("pnpm"):
            pins["pnpm.engines"] = str(engines["pnpm"])
    if isinstance(package_json, dict) and package_json.get("packageManager"):
        pins["packageManager"] = str(package_json["packageManager"])
    for filename, key in ((".nvmrc", "node.nvmrc"), (".node-version", "node.node-version")):
        raw = read_text(os.path.join(repo_root, filename))
        if raw and raw.strip():
            pins[key] = raw.strip()
    return pins


def satisfies(actual: str, pin: str) -> bool:
    """Compare an installed version against a pin.

    Supports the pin shapes this repo can realistically contain: an exact
    version, ``>=x.y.z``, ``^x.y.z``, ``~x.y.z`` and ``x.y.z || >=a.b.c``. It is
    intentionally not a full semver range implementation - anything it does not
    understand is reported as ``WARN`` with both strings shown, rather than
    guessed at.
    """

    actual_parts = parse_version(actual)
    if actual_parts is None:
        return False
    for clause in str(pin).split("||"):
        clause = clause.strip()
        if not clause:
            continue
        pinned = parse_version(clause)
        if pinned is None:
            continue
        if clause.startswith(">="):
            if actual_parts >= pinned:
                return True
        elif clause.startswith("^"):
            if actual_parts[0] == pinned[0] and actual_parts >= pinned:
                return True
        elif clause.startswith("~"):
            if actual_parts[:2] == pinned[:2] and actual_parts >= pinned:
                return True
        elif actual_parts == pinned or actual_parts[: len(pinned)] == pinned:
            return True
    return False


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_required_variables(report: Report, environ: dict[str, str]) -> None:
    missing = []
    weak = []
    for name, description, example in REQUIRED_VARIABLES:
        value = environ.get(name, "")
        if not value.strip() or PLACEHOLDER_PATTERN.match(value.strip()):
            missing.append((name, description, example))
        elif name.endswith("_KEY") and len(value.strip()) < MIN_SECRET_LENGTH:
            weak.append((name, len(value.strip())))
    if missing:
        detail = "; ".join(f"{name} ({description})" for name, description, _ in missing)
        remedy = " ".join(f"export {name}='{example}'" for name, _, example in missing)
        report.record(
            "env.required",
            Status.FAIL,
            f"{len(missing)} required variable(s) missing or placeholder: {detail}",
            command="env | sort",
            remedy=f"Set them, e.g.: {remedy}",
            missing=[name for name, _, _ in missing],
        )
    else:
        report.record(
            "env.required",
            Status.PASS,
            f"All {len(REQUIRED_VARIABLES)} required variables are set.",
            command="env | sort",
        )
    for name, length in weak:
        report.record(
            f"env.strength.{name}",
            Status.FAIL,
            f"{name} is {length} characters; keys must be at least {MIN_SECRET_LENGTH}.",
            remedy=(
                'Regenerate: python3 -c "import secrets;print(secrets.token_urlsafe(32))" '
                f"and set {name}."
            ),
        )


def check_feature_variables(report: Report, environ: dict[str, str]) -> None:
    for name, description in FEATURE_VARIABLES:
        value = environ.get(name, "").strip()
        if not value:
            report.record(
                f"env.feature.{name}",
                Status.WARN,
                f"{name} is not set - {description}. The feature stays disabled.",
                remedy=(
                    f"Leave unset if the feature is intentionally off; otherwise set {name} "
                    "before enabling CHECKIN_LAST_FOUR_LOOKUP_ENABLED."
                ),
            )
        elif len(value) < MIN_SECRET_LENGTH:
            report.record(
                f"env.feature.{name}",
                Status.FAIL,
                f"{name} is only {len(value)} characters. A four-digit HMAC salt this short "
                "is enumerable offline.",
                remedy=f"Regenerate {name} with at least {MIN_SECRET_LENGTH} characters.",
            )
        else:
            report.record(
                f"env.feature.{name}", Status.PASS, f"{name} is set ({len(value)} characters)."
            )


def check_profile(report: Report, environ: dict[str, str], declared_profile: str | None) -> str:
    profile = (declared_profile or environ.get("VAV_ENV") or environ.get("APP_ENV") or "").strip()
    if not profile:
        report.record(
            "env.profile",
            Status.FAIL,
            "No deployment profile declared (VAV_ENV / APP_ENV / --profile).",
            remedy="export VAV_ENV=local  # or ci | staging | production",
        )
        return ""
    report.record("env.profile", Status.PASS, f"Profile is '{profile}'.", command="echo $VAV_ENV")
    return profile.lower()


def check_provider_credentials(report: Report, environ: dict[str, str], profile: str) -> None:
    found = detect_live_credentials(environ)
    if profile in PRODUCTION_PROFILES:
        report.record(
            "env.provider_credentials",
            Status.PASS,
            f"Production profile; {len(found)} provider credential(s) present, as expected.",
            command="env | grep -E 'STRIPE|ALIPAY|WECHAT|TWILIO|SENDGRID|AWS|ALIYUN'",
        )
        return
    if not found:
        report.record(
            "env.provider_credentials",
            Status.PASS,
            f"No live-looking provider credentials in the '{profile or 'unknown'}' profile.",
            command="env | grep -E 'STRIPE|ALIPAY|WECHAT|TWILIO|SENDGRID|AWS|ALIYUN'",
        )
        return
    names = ", ".join(f"{name} ({description})" for name, description in found)
    report.record(
        "env.provider_credentials",
        Status.FAIL,
        (
            f"{len(found)} provider credential(s) look real in the non-production profile "
            f"'{profile}': {names}. A test run with these loaded can charge a real card or "
            "message a real member."
        ),
        command="env | grep -E 'STRIPE|ALIPAY|WECHAT|TWILIO|SENDGRID|AWS|ALIYUN'",
        remedy=(
            "Unset them for this shell (unset " + " ".join(name for name, _ in found) + "), "
            "or switch to the provider's sandbox credentials, or set VAV_ENV=production "
            "if this genuinely is production."
        ),
        variables=[name for name, _ in found],
    )


def check_toolchain(report: Report, repo_root: str) -> None:
    pins = read_pinned_versions(repo_root)
    if not pins:
        report.record(
            "toolchain.pins",
            Status.BLOCKED,
            f"No Node/pnpm pin found under {repo_root} (package.json engines, .nvmrc, "
            ".node-version, packageManager).",
            command=f"ls {repo_root}/package.json {repo_root}/.nvmrc",
            remedy=(
                "Add the pin to package.json 'engines' and .nvmrc so this check has a source "
                "of truth. Until then the toolchain is unverified."
            ),
        )
        return
    report.record(
        "toolchain.pins",
        Status.PASS,
        "Declared pins: " + ", ".join(f"{key}={value}" for key, value in sorted(pins.items())),
        command=f"cat {repo_root}/package.json",
        pins=pins,
    )

    node_pin = pins.get("node.engines") or pins.get("node.nvmrc") or pins.get("node.node-version")
    _check_binary(report, "node", ["node", "--version"], node_pin)

    pnpm_pin = pins.get("pnpm.engines")
    if not pnpm_pin and pins.get("packageManager", "").startswith("pnpm@"):
        pnpm_pin = pins["packageManager"].split("@", 1)[1]
    _check_binary(report, "pnpm", ["pnpm", "--version"], pnpm_pin)


def _check_binary(report: Report, tool: str, argv: list[str], pin: str | None) -> None:
    command = " ".join(argv)
    if pin is None:
        report.record(
            f"toolchain.{tool}",
            Status.WARN,
            f"No pin declared for {tool}; the installed version is not checked.",
            command=command,
            remedy=f"Declare {tool} in package.json 'engines' to make this enforceable.",
        )
        return
    output = run_command(argv, timeout=20)
    if output.missing:
        report.record(
            f"toolchain.{tool}",
            Status.BLOCKED,
            f"{tool} is not installed or not on PATH; pinned {pin}.",
            command=command,
            remedy=f"Install {tool} {pin} (corepack enable, or your version manager) and re-run.",
        )
        return
    if not output.ok:
        report.record(
            f"toolchain.{tool}",
            Status.BLOCKED,
            f"`{command}` exited {output.returncode}: {output.stderr.strip()[:200]}",
            command=command,
            remedy=f"Repair the {tool} installation and re-run.",
        )
        return
    actual = output.stdout.strip()
    if satisfies(actual, pin):
        report.record(
            f"toolchain.{tool}",
            Status.PASS,
            f"{tool} {actual} satisfies the pinned {pin}.",
            command=command,
        )
    elif parse_version(actual) is None:
        report.record(
            f"toolchain.{tool}",
            Status.WARN,
            f"Could not parse `{command}` output {actual!r} against pin {pin}.",
            command=command,
            remedy="Compare by hand; this script does not guess at unparseable versions.",
        )
    else:
        report.record(
            f"toolchain.{tool}",
            Status.FAIL,
            f"{tool} {actual} does not satisfy the pinned {pin}.",
            command=command,
            remedy=f"Install {tool} {pin}. Mismatched toolchains produce lockfile churn and "
            "builds that only fail in CI.",
        )


def _safe(report: Report, name: str, command: str, func, *args) -> None:  # noqa: ANN001, ANN401
    """Run one check group, turning an escaping exception into a BLOCKED result.

    Every check below writes its own results into ``report``; this only exists so
    that a bug in one group cannot take the whole report down with a traceback.
    """

    try:
        func(report, *args)
    except Exception as exc:  # noqa: BLE001 - a preflight must never crash
        report.record(
            name,
            Status.BLOCKED,
            f"{type(exc).__name__}: {exc}",
            command=command,
            remedy="This check could not run; fix the error above and re-run.",
        )


def build_report(
    environ: dict[str, str], *, repo_root: str, declared_profile: str | None = None
) -> Report:
    report = Report(
        "verify_environment",
        "OPS-002 environment preflight: configuration, toolchain pins, credential isolation.",
    )
    resolved_profile = (
        (declared_profile or environ.get("VAV_ENV") or environ.get("APP_ENV") or "").strip().lower()
    )
    _safe(report, "env.profile", "echo $VAV_ENV", check_profile, environ, declared_profile)
    _safe(report, "env.required", "env | sort", check_required_variables, environ)
    _safe(report, "env.feature", "env | sort", check_feature_variables, environ)
    _safe(
        report,
        "env.provider_credentials",
        "env | grep -E 'STRIPE|ALIPAY|WECHAT|TWILIO|SENDGRID|AWS|ALIYUN'",
        check_provider_credentials,
        environ,
        resolved_profile,
    )
    _safe(report, "toolchain.pins", f"cat {repo_root}/package.json", check_toolchain, repo_root)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--profile", default=None, help="Override VAV_ENV for this run.")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: auto-detect).")
    parser.add_argument(
        "--json", dest="json_path", default=None, help="Write the machine-readable report here."
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress the human summary.")
    args = parser.parse_args(argv)

    repo_root = args.repo_root or find_repo_root(os.path.dirname(os.path.abspath(__file__)))
    report = build_report(dict(os.environ), repo_root=repo_root, declared_profile=args.profile)
    return report.emit(args.json_path, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
