from decimal import Decimal

import pytest

from src.domain.rail_freight_calculator import (
    RailFreightCalculatorError,
    RailFreightCalculatorInput,
    calculate_rail_freight_workbook,
)


def test_calculator_reproduces_supplied_workbook_default_result():
    result = calculate_rail_freight_workbook(
        RailFreightCalculatorInput(
            load_tons=Decimal("60"),
            total_freight_yuan=Decimal("1691.1"),
            discount_ratio=Decimal("0.12"),
            electrified_km=Decimal("500"),
        )
    )

    assert result.full_price_total_yuan == Decimal("1691.100")
    assert result.adjusted_total_yuan == Decimal("1327.445279580598303712323228")
    assert result.original_workbook_unit_price_yuan_per_ton == result.input_load_unit_price_yuan_per_ton
    assert result.lines[5].name == "基础运费"
    assert result.lines[6].adjusted_yuan == Decimal("0")


def test_calculator_shows_fixed_60_ton_and_actual_load_unit_prices_separately():
    result = calculate_rail_freight_workbook(
        RailFreightCalculatorInput(
            load_tons=Decimal("80"),
            total_freight_yuan=Decimal("1691.1"),
            discount_ratio=Decimal("0.12"),
            electrified_km=Decimal("500"),
        )
    )

    assert result.original_workbook_unit_price_yuan_per_ton != result.input_load_unit_price_yuan_per_ton
    assert any("固定除以 60" in warning for warning in result.warnings)


def test_local_freight_2_uses_confirmed_discount_correction():
    result = calculate_rail_freight_workbook(
        RailFreightCalculatorInput(
            load_tons=Decimal("60"),
            total_freight_yuan=Decimal("1691.1"),
            discount_ratio=Decimal("0.12"),
            electrified_km=Decimal("500"),
            local_freight_2_adjusted_base_yuan=Decimal("100"),
        )
    )

    assert result.lines[4].adjusted_yuan == Decimal("88")


def test_calculator_rejects_electrification_fee_larger_than_total_freight():
    with pytest.raises(RailFreightCalculatorError, match="大于输入运费"):
        calculate_rail_freight_workbook(
            RailFreightCalculatorInput(
                load_tons=Decimal("60"),
                total_freight_yuan=Decimal("1"),
                discount_ratio=Decimal("0.12"),
                electrified_km=Decimal("500"),
            )
        )
