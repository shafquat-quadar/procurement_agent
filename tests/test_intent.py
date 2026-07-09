"""Intent classification tests."""

from __future__ import annotations

from app.agent import intent as I


def test_po_status_intent_detected():
    intent, missing = I.classify("What is the status of PO 4500123456?")
    assert intent.name == I.PURCHASE_ORDER_STATUS
    assert intent.identifiers.get("PurchaseOrder") == "4500123456"
    assert missing == []


def test_pr_status_intent_detected():
    intent, missing = I.classify("What is the status of PR 10001234?")
    assert intent.name == I.PURCHASE_REQUISITION_STATUS
    assert intent.identifiers.get("PurchaseRequisition") == "10001234"
    assert missing == []


def test_open_pos_without_filter_requires_clarification():
    intent, missing = I.classify("Show me all open purchase orders")
    assert intent.name == I.OPEN_POS_BY_VENDOR
    assert intent.requires_sap
    assert missing  # clarification needed


def test_open_pos_with_vendor_ok():
    intent, missing = I.classify("Show open POs for vendor 10000045")
    assert intent.name == I.OPEN_POS_BY_VENDOR
    assert intent.identifiers.get("Supplier") == "10000045"
    assert missing == []


def test_supplier_lookup_detected():
    intent, missing = I.classify("Find supplier 10000045")
    assert intent.name == I.SUPPLIER_LOOKUP
    assert missing == []


def test_material_lookup_detected():
    intent, missing = I.classify("Find material ABC123")
    assert intent.name == I.MATERIAL_LOOKUP
    assert intent.identifiers.get("Material") == "ABC123"


def test_out_of_scope_detected():
    intent, missing = I.classify("What's the weather today?")
    assert intent.name == I.OUT_OF_SCOPE
    assert not intent.requires_sap
