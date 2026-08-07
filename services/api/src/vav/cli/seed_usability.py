# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from vav.core.database import session_factory

ROOT = Path(__file__).resolve().parents[5]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


async def seed_usability() -> None:
    manifest = yaml.safe_load((ROOT / "config/usability/manifest.yaml").read_text())
    async with session_factory() as session:
        for item in manifest["critical_scenarios"]:
            await session.execute(
                text(
                    "INSERT INTO usability_uat_scenarios (scenario_code,semantic_version,title,persona_code,business_domain,criticality,preconditions,steps,expected_outcomes,automation_level,required_locales,required_device_profiles,lifecycle_status) VALUES (:code,'1.0.0',:title,:persona,:domain,'critical','[]'::jsonb,CAST(:steps AS jsonb),CAST(:outcomes AS jsonb),'hybrid',CAST(:locales AS jsonb),CAST(:devices AS jsonb),'active') ON CONFLICT (scenario_code,semantic_version) DO UPDATE SET required_locales=EXCLUDED.required_locales,required_device_profiles=EXCLUDED.required_device_profiles,lifecycle_status='active'"
                ),
                {
                    **item,
                    "title": item["code"].replace("-", " ").title(),
                    "steps": _json(
                        ["open_entry", "complete_task", "verify_result", "verify_recovery"]
                    ),
                    "outcomes": _json(
                        ["business_state_correct", "no_dead_end", "support_path_available"]
                    ),
                    "locales": _json(item["locales"]),
                    "devices": _json(item["devices"]),
                },
            )
        await session.execute(
            text(
                "INSERT INTO usability_synthetic_blueprints (blueprint_code,semantic_version,persona_manifest,scenario_manifest,scale_profile,deterministic_seed,external_side_effects_allowed,lifecycle_status) VALUES ('SYNTHETIC-STANDARD','1.0.0',CAST(:personas AS jsonb),CAST(:scenarios AS jsonb),'standard',27001,false,'active') ON CONFLICT (blueprint_code,semantic_version) DO UPDATE SET persona_manifest=EXCLUDED.persona_manifest,scenario_manifest=EXCLUDED.scenario_manifest,lifecycle_status='active'"
            ),
            {
                "personas": _json(manifest["personas"]),
                "scenarios": _json([item["code"] for item in manifest["critical_scenarios"]]),
            },
        )
        await session.execute(
            text(
                "INSERT INTO usability_demo_environments (environment_code,base_url,provider_profile,synthetic_only,external_side_effects_disabled,status) VALUES ('demo-local','http://localhost:4173','fake',true,true,'ready') ON CONFLICT (environment_code) DO UPDATE SET provider_profile='fake',synthetic_only=true,external_side_effects_disabled=true,status='ready'"
            )
        )
        compatibility = manifest["compatibility"]
        await session.execute(
            text(
                "INSERT INTO usability_compatibility_policies (policy_code,semantic_version,browser_matrix,device_matrix,input_matrix,network_matrix,critical_journeys,lifecycle_status) VALUES ('COMPATIBILITY-CRITICAL','1.0.0',CAST(:browsers AS jsonb),CAST(:devices AS jsonb),CAST(:inputs AS jsonb),CAST(:networks AS jsonb),CAST(:journeys AS jsonb),'active') ON CONFLICT (policy_code,semantic_version) DO UPDATE SET browser_matrix=EXCLUDED.browser_matrix,device_matrix=EXCLUDED.device_matrix,input_matrix=EXCLUDED.input_matrix,network_matrix=EXCLUDED.network_matrix,critical_journeys=EXCLUDED.critical_journeys,lifecycle_status='active'"
            ),
            {
                "browsers": _json(compatibility["browsers"]),
                "devices": _json(compatibility["devices"]),
                "inputs": _json(compatibility["inputs"]),
                "networks": _json(compatibility["networks"]),
                "journeys": _json([item["code"] for item in manifest["critical_scenarios"]]),
            },
        )
        for locale in manifest["locales"]:
            await session.execute(
                text(
                    "INSERT INTO usability_locale_registry (locale_code,display_name,direction,fallback_locale,date_format,time_format,lifecycle_status) VALUES (:locale,:locale,'ltr','en','yyyy-MM-dd','HH:mm','active') ON CONFLICT (locale_code) DO UPDATE SET lifecycle_status='active'"
                ),
                {"locale": locale},
            )
        for item in manifest["drafts"]:
            await session.execute(
                text(
                    "INSERT INTO usability_draft_definitions (draft_code,semantic_version,owning_module,schema_definition,sensitive_fields,ttl_seconds,conflict_policy,lifecycle_status) VALUES (:code,'1.0.0',:owner,CAST(:schema AS jsonb),CAST(:sensitive AS jsonb),:ttl_seconds,:conflict,'active') ON CONFLICT (draft_code,semantic_version) DO UPDATE SET schema_definition=EXCLUDED.schema_definition,sensitive_fields=EXCLUDED.sensitive_fields,ttl_seconds=EXCLUDED.ttl_seconds,conflict_policy=EXCLUDED.conflict_policy,lifecycle_status='active'"
                ),
                {
                    **item,
                    "schema": _json({"type": "object"}),
                    "sensitive": _json(item["sensitive"]),
                },
            )
        for item in manifest["imports"]:
            await session.execute(
                text(
                    "INSERT INTO usability_import_definitions (import_code,semantic_version,owning_module,schema_definition,maximum_rows,dry_run_required,command_code,lifecycle_status) VALUES (:code,'1.0.0',:owner,CAST(:schema AS jsonb),:maximum_rows,true,:command,'active') ON CONFLICT (import_code,semantic_version) DO UPDATE SET schema_definition=EXCLUDED.schema_definition,maximum_rows=EXCLUDED.maximum_rows,command_code=EXCLUDED.command_code,lifecycle_status='active'"
                ),
                {**item, "schema": _json({"type": "object", "required": ["external_id"]})},
            )
        for item in manifest["support_playbooks"]:
            await session.execute(
                text(
                    "INSERT INTO usability_support_playbooks (playbook_code,semantic_version,owning_module,issue_type,diagnostic_steps,allowed_resolution_codes,escalation_policy,safety_boundary,lifecycle_status) VALUES (:code,'1.0.0',:owner,:code,CAST(:diagnostics AS jsonb),CAST(:resolutions AS jsonb),CAST(:escalation AS jsonb),CAST(:boundary AS jsonb),'draft') ON CONFLICT (playbook_code,semantic_version) DO UPDATE SET allowed_resolution_codes=EXCLUDED.allowed_resolution_codes,lifecycle_status='draft'"
                ),
                {
                    **item,
                    "resolutions": _json([item["resolution"]]),
                    "diagnostics": _json(["inspect_safe_summary", "verify_current_state"]),
                    "escalation": _json({"critical": "on_call"}),
                    "boundary": _json({"no_direct_state_edit": True}),
                },
            )
        await session.commit()
    print(
        f"Usability seed complete: {len(manifest['critical_scenarios'])} critical UAT scenarios, {len(manifest['personas'])} personas; production remains NOT_CERTIFIED"
    )


if __name__ == "__main__":
    asyncio.run(seed_usability())
