from decimal import Decimal

import pytest

from src.domain.route_request import (
    RouteRequest,
    RouteRequestError,
    evaluate_freight_charge,
    validate_request_billing,
)


def make_request(package_type: str, quantity_unit: str) -> RouteRequest:
    return RouteRequest(
        quantity=500,
        quantity_unit=quantity_unit,
        package_type=package_type,
        commodity="玉米",
        origin_port_id="NP_DEMO",
        south_port_id="SP_DEMO",
        customer_id="CUSTOMER_DEMO",
    )


@pytest.mark.parametrize(
    ("package_type", "quantity_unit", "price_unit"),
    [
        ("散粮", "吨", "元/吨"),
        ("集装箱", "箱", "元/箱"),
        ("集装箱", "柜", "元/柜"),
    ],
)
def test_matching_billing_units_calculate_total_cost(package_type, quantity_unit, price_unit):
    request = make_request(package_type, quantity_unit)

    evaluation = evaluate_freight_charge(
        request,
        transport_mode="汽运",
        rate_packaging=package_type,
        raw_price=250,
        price_unit=price_unit,
    )

    assert evaluation.status == "valid"
    assert evaluation.total_cost == Decimal("125000")


@pytest.mark.parametrize(
    ("quantity_unit", "price_unit"),
    [
        ("柜", "元/箱"),
        ("箱", "元/柜"),
    ],
)
def test_box_and_container_load_units_are_not_converted(quantity_unit, price_unit):
    request = make_request("集装箱", quantity_unit)

    evaluation = evaluate_freight_charge(
        request,
        transport_mode="驳船",
        rate_packaging="集装箱",
        raw_price=250,
        price_unit=price_unit,
    )

    assert evaluation.status == "manual_review"
    assert evaluation.total_cost is None
    assert "不能直接计算总费用" in evaluation.message


def test_packaging_is_an_auxiliary_billing_validation():
    request = make_request("散粮", "箱")

    validation = validate_request_billing(request)

    assert validation.status == "manual_review"
    assert "辅助规则期望单位为 吨" in validation.issues[0]


def test_invalid_request_billing_cannot_be_bypassed_by_matching_rate_unit():
    request = make_request("散粮", "箱")

    evaluation = evaluate_freight_charge(
        request,
        transport_mode="汽运",
        rate_packaging="散粮",
        raw_price=250,
        price_unit="元/箱",
    )

    assert evaluation.status == "manual_review"
    assert evaluation.total_cost is None
    assert "辅助规则期望单位为 吨" in evaluation.message


def test_invalid_request_billing_precedes_rate_packaging_filter():
    request = RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="袋装",
        commodity="玉米",
    )

    evaluation = evaluate_freight_charge(
        request,
        transport_mode="汽运",
        rate_packaging="散粮",
        raw_price=250,
        price_unit="元/吨",
    )

    assert evaluation.status == "manual_review"
    assert evaluation.total_cost is None
    assert "尚未配置计费单位规则" in evaluation.message


def test_rate_with_other_packaging_is_not_applicable():
    request = make_request("散粮", "吨")

    evaluation = evaluate_freight_charge(
        request,
        transport_mode="汽运",
        rate_packaging="集装箱",
        raw_price=500,
        price_unit="元/箱",
    )

    assert evaluation.status == "not_applicable"
    assert evaluation.total_cost is None


def test_transport_mode_is_copied_from_freight_rate():
    request = make_request("集装箱", "柜")

    evaluation = evaluate_freight_charge(
        request,
        transport_mode="驳船",
        rate_packaging="集装箱",
        raw_price=250,
        price_unit="元/柜",
    )

    assert evaluation.transport_mode == "驳船"
    assert evaluation.status == "valid"
    assert evaluation.total_cost == Decimal("125000")
    assert not hasattr(request, "transport_mode")


@pytest.mark.parametrize("raw_price", [0, -1, "bad"])
def test_invalid_or_zero_rate_requires_manual_review(raw_price):
    request = make_request("散粮", "吨")

    evaluation = evaluate_freight_charge(
        request,
        transport_mode="汽运",
        rate_packaging="散粮",
        raw_price=raw_price,
        price_unit="元/吨",
    )

    assert evaluation.status == "manual_review"
    assert evaluation.total_cost is None


def test_route_request_normalizes_numeric_and_text_inputs():
    request = RouteRequest(
        quantity="12.5",
        quantity_unit=" 吨 ",
        package_type=" 散粮 ",
        commodity=" 玉米 ",
        trade_type=" 内贸 ",
        shipping_price_mode="index",
        shipping_time_hours="36",
    )

    assert request.quantity == Decimal("12.5")
    assert request.quantity_unit == "吨"
    assert request.package_type == "散粮"
    assert request.trade_type == "内贸"
    assert request.shipping_time_hours == Decimal("36")


def test_route_request_defaults_to_domestic_trade_type():
    request = RouteRequest(500, "吨", "散粮", "玉米")

    assert request.trade_type == "内贸"


def test_route_request_rejects_unknown_trade_type():
    with pytest.raises(RouteRequestError, match="不支持的贸易类型"):
        RouteRequest(500, "吨", "散粮", "玉米", trade_type="转口")


@pytest.mark.parametrize("quantity", [0, -1, "bad"])
def test_route_request_rejects_invalid_quantity(quantity):
    with pytest.raises(RouteRequestError, match="订单数量"):
        RouteRequest(
            quantity=quantity,
            quantity_unit="吨",
            package_type="散粮",
            commodity="玉米",
        )


def test_route_request_rejects_non_positive_shipping_time():
    with pytest.raises(RouteRequestError, match="散船运时必须大于 0"):
        RouteRequest(
            quantity=500,
            quantity_unit="吨",
            package_type="散粮",
            commodity="玉米",
            shipping_time_hours=0,
        )
