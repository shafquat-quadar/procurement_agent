"""Shared test fakes and fixtures."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.agent.graph import AgentDependencies
from app.evidence.store import TraceStore
from app.guardrails.validator import ToolPlanValidator, load_policy
from app.mcp_client.client import McpError, McpToolResult


class FakeChatModel:
    """A ChatModel test double that records prompts and returns a canned reply."""

    def __init__(self, response: str | Callable[[str, str, str], str] = "Grounded answer.") -> None:
        self.response = response
        self.prompts: list[str] = []
        self.calls: list[tuple[str, str, str]] = []

    def generate_text(self, sys_prompt: str, prompt: str, mode: str = "factual") -> str:
        self.calls.append((sys_prompt, prompt, mode))
        self.prompts.append(prompt)
        if callable(self.response):
            return self.response(sys_prompt, prompt, mode)
        return self.response


class FakeMcpClient:
    """An MCP client test double returning a preset result or raising."""

    def __init__(self, result: McpToolResult | None = None, error: McpError | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool: str, arguments: dict[str, Any]) -> McpToolResult:
        self.calls.append((tool, arguments))
        if self.error:
            raise self.error
        return self.result or McpToolResult(tool=tool, content=[])


@pytest.fixture
def validator() -> ToolPlanValidator:
    return ToolPlanValidator(load_policy())


@pytest.fixture
def store() -> TraceStore:
    s = TraceStore(":memory:")
    yield s
    s.close()


def make_deps(
    chat_model: FakeChatModel,
    mcp_client: FakeMcpClient,
    store: TraceStore | None = None,
) -> AgentDependencies:
    return AgentDependencies(
        chat_model=chat_model,
        mcp_client=mcp_client,
        validator=ToolPlanValidator(load_policy()),
        store=store,
    )
