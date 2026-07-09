"""FastAPI service exposing the procurement agent.

Endpoints:
    POST /chat              -> answer a procurement question
    GET  /health            -> health check
    GET  /traces/{trace_id} -> retrieve a stored trace
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.agent.graph import AgentDependencies, run_agent
from app.agent.state import ChatRequest, ChatResponse
from app.config.settings import get_settings
from app.evidence.store import TraceStore
from app.guardrails.validator import ToolPlanValidator, load_policy
from app.maas.chat_model import MaaSChatModel
from app.maas.client import MaaSClient
from app.mcp_client.client import McpClient
from app.observability.logging import configure_logging, get_logger

logger = get_logger("api")


def build_dependencies() -> AgentDependencies:
    """Construct production dependencies from settings."""
    settings = get_settings()
    maas_client = MaaSClient(settings)
    chat_model = MaaSChatModel(client=maas_client, model_name=settings.llm_model)
    mcp_client = McpClient(settings)
    validator = ToolPlanValidator(load_policy())
    store = TraceStore(settings.trace_db_path)
    return AgentDependencies(
        chat_model=chat_model,
        mcp_client=mcp_client,
        validator=validator,
        store=store,
        settings=settings,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.deps = build_dependencies()
    logger.info("service_started", mcp_url=settings.mcp_server_url, model=settings.llm_model)
    try:
        yield
    finally:
        store: TraceStore | None = getattr(app.state.deps, "store", None)
        if store:
            store.close()


app = FastAPI(title="Procurement Agent POC", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    deps: AgentDependencies = app.state.deps
    try:
        return await run_agent(deps, request)
    except Exception:  # never leak internals to the client
        logger.exception("chat_unhandled_error")
        raise HTTPException(status_code=500, detail="The request could not be processed.") from None


@app.get("/traces/{trace_id}")
async def get_trace(trace_id: str) -> dict:
    deps: AgentDependencies = app.state.deps
    if not deps.store:
        raise HTTPException(status_code=404, detail="Trace store not available.")
    trace = deps.store.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return trace
