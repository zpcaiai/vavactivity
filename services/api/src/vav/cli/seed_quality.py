# ruff: noqa: E501

"""Seed governed Batch 21 quality definitions without fabricating approval evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

ROOT = Path(__file__).resolve().parents[5]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


async def seed_quality() -> None:
    await ensure_system_user()
    manifest = yaml.safe_load((ROOT / "quality-manifest.yaml").read_text(encoding="utf-8"))
    async with session_factory() as session:
        for requirement in manifest["requirements"]:
            await session.execute(
                text(
                    "INSERT INTO quality_requirements "
                    "(requirement_code,title,description,source_type,source_reference,source_version,"
                    "requirement_type,business_domain,criticality,status,acceptance_criteria,"
                    "non_functional_criteria,owner_team,introduced_in_batch,target_release,created_by,"
                    "content_fingerprint) VALUES (:code,:title,:description,:source,:reference,'1.0.0',"
                    "'business',:domain,:criticality,'draft',CAST(:acceptance AS jsonb),'{}'::jsonb,"
                    ":owner,:batch,NULL,:actor,:fingerprint) ON CONFLICT (requirement_code) DO UPDATE "
                    "SET title=EXCLUDED.title,description=EXCLUDED.description,"
                    "source_reference=EXCLUDED.source_reference,criticality=EXCLUDED.criticality,"
                    "owner_team=EXCLUDED.owner_team,content_fingerprint=EXCLUDED.content_fingerprint,"
                    "updated_at=now()"
                ),
                {
                    "code": requirement["code"],
                    "title": requirement["title"],
                    "description": (
                        "Governed closure requirement imported from "
                        f"{requirement['source']} for {requirement['module']}."
                    ),
                    "source": requirement["source"],
                    "reference": "ChatGPT-Codex 实现项目方案.md",
                    "domain": requirement["module"],
                    "criticality": requirement["criticality"],
                    "acceptance": _json(
                        [
                            {"criterion": "traceability_complete", "required": True},
                            {"criterion": "current_evidence_accepted", "required": True},
                        ]
                    ),
                    "owner": f"{requirement['module']}_engineering",
                    "batch": requirement["batch"],
                    "actor": SYSTEM_USER_ID,
                    "fingerprint": _fingerprint(requirement),
                },
            )
        for capability in manifest["capabilities"]:
            await session.execute(
                text(
                    "INSERT INTO quality_capabilities "
                    "(capability_code,name,description,capability_type,module_code,criticality,"
                    "lifecycle_status,owning_service,primary_actor_type,current_version,owner_team,"
                    "created_by) VALUES (:code,:name,:description,'admin_action',:module,:criticality,"
                    "'available','api','administrator','1.0.0','quality_engineering',:actor) "
                    "ON CONFLICT (capability_code) DO UPDATE SET name=EXCLUDED.name,"
                    "description=EXCLUDED.description,criticality=EXCLUDED.criticality,updated_at=now()"
                ),
                {
                    "code": capability["code"],
                    "name": capability["name"],
                    "description": f"Batch 21 governed capability: {capability['name']}.",
                    "module": capability["module"],
                    "criticality": capability["criticality"],
                    "actor": SYSTEM_USER_ID,
                },
            )
        for gate in manifest["gates"]:
            await session.execute(
                text(
                    "INSERT INTO quality_gate_definitions "
                    "(gate_code,semantic_version,name,category,enforcement_level,condition_definition,"
                    "required_evidence_types,applicable_release_types,applicable_modules,status,created_by) "
                    "VALUES (:code,'1.0.0',:name,'release',:level,CAST(:condition AS jsonb),"
                    "CAST(:evidence AS jsonb),'[\"standard\"]'::jsonb,'[]'::jsonb,'draft',:actor) "
                    "ON CONFLICT (gate_code,semantic_version) DO UPDATE SET name=EXCLUDED.name,"
                    "condition_definition=EXCLUDED.condition_definition,"
                    "required_evidence_types=EXCLUDED.required_evidence_types"
                ),
                {
                    "code": gate["code"],
                    "name": gate["code"].replace("-", " ").title(),
                    "level": gate["level"],
                    "condition": _json(
                        {
                            "metric": gate["metric"],
                            "operator": gate["operator"],
                            "expected": gate["expected"],
                        }
                    ),
                    "evidence": _json([gate["evidence"]]),
                    "actor": SYSTEM_USER_ID,
                },
            )
        await session.commit()
    print(
        "Quality seed complete: "
        f"{len(manifest['requirements'])} requirements, "
        f"{len(manifest['capabilities'])} capabilities, {len(manifest['gates'])} draft gates; "
        "human approval still required"
    )


if __name__ == "__main__":
    asyncio.run(seed_quality())
