"""Deterministic tool planner.

Maps a classified intent + extracted identifiers to a minimal, policy-safe MCP
tool plan. Planning is deterministic (not LLM-driven) so it can never propose a
blocked action or an unfiltered list query. The plan is still passed through the
policy validator before execution.
"""

from __future__ import annotations

from app.agent import intent as I
from app.agent.state import Intent
from app.mcp_client.tools import ToolCall, ToolCallParams

MAX_ROWS = 50

# Service + entity + default select fields per intent target.
_SELECT: dict[str, list[str]] = {
    "PurchaseOrderSet": [
        "PurchaseOrder",
        "Supplier",
        "DocumentDate",
        "OverallStatus",
        "NetAmount",
        "Currency",
    ],
    "PurchaseOrderItemSet": [
        "PurchaseOrder",
        "PurchaseOrderItem",
        "Material",
        "ShortText",
        "OrderQuantity",
        "NetPrice",
        "Plant",
    ],
    "PurchaseOrderHistorySet": [
        "PurchaseOrder",
        "PurchaseOrderItem",
        "PostingDate",
        "MovementType",
        "Quantity",
        "Amount",
        "Currency",
    ],
    "PurchaseRequisitionSet": [
        "PurchaseRequisition",
        "Material",
        "Plant",
        "CreationDate",
        "ProcessingStatus",
        "PurchaseRequisitionType",
    ],
    "SupplierSet": ["Supplier", "SupplierName", "Country", "CityName"],
    "MaterialSet": ["Material", "MaterialDescription", "MaterialType", "BaseUnit"],
    "PurchaseInfoRecordSet": [
        "PurchasingInfoRecord",
        "Supplier",
        "Material",
        "PurchasingOrganization",
        "NetPriceAmount",
        "Currency",
    ],
}


def _get(service: str, target: str, key: dict) -> ToolCall:
    return ToolCall(
        tool="odata",
        service=service,
        action="get",
        target=target,
        params=ToolCallParams(key=key, select=_SELECT.get(target)),
    )


def _list(service: str, target: str, flt: dict) -> ToolCall:
    return ToolCall(
        tool="odata",
        service=service,
        action="list",
        target=target,
        params=ToolCallParams(filter=flt, select=_SELECT.get(target), top=MAX_ROWS),
    )


def build_plan(intent: Intent) -> list[ToolCall]:  # noqa: C901
    """Build a minimal tool plan for the given intent. May be empty."""
    ids = intent.identifiers
    name = intent.name

    if name == I.PURCHASE_ORDER_STATUS and "PurchaseOrder" in ids:
        return [
            _get("sap_purchase_order", "PurchaseOrderSet", {"PurchaseOrder": ids["PurchaseOrder"]})
        ]

    if name == I.PURCHASE_ORDER_ITEMS and "PurchaseOrder" in ids:
        return [
            _list(
                "sap_purchase_order",
                "PurchaseOrderItemSet",
                {"PurchaseOrder": ids["PurchaseOrder"]},
            )
        ]

    if name == I.PURCHASE_ORDER_HISTORY and "PurchaseOrder" in ids:
        return [
            _list(
                "sap_purchase_order",
                "PurchaseOrderHistorySet",
                {"PurchaseOrder": ids["PurchaseOrder"]},
            )
        ]

    if name == I.PURCHASE_REQUISITION_STATUS and "PurchaseRequisition" in ids:
        return [
            _get(
                "sap_purchase_requisition",
                "PurchaseRequisitionSet",
                {"PurchaseRequisition": ids["PurchaseRequisition"]},
            )
        ]

    if name == I.SUPPLIER_LOOKUP:
        if "Supplier" in ids:
            return [_get("sap_vendor", "SupplierSet", {"Supplier": ids["Supplier"]})]
        if "SupplierName" in ids:
            return [_list("sap_vendor", "SupplierSet", {"SupplierName": ids["SupplierName"]})]

    if name == I.MATERIAL_LOOKUP:
        if "Material" in ids:
            return [_get("sap_material", "MaterialSet", {"Material": ids["Material"]})]
        if "MaterialDescription" in ids:
            return [
                _list(
                    "sap_material",
                    "MaterialSet",
                    {"MaterialDescription": ids["MaterialDescription"]},
                )
            ]

    if name == I.PURCHASE_INFO_RECORD_LOOKUP:
        flt = {}
        if "Supplier" in ids and "Material" in ids:
            flt = {"Supplier": ids["Supplier"], "Material": ids["Material"]}
        elif "Material" in ids and "PurchasingOrganization" in ids:
            flt = {
                "Material": ids["Material"],
                "PurchasingOrganization": ids["PurchasingOrganization"],
            }
        if flt:
            return [_list("sap_purchase_info_record", "PurchaseInfoRecordSet", flt)]

    if name == I.OPEN_POS_BY_VENDOR:
        flt = {
            k: ids[k]
            for k in ("Supplier", "Plant", "PurchasingOrganization", "CompanyCode", "DocumentDate")
            if k in ids
        }
        if flt:
            return [_list("sap_purchase_order", "PurchaseOrderSet", flt)]

    return []
