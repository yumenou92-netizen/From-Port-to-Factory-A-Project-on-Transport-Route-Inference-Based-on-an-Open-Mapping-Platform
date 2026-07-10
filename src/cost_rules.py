from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

try:
    from .unit_conversion import calculate_total_cost
except ImportError:  # Support direct script-style imports used by the current demo.
    from unit_conversion import calculate_total_cost


PriceMode = Literal["index", "manual"]
ManualPriceType = Literal["unit_price", "total_price"]
CostStage = Literal["trunk_shipping", "last_mile_truck", "railway"]


class CostRuleError(ValueError):
    """Raised when a cost rule cannot calculate a defensible cost."""


def calculate_bulk_shipping_cost(
    price_mode: str,
    coal_index: float | None = None,
    manual_quote_price: float | None = None,
    index_multiplier: float = 1.12,
    harbor_sailing_fee: float = 2,
    profit_fee: float = 5,
) -> float:
    """Legacy unit-price helper kept for the current demo and existing tests.

    For new route construction, use calculate_bulk_shipping_total_cost so the
    result is the current order segment total cost in yuan.
    """
    if price_mode == "index":
        if coal_index is None:
            raise ValueError("指数测算模式必须提供 coal_index")
        return round(coal_index * index_multiplier + harbor_sailing_fee + profit_fee, 2)

    if price_mode == "manual":
        if manual_quote_price is None:
            raise ValueError("线下询价模式必须提供 manual_quote_price")
        return manual_quote_price

    raise ValueError(f"未知散船计价模式: {price_mode}")


def calculate_bulk_shipping_unit_price(
    coal_index: int | float | str | Decimal,
    index_multiplier: int | float | str | Decimal = Decimal("1.12"),
    harbor_sailing_fee: int | float | str | Decimal = Decimal("2"),
    profit_fee: int | float | str | Decimal = Decimal("5"),
) -> Decimal:
    """Calculate index-based bulk shipping unit price.

    Business rule:
    unit price = coal index * 1.12 + 2 yuan harbor sailing fee + 5 yuan profit.
    """
    coal_index_value = _to_decimal(coal_index, "煤炭指数")
    multiplier_value = _to_decimal(index_multiplier, "指数系数")
    harbor_fee_value = _to_decimal(harbor_sailing_fee, "港驶费")
    profit_fee_value = _to_decimal(profit_fee, "利润")

    return coal_index_value * multiplier_value + harbor_fee_value + profit_fee_value


def calculate_bulk_shipping_total_cost(
    price_mode: PriceMode,
    quantity: int | float | str | Decimal,
    quantity_unit: str,
    coal_index: int | float | str | Decimal | None = None,
    manual_quote_price: int | float | str | Decimal | None = None,
    manual_price_type: ManualPriceType | None = None,
    manual_price_unit: str | None = None,
    index_price_unit: str = "元/吨",
    index_multiplier: int | float | str | Decimal = Decimal("1.12"),
    harbor_sailing_fee: int | float | str | Decimal = Decimal("2"),
    profit_fee: int | float | str | Decimal = Decimal("5"),
) -> Decimal:
    """Calculate first-stage north-port to south-port bulk shipping total cost.

    Returns the total cost for the current order segment, in yuan.
    """
    if price_mode == "index":
        if coal_index is None:
            raise CostRuleError("指数测算模式必须提供 coal_index")
        unit_price = calculate_bulk_shipping_unit_price(
            coal_index=coal_index,
            index_multiplier=index_multiplier,
            harbor_sailing_fee=harbor_sailing_fee,
            profit_fee=profit_fee,
        )
        return calculate_total_cost(unit_price, index_price_unit, quantity, quantity_unit)

    if price_mode == "manual":
        return calculate_manual_shipping_cost(
            manual_quote_price=manual_quote_price,
            manual_price_type=manual_price_type,
            manual_price_unit=manual_price_unit,
            quantity=quantity,
            quantity_unit=quantity_unit,
        )

    raise CostRuleError(f"未知散船计价模式: {price_mode}")


def calculate_manual_shipping_cost(
    manual_quote_price: int | float | str | Decimal | None,
    manual_price_type: ManualPriceType | None,
    manual_price_unit: str | None,
    quantity: int | float | str | Decimal,
    quantity_unit: str,
) -> Decimal:
    """Calculate manually quoted shipping cost.

    Manual quotes must explicitly state whether the quote is a unit price or total price.
    """
    if manual_quote_price is None:
        raise CostRuleError("人工报价模式必须提供 manual_quote_price")
    if manual_price_type not in ("unit_price", "total_price"):
        raise CostRuleError("人工报价必须显式区分 manual_price_type=unit_price 或 total_price")

    if manual_price_type == "unit_price":
        if not manual_price_unit:
            raise CostRuleError("人工单价报价必须提供 manual_price_unit")
        return calculate_total_cost(manual_quote_price, manual_price_unit, quantity, quantity_unit)

    total_cost = _to_decimal(manual_quote_price, "人工总价")
    if total_cost < 0:
        raise CostRuleError(f"人工总价不能为负数，当前值：{manual_quote_price}")
    return total_cost


def calculate_edge_cost(stage: CostStage, **kwargs) -> Decimal:
    """Unified cost calculation entry point for future TransportEdge construction."""
    if stage == "trunk_shipping":
        return calculate_bulk_shipping_total_cost(**kwargs)

    if stage == "last_mile_truck":
        raise CostRuleError("最后一公里汽运规则已记录，但尚未接入正式费用计算。")

    if stage == "railway":
        raise CostRuleError("铁路费用规则当前仍为旧版函数，尚未接入统一边费用计算。")

    raise CostRuleError(f"未知费用计算阶段: {stage}")


def calculate_railway_cost(
    origin_operation_fee: float,
    railway_freight_fee: float,
    destination_unloading_fee: float,
    short_truck_fee: float,
    is_open_top_container: bool = False,
    tarpaulin_return_fee: float = 0,
) -> float:
    total = origin_operation_fee + railway_freight_fee + destination_unloading_fee + short_truck_fee
    if is_open_top_container:
        total += tarpaulin_return_fee
    return total


def calculate_truck_cost(distance: float, rate_per_km: float, minimum_fee: float = 0) -> float:
    return max(distance * rate_per_km, minimum_fee)


def _to_decimal(value: int | float | str | Decimal, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise CostRuleError(f"{field_name}必须是数值，当前值：{value}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise CostRuleError(f"{field_name}必须是数值，当前值：{value}") from None
    if not number.is_finite():
        raise CostRuleError(f"{field_name}必须是有限数值，当前值：{value}")
    return number
