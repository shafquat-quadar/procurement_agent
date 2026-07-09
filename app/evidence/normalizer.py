"""Normalize raw MCP tool results into Evidence records.

The MCP server may return records in a variety of shapes (OData `d.results`,
a bare list, a single object, or a dict with a `records`/`value` key). This
module coerces those shapes into a consistent Evidence record and applies
injection-safe sanitization before the data can reach the LLM.
"""

from __future__ import annotations

from typing import Any

from app.evidence.models import Evidence
from app.guardrails.injection import sanitize_evidence_records
from app.mcp_client.tools import ToolCall


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of a list of record dicts from an MCP payload."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        # OData v2 shape: {"d": {"results": [...]}} or {"d": {...}}
        if "d" in payload and isinstance(payload["d"], dict):
            d = payload["d"]
            if isinstance(d.get("results"), list):
                return [r for r in d["results"] if isinstance(r, dict)]
            return [d]
        for key in ("results", "records", "value", "items"):
            if isinstance(payload.get(key), list):
                return [r for r in payload[key] if isinstance(r, dict)]
        # A single record object.
        return [payload]
    return []


def normalize_tool_result(
    call: ToolCall,
    payload: Any,
    blocked_terms: tuple[str, ...] | None = None,
) -> Evidence:
    """Turn a raw MCP payload into a sanitized Evidence record."""
    records = _extract_records(payload)
    records = sanitize_evidence_records(records, blocked_terms)

    query: dict[str, Any] = {}
    if call.params.key:
        query.update(call.params.key)
    if call.params.filter:
        query.update(call.params.filter)

    return Evidence(
        service=call.service or "unknown",
        entity=call.target or "unknown",
        action=call.action,
        query=query,
        records_returned=len(records),
        records=records,
    )
