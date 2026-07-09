"""Schemas describing MCP tool calls used by the agent.

The agent only ever talks to SAP through the `odata` (and `odata_help`) MCP
tools exposed by the existing local MCP server. These Pydantic models define the
canonical tool-call contract used throughout the graph, the validator, and the
evidence store.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ODATA_TOOL = "odata"
ODATA_HELP_TOOL = "odata_help"

DISCOVERY_ACTIONS = frozenset({"service_info", "list_entities", "describe_entity"})
READ_ACTIONS = frozenset({"list", "get"})
WRITE_ACTIONS = frozenset({"create", "update", "delete", "approve", "release", "post"})


class ToolCallParams(BaseModel):
    """Parameters for an OData tool call."""

    model_config = ConfigDict(extra="allow")

    key: dict[str, Any] | None = None
    filter: dict[str, Any] | None = None
    select: list[str] | None = None
    top: int | None = None
    entity: str | None = None  # for describe_entity discovery


class ToolCall(BaseModel):
    """A single MCP tool call the agent intends to make.

    This mirrors the documented MCP contract:

        {
          "tool": "odata",
          "service": "sap_purchase_order",
          "action": "get",
          "target": "PurchaseOrderSet",
          "params": {...}
        }
    """

    tool: Literal["odata", "odata_help"] = ODATA_TOOL
    service: str | None = None
    action: str
    target: str | None = None
    params: ToolCallParams = Field(default_factory=ToolCallParams)

    def filter_or_key_fields(self) -> set[str]:
        """Return the set of field names present in key/filter."""
        fields: set[str] = set()
        if self.params.key:
            fields.update(self.params.key.keys())
        if self.params.filter:
            fields.update(self.params.filter.keys())
        return fields

    def to_mcp_arguments(self) -> dict[str, Any]:
        """Serialize to the argument dict passed to the MCP `odata` tool."""
        args: dict[str, Any] = {"action": self.action}
        if self.service:
            args["service"] = self.service
        if self.target:
            args["target"] = self.target
        params = self.params.model_dump(exclude_none=True)
        if params:
            args["params"] = params
        return args


class ToolCallResult(BaseModel):
    """Outcome of an executed tool call, for the API response `tool_calls`."""

    service: str | None = None
    action: str
    target: str | None = None
    status: Literal["success", "error", "blocked"] = "success"
    duration_ms: int = 0
    error: str | None = None
