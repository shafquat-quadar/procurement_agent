"""MCP client over SSE.

Talks to the existing local SAP OData MCP server (exposing `odata` and
`odata_help`) over the SSE transport. Uses the official `mcp` Python SDK when
available; otherwise raises a clear, safe error. The agent depends on the
`McpClientProtocol` interface so tests can inject a fake without a live server.

This is the ONLY path to SAP data. No direct SAP/OData calls exist elsewhere.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.observability.logging import get_logger

logger = get_logger("mcp")


class McpError(Exception):
    """Raised on MCP transport/tool failures. Message is safe to surface."""

    def __init__(self, message: str, *, code: str = "mcp_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class McpToolResult(BaseModel):
    """Normalized MCP tool result."""

    tool: str
    content: Any = None
    is_error: bool = False
    raw_text: str | None = None


@runtime_checkable
class McpClientProtocol(Protocol):
    """Interface the agent depends on for MCP access."""

    async def call_tool(self, tool: str, arguments: dict[str, Any]) -> McpToolResult: ...


def _parse_tool_content(contents: list[Any]) -> tuple[Any, str | None]:
    """Extract a JSON payload (or text) from MCP content items."""
    texts: list[str] = []
    for item in contents:
        text = getattr(item, "text", None)
        if text is None and isinstance(item, dict):
            text = item.get("text")
        if isinstance(text, str):
            texts.append(text)

    joined = "\n".join(texts) if texts else None
    if joined is None:
        return None, None
    try:
        return json.loads(joined), joined
    except (ValueError, TypeError):
        return joined, joined


class McpClient:
    """SSE-based MCP client using the official `mcp` SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._server_url = self._settings.mcp_server_url
        self._timeout = self._settings.mcp_timeout_seconds

    async def call_tool(self, tool: str, arguments: dict[str, Any]) -> McpToolResult:
        """Open an SSE session, call `tool`, and return a normalized result.

        A fresh session per call keeps the POC simple and stateless. For higher
        throughput this could be pooled, but correctness/isolation come first.
        """
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise McpError(
                "The MCP SSE client library is not installed. "
                "Install the optional 'mcp' dependency to enable SAP access.",
                code="mcp_client_missing",
            ) from exc

        try:
            async with sse_client(self._server_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
        except McpError:
            raise
        except Exception as exc:  # transport/protocol failure
            logger.error("mcp_call_failed", tool=tool, error=str(exc))
            raise McpError(
                "The SAP data retrieval failed while contacting the MCP server.",
                code="mcp_transport_error",
            ) from exc

        contents = getattr(result, "content", []) or []
        payload, raw_text = _parse_tool_content(contents)
        is_error = bool(getattr(result, "isError", False))
        return McpToolResult(tool=tool, content=payload, is_error=is_error, raw_text=raw_text)
