from decimal import Decimal

import pytest

from src.cost_rules import (
    CostRuleError,
    calculate_bulk_shipping_cost,
    calculate_bulk_shipping_total_cost,
    calculate_bulk_shipping_unit_price,
    calculate_edge_cost,
    calculate_manual_shipping_cost,
    calculate_railway_cost,
)


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
