# ruff: noqa: E501

"""Synchronize Batch 25 data-governance manifests idempotently."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

ROOT = Path(__file__).resolve().parents[5]
CONFIG = ROOT / "config/data"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _load(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load((CONFIG / name).read_text(encoding="utf-8")))


async def seed_data_governance() -> None:
    await ensure_system_user()
    ownership = _load("ownership.yaml")
    contracts = _load("contracts.yaml")
    lineage = _load("lineage.yaml")
    reconciliations = _load("reconciliations.yaml")
    rules = _load("quality-rules.yaml")
    backfills = _load("backfills.yaml")
    async with session_factory() as session:
        asset_ids: dict[str, Any] = {}
        for asset in ownership["assets"]:
            asset_id = await session.scalar(
                text(
                    "INSERT INTO data_assets (asset_code,display_name,asset_type,owning_module,owning_service,source_of_truth,projection,rebuildable,data_steward_team,classification,retention_policy_code,erasure_policy_code,canonical_identifier_policy,version_policy,mutation_policy,storage_location_type,storage_reference,lifecycle_status,manifest_checksum_sha256) VALUES (:code,:name,:type,:module,'api',:truth,:projection,:rebuildable,:steward,:classification,:retention,:erasure,CAST(:identifier AS jsonb),CAST(:version AS jsonb),CAST(:mutation AS jsonb),:type,:reference,'active',:checksum) ON CONFLICT (asset_code) DO UPDATE SET display_name=EXCLUDED.display_name,asset_type=EXCLUDED.asset_type,owning_module=EXCLUDED.owning_module,source_of_truth=EXCLUDED.source_of_truth,projection=EXCLUDED.projection,rebuildable=EXCLUDED.rebuildable,data_steward_team=EXCLUDED.data_steward_team,classification=EXCLUDED.classification,retention_policy_code=EXCLUDED.retention_policy_code,erasure_policy_code=EXCLUDED.erasure_policy_code,canonical_identifier_policy=EXCLUDED.canonical_identifier_policy,version_policy=EXCLUDED.version_policy,mutation_policy=EXCLUDED.mutation_policy,lifecycle_status='active',manifest_checksum_sha256=EXCLUDED.manifest_checksum_sha256,updated_at=now() RETURNING id"
                ),
                {
                    "code": asset["code"],
                    "name": asset["name"],
                    "type": asset["type"],
                    "module": asset["module"],
                    "truth": asset["truth"],
                    "projection": asset["projection"],
                    "rebuildable": asset["rebuildable"],
                    "steward": f"{asset['module']}_data_stewards",
                    "classification": asset["classification"],
                    "retention": asset["retention"],
                    "erasure": asset["erasure"],
                    "identifier": _json(
                        {"canonical_field": asset["identifier"], "email_phone_forbidden": True}
                    ),
                    "version": _json({"field": "version", "monotonic": True}),
                    "mutation": _json(
                        {
                            "registered_domain_command_required": asset["truth"],
                            "projection_builder_required": asset["projection"],
                        }
                    ),
                    "reference": asset["code"],
                    "checksum": _hash(asset),
                },
            )
            asset_ids[asset["code"]] = asset_id

        for contract in contracts["contracts"]:
            schema = {
                "type": "object",
                "required": contract["required"],
                "properties": {field: {"type": "string"} for field in contract["required"]},
                "additionalProperties": True,
            }
            policies = {
                field: {
                    "classification": "highly_restricted",
                    "logging": "forbidden",
                    "search": "forbidden",
                    "export": "encrypted",
                    "erasure": "policy_driven",
                }
                for field in contract["sensitive"]
            }
            await session.execute(
                text(
                    "INSERT INTO data_contracts (contract_code,semantic_version,contract_type,asset_id,producer_module,consumer_modules,schema_definition,field_policies,compatibility_policy,quality_expectations,status,schema_checksum_sha256,activated_at) VALUES (:code,'1.0.0',:type,:asset,:producer,CAST(:consumers AS jsonb),CAST(:schema AS jsonb),CAST(:policies AS jsonb),:compatibility,CAST(:quality AS jsonb),'active',:checksum,now()) ON CONFLICT (contract_code,semantic_version) DO UPDATE SET asset_id=EXCLUDED.asset_id,producer_module=EXCLUDED.producer_module,consumer_modules=EXCLUDED.consumer_modules,schema_definition=EXCLUDED.schema_definition,field_policies=EXCLUDED.field_policies,compatibility_policy=EXCLUDED.compatibility_policy,quality_expectations=EXCLUDED.quality_expectations,status='active',schema_checksum_sha256=EXCLUDED.schema_checksum_sha256,activated_at=COALESCE(data_contracts.activated_at,now())"
                ),
                {
                    "code": contract["code"],
                    "type": contract["type"],
                    "asset": asset_ids[contract["asset"]],
                    "producer": contract["producer"],
                    "consumers": _json(contract["consumers"]),
                    "schema": _json(schema),
                    "policies": _json(policies),
                    "compatibility": contract["policy"],
                    "quality": _json(
                        {"required_fields_present": True, "consumer_contract_tests": True}
                    ),
                    "checksum": _hash(schema),
                },
            )

        for edge in lineage["edges"]:
            await session.execute(
                text(
                    "INSERT INTO data_lineage_edges (source_asset_id,target_asset_id,transformation_type,field_mapping,propagation_mode,expected_lag_seconds,erasure_propagation,retention_inheritance,release_version,active) VALUES (:source,:target,:transform,'{}'::jsonb,:mode,:lag,:erasure,true,:release,true) ON CONFLICT (source_asset_id,target_asset_id,transformation_type) DO UPDATE SET propagation_mode=EXCLUDED.propagation_mode,expected_lag_seconds=EXCLUDED.expected_lag_seconds,erasure_propagation=EXCLUDED.erasure_propagation,retention_inheritance=EXCLUDED.retention_inheritance,release_version=EXCLUDED.release_version,active=true"
                ),
                {
                    "source": asset_ids[edge["source"]],
                    "target": asset_ids[edge["target"]],
                    "transform": edge["transform"],
                    "mode": edge["mode"],
                    "lag": edge["lag"],
                    "erasure": edge["erasure"],
                    "release": lineage["release_version"],
                },
            )

        for item in reconciliations["reconciliations"]:
            await session.execute(
                text(
                    "INSERT INTO data_reconciliation_definitions (reconciliation_code,source_asset_id,target_asset_id,authoritative_side,comparison_keys,comparison_fields,severity,repair_command_code,active) VALUES (:code,:source,:target,:authority,CAST(:keys AS jsonb),CAST(:fields AS jsonb),'critical',:repair,true) ON CONFLICT (reconciliation_code) DO UPDATE SET source_asset_id=EXCLUDED.source_asset_id,target_asset_id=EXCLUDED.target_asset_id,authoritative_side=EXCLUDED.authoritative_side,comparison_keys=EXCLUDED.comparison_keys,comparison_fields=EXCLUDED.comparison_fields,repair_command_code=EXCLUDED.repair_command_code,active=true"
                ),
                {
                    "code": item["code"],
                    "source": asset_ids[item["source"]],
                    "target": asset_ids[item["target"]],
                    "authority": item["authority"],
                    "keys": _json(item["keys"]),
                    "fields": _json(item["fields"]),
                    "repair": item["repair"],
                },
            )
            repair_type = (
                "projection_rebuild"
                if any(
                    marker in item["repair"] for marker in ("rebuild", "projection", "invalidate")
                )
                else "domain_command"
            )
            await session.execute(
                text(
                    "INSERT INTO data_repair_definitions (repair_code,owning_module,repair_type,command_code,approval_required,postconditions,active) VALUES (:code,:module,:type,:command,true,CAST(:postconditions AS jsonb),true) ON CONFLICT (repair_code) DO UPDATE SET owning_module=EXCLUDED.owning_module,repair_type=EXCLUDED.repair_type,command_code=EXCLUDED.command_code,approval_required=true,postconditions=EXCLUDED.postconditions,active=true"
                ),
                {
                    "code": f"repair.{item['code']}",
                    "module": item["repair"].split(".")[0],
                    "type": repair_type,
                    "command": item["repair"],
                    "postconditions": _json(
                        ["authoritative_source_rechecked", "difference_absent_after_reconciliation"]
                    ),
                },
            )

        for rule in rules["rules"]:
            await session.execute(
                text(
                    "INSERT INTO data_quality_rules (rule_code,version,asset_id,dimension,severity,declarative_rule,sample_policy,schedule_policy,status) VALUES (:code,1,:asset,:dimension,:severity,CAST(:rule AS jsonb),CAST(:sample AS jsonb),CAST(:schedule AS jsonb),'active') ON CONFLICT (rule_code,version) DO UPDATE SET asset_id=EXCLUDED.asset_id,dimension=EXCLUDED.dimension,severity=EXCLUDED.severity,declarative_rule=EXCLUDED.declarative_rule,sample_policy=EXCLUDED.sample_policy,schedule_policy=EXCLUDED.schedule_policy,status='active'"
                ),
                {
                    "code": rule["code"],
                    "asset": asset_ids[rule["asset"]],
                    "dimension": rule["dimension"],
                    "severity": rule["severity"],
                    "rule": _json(
                        {
                            key: value
                            for key, value in rule.items()
                            if key not in {"code", "asset", "dimension", "severity"}
                        }
                    ),
                    "sample": _json({"maximum": 10, "minimized": True, "sensitive_values": False}),
                    "schedule": _json({"mode": "scheduled", "interval_seconds": 3600}),
                },
            )

        for item in backfills["backfills"]:
            await session.execute(
                text(
                    "INSERT INTO data_backfill_definitions (backfill_code,target_asset_id,candidate_query_code,transformation_code,validation_code,chunk_size,rate_limit_per_minute,approval_required,rollback_boundary,active) VALUES (:code,:target,:candidate,:transform,:validate,:chunk,:rate,:approval,CAST(:rollback AS jsonb),true) ON CONFLICT (backfill_code) DO UPDATE SET target_asset_id=EXCLUDED.target_asset_id,candidate_query_code=EXCLUDED.candidate_query_code,transformation_code=EXCLUDED.transformation_code,validation_code=EXCLUDED.validation_code,chunk_size=EXCLUDED.chunk_size,rate_limit_per_minute=EXCLUDED.rate_limit_per_minute,approval_required=EXCLUDED.approval_required,rollback_boundary=EXCLUDED.rollback_boundary,active=true"
                ),
                {
                    "code": item["code"],
                    "target": asset_ids[item["target"]],
                    "candidate": item["candidate"],
                    "transform": item["transform"],
                    "validate": item["validate"],
                    "chunk": item["chunk"],
                    "rate": item["rate"],
                    "approval": item["approval"],
                    "rollback": _json({"projection_only": True, "source_facts_immutable": True}),
                },
            )

        gates = {
            "GATE-DATA-CONTRACT-COVERAGE": ("critical_contract_coverage_percent", 100),
            "GATE-DATA-LINEAGE-COVERAGE": ("critical_lineage_coverage_percent", 100),
            "GATE-DATA-EVENT-GAPS": ("open_critical_event_gaps", 0),
            "GATE-DATA-RECONCILIATION": ("open_critical_reconciliation_differences", 0),
            "GATE-DATA-ERASURE-COMPLETENESS": ("critical_erasure_verification_failures", 0),
            "GATE-DATA-DOMAIN-CERTIFICATION": ("critical_data_domain_certification_percent", 100),
        }
        for code, (metric, expected) in gates.items():
            await session.execute(
                text(
                    "INSERT INTO quality_gate_definitions (gate_code,semantic_version,name,category,enforcement_level,condition_definition,required_evidence_types,applicable_release_types,applicable_modules,status,created_by) VALUES (:code,'1.0.0',:name,'release','blocker',CAST(:condition AS jsonb),'[\"data_contract\",\"lineage\",\"reconciliation\",\"erasure\"]'::jsonb,'[\"standard\"]'::jsonb,'[\"data_governance\"]'::jsonb,'draft',:actor) ON CONFLICT (gate_code,semantic_version) DO UPDATE SET condition_definition=EXCLUDED.condition_definition,required_evidence_types=EXCLUDED.required_evidence_types"
                ),
                {
                    "code": code,
                    "name": code.replace("-", " ").title(),
                    "condition": _json({"metric": metric, "operator": "eq", "expected": expected}),
                    "actor": SYSTEM_USER_ID,
                },
            )
        await session.commit()
    print(
        f"Data governance seed complete: {len(ownership['assets'])} assets, {len(contracts['contracts'])} contracts, {len(lineage['edges'])} lineage edges, {len(reconciliations['reconciliations'])} reconciliations; production certification remains NOT_CERTIFIED"
    )


if __name__ == "__main__":
    asyncio.run(seed_data_governance())
