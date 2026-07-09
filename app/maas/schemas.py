"""Request/response schemas for the MaaS LLM API.

The exact MaaS wire contract is intentionally isolated here and in
`maas/client.py` so it is easy to adapt to the internal implementation without
touching agent logic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MaaSRequest(BaseModel):
    """Payload sent to the MaaS LLM endpoint."""

    model: str
    sys_prompt: str = ""
    prompt: str
    max_tokens: int = 1200
    temperature: float = 0.0
    top_p: float = 0.1
    is_stream: bool = False


class MaaSResponse(BaseModel):
    """Normalized MaaS response with just the generated text."""

    text: str
    model: str | None = None
    raw: dict = Field(default_factory=dict)
