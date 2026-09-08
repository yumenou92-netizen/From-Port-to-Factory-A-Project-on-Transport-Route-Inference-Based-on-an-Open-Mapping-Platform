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
    lines = {line.name: line for line in result.lines}
    assert lines["基础运费"].name == "基础运费"
    assert lines["电气化费"].adjusted_yuan == Decimal("0")


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


def test_each_dynamic_local_freight_uses_confirmed_discount_correction():
    result = calculate_rail_freight_workbook(
        RailFreightCalculatorInput(
            load_tons=Decimal("60"),
            total_freight_yuan=Decimal("1691.1"),
            discount_ratio=Decimal("0.12"),
            electrified_km=Decimal("500"),
            local_freight_adjusted_bases=(Decimal("20"), Decimal("100")),
        )
    )

    lines = {line.name: line for line in result.lines}
    assert lines["地方运费1"].adjusted_yuan == Decimal("17.6")
    assert lines["地方运费2"].adjusted_yuan == Decimal("88")
    assert result.local_freight_adjusted_total_yuan == Decimal("105.6")


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
