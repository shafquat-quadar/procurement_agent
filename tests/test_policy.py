"""Policy validator tests."""

from __future__ import annotations

from app.mcp_client.tools import ToolCall, ToolCallParams


def _get(**kw) -> ToolCall:
    return ToolCall(tool="odata", action="get", **kw)


def test_unknown_service_blocked(validator):
    call = _get(
        service="sap_unknown",
        target="PurchaseOrderSet",
        params=ToolCallParams(key={"PurchaseOrder": "4500123456"}),
    )
    result = validator.validate_call(call)
    assert not result.allowed
    assert any(v.code == "service_not_allowed" for v in result.violations)


def test_unknown_action_blocked(validator):
    call = ToolCall(tool="odata", action="frobnicate", service="sap_purchase_order")
    result = validator.validate_call(call)
    assert not result.allowed
    assert any(v.code == "action_not_allowed" for v in result.violations)


def test_write_action_blocked(validator):
    call = ToolCall(
        tool="odata",
        action="create",
        service="sap_purchase_order",
        target="PurchaseOrderSet",
    )
    result = validator.validate_call(call)
    assert not result.allowed
    assert any(v.code == "write_blocked" for v in result.violations)


def test_list_without_filter_blocked(validator):
    call = ToolCall(
        tool="odata",
        action="list",
        service="sap_purchase_order",
        target="PurchaseOrderSet",
        params=ToolCallParams(top=50),
    )
    result = validator.validate_call(call)
    assert not result.allowed
    assert result.needs_clarification


def test_list_top_over_max_blocked(validator):
    call = ToolCall(
        tool="odata",
        action="list",
        service="sap_purchase_order",
        target="PurchaseOrderSet",
        params=ToolCallParams(filter={"PurchaseOrder": "4500123456"}, top=500),
    )
    result = validator.validate_call(call)
    assert not result.allowed
    assert any(v.code == "row_limit_exceeded" for v in result.violations)


def test_allowed_get_passes(validator):
    call = _get(
        service="sap_purchase_order",
        target="PurchaseOrderSet",
        params=ToolCallParams(key={"PurchaseOrder": "4500123456"}),
    )
    result = validator.validate_call(call)
    assert result.allowed


def test_max_tool_calls_enforced(validator):
    call = _get(
        service="sap_purchase_order",
        target="PurchaseOrderSet",
        params=ToolCallParams(key={"PurchaseOrder": "4500123456"}),
    )
    plan = [call] * (validator.policy.max_tool_calls + 1)
    result = validator.validate_plan(plan)
    assert not result.allowed
    assert any(v.code == "too_many_tool_calls" for v in result.violations)
