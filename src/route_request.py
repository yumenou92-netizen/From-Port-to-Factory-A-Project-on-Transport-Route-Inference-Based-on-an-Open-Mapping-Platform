from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

try:
    from .unit_conversion import UnitConversionError, calculate_total_cost, normalize_quantity_unit
except ImportError:  # Support direct script-style imports used by demo scripts.
    from unit_conversion import UnitConversionError, calculate_total_cost, normalize_quantity_unit


RequestValidationStatus = Literal["valid", "manual_review"]
FreightChargeStatus = Literal["valid", "not_applicable", "manual_review"]
ShippingPriceMode = Literal["index", "manual"]

PACKAGING_QUANTITY_UNITS: Final[dict[str, frozenset[str]]] = {
    "散粮": frozenset({"吨"}),
    "集装箱": frozenset({"箱", "柜"}),
}


class RouteRequestError(ValueError):
    """Raised when an order request cannot be represented safely."""


@dataclass(frozen=True)
class RouteRequest:
    quantity: Decimal
    quantity_unit: str
    package_type: str
    commodity: str
    origin_port_id: str | None = None
    south_port_id: str | None = None
    customer_id: str | None = None
    shipping_price_mode: ShippingPriceMode | None = None
    shipping_time_hours: Decimal | None = None

    def __post_init__(self) -> None:
        quantity = _positive_decimal(self.quantity, "订单数量")
        try:
            quantity_unit = normalize_quantity_unit(self.quantity_unit)
        except UnitConversionError as exc:
            raise RouteRequestError(str(exc)) from exc

        package_type = _required_text(self.package_type, "包装方式")
        commodity = _required_text(self.commodity, "货物品种")
        price_mode = _optional_text(self.shipping_price_mode)
        if price_mode is not None and price_mode not in {"index", "manual"}:
            raise RouteRequestError(f"不支持的散船计价模式：{self.shipping_price_mode}")

        shipping_time = self.shipping_time_hours
        if shipping_time is not None:
            shipping_time = _positive_decimal(shipping_time, "散船运时")

        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "quantity_unit", quantity_unit)
        object.__setattr__(self, "package_type", package_type)
        object.__setattr__(self, "commodity", commodity)
        object.__setattr__(self, "origin_port_id", _optional_text(self.origin_port_id))
        object.__setattr__(self, "south_port_id", _optional_text(self.south_port_id))
        object.__setattr__(self, "customer_id", _optional_text(self.customer_id))
        object.__setattr__(self, "shipping_price_mode", price_mode)
        object.__setattr__(self, "shipping_time_hours", shipping_time)


@dataclass(frozen=True)
class RequestBillingValidation:
    status: RequestValidationStatus
    issues: tuple[str, ...] = ()

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


@dataclass(frozen=True)
class FreightChargeEvaluation:
    status: FreightChargeStatus
    transport_mode: str
    rate_packaging: str
    price_unit: str
    total_cost: Decimal | None
    message: str

    def __post_init__(self) -> None:
        if self.status == "valid":
            if self.total_cost is None or not self.total_cost.is_finite() or self.total_cost <= 0:
                raise ValueError("有效计费结果必须包含大于 0 的运输段总费用。")
        elif self.total_cost is not None:
            raise ValueError("非有效计费结果不得包含运输段总费用。")

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


def validate_request_billing(request: RouteRequest) -> RequestBillingValidation:
    """Use packaging only as an auxiliary check for the order quantity unit."""
    allowed_units = PACKAGING_QUANTITY_UNITS.get(request.package_type)
    if allowed_units is None:
        return RequestBillingValidation(
            status="manual_review",
            issues=(f"包装方式 {request.package_type} 尚未配置计费单位规则，请人工确认。",),
        )

    if request.quantity_unit not in allowed_units:
        expected = "、".join(sorted(allowed_units))
        return RequestBillingValidation(
            status="manual_review",
            issues=(
                f"包装方式为 {request.package_type}，订单数量单位为 {request.quantity_unit}，"
                f"当前辅助规则期望单位为 {expected}，请人工确认。",
            ),
        )

    return RequestBillingValidation(status="valid")


def evaluate_freight_charge(
    request: RouteRequest,
    *,
    transport_mode: str,
    rate_packaging: str,
    raw_price: int | float | str | Decimal,
    price_unit: str,
) -> FreightChargeEvaluation:
    """Evaluate one freight-rate record against an order request.

    Transport mode is copied from the freight-rate record. It is never inferred
    from packaging. Box and container-load units must match exactly.
    """
    mode = str(transport_mode).strip()
    packaging = str(rate_packaging).strip()
    normalized_price_unit = str(price_unit).strip()

    if not mode:
        return _manual_review(mode, packaging, normalized_price_unit, "运价记录缺少运输方式，请人工确认。")
    if not packaging:
        return _manual_review(mode, packaging, normalized_price_unit, "运价记录缺少包装方式，请人工确认。")

    billing_validation = validate_request_billing(request)
    if billing_validation.requires_manual_review:
        return _manual_review(
            mode,
            packaging,
            normalized_price_unit,
            "；".join(billing_validation.issues),
        )

    if packaging != request.package_type:
        return FreightChargeEvaluation(
            status="not_applicable",
            transport_mode=mode,
            rate_packaging=packaging,
            price_unit=normalized_price_unit,
            total_cost=None,
            message=f"订单包装方式为 {request.package_type}，该运价适用于 {packaging}。",
        )

    try:
        total_cost = calculate_total_cost(
            raw_price=raw_price,
            price_unit=normalized_price_unit,
            quantity=request.quantity,
            quantity_unit=request.quantity_unit,
        )
    except UnitConversionError as exc:
        return _manual_review(mode, packaging, normalized_price_unit, str(exc))

    if total_cost == 0:
        return _manual_review(
            mode,
            packaging,
            normalized_price_unit,
            "运价为零，不能自动形成路径成本，请人工确认是否为占位值。",
        )

    return FreightChargeEvaluation(
        status="valid",
        transport_mode=mode,
        rate_packaging=packaging,
        price_unit=normalized_price_unit,
        total_cost=total_cost,
        message="计费单位精确匹配，已换算为当前订单运输段总费用。",
    )


def _manual_review(
    transport_mode: str,
    rate_packaging: str,
    price_unit: str,
    message: str,
) -> FreightChargeEvaluation:
    return FreightChargeEvaluation(
        status="manual_review",
        transport_mode=transport_mode,
        rate_packaging=rate_packaging,
        price_unit=price_unit,
        total_cost=None,
        message=message,
    )


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise RouteRequestError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise RouteRequestError(f"{field_name}必须是数值，当前值：{value}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RouteRequestError(f"{field_name}必须是数值，当前值：{value}") from None
    if not number.is_finite() or number <= 0:
        raise RouteRequestError(f"{field_name}必须大于 0，当前值：{value}")
    return number
