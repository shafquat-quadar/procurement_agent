"""LangGraph controlled ReAct agent.

This is a *controlled* graph, not an unconstrained autonomous agent. Intent
classification and tool planning are deterministic; the LLM is used only for
grounded answer generation. The policy validator runs before any MCP call and
the answer verifier runs before the final response.

Node order:
    classify_intent -> extract_inputs -> decide_if_tool_required ->
    discover_metadata_if_needed -> create_tool_plan -> validate_tool_plan ->
    call_mcp -> normalize_evidence -> draft_answer -> verify_answer ->
    final_response
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from langgraph.graph import END, StateGraph

from app.agent import answer as answer_mod
from app.agent import intent as intent_mod
from app.agent.planner import build_plan
from app.agent.prompts import prompt_meta
from app.agent.state import (
    AgentState,
    ChatRequest,
    ChatResponse,
    Intent,
    VerificationResult,
    new_trace_id,
)
from app.agent.verifier import verify_answer
from app.config.settings import Settings, get_settings
from app.evidence.models import Evidence
from app.evidence.normalizer import normalize_tool_result
from app.evidence.store import TraceStore
from app.guardrails.validator import ToolPlanValidator, load_policy
from app.maas.chat_model import ChatModel
from app.maas.client import MaaSError
from app.mcp_client.client import McpClientProtocol, McpError
from app.mcp_client.tools import ToolCall, ToolCallResult
from app.observability.logging import get_logger

logger = get_logger("agent")


@dataclass
class AgentDependencies:
    """Injected collaborators (allows test fakes for LLM + MCP)."""

    chat_model: ChatModel
    mcp_client: McpClientProtocol
    validator: ToolPlanValidator = field(default_factory=lambda: ToolPlanValidator(load_policy()))
    store: TraceStore | None = None
    settings: Settings = field(default_factory=get_settings)


# --------------------------------------------------------------------- nodes


def _log(event: str, state: AgentState, **kw: object) -> None:
    logger.info(event, trace_id=state.get("trace_id"), **kw)


async def _classify_intent(state: AgentState, deps: AgentDependencies) -> AgentState:
    intent, missing = intent_mod.classify(state["user_message"])
    _log("intent_classified", state, intent=intent.name, missing_inputs=missing)
    return {"intent": intent.model_dump(), "missing_inputs": missing}


async def _extract_inputs(state: AgentState, deps: AgentDependencies) -> AgentState:
    # Identifiers were extracted during classification; this node is where richer
    # slot-filling would live. It currently just surfaces the extracted inputs.
    intent = Intent(**state["intent"])
    return {"intent": intent.model_dump()}


async def _decide_if_tool_required(state: AgentState, deps: AgentDependencies) -> AgentState:
    intent = Intent(**state["intent"])
    missing = state.get("missing_inputs", [])
    if intent.requires_sap and missing:
        question = _clarification_prompt(intent, missing)
        _log("clarification_required", state, missing_inputs=missing)
        return {"needs_clarification": True, "clarification_question": question}
    return {"needs_clarification": False}


async def _discover_metadata_if_needed(state: AgentState, deps: AgentDependencies) -> AgentState:
    # Metadata discovery (service_info/list_entities/describe_entity) would run
    # here when an entity/field is unknown. For the supported intents the schema
    # is known, so this is a controlled no-op.
    return {}


async def _create_tool_plan(state: AgentState, deps: AgentDependencies) -> AgentState:
    intent = Intent(**state["intent"])
    plan = build_plan(intent)
    _log("tool_plan_created", state, plan_size=len(plan), intent=intent.name)
    if not plan:
        missing = state.get("missing_inputs") or ["required details"]
        question = _clarification_prompt(intent, missing)
        return {"tool_plan": [], "needs_clarification": True, "clarification_question": question}
    return {"tool_plan": plan, "needs_clarification": False}


async def _validate_tool_plan(state: AgentState, deps: AgentDependencies) -> AgentState:
    plan: list[ToolCall] = state.get("tool_plan", [])
    result = deps.validator.validate_plan(plan)
    if not result.allowed:
        _log("tool_call_blocked", state, reason=result.user_message)
        if deps.store and state.get("trace_id"):
            deps.store.record_error(state["trace_id"], "policy_block", result.user_message or "")
        if result.needs_clarification:
            return {
                "needs_clarification": True,
                "clarification_question": result.clarification_question,
                "validated_tool_calls": [],
            }
        return {
            "needs_clarification": False,
            "clarification_question": None,
            "validated_tool_calls": [],
            "errors": _append_error(state, "policy_block", result.user_message or "Blocked."),
            "final_answer": result.user_message or "This request was blocked by policy.",
        }
    _log("tool_call_validated", state, calls=len(plan))
    return {"validated_tool_calls": plan}


async def _call_mcp(state: AgentState, deps: AgentDependencies) -> AgentState:
    calls: list[ToolCall] = state.get("validated_tool_calls", [])
    tool_results: list[ToolCallResult] = []
    evidence: list[Evidence] = []
    blocked_terms = deps.validator.policy.blocked_terms

    for call in calls:
        _log("mcp_tool_call_started", state, action=call.action, target=call.target)
        started = time.monotonic()
        try:
            raw = await deps.mcp_client.call_tool(call.tool, call.to_mcp_arguments())
        except McpError as exc:
            duration = int((time.monotonic() - started) * 1000)
            tool_results.append(
                ToolCallResult(
                    service=call.service,
                    action=call.action,
                    target=call.target,
                    status="error",
                    duration_ms=duration,
                    error=exc.message,
                )
            )
            _log("error", state, code=exc.code, error=exc.message)
            return {
                "tool_results": tool_results,
                "evidence": evidence,
                "errors": _append_error(state, exc.code, exc.message),
                "final_answer": answer_mod.SAFE_RETRIEVAL_FAILED,
            }

        duration = int((time.monotonic() - started) * 1000)
        status = "error" if raw.is_error else "success"
        tool_results.append(
            ToolCallResult(
                service=call.service,
                action=call.action,
                target=call.target,
                status=status,
                duration_ms=duration,
            )
        )
        _log("mcp_tool_call_finished", state, status=status, duration_ms=duration)

        ev = normalize_tool_result(call, raw.content, blocked_terms)
        evidence.append(ev)

    return {"tool_results": tool_results, "evidence": evidence}


async def _normalize_evidence(state: AgentState, deps: AgentDependencies) -> AgentState:
    evidence: list[Evidence] = state.get("evidence", [])
    _log("evidence_normalized", state, records=sum(e.records_returned for e in evidence))
    return {}


async def _draft_answer(state: AgentState, deps: AgentDependencies) -> AgentState:
    intent = Intent(**state["intent"])
    evidence: list[Evidence] = state.get("evidence", [])

    if intent.name == intent_mod.OUT_OF_SCOPE:
        _log("answer_drafted", state, length=len(answer_mod.SAFE_OUT_OF_SCOPE), out_of_scope=True)
        return {"draft_answer": answer_mod.SAFE_OUT_OF_SCOPE}

    try:
        if not intent.requires_sap:
            draft = answer_mod.generate_help_answer(deps.chat_model, state["user_message"])
        else:
            draft = answer_mod.generate_answer(deps.chat_model, state["user_message"], evidence)
    except MaaSError as exc:
        _log("error", state, code=exc.code, error=exc.message)
        return {
            "draft_answer": "",
            "final_answer": answer_mod.SAFE_LLM_UNAVAILABLE,
            "errors": _append_error(state, exc.code, exc.message),
        }
    _log("answer_drafted", state, length=len(draft))
    return {"draft_answer": draft}


async def _verify_answer(state: AgentState, deps: AgentDependencies) -> AgentState:
    intent = Intent(**state["intent"])
    evidence: list[Evidence] = state.get("evidence", [])
    draft = state.get("draft_answer", "")

    # Help answers carry no SAP factual claims; still run the verifier for safety.
    result = verify_answer(draft, evidence, state["user_message"], intent.identifiers)

    if not result.final_answer_allowed and intent.requires_sap:
        # Regenerate once, strictly from evidence.
        try:
            regenerated = answer_mod.generate_answer(
                deps.chat_model, state["user_message"], evidence
            )
        except MaaSError:
            regenerated = ""
        recheck = verify_answer(regenerated, evidence, state["user_message"], intent.identifiers)
        if recheck.final_answer_allowed and regenerated:
            _log("answer_verified", state, supported=True, regenerated=True)
            return {"draft_answer": regenerated, "verification": recheck.model_dump()}
        _log("answer_verified", state, supported=False, unsupported=result.unsupported_claims)
        return {
            "verification": recheck.model_dump(),
            "final_answer": answer_mod.SAFE_UNSUPPORTED,
        }

    _log("answer_verified", state, supported=result.supported)
    return {"verification": result.model_dump()}


async def _final_response(state: AgentState, deps: AgentDependencies) -> AgentState:
    intent = Intent(**state["intent"])

    if state.get("needs_clarification"):
        final = ""
    else:
        final = state.get("final_answer") or state.get("draft_answer") or ""

    verification = state.get("verification") or VerificationResult().model_dump()
    _persist(state, deps, intent, final, verification)
    _log(
        "final_answer_returned",
        state,
        needs_clarification=state.get("needs_clarification", False),
    )
    return {"final_answer": final, "verification": verification}


# ----------------------------------------------------------------- routing


def _route_after_decide(state: AgentState) -> str:
    if state.get("needs_clarification"):
        return "clarify"
    intent = Intent(**state["intent"])
    if not intent.requires_sap:
        return "help"
    return "tool"


def _route_after_plan(state: AgentState) -> str:
    if state.get("needs_clarification"):
        return "clarify"
    return "validate"


def _route_after_validate(state: AgentState) -> str:
    if state.get("needs_clarification") or state.get("final_answer"):
        return "final"
    return "call"


def _route_after_call(state: AgentState) -> str:
    if state.get("final_answer"):  # retrieval error path
        return "final"
    return "normalize"


def _route_after_draft(state: AgentState) -> str:
    if state.get("final_answer"):  # LLM error path
        return "final"
    return "verify"


# ------------------------------------------------------------------ helpers


def _clarification_prompt(intent: Intent, missing: list[str]) -> str:
    needed = ", ".join(missing) if missing else "more details"
    return (
        f"I need a bit more information to look this up in SAP. "
        f"Please provide: {needed}."
    )


def _append_error(state: AgentState, code: str, message: str) -> list[dict[str, str]]:
    errors = list(state.get("errors", []))
    errors.append({"code": code, "message": message})
    return errors


def _persist(
    state: AgentState,
    deps: AgentDependencies,
    intent: Intent,
    final_answer: str,
    verification: dict,
) -> None:
    if not deps.store or not state.get("trace_id"):
        return
    store = deps.store
    trace_id = state["trace_id"]
    session_id = state.get("session_id")
    if session_id:
        store.ensure_session(session_id)
    store.record_message(
        trace_id=trace_id,
        session_id=session_id,
        user_question=state["user_message"],
        intent=intent.name,
        final_answer=final_answer,
        needs_clarification=bool(state.get("needs_clarification")),
    )
    for tr in state.get("tool_results", []):
        store.record_tool_call(
            trace_id, tr.service, tr.action, tr.target, tr.status, tr.duration_ms
        )
    for ev in state.get("evidence", []):
        store.record_evidence(
            trace_id,
            ev.evidence_id,
            ev.service,
            ev.entity,
            ev.action,
            ev.records_returned,
            ev.query,
        )
    store.record_verification(
        trace_id,
        bool(verification.get("supported", True)),
        list(verification.get("unsupported_claims", [])),
    )


# ------------------------------------------------------------------- build


def build_agent(deps: AgentDependencies):
    """Compile the LangGraph agent with injected dependencies."""

    def node(fn):
        async def _wrapped(state: AgentState) -> AgentState:
            return await fn(state, deps)

        return _wrapped

    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", node(_classify_intent))
    graph.add_node("extract_inputs", node(_extract_inputs))
    graph.add_node("decide_if_tool_required", node(_decide_if_tool_required))
    graph.add_node("discover_metadata_if_needed", node(_discover_metadata_if_needed))
    graph.add_node("create_tool_plan", node(_create_tool_plan))
    graph.add_node("validate_tool_plan", node(_validate_tool_plan))
    graph.add_node("call_mcp", node(_call_mcp))
    graph.add_node("normalize_evidence", node(_normalize_evidence))
    graph.add_node("draft_answer", node(_draft_answer))
    graph.add_node("verify_answer", node(_verify_answer))
    graph.add_node("final_response", node(_final_response))

    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "extract_inputs")
    graph.add_edge("extract_inputs", "decide_if_tool_required")
    graph.add_conditional_edges(
        "decide_if_tool_required",
        _route_after_decide,
        {
            "clarify": "final_response",
            "help": "draft_answer",
            "tool": "discover_metadata_if_needed",
        },
    )
    graph.add_edge("discover_metadata_if_needed", "create_tool_plan")
    graph.add_conditional_edges(
        "create_tool_plan",
        _route_after_plan,
        {"clarify": "final_response", "validate": "validate_tool_plan"},
    )
    graph.add_conditional_edges(
        "validate_tool_plan",
        _route_after_validate,
        {"final": "final_response", "call": "call_mcp"},
    )
    graph.add_conditional_edges(
        "call_mcp",
        _route_after_call,
        {"final": "final_response", "normalize": "normalize_evidence"},
    )
    graph.add_edge("normalize_evidence", "draft_answer")
    graph.add_conditional_edges(
        "draft_answer",
        _route_after_draft,
        {"final": "final_response", "verify": "verify_answer"},
    )
    graph.add_edge("verify_answer", "final_response")
    graph.add_edge("final_response", END)

    return graph.compile()


async def run_agent(deps: AgentDependencies, request: ChatRequest) -> ChatResponse:
    """Run the agent for a single chat request and return a ChatResponse."""
    trace_id = new_trace_id()
    logger.info(
        "chat_received",
        trace_id=trace_id,
        session_id=request.session_id,
        prompts=prompt_meta(),
    )

    initial: AgentState = {
        "trace_id": trace_id,
        "session_id": request.session_id,
        "user_message": request.message,
        "user_context": request.user_context.model_dump(),
        "errors": [],
        "tool_results": [],
        "evidence": [],
    }

    compiled = build_agent(deps)
    final_state: AgentState = await compiled.ainvoke(initial)

    verification = VerificationResult(**(final_state.get("verification") or {}))
    evidence: list[Evidence] = final_state.get("evidence", [])
    tool_results: list[ToolCallResult] = final_state.get("tool_results", [])

    return ChatResponse(
        trace_id=trace_id,
        answer=final_state.get("final_answer", ""),
        needs_clarification=bool(final_state.get("needs_clarification")),
        clarification_question=final_state.get("clarification_question"),
        evidence_summary=[ev.summary() for ev in evidence],
        tool_calls=tool_results,
        verification=verification,
    )
