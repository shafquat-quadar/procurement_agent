"""Request/response schemas for the MaaS LLM API.

The exact MaaS wire contract is intentionally isolated here and in
`maas/client.py` so it is easy to adapt to the internal implementation without
touching agent logic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MaaSRequest(BaseModel):
    """Payload sent to the MaaS LLM endpoint.

    Mirrors the documented MaaS request body:
        {model, sys_prompt, prompt, max_tokens, temperature, top_p, is_stream}
    """

    model: str
    sys_prompt: str = ""
    prompt: str
    max_tokens: int = 1200
    temperature: float = 0.0
    top_p: float = 0.1
    is_stream: bool = False

    def to_payload(self) -> dict:
        """Serialize to the documented MaaS JSON body.

        The MaaS docs show `is_stream` as a capitalized string ("True"/"False").
        If your MaaS instance expects a JSON boolean instead, change this one
        line to `self.is_stream`.
        """
        return {
            "model": self.model,
            "sys_prompt": self.sys_prompt,
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "is_stream": "True" if self.is_stream else "False",
        }


class MaaSResponse(BaseModel):
    """Normalized MaaS response with just the generated text."""

    text: str
    model: str | None = None
    raw: dict = Field(default_factory=dict)
