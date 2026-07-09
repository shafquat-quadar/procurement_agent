# Local Procurement ReAct Chatbot POC using MaaS + MCP + SAP OData

A local, policy-controlled procurement chatbot that answers SAP procurement
questions using **MaaS** as the LLM abstraction layer and a **local SAP OData
MCP server** as the *only* SAP data access layer.

> **Key principle:** The LLM must never invent SAP facts. Every SAP factual
> answer is grounded only in evidence returned through MCP tool calls, and a
> deterministic verifier enforces this before any answer is returned.

---

## 1. Overview

This POC wraps an existing local SAP OData MCP server (exposing the `odata` and
`odata_help` tools over SSE) with a controlled LangGraph ReAct agent, a FastAPI
service, and a Chainlit chat UI. It is **read-only**: it can look up purchase
orders, purchase requisitions, suppliers, materials, and info records, but it
can never write back to SAP.

The agent is deliberately *controlled* rather than autonomous:

- Intent classification and tool planning are **deterministic** (rule-based).
- The LLM is used only for **grounded answer generation**.
- A **policy validator** runs before every MCP call.
- A **verifier** runs before every final answer.

## 2. Architecture

```
User
  ↓
Chainlit UI
  ↓
FastAPI /chat
  ↓
LangGraph controlled ReAct agent
  ↓
MaaSChatModel
  ↓
Policy validator
  ↓
MCP client over SSE
  ↓
local-odata-mcp
  ↓
SAP OData backend
  ↓
Evidence normalizer
  ↓
Answer verifier
  ↓
Grounded final answer
```

Graph node order:

```
classify_intent → extract_inputs → decide_if_tool_required →
discover_metadata_if_needed → create_tool_plan → validate_tool_plan →
call_mcp → normalize_evidence → draft_answer → verify_answer → final_response
```

## 3. Key design principle: SAP facts require SAP evidence

- The final answer may only use facts present in **Evidence** records.
- If no evidence exists, the agent does not answer SAP factual questions.
- If evidence is empty, it says no matching SAP data was found.
- If evidence is ambiguous or identifiers are missing, it asks for clarification.
- If the MCP/SAP call fails, it says the SAP data retrieval failed — safely.
- A deterministic verifier checks every PO/PR number, vendor, supplier,
  material, date, quantity, amount, price, plant, purchasing org, and status in
  the answer against the evidence. Unsupported claims trigger a regeneration and,
  if still unsupported, a safe refusal.

## 4. Tech stack

Python 3.11+, FastAPI, Uvicorn, LangGraph, LangChain core, httpx, Pydantic v2,
python-dotenv, PyYAML, SQLite, structlog, Chainlit, pytest, pytest-asyncio,
respx, ruff. MCP access uses the official `mcp` SSE client (optional
`langchain-mcp-adapters` may be used); a clean `McpClient` abstraction isolates
the transport.

Explicitly **not** used: vector DB, Redis, Kafka, Kubernetes, CrewAI, Autogen,
write-back to SAP, fake SAP data, hardcoded credentials, or direct SAP calls
outside MCP.

## 5. Folder structure

```
app/
  main.py            # FastAPI: /chat, /health, /traces/{trace_id}
  chainlit_app.py    # Chainlit UI
  agent/             # graph, state, prompts loader, intent, planner, verifier, answer
  maas/              # MaaS client, LangChain chat model, schemas
  mcp_client/        # MCP SSE client + tool-call schemas
  guardrails/        # policy.yaml, validator, redaction, injection
  evidence/          # evidence models, SQLite store, normalizer
  observability/     # structlog logging
  config/            # settings (env-only)
  prompts/           # prompt markdown files
tests/               # pytest suite
.env.example
pyproject.toml
README.md
run_local.sh
```

## 6. Environment configuration

All configuration is environment-only (never hardcoded). Copy `.env.example` to
`.env` and fill in values:

| Variable | Purpose |
| --- | --- |
| `ACCESS_KEY` / `ACCESS_SECRET` | MaaS credentials |
| `TOKEN_URL` | MaaS token endpoint |
| `LLM_URL` | MaaS LLM endpoint |
| `LLM_MODEL` | Model name (default `gemini-3`) |
| `SUBSCRIPTION_KEY` | API gateway subscription key |
| `SSL_CERTIFICATE` | Path to a CA/SSL bundle for outbound TLS |
| `MCP_SERVER_URL` | MCP SSE URL (default `http://127.0.0.1:8000/sse`) |
| `NO_PROXY` | Bypass proxy for localhost |
| `CHAT_API_URL` | FastAPI base URL the Chainlit UI calls |
| `TRACE_DB_PATH` | SQLite trace DB path |

> The exact MaaS auth contract is isolated in `app/maas/client.py`
> (`_build_token_request` / `_build_llm_headers`). If your internal MaaS uses a
> different header/body format, adapt those two methods only. If a
> `maas_sample_code.py` exists in the repo, align them to it.

## 7. How to run

**Step 1 — Create a virtual environment.**

```bash
python -m venv .venv
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate
```

**Step 2 — Install dependencies.**

```bash
pip install -e ".[dev]"
# to enable the MCP SSE client:
pip install -e ".[dev,mcp]"
# or, if uv is available:
uv sync
```

**Step 3 — Create `.env` from `.env.example`.**

```bash
cp .env.example .env
```

**Step 4 — Fill `.env` values** (see the table above).

**Step 5 — Start the existing MCP server (terminal 1).** See section 8.

**Step 6 — Start FastAPI (terminal 2).** See section 9.

**Step 7 — Start Chainlit (terminal 3).** See section 10.

**Step 8 — Ask example questions.** See section 15.

## 8. How to run the MCP server

The MCP server is a separate, existing component. Start it in its own terminal:

```bash
python -m odata_mcp --config config.yaml --transport sse
```

Confirm it is reachable at:

```
http://127.0.0.1:8000/sse
```

This POC does **not** modify or replace the MCP server; it only consumes it.

## 9. How to run the FastAPI service

```bash
uvicorn app.main:app --reload --port 9000
# or:
./run_local.sh
```

Health check:

```
http://127.0.0.1:9000/health   ->   {"status": "ok"}
```

## 10. How to run the Chainlit UI

```bash
chainlit run app/chainlit_app.py
```

The UI sends messages to the FastAPI `/chat` endpoint and displays the answer,
`trace_id`, evidence summary, and tool-call summary. It never displays hidden
chain-of-thought, raw tokens, headers, secrets, cookies, CSRF tokens, or stack
traces.

## 11. How prompts are managed

Prompts live in `app/prompts/`:

- `system.procurement.md`
- `intent_classifier.md`
- `tool_planner.md`
- `answer_generator.md`
- `answer_verifier.md`

Rules:

- Prompts are loaded from files (not hardcoded) via `app/agent/prompts.py`.
- Prompts are **versioned** in `app/agent/prompts.py` (`PROMPT_VERSIONS`); prompt
  file names and versions are included in trace logs (`chat_received`).
- Prompt changes should be reviewed because they affect model behavior.
- **Prompt changes cannot bypass `policy.yaml`.** The policy validator is
  deterministic and always runs before MCP calls. The answer verifier always
  runs before the final response.
- Do not add SAP facts into prompts.
- Do not add fake examples that look like real SAP records unless clearly marked
  as examples.
- Do not put credentials or internal URLs in prompts.

To update a prompt: edit its `.md` file, bump its version in
`PROMPT_VERSIONS`, and review the change. Deterministic guardrails are
unaffected.

## 12. How guardrails work

Guardrails are defined in `app/guardrails/policy.yaml` and enforced
deterministically in `app/guardrails/validator.py`:

- **Read-only mode** — mode `read_only`.
- **Service allowlist** — only the five procurement services are permitted.
- **Action allowlist** — only `service_info`, `list_entities`, `describe_entity`,
  `list`, `get`.
- **Blocked write actions** — `create`, `update`, `delete`, `approve`,
  `release`, `post` are always rejected.
- **Required filters for list queries** — a `list` must include a filter, and
  known entities require at least one of a specific set of fields.
- **Max rows per call** — `top` is capped at 50.
- **Max tool calls per question** — capped at 8.
- **Evidence-only final answer** — the answer generator only sees evidence.
- **Verifier pass** — a deterministic check that every SAP claim is grounded.
- **Secret redaction** — tokens, cookies, bearer values, authorization headers,
  and secrets are stripped from any text/mapping shown to the user, logged, or
  sent to the LLM.
- **Prompt injection defense** — SAP field values are treated as inert,
  untrusted data; secret-like fragments are redacted before evidence reaches the
  LLM, and instructions embedded in SAP data are never followed.
- **Safe errors** — users always receive a safe, non-leaking message.

## 13. How evidence verification works

1. Every validated MCP call produces an **Evidence** record (service, entity,
   action, query, retrieved-at, records).
2. The answer generator receives only sanitized evidence and the user question.
3. The verifier (`app/agent/verifier.py`) extracts factual claims from the draft
   answer (numbers, currencies, statuses) and checks each against the evidence
   (plus the user's own supplied identifiers).
4. If any claim is unsupported, the answer is regenerated strictly from
   evidence. If it still fails, the agent returns:
   *"I could not generate a fully supported answer from the SAP evidence
   retrieved."*

## 14. Supported intents

- `purchase_order_status` (requires PO number)
- `purchase_order_items` (requires PO number)
- `purchase_requisition_status` (requires PR number)
- `supplier_lookup` (requires supplier number or name)
- `material_lookup` (requires material number or description)
- `purchase_info_record_lookup` (requires supplier + material, or material + purchasing org)
- `open_purchase_orders_by_vendor` (requires vendor, plant, purchasing org, company code, or date range)
- `purchase_order_history` (requires PO number)
- `explain_procurement_field` (no SAP data)
- `out_of_scope`

## 15. Example questions

- What is the status of PO 4500123456?
- Show me items for PO 4500123456.
- What is the status of PR 10001234?
- Find supplier 10000045.
- Find material ABC123.
- Show open POs for vendor 10000045 in July 2026.

## 16. Testing

```bash
pytest
ruff check app tests
```

The suite covers the policy validator, verifier, intent classification,
redaction, and end-to-end agent flows (happy path, empty result, MCP timeout,
prompt injection) using mocked MCP and LLM dependencies — no live SAP/MaaS
connection is required to run the tests.

## 17. Troubleshooting

- **`/health` fails to start** — check that dependencies installed and the
  virtualenv is active.
- **MCP calls fail with "client library not installed"** — install the optional
  MCP dependency: `pip install -e ".[mcp]"`.
- **MCP connection refused** — ensure the MCP server is running at
  `MCP_SERVER_URL` and reachable; confirm `http://127.0.0.1:8000/sse`.
- **MaaS token/LLM errors** — verify `TOKEN_URL`, `LLM_URL`, credentials, and
  `SSL_CERTIFICATE`; the auth contract lives in `app/maas/client.py`.
- **Proxy interfering with localhost** — set `NO_PROXY=127.0.0.1,localhost`.
- **Chainlit can't reach the API** — check `CHAT_API_URL`.

## 18. Known limitations

- POC is read-only.
- Only supported intents are enabled.
- Broad analytical queries require explicit filters.
- No write-back to SAP.
- No long-term enterprise auth model yet.
- User authorization currently depends on local `user_context` and SAP/MCP
  backend behavior.
- MaaS API contract may need adjustment based on internal implementation.
- MCP server must be running separately.
- The chatbot does not answer SAP factual questions without evidence.

## 19. Future hardening

- Enforce `user_context` roles/plants/purchasing-orgs as SAP-side authorization.
- Add per-session rate limiting and audit export.
- Add richer metadata discovery + caching for unknown entities/fields.
- Add an optional LLM-based secondary verifier alongside the deterministic gate.
- Expand intent coverage and add golden-answer regression tests.
- Move token handling to a dedicated secrets manager.
```
