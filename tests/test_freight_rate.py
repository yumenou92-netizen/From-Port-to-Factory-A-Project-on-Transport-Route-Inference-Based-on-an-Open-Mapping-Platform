from datetime import date
from decimal import Decimal

import pytest

from src.freight_rate import FreightRateError, create_freight_rate
from src.route_request import RouteRequest


def make_request() -> RouteRequest:
    return RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="散粮",
        commodity="测试粮种",
    )


def make_rate(**overrides):
    values = {
        "origin_name": "测试北港",
        "destination_name": "测试南港",
        "transport_mode": "驳船",
        "package_type": "散粮",
        "commodity_scope": "测试粮种、测试麦种",
        "raw_price": 20,
        "raw_price_unit": "元/吨",
        "price_type": "unit_price",
        "price_source": "测试来源",
        "maintained_at": "2026-04-15",
        "source_file": "测试运价表.json",
        "source_row_number": 1,
    }
    values.update(overrides)
    return create_freight_rate(**values)


def test_create_freight_rate_normalizes_fields_and_generates_stable_id():
    first = make_rate(origin_name=" 测试北港 ", raw_price="20.0")
    second = make_rate(origin_name="测试北港", raw_price=Decimal("20"))

    assert first.rate_id == second.rate_id
    assert first.rate_id.startswith("rate_")
    assert first.origin_name == "测试北港"
    assert first.raw_price == Decimal("20.0")
    assert first.maintained_at == date(2026, 4, 15)
    assert first.price_type == "unit_price"


def test_rate_id_does_not_depend_on_source_row_number():
    first = make_rate(source_row_number=1)
    second = make_rate(source_row_number=2)

    assert first.rate_id == second.rate_id
    assert first.business_route_key == second.business_route_key


def test_bind_node_ids_preserves_original_rate():
    rate = make_rate()

    bound = rate.bind_node_ids("NODE_NORTH", "NODE_SOUTH")

    assert not rate.is_node_resolved
    assert bound.is_node_resolved
    assert bound.from_node_id == "NODE_NORTH"
    assert bound.to_node_id == "NODE_SOUTH"
    assert bound.rate_id == rate.rate_id


def test_supports_commodity_uses_explicit_scope():
    rate = make_rate(commodity_scope="测试粮种，测试麦种/测试豆种")

    assert rate.supports_commodity("测试粮种")
    assert rate.supports_commodity("测试豆种")
    assert not rate.supports_commodity("范围外品种")


def test_unit_price_evaluation_outputs_current_segment_total_cost():
    evaluation = make_rate(raw_price=20).evaluate_for_request(make_request())

    assert evaluation.status == "valid"
    assert evaluation.total_cost == Decimal("10000")
    assert evaluation.transport_mode == "驳船"
    assert evaluation.rule_id == "freight_rate_unit_price"
    assert evaluation.rule_version == "1.0"
    assert "500吨 × 20元/吨 = 10000元" == evaluation.calculation_detail
    assert evaluation.price_source == "测试来源"


def test_total_price_evaluation_does_not_multiply_order_quantity():
    rate = make_rate(
        raw_price=88000,
        raw_price_unit="元",
        price_type="total_price",
    )

    evaluation = rate.evaluate_for_request(make_request())

    assert evaluation.status == "valid"
    assert evaluation.total_cost == Decimal("88000")
    assert "total_price" in evaluation.message
    assert evaluation.rule_id == "freight_rate_total_price"
    assert "人工总价 88000元" in evaluation.calculation_detail


def test_total_price_with_unit_price_unit_requires_manual_review():
    rate = make_rate(
        raw_price=88000,
        raw_price_unit="元/吨",
        price_type="total_price",
    )

    evaluation = rate.evaluate_for_request(make_request())

    assert evaluation.status == "manual_review"
    assert evaluation.total_cost is None
    assert "总金额单位元" in evaluation.message


def test_rate_not_applicable_to_request_commodity_is_not_evaluated():
    rate = make_rate(commodity_scope="小麦")

    evaluation = rate.evaluate_for_request(make_request())

    assert evaluation.status == "not_applicable"
    assert evaluation.total_cost is None
    assert "不适用于订单品种" in evaluation.message


def test_total_price_respects_package_type():
    rate = make_rate(
        raw_price=88000,
        raw_price_unit="元",
        price_type="total_price",
        package_type="集装箱",
    )

    evaluation = rate.evaluate_for_request(make_request())

    assert evaluation.status == "not_applicable"
    assert evaluation.total_cost is None


def test_total_price_respects_request_billing_validation():
    rate = make_rate(raw_price=88000, raw_price_unit="元", price_type="total_price")
    request = RouteRequest(
        quantity=500,
        quantity_unit="箱",
        package_type="散粮",
        commodity="测试粮种",
    )

    evaluation = rate.evaluate_for_request(request)

    assert evaluation.status == "manual_review"
    assert evaluation.total_cost is None


@pytest.mark.parametrize("raw_price", [0, -1])
def test_non_positive_total_price_requires_manual_review(raw_price):
    rate = make_rate(
        raw_price=raw_price,
        raw_price_unit="元",
        price_type="total_price",
    )

    evaluation = rate.evaluate_for_request(make_request())

    assert evaluation.status == "manual_review"
    assert evaluation.total_cost is None


def test_invalid_maintenance_date_has_clear_error():
    with pytest.raises(FreightRateError, match="YYYY-MM-DD"):
        make_rate(maintained_at="2026/04/15")


def test_invalid_price_type_has_clear_error():
    with pytest.raises(FreightRateError, match="unit_price 或 total_price"):
        make_rate(price_type="unknown")


@pytest.mark.parametrize("source_row_number", [0, -1, True, "1"])
def test_invalid_source_row_number_has_clear_error(source_row_number):
    with pytest.raises(FreightRateError, match="大于 0 的整数"):
        make_rate(source_row_number=source_row_number)
