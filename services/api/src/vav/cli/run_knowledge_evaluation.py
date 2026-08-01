from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.models.knowledge import (
    KnowledgeEvaluationCase,
    KnowledgeEvaluationDataset,
    KnowledgeIndexVersion,
    KnowledgeSpace,
)
from vav.modules.knowledge.service import knowledge_service


@dataclass
class Metrics:
    passed: int = 0
    forbidden_leakage: int = 0
    authorization_violations: int = 0
    citation_valid: int = 0
    citations: int = 0
    safety_passed: int = 0
    safety_total: int = 0
    latency_ms: list[int] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.passed


async def evaluate(
    *,
    session: AsyncSession,
    space: KnowledgeSpace,
    index: KnowledgeIndexVersion,
    cases: list[KnowledgeEvaluationCase],
) -> Metrics:
    metrics = Metrics()
    for case in cases:
        result = await knowledge_service.retrieve(
            session,
            space=space,
            query=case.query,
            locale=case.locale,
            region=case.region,
            roles=case.principal_roles,
            top_k=8,
            public=True,
            actor_id=None,
            index_version_id=index.id,
        )
        codes = {item["document_code"] for item in result["items"]}
        forbidden = bool(codes.intersection(case.forbidden_document_codes))
        if forbidden:
            metrics.forbidden_leakage += 1
            metrics.authorization_violations += 1
        hit = (
            result["no_answer"] is True
            if case.expected_no_answer
            else bool(codes.intersection(case.expected_document_codes))
        )
        passed = hit and not forbidden
        metrics.passed += int(passed)
        if case.safety_boundary:
            metrics.safety_total += 1
            metrics.safety_passed += int(passed)
        for item in result["items"]:
            metrics.citations += 1
            metrics.citation_valid += int(
                bool(
                    item.get("document_id")
                    and item.get("document_version_id")
                    and item.get("chunk_id")
                    and item.get("source_locator") is not None
                    and item.get("excerpt_sha256")
                )
            )
        metrics.latency_ms.append(int(result.get("latency_ms", 0)))
    return metrics


def percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * quantile))]


async def main() -> None:
    async with session_factory() as session:
        dataset = await session.scalar(
            select(KnowledgeEvaluationDataset).where(
                KnowledgeEvaluationDataset.dataset_code == "batch-09-core"
            )
        )
        space = await session.scalar(
            select(KnowledgeSpace).where(KnowledgeSpace.space_code == "vav-public-guidance")
        )
        active = (
            await session.scalar(
                select(KnowledgeIndexVersion).where(
                    KnowledgeIndexVersion.space_id == space.id,
                    KnowledgeIndexVersion.status == "active",
                )
            )
            if space
            else None
        )
        candidate = (
            await session.scalar(
                select(KnowledgeIndexVersion)
                .where(
                    KnowledgeIndexVersion.space_id == space.id,
                    KnowledgeIndexVersion.status == "ready_for_evaluation",
                )
                .order_by(KnowledgeIndexVersion.version_number.desc())
                .limit(1)
            )
            if space
            else None
        )
        target = candidate or active
        if dataset is None or space is None or target is None:
            raise RuntimeError("Seed and build knowledge before evaluation.")
        cases = list(
            (
                await session.scalars(
                    select(KnowledgeEvaluationCase).where(
                        KnowledgeEvaluationCase.dataset_id == dataset.id
                    )
                )
            ).all()
        )
        target_metrics = await evaluate(session=session, space=space, index=target, cases=cases)
        baseline_metrics = (
            await evaluate(session=session, space=space, index=active, cases=cases)
            if active and active.id != target.id
            else target_metrics
        )
        categories = {case.category for case in cases}
        required_categories = {
            "relevance",
            "multilingual",
            "acl",
            "authorization",
            "expired_content",
            "conflicting_version",
            "no_answer",
            "prompt_injection",
        }
        settings = get_settings()
        citation_accuracy = (
            target_metrics.citation_valid / target_metrics.citations
            if target_metrics.citations
            else 1.0
        )
        gates = {
            "minimum_cases": len(cases) >= settings.knowledge_evaluation_min_cases,
            "all_cases_pass": target_metrics.passed == len(cases),
            "required_categories": required_categories.issubset(categories),
            "authorization_violations_zero": target_metrics.authorization_violations == 0,
            "forbidden_leakage_zero": target_metrics.forbidden_leakage == 0,
            "safety_cases_pass": target_metrics.safety_passed == target_metrics.safety_total,
            "citation_accuracy": citation_accuracy == 1.0,
            "not_below_active": target_metrics.passed >= baseline_metrics.passed,
        }
        status = "passed" if all(gates.values()) else "failed"
        metrics_payload = {
            "provider": "fake",
            "gate": "local",
            "passed_cases": target_metrics.passed,
            "baseline_passed_cases": baseline_metrics.passed,
            "citation_accuracy": citation_accuracy,
            "latency_p50_ms": percentile(target_metrics.latency_ms or [], 0.50),
            "latency_p95_ms": percentile(target_metrics.latency_ms or [], 0.95),
            "categories": sorted(categories),
            "gates": gates,
        }
        await session.execute(
            text(
                "INSERT INTO knowledge_evaluation_runs "
                "(dataset_id,index_version_id,status,total_cases,passed_cases,"
                "authorization_violations,acl_leakage_count,metrics) "
                "VALUES (:dataset,:index,:status,:total,:passed,:violations,:leakage,"
                "CAST(:metrics AS jsonb))"
            ),
            {
                "dataset": dataset.id,
                "index": target.id,
                "status": status,
                "total": len(cases),
                "passed": target_metrics.passed,
                "violations": target_metrics.authorization_violations,
                "leakage": target_metrics.forbidden_leakage,
                "metrics": json.dumps(metrics_payload),
            },
        )
        target.evaluation_status = status
        target.validation_report = {
            **(target.validation_report or {}),
            "evaluation": metrics_payload,
        }
        await session.commit()
    print(
        f"Knowledge evaluation {status}: {target_metrics.passed}/{len(cases)}, "
        f"authorization_violations={target_metrics.authorization_violations}, "
        f"acl_leakage={target_metrics.forbidden_leakage}"
    )
    if status != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
