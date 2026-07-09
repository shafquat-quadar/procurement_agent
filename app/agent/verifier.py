"""Deterministic answer verifier.

Checks that every factual SAP claim in a draft answer is supported by retrieved
evidence. This is a hard, deterministic gate that always runs before the final
response — it does not depend on the LLM and cannot be bypassed by prompts.

A claim is "grounded" if it appears in the evidence. Identifiers the user
supplied (and text from their own question) are also acceptable context, so an
honest "no matching data found for PO X" message does not fail verification for
echoing the user's own PO number.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.state import VerificationResult
from app.evidence.models import Evidence

# Numbers: amounts, quantities, prices, PO/PR numbers.
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_CURRENCY_RE = re.compile(r"\b[A-Z]{3}\b")

# Assertive SAP status/state words that must be evidence-backed if claimed.
_STATUS_WORDS: tuple[str, ...] = (
    "delayed",
    "overdue",
    "approved",
    "rejected",
    "released",
    "blocked",
    "cancelled",
    "canceled",
    "completed",
    "delivered",
    "invoiced",
    "goods receipt",
)

_CURRENCIES: frozenset[str] = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "INR", "CNY", "CHF", "CAD", "AUD",
        "SGD", "HKD", "SEK", "NOK", "DKK", "KRW", "MXN", "BRL", "ZAR",
    }
)


def _normalize(text: str) -> str:
    return re.sub(r"[,$]", "", text).lower()


def _is_claim_number(raw: str) -> bool:
    """Only treat sizeable numbers / decimals as factual claims.

    Small counts like "1 record" or "3 items" are not SAP field values.
    """
    digits = re.sub(r"\D", "", raw)
    return len(digits) >= 3 or "." in raw


def verify_answer(
    draft_answer: str,
    evidence: list[Evidence],
    user_message: str = "",
    identifiers: dict[str, Any] | None = None,
) -> VerificationResult:
    """Verify a draft answer against evidence. Returns a VerificationResult."""
    grounding_parts: list[str] = []
    for ev in evidence:
        grounding_parts.extend(ev.flattened_values())
    if identifiers:
        grounding_parts.extend(str(v) for v in identifiers.values())
    if user_message:
        grounding_parts.append(user_message)

    blob = _normalize(" ".join(grounding_parts))

    unsupported: list[str] = []

    # Numeric claims.
    for raw in set(_NUMBER_RE.findall(draft_answer)):
        if not _is_claim_number(raw):
            continue
        norm = _normalize(raw)
        if norm and norm not in blob:
            unsupported.append(raw)

    # Currency claims.
    for cur in set(_CURRENCY_RE.findall(draft_answer)):
        if cur not in _CURRENCIES:
            continue
        if cur.lower() not in blob:
            unsupported.append(cur)

    # Status claims.
    for word in _STATUS_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", draft_answer, re.IGNORECASE) and word not in blob:
            unsupported.append(word)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unsupported = [c for c in unsupported if not (c in seen or seen.add(c))]

    supported = not unsupported
    return VerificationResult(
        supported=supported,
        unsupported_claims=unsupported,
        final_answer_allowed=supported,
    )
