"""Application settings loaded from environment variables only.

Credentials and endpoints are never hardcoded. All sensitive values come from
the process environment (typically populated from a local `.env` file that is
not committed).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the procurement agent POC."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- MaaS / LLM ---
    access_key: str = Field(default="", alias="ACCESS_KEY")
    access_secret: str = Field(default="", alias="ACCESS_SECRET")
    token_url: str = Field(default="", alias="TOKEN_URL")
    llm_url: str = Field(default="", alias="LLM_URL")
    llm_model: str = Field(default="gemini-3", alias="LLM_MODEL")
    subscription_key: str = Field(default="", alias="SUBSCRIPTION_KEY")
    ssl_certificate: str = Field(default="", alias="SSL_CERTIFICATE")

    # --- MCP ---
    mcp_server_url: str = Field(default="http://127.0.0.1:8000/sse", alias="MCP_SERVER_URL")

    # --- Networking / local service ---
    no_proxy: str = Field(default="127.0.0.1,localhost", alias="NO_PROXY")
    chat_api_url: str = Field(default="http://127.0.0.1:9000", alias="CHAT_API_URL")

    # --- Persistence / logging ---
    trace_db_path: str = Field(default="./procurement_traces.db", alias="TRACE_DB_PATH")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # --- Request tuning (seconds) ---
    llm_timeout_seconds: float = Field(default=60.0, alias="LLM_TIMEOUT_SECONDS")
    mcp_timeout_seconds: float = Field(default=30.0, alias="MCP_TIMEOUT_SECONDS")

    @property
    def ssl_verify(self) -> str | bool:
        """Value suitable for httpx `verify=`: a CA bundle path or True."""
        return self.ssl_certificate if self.ssl_certificate else True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
