from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Sequence

from src.domain.route_request import ALLOWED_TRADE_TYPES, RouteRequest


InlandWaterwayFreightStatus = Literal["resolved", "manual_review"]
InlandWaterwayFreightSourceType = Literal["real_data", "demo_placeholder"]


class InlandWaterwayFreightError(ValueError):
    """Raised when inland-waterway freight data is internally inconsistent."""


@dataclass(frozen=True)
class InlandWaterwayFreightRecord:
    origin_region_code: str
    destination_region_code: str
    package_type: str
    commodity_scope: tuple[str, ...]
    unit_price_yuan_per_ton: Decimal
    fee_unit: str
    trade_type: str
    bidirectional: bool
    source_type: InlandWaterwayFreightSourceType
    source: str
    rule_id: str
    rule_version: str
    maintained_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "origin_region_code",
            _required_text(self.origin_region_code, "驳船费率起点区域"),
        )
        object.__setattr__(
            self,
            "destination_region_code",
            _required_text(self.destination_region_code, "驳船费率终点区域"),
        )
        object.__setattr__(
            self,
            "package_type",
            _required_text(self.package_type, "驳船费率包装方式"),
        )
        object.__setattr__(
            self,
            "commodity_scope",
            _normalized_scope(self.commodity_scope),
        )
        object.__setattr__(
            self,
            "unit_price_yuan_per_ton",
            _positive_decimal(self.unit_price_yuan_per_ton, "驳船单位费率"),
        )
        object.__setattr__(self, "fee_unit", _required_text(self.fee_unit, "驳船费率单位"))
        object.__setattr__(self, "trade_type", _required_text(self.trade_type, "贸易类型"))
        object.__setattr__(self, "source", _required_text(self.source, "驳船费率来源"))
        object.__setattr__(self, "rule_id", _required_text(self.rule_id, "驳船费率规则编号"))
        object.__setattr__(
            self,
            "rule_version",
            _required_text(self.rule_version, "驳船费率规则版本"),
        )
        object.__setattr__(self, "maintained_at", _optional_text(self.maintained_at))
        if self.fee_unit != "元/吨":
            raise InlandWaterwayFreightError(
                f"当前散粮驳船费率只支持元/吨，不支持 {self.fee_unit}。"
            )
        if self.trade_type not in ALLOWED_TRADE_TYPES:
            supported = "、".join(sorted(ALLOWED_TRADE_TYPES))
            raise InlandWaterwayFreightError(
                f"不支持的贸易类型：{self.trade_type}；当前支持 {supported}。"
            )
        if self.source_type not in {"real_data", "demo_placeholder"}:
            raise InlandWaterwayFreightError(
                f"不支持的驳船费率来源类型：{self.source_type}"
            )
        if not isinstance(self.bidirectional, bool):
            raise InlandWaterwayFreightError("驳船费率双向标志必须是布尔值。")

    def matches_route(
        self,
        origin_region_code: str,
        destination_region_code: str,
    ) -> bool:
        if (
            origin_region_code == self.origin_region_code
            and destination_region_code == self.destination_region_code
        ):
            return True
        return (
            self.bidirectional
            and origin_region_code == self.destination_region_code
            and destination_region_code == self.origin_region_code
        )

    def supports_request(self, request: RouteRequest) -> bool:
        return (
            request.quantity_unit == "吨"
            and request.package_type == self.package_type
            and request.trade_type == self.trade_type
            and (
                request.commodity in self.commodity_scope
                or "*" in self.commodity_scope
            )
        )

    @property
    def source_ref(self) -> str:
        prefix = f"{self.source_type}:"
        return self.source if self.source.startswith(prefix) else f"{prefix}{self.source}"


@dataclass(frozen=True)
class InlandWaterwayFreightQuote:
    status: InlandWaterwayFreightStatus
    message: str
    total_cost_yuan: Decimal | None = None
    record: InlandWaterwayFreightRecord | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class TableInlandWaterwayFreightProvider:
    def __init__(self, records: Sequence[InlandWaterwayFreightRecord] = ()) -> None:
        self.records = tuple(records)

    def quote(
        self,
        *,
        origin_region_code: str,
        destination_region_code: str,
        request: RouteRequest,
    ) -> InlandWaterwayFreightQuote:
        matches = [
            record
            for record in self.records
            if record.matches_route(origin_region_code, destination_region_code)
            and record.supports_request(request)
        ]
        if not matches:
            return InlandWaterwayFreightQuote(
                status="manual_review",
                message=(
                    f"没有匹配 {origin_region_code} 至 {destination_region_code}、"
                    f"{request.trade_type}/{request.package_type}/{request.commodity} "
                    "的驳船费率；不得补零。"
                ),
            )
        if len(matches) > 1:
            sources = "；".join(record.source_ref for record in matches)
            return InlandWaterwayFreightQuote(
                status="manual_review",
                message=f"匹配到多条驳船费率，请人工去重：{sources}",
            )
        record = matches[0]
        return InlandWaterwayFreightQuote(
            status="resolved",
            total_cost_yuan=record.unit_price_yuan_per_ton * request.quantity,
            record=record,
            message=(
                f"已按 {record.unit_price_yuan_per_ton}元/吨×"
                f"{request.quantity}{request.quantity_unit} 计算驳船运费。"
            ),
        )


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise InlandWaterwayFreightError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_scope(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not normalized:
        raise InlandWaterwayFreightError("驳船费率适用品种不能为空。")
    return normalized


def _positive_decimal(value: object, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise InlandWaterwayFreightError(f"{field_name}必须是大于 0 的有限数值。") from None
    if not number.is_finite() or number <= 0:
        raise InlandWaterwayFreightError(f"{field_name}必须是大于 0 的有限数值。")
    return number
