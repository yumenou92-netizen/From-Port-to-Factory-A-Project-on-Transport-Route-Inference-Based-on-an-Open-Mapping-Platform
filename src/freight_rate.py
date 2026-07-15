from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

try:
    from .cost_rules import CostCalculationResult, DEFAULT_COST_RULE_ENGINE
    from .route_request import RouteRequest
except ImportError:  # Support direct script-style imports used by demo scripts.
    from cost_rules import CostCalculationResult, DEFAULT_COST_RULE_ENGINE
    from route_request import RouteRequest


PriceType = Literal["unit_price", "total_price"]


class FreightRateError(ValueError):
    """Raised when a freight rate cannot be represented safely."""


@dataclass(frozen=True)
class FreightRate:
    rate_id: str
    origin_name: str
    destination_name: str
    transport_mode: str
    package_type: str
    commodity_scope: str
    raw_price: Decimal
    raw_price_unit: str
    price_type: PriceType
    price_source: str
    maintained_at: date | None = None
    from_node_id: str | None = None
    to_node_id: str | None = None
    source_file: str | None = None
    source_row_number: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate_id", _required_text(self.rate_id, "费率编号"))
        object.__setattr__(self, "origin_name", _required_text(self.origin_name, "始发"))
        object.__setattr__(self, "destination_name", _required_text(self.destination_name, "到达"))
        object.__setattr__(self, "transport_mode", _required_text(self.transport_mode, "运输方式"))
        object.__setattr__(self, "package_type", _required_text(self.package_type, "包装方式"))
        object.__setattr__(self, "commodity_scope", _required_text(self.commodity_scope, "适用品种"))
        object.__setattr__(self, "raw_price", _finite_decimal(self.raw_price, "原始价格"))
        object.__setattr__(self, "raw_price_unit", _required_text(self.raw_price_unit, "原始费用单位"))
        object.__setattr__(self, "price_type", _required_text(self.price_type, "价格类型"))
        object.__setattr__(self, "price_source", _required_text(self.price_source, "价格来源"))
        object.__setattr__(self, "from_node_id", _optional_text(self.from_node_id))
        object.__setattr__(self, "to_node_id", _optional_text(self.to_node_id))
        object.__setattr__(self, "source_file", _optional_text(self.source_file))

        if self.price_type not in {"unit_price", "total_price"}:
            raise FreightRateError(
                f"价格类型必须为 unit_price 或 total_price，当前值：{self.price_type}"
            )
        if self.maintained_at is not None and not isinstance(self.maintained_at, date):
            raise FreightRateError("维护日期必须是 date 或 None。")
        if self.source_row_number is not None and (
            isinstance(self.source_row_number, bool)
            or not isinstance(self.source_row_number, int)
            or self.source_row_number <= 0
        ):
            raise FreightRateError("来源行号必须是大于 0 的整数。")

    @property
    def business_route_key(self) -> tuple[str, ...]:
        """Stable route identity used by the later latest-rate selection stage."""
        return (
            self.from_node_id or _normalize_identity_text(self.origin_name),
            self.to_node_id or _normalize_identity_text(self.destination_name),
            _normalize_identity_text(self.transport_mode),
            _normalize_identity_text(self.package_type),
            _canonical_commodity_scope(self.commodity_scope),
            self.price_type,
            _normalize_identity_text(self.raw_price_unit),
        )

    @property
    def is_node_resolved(self) -> bool:
        return self.from_node_id is not None and self.to_node_id is not None

    def supports_commodity(self, commodity: str) -> bool:
        requested = str(commodity).strip()
        allowed = {
            item.strip()
            for item in re.split(r"[,，、/]+", self.commodity_scope)
            if item.strip()
        }
        return requested in allowed

    def bind_node_ids(
        self,
        from_node_id: str | None,
        to_node_id: str | None,
    ) -> FreightRate:
        return replace(
            self,
            from_node_id=_optional_text(from_node_id),
            to_node_id=_optional_text(to_node_id),
        )

    def evaluate_for_request(self, request: RouteRequest) -> CostCalculationResult:
        """Compatibility entry point delegated to the formal cost-rule engine."""
        return DEFAULT_COST_RULE_ENGINE.evaluate_freight_rate(self, request)


def create_freight_rate(
    *,
    origin_name: str,
    destination_name: str,
    transport_mode: str,
    package_type: str,
    commodity_scope: str,
    raw_price: int | float | str | Decimal,
    raw_price_unit: str,
    price_type: PriceType,
    price_source: str,
    maintained_at: date | str | None = None,
    from_node_id: str | None = None,
    to_node_id: str | None = None,
    source_file: str | None = None,
    source_row_number: int | None = None,
) -> FreightRate:
    normalized_origin = _required_text(origin_name, "始发")
    normalized_destination = _required_text(destination_name, "到达")
    normalized_transport_mode = _required_text(transport_mode, "运输方式")
    normalized_package_type = _required_text(package_type, "包装方式")
    normalized_commodity_scope = _required_text(commodity_scope, "适用品种")
    normalized_price_unit = _required_text(raw_price_unit, "原始费用单位")
    normalized_price_type = _required_text(price_type, "价格类型")
    normalized_price_source = _required_text(price_source, "价格来源")
    normalized_from_node_id = _optional_text(from_node_id)
    normalized_to_node_id = _optional_text(to_node_id)
    normalized_source_file = _optional_text(source_file)
    normalized_date = parse_maintained_at(maintained_at)
    normalized_price = _finite_decimal(raw_price, "原始价格")
    rate_id = make_freight_rate_id(
        origin_name=normalized_origin,
        destination_name=normalized_destination,
        transport_mode=normalized_transport_mode,
        package_type=normalized_package_type,
        commodity_scope=normalized_commodity_scope,
        raw_price=normalized_price,
        raw_price_unit=normalized_price_unit,
        price_type=normalized_price_type,
        price_source=normalized_price_source,
        maintained_at=normalized_date,
    )
    return FreightRate(
        rate_id=rate_id,
        origin_name=normalized_origin,
        destination_name=normalized_destination,
        transport_mode=normalized_transport_mode,
        package_type=normalized_package_type,
        commodity_scope=normalized_commodity_scope,
        raw_price=normalized_price,
        raw_price_unit=normalized_price_unit,
        price_type=normalized_price_type,
        price_source=normalized_price_source,
        maintained_at=normalized_date,
        from_node_id=normalized_from_node_id,
        to_node_id=normalized_to_node_id,
        source_file=normalized_source_file,
        source_row_number=source_row_number,
    )


def make_freight_rate_id(**values: object) -> str:
    maintained_at = values.get("maintained_at")
    if isinstance(maintained_at, date):
        values["maintained_at"] = maintained_at.isoformat()
    normalized_parts: list[str] = []
    for key, value in sorted(values.items()):
        if isinstance(value, Decimal):
            text = _canonical_decimal(value)
        elif key == "commodity_scope":
            text = _canonical_commodity_scope(str(value))
        else:
            text = _normalize_identity_text(value)
        normalized_parts.append(f"{key}={text}")
    normalized = "|".join(normalized_parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"rate_{digest}"


def parse_maintained_at(value: date | str | None) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise FreightRateError(f"维护日期必须符合 YYYY-MM-DD，当前值：{value}") from exc


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise FreightRateError(f"{field_name}必须是文本。")
    text = value.strip()
    if not text:
        raise FreightRateError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FreightRateError("可选文本字段必须是文本或 None。")
    text = value.strip()
    return text or None


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise FreightRateError(f"{field_name}必须是数值，当前值：{value}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise FreightRateError(f"{field_name}必须是数值，当前值：{value}") from None
    if not number.is_finite():
        raise FreightRateError(f"{field_name}必须是有限数值，当前值：{value}")
    return number


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _canonical_commodity_scope(value: str) -> str:
    commodities = {
        item.strip()
        for item in re.split(r"[,，、/]+", str(value))
        if item.strip()
    }
    return ",".join(sorted(commodities))


def _normalize_identity_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value).strip()).replace("／", "/")
