from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Final


SUPPORTED_QUANTITY_UNITS: Final[set[str]] = {"吨", "箱", "柜"}
SUPPORTED_PRICE_BASE_UNITS: Final[set[str]] = {"吨", "箱", "柜"}


class UnitConversionError(ValueError):
    """Base error for order quantity and freight unit conversion failures."""


class UnsupportedQuantityUnitError(UnitConversionError):
    """Raised when an order quantity unit is not supported."""


class UnsupportedPriceUnitError(UnitConversionError):
    """Raised when a freight price unit is not supported."""


class UnitMismatchError(UnitConversionError):
    """Raised when order quantity unit and freight price unit do not match."""


class InvalidQuantityError(UnitConversionError):
    """Raised when quantity cannot be converted to a positive number."""


class InvalidPriceError(UnitConversionError):
    """Raised when freight price cannot be converted to a non-negative number."""


def normalize_quantity_unit(quantity_unit: str) -> str:
    unit = _clean_unit_text(quantity_unit)
    if unit not in SUPPORTED_QUANTITY_UNITS:
        raise UnsupportedQuantityUnitError(f"不支持的数量单位：{quantity_unit}")
    return unit


def normalize_price_unit(price_unit: str) -> str:
    text = _clean_unit_text(price_unit)
    match = re.fullmatch(r"元[/／](.+)", text)
    if not match:
        raise UnsupportedPriceUnitError(f"不支持的费用单位：{price_unit}")

    base_unit = _clean_unit_text(match.group(1))
    if base_unit not in SUPPORTED_PRICE_BASE_UNITS:
        raise UnsupportedPriceUnitError(f"不支持的费用单位：{price_unit}")
    return base_unit


def calculate_total_cost(raw_price: int | float | str | Decimal, price_unit: str, quantity: int | float | str | Decimal, quantity_unit: str) -> Decimal:
    """Convert a unit freight price into the total cost for the current order.

    The returned value is always the total amount for one transport segment, in yuan.
    """
    normalized_quantity_unit = normalize_quantity_unit(quantity_unit)
    normalized_price_base_unit = normalize_price_unit(price_unit)

    if normalized_quantity_unit != normalized_price_base_unit:
        raise UnitMismatchError(
            f"订单数量单位为 {normalized_quantity_unit}，但运价单位为 {price_unit}，不能直接计算总费用。"
        )

    quantity_value = _to_decimal(quantity, InvalidQuantityError, "订单数量")
    price_value = _to_decimal(raw_price, InvalidPriceError, "运价")

    if quantity_value <= 0:
        raise InvalidQuantityError(f"订单数量必须大于 0，当前值：{quantity}")
    if price_value < 0:
        raise InvalidPriceError(f"运价不能为负数，当前值：{raw_price}")

    return price_value * quantity_value


def _clean_unit_text(value: str) -> str:
    if value is None:
        return ""
    return str(value).strip().replace(" ", "")


def _to_decimal(value: int | float | str | Decimal, error_type: type[UnitConversionError], field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise error_type(f"{field_name}必须是数值，当前值：{value}")

    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise error_type(f"{field_name}必须是数值，当前值：{value}") from None

    if not number.is_finite():
        raise error_type(f"{field_name}必须是有限数值，当前值：{value}")
    return number
