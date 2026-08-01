from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.knowledge import KnowledgeSpace
from vav.modules.ai_assistant.classification import assess_completeness, classify_message
from vav.modules.ai_assistant.providers import AiModelProvider
from vav.modules.ai_assistant.safety import assess_risk, safety_response
from vav.modules.ai_assistant.schemas import (
    GeneratedAgentResponse,
    HannaAgentState,
    MessageClassification,
    ResponseClaim,
    RiskAssessment,
    RiskLevel,
)
from vav.modules.ai_assistant.tooling import execute_read_tool
from vav.modules.knowledge.service import knowledge_service

GRAPH_VERSION = "1.0.0"
STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GraphDependencies:
    session: AsyncSession
    provider: AiModelProvider
    current_user_id: UUID
    user_roles: list[str]
    region: str | None = None


def _visit(state: HannaAgentState, node: str) -> list[str]:
    return [*state.get("visited_nodes", []), node]


def build_hanna_graph(dependencies: GraphDependencies) -> Any:
    async def load_context(state: HannaAgentState) -> dict[str, Any]:
        return {"visited_nodes": _visit(state, "load_context")}

    async def consent_guard(state: HannaAgentState) -> dict[str, Any]:
        if state.get("consented"):
            return {"next_action": "risk", "visited_nodes": _visit(state, "consent_guard")}
        response = GeneratedAgentResponse(
            understanding_summary="开始前需要确认 AI 服务声明与数据用途。",
            safety_notice="请先阅读并明确同意 AI 服务声明；长期记忆需要单独选择。",
            final_text="请先阅读并明确同意 AI 服务声明后再开始对话。",
        )
        return {
            "next_action": "consent_required",
            "generated_response": response.model_dump(mode="json"),
            "visited_nodes": _visit(state, "consent_guard"),
        }

    async def risk_prescreen(state: HannaAgentState) -> dict[str, Any]:
        risk = await dependencies.provider.generate_structured(
            task_type="risk_classification",
            schema=RiskAssessment,
            input_data={"message": state["user_message"]},
        )
        return {
            "risk_assessment": risk.model_dump(mode="json"),
            "visited_nodes": _visit(state, "risk_prescreen"),
        }

    async def classify(state: HannaAgentState) -> dict[str, Any]:
        value = await dependencies.provider.generate_structured(
            task_type="message_classification",
            schema=MessageClassification,
            input_data={"message": state["user_message"]},
        )
        return {
            "classification": value.model_dump(mode="json"),
            "visited_nodes": _visit(state, "classify_message"),
        }

    async def completeness(state: HannaAgentState) -> dict[str, Any]:
        classification = MessageClassification.model_validate(state["classification"])
        value = assess_completeness(state["user_message"], classification)
        return {
            "completeness": value.model_dump(mode="json"),
            "visited_nodes": _visit(state, "assess_completeness"),
        }

    async def clarify(state: HannaAgentState) -> dict[str, Any]:
        questions = cast(dict[str, Any], state["completeness"])["clarifying_questions"][:2]
        final = "为了避免武断判断，我想先确认：\n" + "\n".join(
            f"{index}. {question}" for index, question in enumerate(questions, 1)
        )
        response = GeneratedAgentResponse(
            opening_empathy="谢谢你愿意说明这个困扰。",
            understanding_summary="现有信息还不足以给出负责任的具体建议。",
            reflection_questions=questions,
            final_text=final,
        )
        return {
            "next_action": "wait_for_user",
            "generated_response": response.model_dump(mode="json"),
            "visited_nodes": _visit(state, "ask_clarifying_question"),
        }

    async def retrieve(state: HannaAgentState) -> dict[str, Any]:
        classification = MessageClassification.model_validate(state["classification"])
        if not classification.requires_knowledge_retrieval:
            return {
                "retrieval_bundle": {"items": [], "no_answer": True},
                "visited_nodes": _visit(state, "retrieve_knowledge"),
            }
        items: list[dict[str, Any]] = []
        for code in (
            "hanna_relationship_method",
            "public_faq",
            "safety_boundaries",
            "vav-public-guidance",
        ):
            space = await dependencies.session.scalar(
                select(KnowledgeSpace).where(KnowledgeSpace.space_code == code)
            )
            if space is None:
                continue
            result = await knowledge_service.retrieve(
                dependencies.session,
                space=space,
                query=state["user_message"],
                locale=state["locale"],
                region=dependencies.region,
                roles=dependencies.user_roles,
                top_k=max(1, 8 - len(items)),
                public=True,
                actor_id=dependencies.current_user_id,
            )
            items.extend(result.get("items", []))
            if len(items) >= 8:
                break
        return {
            "retrieval_bundle": {"items": items[:8], "no_answer": not items},
            "citations": [
                {
                    "citation_id": item.get("citation_id"),
                    "document_code": item.get("document_code"),
                    "document_version_id": item.get("document_version_id"),
                    "chunk_id": item.get("chunk_id"),
                    "source_locator": item.get("source_locator", {}),
                    "excerpt": item.get("excerpt"),
                }
                for item in items[:8]
            ],
            "visited_nodes": _visit(state, "retrieve_knowledge"),
        }

    async def plan_tools(state: HannaAgentState) -> dict[str, Any]:
        classification = MessageClassification.model_validate(state["classification"])
        calls = (
            await dependencies.provider.generate_tool_calls(
                task_type="tool_planning", input_data={"message": state["user_message"]}
            )
            if classification.requires_current_service_data
            else []
        )
        return {"planned_tool_calls": calls[:6], "visited_nodes": _visit(state, "plan_tools")}

    async def execute_tools(state: HannaAgentState) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for call in state.get("planned_tool_calls", [])[:6]:
            code = str(call.get("tool_code", ""))
            try:
                output = await execute_read_tool(
                    dependencies.session,
                    tool_code=code,
                    arguments=cast(dict[str, Any], call.get("arguments", {})),
                    current_user_id=dependencies.current_user_id,
                    locale=state["locale"],
                )
                results.append({"tool_code": code, "status": "completed", "output": output})
            except Exception as exc:
                results.append(
                    {
                        "tool_code": code,
                        "status": "failed",
                        "error": type(exc).__name__,
                    }
                )
        return {"tool_results": results, "visited_nodes": _visit(state, "execute_tools")}

    async def plan_response(state: HannaAgentState) -> dict[str, Any]:
        classification = MessageClassification.model_validate(state["classification"])
        retrieval_bundle = state.get("retrieval_bundle") or {}
        return {
            "response_plan": {
                "topic": classification.primary_topic.value,
                "intent": classification.user_intent.value,
                "use_knowledge": bool(retrieval_bundle.get("items")),
                "successful_tools": [
                    item["tool_code"]
                    for item in state.get("tool_results", [])
                    if item.get("status") == "completed"
                ],
            },
            "visited_nodes": _visit(state, "plan_response"),
        }

    async def generate(state: HannaAgentState) -> dict[str, Any]:
        classification = MessageClassification.model_validate(state["classification"])
        retrieval_bundle = state.get("retrieval_bundle") or {}
        knowledge_items = retrieval_bundle.get("items", [])
        tool_results = [
            item for item in state.get("tool_results", []) if item.get("status") == "completed"
        ]
        claims: list[ResponseClaim] = []
        source_line = ""
        if knowledge_items:
            first = knowledge_items[0]
            excerpt = first.get("excerpt") or "已授权资料支持这一方向，但公开原文不可展示。"
            citation_id = UUID(str(first["citation_id"]))
            claims.append(
                ResponseClaim(
                    claim_id="knowledge-1",
                    claim_text=str(excerpt)[:300],
                    claim_type="knowledge",
                    citation_ids=[citation_id],
                    support_level="directly_supported",
                )
            )
            source_line = f"\n\n来源：[{first['document_code']} · v{first['version_number']}]"
        service_lines: list[str] = []
        recommendations: list[dict[str, Any]] = []
        for result in tool_results:
            for item in result["output"].get("items", [])[:2]:
                title = (
                    item.get("title")
                    or item.get("name")
                    or item.get("activity_code")
                    or item.get("course_code")
                )
                if title:
                    service_lines.append(f"- {title}（当前状态由 {result['tool_code']} 查询）")
                    recommendations.append(
                        {
                            "type": result["tool_code"],
                            "resource_id": item.get("id"),
                            "title": title,
                            "availability": item.get("status", "available"),
                            "reason": f"与你提到的 {classification.primary_topic.value} 相关。",
                        }
                    )
        understanding = (
            f"你主要在询问 {classification.primary_topic.value}，"
            f"并希望获得 {classification.user_intent.value}。"
        )
        actions = [
            "先区分你能控制的表达与对方有权自主决定的部分。",
            "选择一次具体互动，用观察、感受、需要和请求四步写下准备表达的内容。",
        ]
        final = (
            "谢谢你把这个问题带到这里。\n\n"
            f"{understanding}\n\n"
            "一个可能的盲点是：急于得到确定答案时，容易忽略双方都需要自愿和可撤回的空间。\n\n"
            "可以先做两步：\n1. " + actions[0] + "\n2. " + actions[1]
        )
        if service_lines:
            final += "\n\n当前可核对的服务：\n" + "\n".join(service_lines[:3])
        final += source_line
        response = GeneratedAgentResponse(
            opening_empathy="谢谢你愿意说出这个困扰。",
            understanding_summary=understanding,
            blind_spot_reflections=["不要把对方的沉默或犹豫自动解释成确定结论。"],
            action_suggestions=actions,
            reflection_questions=["你最希望对方理解的需要是什么？"],
            service_recommendations=recommendations[:3],
            claims=claims,
            final_text=final,
        )
        return {
            "generated_response": response.model_dump(mode="json"),
            "visited_nodes": _visit(state, "generate_response"),
        }

    async def validate_citations(state: HannaAgentState) -> dict[str, Any]:
        response = GeneratedAgentResponse.model_validate(state["generated_response"])
        retrieval_bundle = state.get("retrieval_bundle") or {}
        available = {str(item.get("citation_id")) for item in retrieval_bundle.get("items", [])}
        valid = all(
            claim.support_level != "directly_supported"
            or (claim.citation_ids and all(str(value) in available for value in claim.citation_ids))
            for claim in response.claims
        )
        if not valid:
            response = GeneratedAgentResponse(
                understanding_summary="现有资料不足以支持原回答中的核心主张。",
                safety_notice="引用验证失败，原回答未发送。",
                final_text="现有已授权资料不足以支持一个可靠结论。你可以补充情境，或选择真人支持。",
            )
        return {
            "generated_response": response.model_dump(mode="json"),
            "next_action": "citations_valid" if valid else "citation_fallback",
            "visited_nodes": _visit(state, "validate_citations"),
        }

    async def postcheck(state: HannaAgentState) -> dict[str, Any]:
        response = GeneratedAgentResponse.model_validate(state["generated_response"])
        blocked = any(
            phrase in response.final_text.casefold()
            for phrase in ("你一定患有", "保证绝对保密", "一定违法", "you definitely have")
        )
        if blocked:
            response = GeneratedAgentResponse(
                understanding_summary="回答触发服务边界，已安全降级。",
                safety_notice="本 AI 不提供诊断、法律结论或绝对保密承诺。",
                final_text="这个问题超出本 AI 可以负责任回答的范围，建议联系合适的真人或专业支持。",
            )
        return {
            "generated_response": response.model_dump(mode="json"),
            "next_action": "safe" if not blocked else "safe_rewrite",
            "visited_nodes": _visit(state, "safety_postcheck"),
        }

    async def create_referral(state: HannaAgentState) -> dict[str, Any]:
        risk = RiskAssessment.model_validate(state["risk_assessment"])
        return {
            "referral": {
                "type": "safety_review",
                "priority": "immediate"
                if risk.level is RiskLevel.IMMEDIATE
                else "high"
                if risk.level is RiskLevel.HIGH
                else "normal",
                "risk_level": risk.level.value,
                "risk_category": risk.categories[0].value,
                "consent_status": "safety_policy_basis",
            },
            "visited_nodes": _visit(state, "create_referral"),
        }

    async def safe_response(state: HannaAgentState) -> dict[str, Any]:
        response = safety_response(
            RiskAssessment.model_validate(state["risk_assessment"]), state["locale"]
        )
        return {
            "generated_response": response.model_dump(mode="json"),
            "next_action": "safety_paused",
            "visited_nodes": _visit(state, "safety_response"),
        }

    async def persist(state: HannaAgentState) -> dict[str, Any]:
        return {"visited_nodes": _visit(state, "persist_turn")}

    def after_consent(state: HannaAgentState) -> Literal["risk_prescreen", "persist_turn"]:
        return "risk_prescreen" if state.get("consented") else "persist_turn"

    def after_risk(state: HannaAgentState) -> Literal["classify_message", "create_referral"]:
        risk = RiskAssessment.model_validate(state["risk_assessment"])
        return (
            "create_referral"
            if risk.level in {RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.IMMEDIATE}
            else "classify_message"
        )

    def after_completeness(
        state: HannaAgentState,
    ) -> Literal["ask_clarifying_question", "retrieve_knowledge"]:
        return (
            "retrieve_knowledge"
            if cast(dict[str, Any], state["completeness"])["sufficient_for_response"]
            else "ask_clarifying_question"
        )

    def after_tools(state: HannaAgentState) -> Literal["execute_tools", "plan_response"]:
        return "execute_tools" if state.get("planned_tool_calls") else "plan_response"

    builder = StateGraph(HannaAgentState)
    for name, node in (
        ("load_context", load_context),
        ("consent_guard", consent_guard),
        ("risk_prescreen", risk_prescreen),
        ("classify_message", classify),
        ("assess_completeness", completeness),
        ("ask_clarifying_question", clarify),
        ("retrieve_knowledge", retrieve),
        ("plan_tools", plan_tools),
        ("execute_tools", execute_tools),
        ("plan_response", plan_response),
        ("generate_response", generate),
        ("validate_citations", validate_citations),
        ("safety_postcheck", postcheck),
        ("create_referral", create_referral),
        ("safety_response", safe_response),
        ("persist_turn", persist),
    ):
        builder.add_node(name, node)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "consent_guard")
    builder.add_conditional_edges("consent_guard", after_consent)
    builder.add_conditional_edges("risk_prescreen", after_risk)
    builder.add_edge("create_referral", "safety_response")
    builder.add_edge("safety_response", "persist_turn")
    builder.add_edge("classify_message", "assess_completeness")
    builder.add_conditional_edges("assess_completeness", after_completeness)
    builder.add_edge("ask_clarifying_question", "persist_turn")
    builder.add_edge("retrieve_knowledge", "plan_tools")
    builder.add_conditional_edges("plan_tools", after_tools)
    builder.add_edge("execute_tools", "plan_response")
    builder.add_edge("plan_response", "generate_response")
    builder.add_edge("generate_response", "validate_citations")
    builder.add_edge("validate_citations", "safety_postcheck")
    builder.add_edge("safety_postcheck", "persist_turn")
    builder.add_edge("persist_turn", END)
    return builder.compile()


def deterministic_prescreen(message: str) -> RiskAssessment:
    return assess_risk(message)


def deterministic_classification(message: str) -> MessageClassification:
    return classify_message(message)
