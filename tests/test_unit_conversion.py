from decimal import Decimal

import pytest

from src.unit_conversion import (
    InvalidPriceError,
    InvalidQuantityError,
    UnitMismatchError,
    UnsupportedPriceUnitError,
    UnsupportedQuantityUnitError,
    calculate_total_cost,
    normalize_price_unit,
    normalize_quantity_unit,
)


@pytest.mark.parametrize(
    ("quantity", "quantity_unit", "price", "price_unit", "expected"),
    [
        (500, "吨", 250, "元/吨", Decimal("125000")),
        (500, "箱", 250, "元/箱", Decimal("125000")),
        (500, "柜", 250, "元/柜", Decimal("125000")),
        ("12.5", "吨", "20.4", "元/吨", Decimal("255.00")),
    ],
)
def test_calculate_total_cost_when_units_match(quantity, quantity_unit, price, price_unit, expected):
    assert calculate_total_cost(price, price_unit, quantity, quantity_unit) == expected


@pytest.mark.parametrize(
    ("quantity_unit", "price_unit"),
    [
        ("吨", "元/箱"),
        ("箱", "元/吨"),
        ("柜", "元/吨"),
    ],
)
def test_calculate_total_cost_rejects_mismatched_units(quantity_unit, price_unit):
    with pytest.raises(UnitMismatchError, match="不能直接计算总费用"):
        calculate_total_cost(250, price_unit, 500, quantity_unit)


def test_normalize_quantity_unit_rejects_unsupported_unit():
    with pytest.raises(UnsupportedQuantityUnitError, match="不支持的数量单位"):
        normalize_quantity_unit("车")


def test_normalize_price_unit_rejects_unsupported_unit():
    with pytest.raises(UnsupportedPriceUnitError, match="不支持的费用单位"):
        normalize_price_unit("元/车")


def test_normalize_price_unit_rejects_invalid_format():
    with pytest.raises(UnsupportedPriceUnitError, match="不支持的费用单位"):
        normalize_price_unit("250元每吨")


def test_calculate_total_cost_rejects_zero_quantity():
    with pytest.raises(InvalidQuantityError, match="订单数量必须大于 0"):
        calculate_total_cost(250, "元/吨", 0, "吨")


def test_calculate_total_cost_rejects_negative_price():
    with pytest.raises(InvalidPriceError, match="运价不能为负数"):
        calculate_total_cost(-1, "元/吨", 500, "吨")


def test_unit_text_is_trimmed_before_matching():
    assert normalize_quantity_unit(" 吨 ") == "吨"
    assert normalize_price_unit(" 元 / 吨 ") == "吨"
