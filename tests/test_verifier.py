"""Answer verifier tests."""

from __future__ import annotations

from app.agent.verifier import verify_answer
from app.evidence.models import Evidence


def _po_evidence() -> Evidence:
    return Evidence(
        service="sap_purchase_order",
        entity="PurchaseOrderSet",
        action="get",
        records_returned=1,
        records=[
            {
                "PurchaseOrder": "4500123456",
                "Supplier": "10000045",
                "OverallStatus": "Open",
                "NetAmount": "5000.00",
                "Currency": "USD",
            }
        ],
    )


def test_supported_answer_passes():
    ev = _po_evidence()
    answer = (
        "Purchase order 4500123456 from supplier 10000045 is Open with a net "
        "amount of 5000.00 USD."
    )
    result = verify_answer(answer, [ev])
    assert result.supported
    assert result.final_answer_allowed
    assert result.unsupported_claims == []


def test_unsupported_po_status_fails():
    ev = _po_evidence()
    answer = "Purchase order 4500123456 is delayed."
    result = verify_answer(answer, [ev])
    assert not result.supported
    assert "delayed" in result.unsupported_claims


def test_unsupported_amount_fails():
    ev = _po_evidence()
    answer = "Purchase order 4500123456 has a net amount of 9999.99 USD."
    result = verify_answer(answer, [ev])
    assert not result.supported
    assert "9999.99" in result.unsupported_claims


def test_no_evidence_fails_for_sap_factual_answer():
    answer = "Purchase order 4500123456 has a net amount of 5000.00 USD."
    result = verify_answer(answer, [], user_message="", identifiers=None)
    assert not result.supported
    assert not result.final_answer_allowed
