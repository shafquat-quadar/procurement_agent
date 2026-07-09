"""Deterministic policy validator.

This is the security boundary between the (LLM-produced) tool plan and the MCP
server. It runs before every MCP call and cannot be bypassed by prompt changes.
It enforces read-only mode, service/action allowlists, write blocks, row/call
limits, and required filters for list queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.mcp_client.tools import DISCOVERY_ACTIONS, ToolCall

_POLICY_PATH = Path(__file__).with_name("policy.yaml")


class Policy(BaseModel):
    """Parsed guardrail policy."""

    mode: str = "read_only"
    allowed_tools: list[str] = []
    allowed_actions: list[str] = []
    blocked_actions: list[str] = []
    allowed_services: list[str] = []
    query_limits: dict[str, Any] = {}
    required_filters: dict[str, dict[str, list[str]]] = {}
    redaction: dict[str, Any] = {}
    raw_payload: dict[str, Any] = {}

    @property
    def max_tool_calls(self) -> int:
        return int(self.query_limits.get("max_tool_calls_per_question", 8))

    @property
    def max_rows(self) -> int:
        return int(self.query_limits.get("max_rows_per_call", 50))

    @property
    def require_filter_for_list(self) -> bool:
        return bool(self.query_limits.get("require_filter_for_list", True))

    @property
    def blocked_terms(self) -> tuple[str, ...]:
        return tuple(self.redaction.get("blocked_terms", []))


def load_policy(path: str | Path | None = None) -> Policy:
    """Load and parse policy.yaml."""
    policy_path = Path(path) if path else _POLICY_PATH
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    return Policy(**data)


class PolicyViolation(BaseModel):
    """A single reason a tool call was rejected."""

    code: str
    message: str  # safe, user-facing


class ValidationResult(BaseModel):
    """Result of validating one tool call."""

    allowed: bool
    violations: list[PolicyViolation] = []
    # If the fix is a user clarification (e.g. missing filter), surface it.
    needs_clarification: bool = False
    clarification_question: str | None = None

    @property
    def user_message(self) -> str | None:
        if self.allowed:
            return None
        if self.clarification_question:
            return self.clarification_question
        return "; ".join(v.message for v in self.violations) or "Request blocked by policy."


@dataclass
class ToolPlanValidator:
    """Validates tool calls against a loaded policy."""

    policy: Policy = field(default_factory=load_policy)

    def validate_plan(self, plan: list[ToolCall]) -> ValidationResult:
        """Validate an entire plan, including the call-count limit."""
        if len(plan) > self.policy.max_tool_calls:
            return ValidationResult(
                allowed=False,
                violations=[
                    PolicyViolation(
                        code="too_many_tool_calls",
                        message=(
                            "This question would require too many SAP lookups. "
                            "Please narrow it with a specific identifier or filter."
                        ),
                    )
                ],
            )
        for call in plan:
            result = self.validate_call(call)
            if not result.allowed:
                return result
        return ValidationResult(allowed=True)

    def validate_call(self, call: ToolCall) -> ValidationResult:  # noqa: C901
        """Validate a single tool call. First failing rule wins."""
        # 1. Allowed tool.
        if call.tool not in self.policy.allowed_tools:
            return self._deny(
                "tool_not_allowed",
                f"The tool '{call.tool}' is not permitted.",
            )

        # 2. Blocked (write) action — checked before allowlist for a clear reason.
        if call.action in self.policy.blocked_actions:
            return self._deny(
                "write_blocked",
                "Write operations to SAP are not allowed. This assistant is read-only.",
            )

        # 3. Allowed action.
        if call.action not in self.policy.allowed_actions:
            return self._deny(
                "action_not_allowed",
                f"The action '{call.action}' is not supported.",
            )

        # Discovery actions on the odata_help / odata tool need no service/filter checks.
        if call.action in DISCOVERY_ACTIONS:
            # A service is still required to scope discovery, except pure help.
            unknown_service = call.service and call.service not in self.policy.allowed_services
            if call.tool == "odata" and unknown_service:
                return self._deny(
                    "service_not_allowed",
                    f"The service '{call.service}' is not in the allowed list.",
                )
            return ValidationResult(allowed=True)

        # 4. Allowed service (for read actions).
        if not call.service:
            return self._deny("service_missing", "A SAP service must be specified.")
        if call.service not in self.policy.allowed_services:
            return self._deny(
                "service_not_allowed",
                f"The service '{call.service}' is not in the allowed list.",
            )

        # 5. get requires a key.
        if call.action == "get":
            if not call.params.key:
                return self._deny(
                    "missing_key",
                    "A record key is required to fetch a single SAP record.",
                )
            return ValidationResult(allowed=True)

        # 6. list rules.
        if call.action == "list":
            if not call.target:
                return self._deny("target_missing", "A target entity set is required.")

            # 6a. Filter requirement.
            filter_fields = set((call.params.filter or {}).keys())
            if self.policy.require_filter_for_list and not filter_fields:
                return ValidationResult(
                    allowed=False,
                    needs_clarification=True,
                    clarification_question=self._required_filter_prompt(call.target),
                    violations=[
                        PolicyViolation(
                            code="unfiltered_list",
                            message="List queries require at least one filter.",
                        )
                    ],
                )

            # 6b. Required filters for known targets.
            req = self.policy.required_filters.get(call.target)
            if req:
                any_of = set(req.get("any_of", []))
                if any_of and not (filter_fields & any_of):
                    return ValidationResult(
                        allowed=False,
                        needs_clarification=True,
                        clarification_question=self._required_filter_prompt(call.target),
                        violations=[
                            PolicyViolation(
                                code="required_filter_missing",
                                message=(
                                    f"Provide at least one of: {', '.join(sorted(any_of))}."
                                ),
                            )
                        ],
                    )

            # 6c. Row bound.
            top = call.params.top
            if top is None:
                return self._deny(
                    "unbounded_query",
                    "List queries must be bounded with a row limit.",
                )
            if top > self.policy.max_rows:
                return self._deny(
                    "row_limit_exceeded",
                    f"Requested too many rows. The maximum is {self.policy.max_rows}.",
                )
            if top <= 0:
                return self._deny("invalid_top", "Row limit must be a positive number.")

            return ValidationResult(allowed=True)

        return self._deny("unknown_action", f"The action '{call.action}' is not recognized.")

    @staticmethod
    def _deny(code: str, message: str) -> ValidationResult:
        return ValidationResult(
            allowed=False,
            violations=[PolicyViolation(code=code, message=message)],
        )

    def _required_filter_prompt(self, target: str) -> str:
        req = self.policy.required_filters.get(target, {})
        any_of = req.get("any_of", [])
        if any_of:
            return (
                f"To look up {target}, please provide at least one of: "
                f"{', '.join(any_of)}."
            )
        return f"Please provide a filter to narrow the {target} query."
