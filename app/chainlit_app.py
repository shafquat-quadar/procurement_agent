"""Chainlit chat UI for the procurement agent.

Sends user messages to the FastAPI /chat endpoint and renders:
  * the final answer
  * the trace id
  * an evidence summary
  * a tool-call summary

It never renders hidden chain-of-thought, raw tokens/headers, secrets, cookies,
CSRF tokens, or stack traces. Displayed text is additionally passed through the
secret redactor as defense-in-depth.
"""

from __future__ import annotations

import os

import chainlit as cl
import httpx

from app.guardrails.redaction import redact_text

API_URL = os.getenv("CHAT_API_URL", "http://127.0.0.1:9000").rstrip("/")
NO_PROXY = os.getenv("NO_PROXY", "127.0.0.1,localhost")
# Ensure local API calls bypass any configured proxy.
os.environ.setdefault("NO_PROXY", NO_PROXY)
os.environ.setdefault("no_proxy", NO_PROXY)


@cl.on_chat_start
async def on_start() -> None:
    cl.user_session.set("session_id", cl.user_session.get("id"))
    await cl.Message(
        content=(
            "Procurement assistant ready. Ask about POs, PRs, suppliers, "
            "materials, or info records. Answers are grounded only in SAP "
            "evidence retrieved via MCP."
        )
    ).send()


def _format_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return "_No SAP evidence used._"
    lines = ["**Evidence**"]
    for ev in evidence:
        lines.append(
            f"- `{ev.get('evidence_id')}` · {ev.get('service')}/{ev.get('entity')} "
            f"· {ev.get('action')} · {ev.get('records_returned')} record(s)"
        )
    return "\n".join(lines)


def _format_tool_calls(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return "_No SAP tool calls made._"
    lines = ["**Tool calls**"]
    for tc in tool_calls:
        lines.append(
            f"- {tc.get('service')} · {tc.get('action')} · {tc.get('target')} "
            f"· {tc.get('status')} · {tc.get('duration_ms')} ms"
        )
    return "\n".join(lines)


def _format_verification(verification: dict) -> str:
    supported = verification.get("supported", True)
    unsupported = verification.get("unsupported_claims", [])
    if supported:
        return "**Verification:** ✅ all claims supported by evidence"
    return f"**Verification:** ⚠️ unsupported claims removed: {', '.join(unsupported) or 'n/a'}"


@cl.on_message
async def on_message(message: cl.Message) -> None:
    payload = {
        "message": message.content,
        "session_id": cl.user_session.get("session_id"),
        "user_context": {
            "user_id": "local-user",
            "roles": ["PROCUREMENT_READ"],
            "plants": [],
            "purchasing_orgs": [],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(f"{API_URL}/chat", json=payload)
    except httpx.HTTPError:
        await cl.Message(content="The assistant service is unreachable right now.").send()
        return

    if resp.status_code != 200:
        await cl.Message(content="The request could not be processed.").send()
        return

    data = resp.json()

    if data.get("needs_clarification"):
        question = data.get("clarification_question") or "Could you provide more detail?"
        await cl.Message(content=redact_text(question)).send()
        return

    answer = redact_text(data.get("answer") or "")
    details = "\n\n".join(
        [
            _format_verification(data.get("verification", {})),
            _format_evidence(data.get("evidence_summary", [])),
            _format_tool_calls(data.get("tool_calls", [])),
            f"_trace_id: `{data.get('trace_id')}`_",
        ]
    )
    await cl.Message(content=f"{answer}\n\n---\n{redact_text(details)}").send()
