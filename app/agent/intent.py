"""Deterministic intent classification and identifier extraction.

Intent detection is rule-based (not left to the LLM) so it is predictable,
testable, and cannot be steered by injected content. The LLM is used later for
answer generation and verification, always grounded in evidence.

Each supported intent declares which identifiers it requires. When required
identifiers are missing, the agent asks a clarification question instead of
running a broad, unfiltered SAP query.
"""

from __future__ import annotations

import re

from app.agent.state import Intent

# Supported intents.
PURCHASE_ORDER_STATUS = "purchase_order_status"
PURCHASE_ORDER_ITEMS = "purchase_order_items"
PURCHASE_REQUISITION_STATUS = "purchase_requisition_status"
SUPPLIER_LOOKUP = "supplier_lookup"
MATERIAL_LOOKUP = "material_lookup"
PURCHASE_INFO_RECORD_LOOKUP = "purchase_info_record_lookup"
OPEN_POS_BY_VENDOR = "open_purchase_orders_by_vendor"
PURCHASE_ORDER_HISTORY = "purchase_order_history"
EXPLAIN_FIELD = "explain_procurement_field"
OUT_OF_SCOPE = "out_of_scope"

# --- identifier extraction patterns ---
_PO_KEYED_RE = re.compile(r"(?:purchase\s*order|p\.?\s*o\.?)\s*#?\s*[:\-]?\s*(\d{6,12})", re.I)
_PO_BARE_RE = re.compile(r"\b(45\d{8})\b")
_PR_KEYED_RE = re.compile(
    r"(?:purchase\s*requisition|requisition|p\.?\s*r\.?)\s*#?\s*[:\-]?\s*(\d{6,12})", re.I
)
_SUPPLIER_RE = re.compile(r"(?:supplier|vendor)\s*#?\s*[:\-]?\s*(\d{4,12})", re.I)
_SUPPLIER_NAME_RE = re.compile(
    r"(?:supplier|vendor)\s+(?:name(?:d)?|called)\s+([A-Za-z][\w &.\-]{2,40})", re.I
)
_MATERIAL_RE = re.compile(r"material\s*#?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-_/]{1,30})", re.I)
_PLANT_RE = re.compile(r"plant\s*#?\s*[:\-]?\s*([A-Za-z0-9]{2,6})", re.I)
_PORG_RE = re.compile(
    r"(?:purchasing\s*org(?:anization)?|p\.?org)\s*#?\s*[:\-]?\s*([A-Za-z0-9]{2,6})", re.I
)
_COMPANY_RE = re.compile(r"company\s*code\s*#?\s*[:\-]?\s*([A-Za-z0-9]{2,6})", re.I)
_DATE_RANGE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{4}|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
    r"[a-z]*\s*\d{4})",
    re.I,
)

_HELP_HINTS = ("what does", "what is the meaning", "explain", "definition of", "what's the meaning")
_ITEMS_HINTS = ("item", "line item", "position", "lines")
_HISTORY_HINTS = ("history", "changes", "change log", "audit")
_OPEN_HINTS = ("open po", "open purchase order", "open orders", "outstanding po")
_INFO_RECORD_HINTS = ("info record", "information record", "pir", "inforecord")


def _first(*matches: re.Match | None) -> str | None:
    for m in matches:
        if m:
            return m.group(1).strip()
    return None


def _extract_identifiers(text: str) -> dict[str, str]:
    ids: dict[str, str] = {}
    po = _first(_PO_KEYED_RE.search(text), _PO_BARE_RE.search(text))
    if po:
        ids["PurchaseOrder"] = po
    pr = _first(_PR_KEYED_RE.search(text))
    if pr:
        ids["PurchaseRequisition"] = pr
    supplier = _first(_SUPPLIER_RE.search(text))
    if supplier:
        ids["Supplier"] = supplier
    supplier_name = _first(_SUPPLIER_NAME_RE.search(text))
    if supplier_name:
        ids["SupplierName"] = supplier_name
    material = _first(_MATERIAL_RE.search(text))
    if material and material.lower() not in {"description", "number", "code"}:
        ids["Material"] = material
    plant = _first(_PLANT_RE.search(text))
    if plant:
        ids["Plant"] = plant
    porg = _first(_PORG_RE.search(text))
    if porg:
        ids["PurchasingOrganization"] = porg
    company = _first(_COMPANY_RE.search(text))
    if company:
        ids["CompanyCode"] = company
    if _DATE_RANGE_RE.search(text):
        ids["DocumentDate"] = _DATE_RANGE_RE.search(text).group(1)
    return ids


def _contains(text: str, hints: tuple[str, ...]) -> bool:
    return any(h in text for h in hints)


def classify(message: str) -> tuple[Intent, list[str]]:
    """Return (Intent, missing_inputs) for a user message."""
    text = message.lower()
    ids = _extract_identifiers(message)

    intent_name = _pick_intent(text, ids)
    requires_sap = intent_name not in {EXPLAIN_FIELD, OUT_OF_SCOPE}
    missing = _missing_inputs(intent_name, ids)

    confidence = 0.9 if intent_name != OUT_OF_SCOPE else 0.5
    intent = Intent(
        name=intent_name,
        identifiers=ids,
        requires_sap=requires_sap,
        confidence=confidence,
    )
    return intent, missing


def _pick_intent(text: str, ids: dict[str, str]) -> str:  # noqa: C901
    has_po = "PurchaseOrder" in ids
    has_pr = "PurchaseRequisition" in ids

    # Explanations / field meaning (no SAP data required).
    if _contains(text, _HELP_HINTS) and not (has_po or has_pr):
        return EXPLAIN_FIELD

    # Info record.
    if _contains(text, _INFO_RECORD_HINTS):
        return PURCHASE_INFO_RECORD_LOOKUP

    # Purchase requisition.
    if has_pr or "requisition" in text:
        return PURCHASE_REQUISITION_STATUS

    # Open POs by vendor (broad list).
    if _contains(text, _OPEN_HINTS) or (
        "open" in text and ("po" in text or "purchase order" in text)
    ):
        return OPEN_POS_BY_VENDOR

    # PO-centric intents.
    po_context = has_po or "purchase order" in text or re.search(r"\bpo\b", text)
    if po_context:
        if _contains(text, _HISTORY_HINTS):
            return PURCHASE_ORDER_HISTORY
        if _contains(text, _ITEMS_HINTS):
            return PURCHASE_ORDER_ITEMS
        return PURCHASE_ORDER_STATUS

    # Supplier / vendor lookup.
    if ("supplier" in text or "vendor" in text) and (
        "Supplier" in ids or "SupplierName" in ids or "find" in text or "look" in text
    ):
        return SUPPLIER_LOOKUP

    # Material lookup.
    if "material" in text or "part number" in text:
        return MATERIAL_LOOKUP

    return OUT_OF_SCOPE


def _missing_inputs(intent_name: str, ids: dict[str, str]) -> list[str]:  # noqa: C901
    def has_any(*keys: str) -> bool:
        return any(k in ids for k in keys)

    if intent_name in {PURCHASE_ORDER_STATUS, PURCHASE_ORDER_ITEMS, PURCHASE_ORDER_HISTORY}:
        return [] if "PurchaseOrder" in ids else ["PurchaseOrder"]

    if intent_name == PURCHASE_REQUISITION_STATUS:
        return [] if "PurchaseRequisition" in ids else ["PurchaseRequisition"]

    if intent_name == SUPPLIER_LOOKUP:
        return [] if has_any("Supplier", "SupplierName") else ["Supplier or SupplierName"]

    if intent_name == MATERIAL_LOOKUP:
        if has_any("Material", "MaterialDescription"):
            return []
        return ["Material or MaterialDescription"]

    if intent_name == PURCHASE_INFO_RECORD_LOOKUP:
        if ("Supplier" in ids and "Material" in ids) or (
            "Material" in ids and "PurchasingOrganization" in ids
        ):
            return []
        return ["Supplier + Material, or Material + PurchasingOrganization"]

    if intent_name == OPEN_POS_BY_VENDOR:
        if has_any("Supplier", "Plant", "PurchasingOrganization", "CompanyCode", "DocumentDate"):
            return []
        return ["vendor, plant, purchasing org, company code, or date range"]

    return []
