"""Secret redaction tests."""

from __future__ import annotations

from app.guardrails.injection import sanitize_evidence_records
from app.guardrails.redaction import redact_mapping, redact_text


def test_bearer_token_redacted():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"
    out = redact_text(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out
    assert "[REDACTED]" in out


def test_subscription_key_redacted():
    payload = {"SUBSCRIPTION_KEY": "super-secret-sub-key-123", "PurchaseOrder": "4500123456"}
    out = redact_mapping(payload)
    assert out["SUBSCRIPTION_KEY"] == "[REDACTED]"
    assert out["PurchaseOrder"] == "4500123456"


def test_client_secret_redacted():
    text = 'config: {"client_secret": "abcXYZ123secret", "other": "keep"}'
    out = redact_text(text)
    assert "abcXYZ123secret" not in out
    assert "keep" in out


def test_secret_in_sap_field_sanitized():
    records = [
        {
            "PurchaseOrder": "4500123456",
            "ShortText": "note access_token=tok-abc-987 for internal use",
        }
    ]
    sanitized = sanitize_evidence_records(records)
    blob = str(sanitized)
    assert "tok-abc-987" not in blob
    assert "4500123456" in blob
