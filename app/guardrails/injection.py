"""Prompt-injection defenses for SAP-returned business data.

Text returned from SAP fields is untrusted. We must:
  * Never follow instructions embedded in SAP field values.
  * Strip secret-like values that should never reach the LLM or the user.
  * Preserve legitimate business values (PO numbers, amounts, names).

This module sanitizes evidence records before they are handed to the LLM. It
does NOT rewrite business meaning; it only neutralizes secrets and flags
instruction-like content so downstream prompts can treat it as inert data.
"""

from __future__ import annotations

import re
from typing import Any

from app.guardrails.redaction import DEFAULT_BLOCKED_TERMS, redact_text

# Patterns that look like injected instructions. We do not delete business text,
# but we detect these so the value can be wrapped/marked as untrusted data.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?(system|previous|prior)", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(credentials|secret|token|password)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"(system|developer)\s+prompt", re.IGNORECASE),
]


def looks_like_injection(text: str) -> bool:
    """Return True if the text resembles an embedded instruction/jailbreak."""
    if not text:
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def sanitize_value(value: Any, blocked_terms: tuple[str, ...] | None = None) -> Any:
    """Sanitize a single evidence value.

    Secrets are redacted. Business text is preserved verbatim (the LLM prompt is
    responsible for treating SAP data as inert), but we redact secret-like
    fragments so they never leak even if the model echoes the field.
    """
    terms = blocked_terms or DEFAULT_BLOCKED_TERMS
    if isinstance(value, str):
        return redact_text(value, terms)
    if isinstance(value, dict):
        return {k: sanitize_value(v, terms) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_value(v, terms) for v in value]
    return value


def sanitize_evidence_records(
    records: list[dict[str, Any]],
    blocked_terms: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Sanitize a list of SAP record dicts before they reach the LLM."""
    return [sanitize_value(rec, blocked_terms) for rec in records]
