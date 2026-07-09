"""Evidence models.

An Evidence record captures exactly what SAP returned for a validated tool call.
The final answer may only use facts present in evidence records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex[:12]}"


class Evidence(BaseModel):
    """A grounded record of SAP data retrieved via MCP."""

    evidence_id: str = Field(default_factory=_evidence_id)
    source: str = "SAP"
    service: str
    entity: str
    action: str
    query: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: str = Field(default_factory=_now_iso)
    records_returned: int = 0
    records: list[dict[str, Any]] = Field(default_factory=list)

    def summary(self) -> EvidenceSummary:
        return EvidenceSummary(
            evidence_id=self.evidence_id,
            source=self.source,
            service=self.service,
            entity=self.entity,
            action=self.action,
            records_returned=self.records_returned,
        )

    def flattened_values(self) -> set[str]:
        """Return all scalar values (as strings) present in the evidence records.

        Used by the deterministic verifier to check that claims in the answer are
        grounded in retrieved SAP data.
        """
        values: set[str] = set()

        def _walk(value: Any) -> None:
            if isinstance(value, dict):
                for v in value.values():
                    _walk(v)
            elif isinstance(value, (list, tuple)):
                for v in value:
                    _walk(v)
            elif value is not None:
                values.add(str(value).strip())

        for rec in self.records:
            _walk(rec)
        return {v for v in values if v}


class EvidenceSummary(BaseModel):
    """Compact evidence descriptor returned in the API response."""

    evidence_id: str
    source: str = "SAP"
    service: str
    entity: str
    action: str
    records_returned: int
