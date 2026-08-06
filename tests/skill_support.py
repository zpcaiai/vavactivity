from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from vav_skill_sdk.context import SkillContext, SkillPrincipal
from vav_skill_sdk.manifest import validate_manifest
from vav_skill_runtime.registry import RegisteredVersion

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skill-packs/examples/vav.example.echo"


def registered_version(
    *,
    version: str = "1.0.0",
    signature_status: str = "verified",
    trust_level: str = "official_signed",
) -> RegisteredVersion:
    manifest = validate_manifest(EXAMPLE / "skill.yaml")
    if version != manifest.metadata.version:
        payload = manifest.canonical()
        payload["metadata"]["version"] = version
        manifest = manifest.__class__.model_validate(payload)
    return RegisteredVersion(
        manifest=manifest,
        input_schema=json.loads((EXAMPLE / "schemas/input.schema.json").read_text()),
        output_schema=json.loads((EXAMPLE / "schemas/output.schema.json").read_text()),
        error_schema=json.loads((EXAMPLE / "schemas/error.schema.json").read_text()),
        package_checksum=f"checksum-{version}",
        signature_status=signature_status,  # type: ignore[arg-type]
        security_status="passed",
        review_status="approved",
        trust_level=trust_level,  # type: ignore[arg-type]
    )


def context(
    *,
    permissions: frozenset[str] = frozenset(),
    idempotency_key: str | None = None,
    actor_user_id: UUID | None = None,
) -> SkillContext:
    return SkillContext(
        execution_id=uuid4(),
        installation_id=uuid4(),
        actor_user_id=actor_user_id,
        principal=SkillPrincipal(principal_type="service", principal_id="runtime-test"),
        locale="en",
        timezone="UTC",
        idempotency_key=idempotency_key,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        permissions=permissions,
        request_id=uuid4(),
        trace_id=uuid4().hex,
    )
