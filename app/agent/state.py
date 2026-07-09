"""Agent graph state and shared request/response schemas."""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from app.evidence.models import Evidence, EvidenceSummary
from app.mcp_client.tools import ToolCall, ToolCallResult


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex}"


# --- API schemas ---------------------------------------------------------


class UserContext(BaseModel):
    user_id: str = "local-user"
    roles: list[str] = Field(default_factory=list)
    plants: list[str] = Field(default_factory=list)
    purchasing_orgs: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_context: UserContext = Field(default_factory=UserContext)


class VerificationResult(BaseModel):
    supported: bool = True
    unsupported_claims: list[str] = Field(default_factory=list)
    final_answer_allowed: bool = True


class ChatResponse(BaseModel):
    trace_id: str
    answer: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    evidence_summary: list[EvidenceSummary] = Field(default_factory=list)
    tool_calls: list[ToolCallResult] = Field(default_factory=list)
    verification: VerificationResult = Field(default_factory=VerificationResult)


class Intent(BaseModel):
    name: str = "out_of_scope"
    identifiers: dict[str, Any] = Field(default_factory=dict)
    requires_sap: bool = False
    confidence: float = 0.0


# --- LangGraph state -----------------------------------------------------


class AgentState(TypedDict, total=False):
    """Mutable state threaded through the LangGraph nodes."""

    trace_id: str
    session_id: str | None
    user_message: str
    user_context: dict[str, Any]

    intent: dict[str, Any]
    missing_inputs: list[str]

    tool_plan: list[ToolCall]
    validated_tool_calls: list[ToolCall]
    tool_results: list[ToolCallResult]
    evidence: list[Evidence]

    draft_answer: str
    verification: dict[str, Any]
    final_answer: str

    needs_clarification: bool
    clarification_question: str | None
    errors: list[dict[str, str]]
