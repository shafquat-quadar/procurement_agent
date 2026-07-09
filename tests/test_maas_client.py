"""MaaS client contract tests (token flow + documented request body).

These lock the wire contract described in the MaaS docs: a token POST that
returns an access token, followed by an LLM POST carrying the bearer token, the
APIM subscription-key header, and the documented JSON body (including
`is_stream` serialized as a capitalized string).
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config.settings import Settings
from app.maas.client import MaaSClient, MaaSError
from app.maas.schemas import MaaSRequest

TOKEN_URL = "https://apim.example.test/token"
LLM_URL = "https://apim.example.test/llm/chat"


def _settings() -> Settings:
    return Settings(
        ACCESS_KEY="client-key",
        ACCESS_SECRET="secret-key",
        TOKEN_URL=TOKEN_URL,
        LLM_URL=LLM_URL,
        LLM_MODEL="gemini-3",
        SUBSCRIPTION_KEY="sub-key-123",
        SSL_CERTIFICATE="",
    )


def _request() -> MaaSRequest:
    return MaaSRequest(
        model="gemini-3",
        sys_prompt="You are a helpful assistant.",
        prompt="Summarize the PO.",
        max_tokens=1200,
        temperature=0.0,
        top_p=0.1,
        is_stream=False,
    )


def test_is_stream_serialized_as_string():
    payload = _request().to_payload()
    assert payload["is_stream"] == "False"
    assert set(payload) == {
        "model",
        "sys_prompt",
        "prompt",
        "max_tokens",
        "temperature",
        "top_p",
        "is_stream",
    }


@respx.mock
def test_token_then_llm_happy_path():
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-abc", "expires_in": 3600})
    )
    llm_route = respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json={"response": "PO 4500123456 is Open."})
    )

    result = MaaSClient(_settings()).complete(_request())

    assert result.text == "PO 4500123456 is Open."
    assert token_route.called
    assert llm_route.called

    llm_request = llm_route.calls.last.request
    assert llm_request.headers["Authorization"] == "Bearer tok-abc"
    assert llm_request.headers["Ocp-Apim-Subscription-Key"] == "sub-key-123"
    body = json.loads(llm_request.content)
    assert body["model"] == "gemini-3"
    assert body["sys_prompt"] == "You are a helpful assistant."
    assert body["is_stream"] == "False"


@respx.mock
def test_token_failure_raises_safe_error():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401, json={"error": "nope"}))
    with pytest.raises(MaaSError) as exc:
        MaaSClient(_settings()).complete(_request())
    assert exc.value.code == "token_rejected"


@respx.mock
def test_empty_llm_response_raises():
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-abc", "expires_in": 3600})
    )
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json={"response": ""}))
    with pytest.raises(MaaSError) as exc:
        MaaSClient(_settings()).complete(_request())
    assert exc.value.code in {"llm_empty", "llm_malformed"}
