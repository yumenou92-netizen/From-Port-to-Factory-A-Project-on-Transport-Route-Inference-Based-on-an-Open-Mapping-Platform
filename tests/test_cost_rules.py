from dataclasses import asdict
from decimal import Decimal

import pytest

from src.cost_rules import (
    BULK_SHIPPING_INDEX_RULE,
    DEFAULT_COST_RULE_ENGINE,
    FREIGHT_RATE_TOTAL_PRICE_RULE,
    FREIGHT_RATE_UNIT_PRICE_RULE,
    UNKNOWN_TRUCK_BULK_RULE,
    UNKNOWN_TRUCK_CONTAINER_RULE,
    CostCalculationResult,
    CostRuleConfig,
    CostRuleEngine,
    CostRuleError,
    DisabledCostRuleError,
    calculate_bulk_shipping_cost,
    calculate_bulk_shipping_total_cost,
    calculate_bulk_shipping_unit_price,
    calculate_edge_cost,
    calculate_manual_shipping_cost,
    calculate_railway_cost,
)
from src.route_request import RouteRequest


def test_bulk_shipping_index():
    assert calculate_bulk_shipping_cost("index", coal_index=100) == 119


def test_bulk_shipping_manual():
    assert calculate_bulk_shipping_cost("manual", manual_quote_price=88) == 88


def test_railway_open_top():
    assert calculate_railway_cost(1, 2, 3, 4, True, 5) == 15


def test_bulk_shipping_unit_price_index_rule():
    assert calculate_bulk_shipping_unit_price(coal_index=100) == Decimal("119.00")


def test_bulk_shipping_total_cost_from_index_unit_price():
    assert calculate_bulk_shipping_total_cost(
        price_mode="index",
        coal_index=100,
        quantity=500,
        quantity_unit="吨",
    ) == Decimal("59500.00")


def test_manual_shipping_unit_price_requires_matching_unit():
    assert calculate_manual_shipping_cost(
        manual_quote_price=250,
        manual_price_type="unit_price",
        manual_price_unit="元/吨",
        quantity=500,
        quantity_unit="吨",
    ) == Decimal("125000")


def test_manual_shipping_total_price_uses_quote_directly():
    assert calculate_manual_shipping_cost(
        manual_quote_price=88888,
        manual_price_type="total_price",
        manual_price_unit=None,
        quantity=500,
        quantity_unit="吨",
    ) == Decimal("88888")


def test_manual_shipping_requires_price_type():
    with pytest.raises(CostRuleError, match="必须显式区分"):
        calculate_manual_shipping_cost(
            manual_quote_price=250,
            manual_price_type=None,
            manual_price_unit="元/吨",
            quantity=500,
            quantity_unit="吨",
        )


def test_calculate_edge_cost_dispatches_trunk_shipping():
    assert calculate_edge_cost(
        "trunk_shipping",
        price_mode="manual",
        manual_quote_price=250,
        manual_price_type="unit_price",
        manual_price_unit="元/吨",
        quantity=500,
        quantity_unit="吨",
    ) == Decimal("125000")


def test_calculate_edge_cost_keeps_last_mile_unimplemented():
    with pytest.raises(CostRuleError, match="尚未接入正式费用计算"):
        calculate_edge_cost("last_mile_truck")


def test_cost_calculation_result_exposes_legacy_total_cost_alias():
    result = CostCalculationResult(
        status="valid",
        total_cost_yuan=Decimal("125000"),
        rule_id="test_rule",
        rule_version="1.0",
        calculation_detail="500吨 × 250元/吨 = 125000元",
        price_source="脱敏测试",
        transport_mode="汽运",
        rate_packaging="散粮",
        price_unit="元/吨",
        message="测试通过",
    )

    assert result.total_cost == Decimal("125000")
    assert asdict(result)["total_cost"] == Decimal("125000")
    assert asdict(result)["total_cost_yuan"] == Decimal("125000")
    assert not result.requires_manual_review


@pytest.mark.parametrize(
    ("status", "total_cost"),
    [
        ("unknown", None),
        ("valid", None),
        ("valid", Decimal("0")),
        ("manual_review", Decimal("1")),
        ("not_applicable", Decimal("1")),
    ],
)
def test_cost_calculation_result_rejects_invalid_state(status, total_cost):
    with pytest.raises(CostRuleError):
        CostCalculationResult(
            status=status,
            total_cost_yuan=total_cost,
            rule_id="test_rule",
            rule_version="1.0",
            calculation_detail="测试计算过程",
            price_source="脱敏测试",
            transport_mode="汽运",
            rate_packaging="散粮",
            price_unit="元/吨",
            message="测试消息",
        )


def test_cost_rule_engine_calculates_bulk_shipping_index_with_trace():
    request = RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="散粮",
        commodity="测试粮种",
    )

    result = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="index",
        coal_index=100,
        price_source="脱敏指数",
    )

    assert result.status == "valid"
    assert result.total_cost_yuan == Decimal("59500.00")
    assert result.rule_id == BULK_SHIPPING_INDEX_RULE.rule_id
    assert result.rule_version == "1.0"
    assert "100×1.12+2+5" in result.calculation_detail
    assert result.price_source == "脱敏指数"


def test_cost_rule_engine_uses_registered_index_parameters():
    custom_index_rule = CostRuleConfig(
        rule_id="bulk_shipping_index",
        rule_version="test-2.0",
        rule_name="测试指数规则",
        rule_type="index_formula",
        enabled=True,
        parameters={
            "index_multiplier": Decimal("1"),
            "harbor_sailing_fee_yuan_per_ton": Decimal("3"),
            "profit_fee_yuan_per_ton": Decimal("7"),
            "price_unit": "元/吨",
        },
    )
    engine = CostRuleEngine((custom_index_rule,))
    request = RouteRequest(10, "吨", "散粮", "测试粮种")

    result = engine.calculate_bulk_shipping(request, price_mode="index", coal_index=100)

    assert result.total_cost_yuan == Decimal("1100")
    assert result.rule_version == "test-2.0"
    assert "100×1+3+7=110" in result.calculation_detail


def test_cost_rule_engine_trace_uses_configured_price_unit():
    custom_index_rule = CostRuleConfig(
        rule_id="bulk_shipping_index",
        rule_version="test-box",
        rule_name="测试箱计价规则",
        rule_type="index_formula",
        enabled=True,
        parameters={
            "index_multiplier": Decimal("1"),
            "harbor_sailing_fee_yuan_per_ton": Decimal("3"),
            "profit_fee_yuan_per_ton": Decimal("7"),
            "price_unit": "元/箱",
        },
    )
    engine = CostRuleEngine((custom_index_rule,))
    request = RouteRequest(10, "箱", "集装箱", "测试粮种")

    result = engine.calculate_bulk_shipping(request, price_mode="index", coal_index=100)

    assert result.total_cost_yuan == Decimal("1100")
    assert result.price_unit == "元/箱"
    assert "110元/箱×10箱" in result.calculation_detail


def test_cost_rule_engine_reports_missing_maintained_parameter():
    incomplete_rule = CostRuleConfig(
        rule_id="bulk_shipping_index",
        rule_version="test-incomplete",
        rule_name="缺少参数的测试规则",
        rule_type="index_formula",
        enabled=True,
        parameters={"price_unit": "元/吨"},
    )
    engine = CostRuleEngine((incomplete_rule,))
    request = RouteRequest(10, "吨", "散粮", "测试粮种")

    result = engine.calculate_bulk_shipping(request, price_mode="index", coal_index=100)

    assert result.status == "manual_review"
    assert "缺少参数" in result.message


def test_manual_total_quote_cannot_bypass_request_billing_validation():
    request = RouteRequest(500, "箱", "散粮", "测试粮种")

    result = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="manual",
        manual_quote_price=88888,
        manual_price_type="total_price",
    )

    assert result.status == "manual_review"
    assert result.total_cost_yuan is None
    assert "辅助规则期望单位为 吨" in result.message


def test_missing_manual_price_type_uses_validation_rule():
    request = RouteRequest(500, "吨", "散粮", "测试粮种")

    result = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="manual",
        manual_quote_price=250,
        manual_price_type=None,
        manual_price_unit="元/吨",
    )

    assert result.status == "manual_review"
    assert result.rule_id == "bulk_shipping_manual_quote_validation"
    assert "必须显式区分" in result.message


@pytest.mark.parametrize(
    ("manual_price_type", "manual_price_unit", "expected_rule", "expected_total"),
    [
        ("unit_price", "元/吨", "bulk_shipping_manual_unit_price", Decimal("125000")),
        ("total_price", None, "bulk_shipping_manual_total_price", Decimal("88888")),
    ],
)
def test_cost_rule_engine_calculates_manual_quotes_with_trace(
    manual_price_type,
    manual_price_unit,
    expected_rule,
    expected_total,
):
    request = RouteRequest(500, "吨", "散粮", "测试粮种")
    quote = 250 if manual_price_type == "unit_price" else 88888

    result = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="manual",
        manual_quote_price=quote,
        manual_price_type=manual_price_type,
        manual_price_unit=manual_price_unit,
    )

    assert result.status == "valid"
    assert result.total_cost_yuan == expected_total
    assert result.rule_id == expected_rule
    assert result.rule_version == "1.0"
    assert result.message == "已按散船人工报价规则计算当前订单运输段总费用。"
    if manual_price_type == "unit_price":
        assert result.price_unit == "元/吨"
        assert result.calculation_detail == "500吨 × 250元/吨 = 125000元"
    else:
        assert result.price_unit == "元"
        assert result.calculation_detail == "人工总价 88888元，直接作为当前订单运输段总费用。"


@pytest.mark.parametrize(
    ("manual_price_type", "manual_quote_price", "manual_price_unit", "expected_message"),
    [
        ("unit_price", None, "元/吨", "必须提供 manual_quote_price"),
        ("unit_price", 250, None, "必须提供 manual_price_unit"),
        ("total_price", 0, None, "必须大于 0"),
    ],
)
def test_cost_rule_engine_returns_traceable_review_for_invalid_manual_quote(
    manual_price_type,
    manual_quote_price,
    manual_price_unit,
    expected_message,
):
    request = RouteRequest(500, "吨", "散粮", "测试粮种")

    result = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="manual",
        manual_quote_price=manual_quote_price,
        manual_price_type=manual_price_type,
        manual_price_unit=manual_price_unit,
    )

    assert result.status == "manual_review"
    assert result.rule_id.startswith("bulk_shipping_manual_")
    assert result.rule_version == "1.0"
    assert expected_message in result.message
    assert result.calculation_detail.startswith("未计算：")


def test_freight_rate_rules_are_registered_as_enabled():
    assert DEFAULT_COST_RULE_ENGINE.get_rule(FREIGHT_RATE_UNIT_PRICE_RULE.rule_id).enabled
    assert DEFAULT_COST_RULE_ENGINE.get_rule(FREIGHT_RATE_TOTAL_PRICE_RULE.rule_id).enabled


@pytest.mark.parametrize(
    "rule",
    [UNKNOWN_TRUCK_BULK_RULE, UNKNOWN_TRUCK_CONTAINER_RULE],
)
def test_unknown_truck_rules_are_registered_but_cannot_execute(rule):
    registered = DEFAULT_COST_RULE_ENGINE.get_rule(rule.rule_id)

    assert not registered.enabled
    assert registered.parameters
    assert registered.disabled_reason
    with pytest.raises(DisabledCostRuleError, match="当前未启用"):
        DEFAULT_COST_RULE_ENGINE.require_enabled(rule.rule_id)


def test_unknown_truck_rule_ids_and_versions_are_stable():
    assert UNKNOWN_TRUCK_BULK_RULE.rule_id == "unknown_truck_bulk_distance_tier"
    assert UNKNOWN_TRUCK_CONTAINER_RULE.rule_id == "unknown_truck_container_distance"
    assert UNKNOWN_TRUCK_BULK_RULE.rule_version == "draft-1"
    assert UNKNOWN_TRUCK_CONTAINER_RULE.rule_version == "draft-1"


def test_cost_rule_registry_rejects_duplicate_rule_ids():
    with pytest.raises(CostRuleError, match="不能重复"):
        CostRuleEngine((FREIGHT_RATE_UNIT_PRICE_RULE, FREIGHT_RATE_UNIT_PRICE_RULE))


def test_cost_rule_registry_reports_unknown_rule_id():
    with pytest.raises(CostRuleError, match="找不到计费规则"):
        DEFAULT_COST_RULE_ENGINE.get_rule("missing_rule")


def test_disabled_rule_requires_reason():
    with pytest.raises(CostRuleError, match="disabled_reason"):
        CostRuleConfig(
            rule_id="disabled_without_reason",
            rule_version="draft",
            rule_name="测试禁用规则",
            rule_type="test",
            enabled=False,
        )
