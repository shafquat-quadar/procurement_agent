"""MaaS client: token retrieval + chat completion.

All auth/endpoint details are environment-driven. The request/header format is
isolated here so it can be adapted to the internal MaaS contract without
touching the agent. If a `maas_sample_code.py` exists in the repo, align the
`_build_token_request` / `_build_llm_headers` methods to it.

Error handling covers:
  * token retrieval failure
  * LLM timeout
  * malformed response
  * empty response
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.config.settings import Settings, get_settings
from app.maas.schemas import MaaSRequest, MaaSResponse
from app.observability.logging import get_logger

logger = get_logger("maas")


class MaaSError(Exception):
    """Raised for any MaaS auth/LLM failure. Message is safe to surface."""

    def __init__(self, message: str, *, code: str = "maas_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MaaSClient:
    """Handles OAuth-style token retrieval and LLM invocation for MaaS."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------------ token
    def _build_token_request(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return (headers, form/json body) for the token request.

        Adapt this to the internal MaaS auth contract. The default assumes an
        OAuth2 client-credentials flow with the access key/secret in the body.
        """
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if self._settings.subscription_key:
            headers["Ocp-Apim-Subscription-Key"] = self._settings.subscription_key
        body = {
            "grant_type": "client_credentials",
            "client_id": self._settings.access_key,
            "client_secret": self._settings.access_secret,
        }
        return headers, body

    def _get_token(self) -> str:
        """Fetch (and cache) an access token."""
        now = time.monotonic()
        if self._token and now < self._token_expiry:
            return self._token

        if not self._settings.token_url:
            raise MaaSError(
                "MaaS is not configured (TOKEN_URL missing).", code="maas_not_configured"
            )

        headers, body = self._build_token_request()
        try:
            with httpx.Client(
                verify=self._settings.ssl_verify, timeout=self._settings.llm_timeout_seconds
            ) as client:
                resp = client.post(self._settings.token_url, headers=headers, data=body)
        except httpx.HTTPError as exc:
            logger.error("maas_token_request_failed", error=str(exc))
            raise MaaSError(
                "Failed to reach the MaaS token endpoint.", code="token_failed"
            ) from exc

        if resp.status_code >= 400:
            logger.error("maas_token_http_error", status=resp.status_code)
            raise MaaSError("MaaS token request was rejected.", code="token_rejected")

        try:
            data = resp.json()
        except ValueError as exc:
            raise MaaSError("MaaS token response was malformed.", code="token_malformed") from exc

        token = data.get("access_token") or data.get("token")
        if not token:
            raise MaaSError("MaaS token response did not contain a token.", code="token_missing")

        expires_in = float(data.get("expires_in", 3000))
        self._token = token
        # Refresh a minute early.
        self._token_expiry = now + max(expires_in - 60, 30)
        return token

    # -------------------------------------------------------------------- llm
    def _build_llm_headers(self, token: str) -> dict[str, str]:
        """Return headers for the LLM call. Adapt to the internal contract."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if self._settings.subscription_key:
            headers["Ocp-Apim-Subscription-Key"] = self._settings.subscription_key
        return headers

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        """Extract generated text from a variety of possible response shapes."""
        if not isinstance(data, dict):
            raise MaaSError("MaaS response was malformed.", code="llm_malformed")

        # Common flat shapes.
        for key in ("response", "text", "output", "content", "message", "result"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val

        # OpenAI-style choices.
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    return msg["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]

        # Nested data.
        nested = data.get("data")
        if isinstance(nested, dict):
            return MaaSClient._extract_text(nested)

        raise MaaSError("MaaS response did not contain any text.", code="llm_empty")

    def complete(self, request: MaaSRequest) -> MaaSResponse:
        """Call the MaaS LLM endpoint and return normalized text."""
        if not self._settings.llm_url:
            raise MaaSError("MaaS is not configured (LLM_URL missing).", code="maas_not_configured")

        token = self._get_token()
        headers = self._build_llm_headers(token)

        try:
            with httpx.Client(
                verify=self._settings.ssl_verify, timeout=self._settings.llm_timeout_seconds
            ) as client:
                resp = client.post(
                    self._settings.llm_url,
                    headers=headers,
                    json=request.model_dump(),
                )
        except httpx.TimeoutException as exc:
            logger.error("maas_llm_timeout")
            raise MaaSError("The LLM request timed out.", code="llm_timeout") from exc
        except httpx.HTTPError as exc:
            logger.error("maas_llm_request_failed", error=str(exc))
            raise MaaSError("Failed to reach the MaaS LLM endpoint.", code="llm_failed") from exc

        if resp.status_code >= 400:
            logger.error("maas_llm_http_error", status=resp.status_code)
            raise MaaSError("The MaaS LLM request was rejected.", code="llm_rejected")

        try:
            data = resp.json()
        except ValueError as exc:
            raise MaaSError("The MaaS LLM response was malformed.", code="llm_malformed") from exc

        text = self._extract_text(data)
        if not text.strip():
            raise MaaSError("The MaaS LLM returned an empty response.", code="llm_empty")

        return MaaSResponse(text=text, model=data.get("model", request.model), raw=data)
