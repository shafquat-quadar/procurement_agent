"""Secret redaction utilities.

These functions strip secret-like values from any text or mapping before it is
shown to the user, logged, or sent to the LLM. Redaction is deterministic and
independent of prompts.
"""

from __future__ import annotations

import re
from typing import Any

# Terms whose *values* (in key/value pairs) or presence in headers indicate a
# secret. Kept lowercase for case-insensitive matching.
DEFAULT_BLOCKED_TERMS: tuple[str, ...] = (
    "access_token",
    "refresh_token",
    "client_secret",
    "access_secret",
    "subscription_key",
    "authorization",
    "cookie",
    "x-csrf-token",
    "csrf",
    "password",
    "bearer",
    "set-cookie",
    "api_key",
    "apikey",
)

REDACTED = "[REDACTED]"

# Bearer tokens: `Bearer <token>` (also matches lowercase "bearer").
_BEARER_RE = re.compile(r"\bbearer\s+[A-Za-z0-9._\-+/=]+", re.IGNORECASE)
# Authorization header line.
_AUTH_HEADER_RE = re.compile(r"authorization\s*[:=]\s*\S+", re.IGNORECASE)
# key=value / "key": "value" style secrets.
_KV_SECRET_RE = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(t) for t in DEFAULT_BLOCKED_TERMS)
    + r")\b(\s*[:=]\s*|\"?\s*:\s*\"?)([^\s,;\"}]+)"
)


def redact_text(text: str, blocked_terms: tuple[str, ...] | list[str] | None = None) -> str:
    """Redact secret-like substrings from free text."""
    if not text:
        return text

    result = _BEARER_RE.sub(f"bearer {REDACTED}", text)
    result = _AUTH_HEADER_RE.sub(f"authorization: {REDACTED}", result)

    terms = tuple(t.lower() for t in (blocked_terms or DEFAULT_BLOCKED_TERMS))
    kv_re = re.compile(
        r"(?i)\b(" + "|".join(re.escape(t) for t in terms)
        + r")\b(\s*[:=]\s*|\"?\s*:\s*\"?)([^\s,;\"}]+)"
    )
    result = kv_re.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", result)
    return result


def _is_secret_key(key: str, blocked_terms: tuple[str, ...]) -> bool:
    key_l = key.lower()
    return any(term in key_l for term in blocked_terms)


def redact_mapping(
    value: Any,
    blocked_terms: tuple[str, ...] | list[str] | None = None,
) -> Any:
    """Recursively redact secret values in dicts/lists.

    Keys whose name matches a blocked term have their value replaced entirely.
    String values are additionally scrubbed of inline secrets.
    """
    terms = tuple(t.lower() for t in (blocked_terms or DEFAULT_BLOCKED_TERMS))

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_secret_key(k, terms):
                out[k] = REDACTED
            else:
                out[k] = redact_mapping(v, terms)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_mapping(v, terms) for v in value]
    if isinstance(value, str):
        return redact_text(value, terms)
    return value
