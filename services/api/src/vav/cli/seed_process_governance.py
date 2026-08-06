# ruff: noqa: E501

"""Idempotently synchronize Batch 24 process manifests."""

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
CONFIG = ROOT / "config/process"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load((CONFIG / name).read_text(encoding="utf-8")))


def _checksum(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _step_type(code: str) -> str:
    if code.startswith("await-"):
        return "event_wait"
    if code in {
        "counselor-confirmation",
        "safety-review",
        "triage-case",
        "decide-action",
        "independent-review",
        "release-decision",
    }:
        return "human_task"
    if "provider" in code or code in {"charge-provider", "send-provider"}:
        return "provider_call"
    return "command"


async def seed_process_governance() -> None:
    await ensure_system_user()
    process_manifest = _load("business-processes.yaml")
    machine_manifest = _load("state-machines.yaml")
    compensation_manifest = _load("compensations.yaml")
    async with session_factory() as session:
        for process in process_manifest["processes"]:
            checksum = _checksum(process)
            definition_id = await session.scalar(
                text(
                    "INSERT INTO process_definitions (process_code,version,process_type,business_domain,criticality,owner_team,participant_modules,actor_types,start_condition,terminal_states,sla_seconds,cancellation_policy,compensation_policy,stuck_policy,status,manifest_checksum_sha256,activated_at) VALUES (:code,1,:type,:domain,'critical',:owner,CAST(:modules AS jsonb),CAST(:actors AS jsonb),CAST(:start AS jsonb),CAST(:terminals AS jsonb),:sla,CAST(:cancellation AS jsonb),CAST(:compensation AS jsonb),CAST(:stuck AS jsonb),'active',:checksum,now()) ON CONFLICT (process_code,version) DO UPDATE SET process_type=EXCLUDED.process_type,business_domain=EXCLUDED.business_domain,owner_team=EXCLUDED.owner_team,participant_modules=EXCLUDED.participant_modules,actor_types=EXCLUDED.actor_types,sla_seconds=EXCLUDED.sla_seconds,cancellation_policy=EXCLUDED.cancellation_policy,compensation_policy=EXCLUDED.compensation_policy,stuck_policy=EXCLUDED.stuck_policy,status='active',manifest_checksum_sha256=EXCLUDED.manifest_checksum_sha256,activated_at=COALESCE(process_definitions.activated_at,now()) RETURNING id"
                ),
                {
                    "code": process["code"],
                    "type": process["type"],
                    "domain": process["domain"],
                    "owner": process["owner"],
                    "modules": _json(process["modules"]),
                    "actors": _json(process["actors"]),
                    "start": _json({"registered_command_required": True}),
                    "terminals": _json(
                        {
                            "success": "succeeded",
                            "failure": "failed",
                            "cancellation": "cancelled",
                            "expiry": "expired",
                            "safety": "safety_frozen",
                            "manual": "manual_intervention",
                        }
                    ),
                    "sla": process["sla"],
                    "cancellation": _json(
                        {"user_allowed_before_irreversible_step": True, "safety_priority": True}
                    ),
                    "compensation": _json(
                        {"reverse_dependency_order": True, "preserve_irreversible_facts": True}
                    ),
                    "stuck": _json(
                        {
                            "progress_sla_seconds": max(60, min(process["sla"], 86400)),
                            "allowed_recovery_commands": [
                                "process.retry_registered_step",
                                "process.rebuild_projection",
                            ],
                        }
                    ),
                    "checksum": checksum,
                },
            )
            for index, step_code in enumerate(process["steps"], start=1):
                step_type = _step_type(step_code)
                timeout = min(process["sla"], 86400) if step_type != "command" else None
                command = (
                    None
                    if step_type == "event_wait"
                    else f"{process['owner']}.{step_code.replace('-', '_')}"
                )
                expected_events = (
                    [f"{process['owner']}.{step_code.replace('await-', '').replace('-', '_')}.v1"]
                    if step_type == "event_wait"
                    else []
                )
                await session.execute(
                    text(
                        "INSERT INTO process_step_definitions (process_definition_id,step_code,sequence,step_type,owning_module,command_code,expected_event_codes,preconditions,postconditions,timeout_seconds,retry_policy,idempotency_scope,concurrency_mode,compensation_code,required) VALUES (:definition,:code,:sequence,:type,:module,:command,CAST(:events AS jsonb),CAST(:preconditions AS jsonb),CAST(:postconditions AS jsonb),:timeout,CAST(:retry AS jsonb),'saga_step','optimistic_lock',NULL,:required) ON CONFLICT (process_definition_id,step_code) DO UPDATE SET sequence=EXCLUDED.sequence,step_type=EXCLUDED.step_type,owning_module=EXCLUDED.owning_module,command_code=EXCLUDED.command_code,expected_event_codes=EXCLUDED.expected_event_codes,preconditions=EXCLUDED.preconditions,postconditions=EXCLUDED.postconditions,timeout_seconds=EXCLUDED.timeout_seconds,retry_policy=EXCLUDED.retry_policy,idempotency_scope=EXCLUDED.idempotency_scope,concurrency_mode=EXCLUDED.concurrency_mode,required=EXCLUDED.required"
                    ),
                    {
                        "definition": definition_id,
                        "code": step_code,
                        "sequence": index,
                        "type": step_type,
                        "module": process["modules"][min(index - 1, len(process["modules"]) - 1)],
                        "command": command,
                        "events": _json(expected_events),
                        "preconditions": _json(
                            [
                                "authorization_valid",
                                "domain_state_allows_command",
                                "safety_and_privacy_rechecked",
                            ]
                        ),
                        "postconditions": _json(
                            ["typed_command_receipt", "authoritative_domain_event_or_state_version"]
                        ),
                        "timeout": timeout,
                        "retry": _json(
                            {
                                "mode": "exponential_backoff",
                                "maximum_attempts": 5,
                                "non_retryable": [
                                    "authorization",
                                    "business_conflict",
                                    "safety_restriction",
                                ],
                            }
                        ),
                        "required": not step_code.startswith("notify-"),
                    },
                )

        for machine in machine_manifest["machines"]:
            checksum = _checksum(machine)
            await session.execute(
                text(
                    "INSERT INTO state_machine_definitions (machine_code,version,owning_module,aggregate_type,initial_state,state_manifest,transition_manifest,invariant_manifest,source_location,manifest_checksum_sha256,status) VALUES (:code,1,:module,:aggregate,:initial,CAST(:states AS jsonb),CAST(:transitions AS jsonb),CAST(:invariants AS jsonb),:source,:checksum,'draft') ON CONFLICT (machine_code,version) DO UPDATE SET owning_module=EXCLUDED.owning_module,aggregate_type=EXCLUDED.aggregate_type,initial_state=EXCLUDED.initial_state,state_manifest=EXCLUDED.state_manifest,transition_manifest=EXCLUDED.transition_manifest,invariant_manifest=EXCLUDED.invariant_manifest,source_location=EXCLUDED.source_location,manifest_checksum_sha256=EXCLUDED.manifest_checksum_sha256,status=CASE WHEN state_machine_definitions.verification_status='pass' THEN 'active' ELSE 'draft' END"
                ),
                {
                    "code": machine["code"],
                    "module": machine["module"],
                    "aggregate": machine["aggregate"],
                    "initial": machine["initial"],
                    "states": _json(machine["states"]),
                    "transitions": _json(machine["transitions"]),
                    "invariants": _json(
                        [
                            "one_initial_state",
                            "terminal_states_are_final",
                            "waiting_states_have_timeout",
                            "authorization_required",
                            "idempotency_required",
                            "concurrency_policy_required",
                        ]
                    ),
                    "source": "config/process/state-machines.yaml",
                    "checksum": checksum,
                },
            )

        for compensation in compensation_manifest["compensations"]:
            await session.execute(
                text(
                    "INSERT INTO process_compensation_definitions (compensation_code,owning_module,target_command_code,input_mapping,retry_policy,reversible,human_approval_required,preserves_irreversible_facts,active) VALUES (:code,:module,:command,CAST(:mapping AS jsonb),CAST(:retry AS jsonb),:reversible,:approval,true,true) ON CONFLICT (compensation_code) DO UPDATE SET owning_module=EXCLUDED.owning_module,target_command_code=EXCLUDED.target_command_code,input_mapping=EXCLUDED.input_mapping,retry_policy=EXCLUDED.retry_policy,reversible=EXCLUDED.reversible,human_approval_required=EXCLUDED.human_approval_required,preserves_irreversible_facts=true,active=true"
                ),
                {
                    "code": compensation["code"],
                    "module": compensation["module"],
                    "command": compensation["command"],
                    "mapping": _json(
                        {"source": "typed_step_receipt", "raw_domain_mutation": False}
                    ),
                    "retry": _json({"mode": "exponential_backoff", "maximum_attempts": 3}),
                    "reversible": compensation["reversible"],
                    "approval": compensation["approval"],
                },
            )

        gates = {
            "GATE-PROCESS-STATE-MACHINE": ("invalid_critical_state_machines", 0),
            "GATE-PROCESS-SAGA-IDEMPOTENCY": ("critical_saga_duplicate_side_effects", 0),
            "GATE-PROCESS-COMPENSATION": ("critical_compensation_test_pass_percent", 100),
            "GATE-PROCESS-STUCK-CRITICAL": ("open_critical_stuck_processes", 0),
            "GATE-PROCESS-BUSINESS-LINE-CERTIFICATION": (
                "critical_business_domain_certification_percent",
                100,
            ),
        }
        for gate_code, (metric, expected) in gates.items():
            await session.execute(
                text(
                    "INSERT INTO quality_gate_definitions (gate_code,semantic_version,name,category,enforcement_level,condition_definition,required_evidence_types,applicable_release_types,applicable_modules,status,created_by) VALUES (:code,'1.0.0',:name,'release','blocker',CAST(:condition AS jsonb),'[\"process_test\",\"process_simulation\",\"process_certification\"]'::jsonb,'[\"standard\"]'::jsonb,'[\"process_governance\"]'::jsonb,'draft',:actor) ON CONFLICT (gate_code,semantic_version) DO UPDATE SET condition_definition=EXCLUDED.condition_definition,required_evidence_types=EXCLUDED.required_evidence_types"
                ),
                {
                    "code": gate_code,
                    "name": gate_code.replace("-", " ").title(),
                    "condition": _json({"metric": metric, "operator": "eq", "expected": expected}),
                    "actor": SYSTEM_USER_ID,
                },
            )
        await session.commit()
    print(
        f"Process governance seed complete: {len(process_manifest['processes'])} processes, {len(machine_manifest['machines'])} state machines, {len(compensation_manifest['compensations'])} compensations; production certification remains NOT_CERTIFIED"
    )


if __name__ == "__main__":
    asyncio.run(seed_process_governance())
