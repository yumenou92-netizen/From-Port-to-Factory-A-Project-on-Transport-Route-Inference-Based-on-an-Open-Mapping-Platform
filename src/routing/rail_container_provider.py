"""Rail-container north-to-south trunk contract.

This provider is deliberately isolated from bulk shipping and container-vessel
providers.  It can build a railway edge from a fully specified record. Test
records remain visibly labelled ``demo_placeholder``; a separate local adapter
may supply confirmed railway business records as ``real_data``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Sequence

from src.domain.cost_rules import CostCalculationResult
from src.domain.freight_rate import create_freight_rate
from src.domain.route_request import RouteRequest
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_contracts import CostComponent, CostSourceType
from src.routing.transport_edge import TransportEdge, build_transport_edge


RAIL_CONTAINER_RULE_ID = "rail_container_rate_time"
RAIL_CONTAINER_RULE_VERSION = "0.2"
OPEN_TOP_TARPAULIN_YUAN_PER_BOX = Decimal("250")
RailContainerSourceType = Literal["real_data", "demo_placeholder"]


class RailContainerError(ValueError):
    """Raised when a railway-container record cannot safely form an edge."""


@dataclass(frozen=True)
class RailContainerTimeRegion:
    """Confirmed regional duration for a complete north-to-south rail segment."""

    origin_region: str
    destination_region: str
    duration_hours: Decimal
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin_region", _required_text(self.origin_region, "origin_region"))
        object.__setattr__(self, "destination_region", _required_text(self.destination_region, "destination_region"))
        object.__setattr__(self, "duration_hours", _positive_decimal(self.duration_hours, "铁路运输总时效"))
        object.__setattr__(self, "source", _required_text(self.source, "source"))


class TableRailContainerTimeProvider:
    """Exact regional time lookup; missing mappings never become a guessed time."""

    def __init__(self, records: Sequence[RailContainerTimeRegion]) -> None:
        self.records = tuple(records)

    def match(self, *, origin_region: str, destination_region: str) -> RailContainerTimeRegion | None:
        matches = [
            record for record in self.records
            if record.origin_region == origin_region and record.destination_region == destination_region
        ]
        if len(matches) != 1:
            return None
        return matches[0]


@dataclass(frozen=True)
class RailContainerRateTimeRecord:
    """One north-station to south-station railway-container record.

    The station fees are part of the record rather than global defaults, so a
    future station-fee table can replace a test value without changing routing.
    ``duration_hours`` is the complete railway segment duration.
    """

    north_station_name: str
    south_station_name: str
    north_station_node_id: str
    south_station_node_id: str
    commodity_scope: tuple[str, ...]
    trade_type: str
    container_type: Literal["顶开门箱", "敞顶箱"]
    base_freight_yuan_per_box: Decimal
    discount_ratio: Decimal
    origin_station_fee_yuan_per_box: Decimal
    destination_station_fee_yuan_per_box: Decimal
    duration_hours: Decimal
    source: str
    source_type: RailContainerSourceType

    def __post_init__(self) -> None:
        for field_name in (
            "north_station_name",
            "south_station_name",
            "north_station_node_id",
            "south_station_node_id",
            "trade_type",
            "source",
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        commodities = tuple(_required_text(item, "commodity_scope") for item in self.commodity_scope)
        if not commodities:
            raise RailContainerError("commodity_scope 不能为空。")
        object.__setattr__(self, "commodity_scope", commodities)
        if self.trade_type not in {"内贸", "外贸"}:
            raise RailContainerError("trade_type 必须为“内贸”或“外贸”。")
        if self.container_type not in {"顶开门箱", "敞顶箱"}:
            raise RailContainerError("container_type 必须为“顶开门箱”或“敞顶箱”。")
        if self.source_type not in {"real_data", "demo_placeholder"}:
            raise RailContainerError("source_type 必须为 real_data 或 demo_placeholder。")
        object.__setattr__(self, "base_freight_yuan_per_box", _positive_decimal(self.base_freight_yuan_per_box, "铁路基础运价"))
        discount = _non_negative_decimal(self.discount_ratio, "铁路下浮比例")
        if discount >= Decimal("1"):
            raise RailContainerError("铁路下浮比例必须大于等于 0 且小于 1。")
        object.__setattr__(self, "discount_ratio", discount)
        object.__setattr__(self, "origin_station_fee_yuan_per_box", _positive_decimal(self.origin_station_fee_yuan_per_box, "上站费"))
        object.__setattr__(self, "destination_station_fee_yuan_per_box", _positive_decimal(self.destination_station_fee_yuan_per_box, "下站费"))
        object.__setattr__(self, "duration_hours", _positive_decimal(self.duration_hours, "铁路运输总时效"))

    @property
    def executed_freight_yuan_per_box(self) -> Decimal:
        return self.base_freight_yuan_per_box * (Decimal("1") - self.discount_ratio)

    @property
    def tarpaulin_yuan_per_box(self) -> Decimal:
        return OPEN_TOP_TARPAULIN_YUAN_PER_BOX if self.container_type == "敞顶箱" else Decimal("0")

    def supports_request(self, request: RouteRequest) -> bool:
        return (
            request.package_type == "集装箱"
            and request.quantity_unit == "箱"
            and request.trade_type == self.trade_type
            and request.commodity in self.commodity_scope
        )


@dataclass(frozen=True)
class RailContainerMatch:
    status: Literal["resolved", "not_applicable", "manual_review"]
    message: str
    record: RailContainerRateTimeRecord | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class TableRailContainerProvider:
    """Match typed rail-container records and produce a formal trunk edge."""

    def __init__(self, records: Sequence[RailContainerRateTimeRecord]) -> None:
        self.records = tuple(records)

    def match(
        self,
        *,
        north_station_name: str,
        south_station_name: str,
        request: RouteRequest,
        container_type: str,
    ) -> RailContainerMatch:
        if request.package_type != "集装箱" or request.quantity_unit != "箱":
            return RailContainerMatch("not_applicable", "铁路集装箱首轮仅支持“集装箱/箱”订单；“柜”不得自动换算。")
        candidates = [
            record for record in self.records
            if record.north_station_name == north_station_name
            and record.south_station_name == south_station_name
            and record.container_type == container_type
            and record.supports_request(request)
        ]
        if not candidates:
            return RailContainerMatch("manual_review", "未找到同时具备铁路运费、站点费用和完整运输时效的铁路集装箱记录；不构边。")
        if len(candidates) != 1:
            return RailContainerMatch("manual_review", "铁路集装箱记录无法唯一匹配，请人工确认后再构边。")
        return RailContainerMatch("resolved", "已匹配铁路集装箱费率、站点费用和完整运输时效。", candidates[0])

    def build_edge(
        self,
        *,
        north_station_name: str,
        south_station_name: str,
        request: RouteRequest,
        container_type: str,
    ) -> tuple[TransportEdge | None, RailContainerMatch]:
        match = self.match(
            north_station_name=north_station_name,
            south_station_name=south_station_name,
            request=request,
            container_type=container_type,
        )
        if not match.is_resolved or match.record is None:
            return None, match
        record = match.record
        source_reference = _source_reference(record)
        quantity = request.quantity
        freight_total = record.executed_freight_yuan_per_box * quantity
        origin_fee_total = record.origin_station_fee_yuan_per_box * quantity
        destination_fee_total = record.destination_station_fee_yuan_per_box * quantity
        tarpaulin_total = record.tarpaulin_yuan_per_box * quantity
        total_cost = freight_total + origin_fee_total + destination_fee_total + tarpaulin_total
        rate = create_freight_rate(
            origin_name=record.north_station_name,
            destination_name=record.south_station_name,
            transport_mode="铁路",
            package_type="集装箱",
            commodity_scope="、".join(record.commodity_scope),
            raw_price=record.base_freight_yuan_per_box,
            raw_price_unit="元/箱",
            price_type="unit_price",
            price_source=source_reference,
            from_node_id=record.north_station_node_id,
            to_node_id=record.south_station_node_id,
        )
        detail = (
            f"铁路执行运价={record.base_freight_yuan_per_box}×(1-{record.discount_ratio})"
            f"={record.executed_freight_yuan_per_box}元/箱；"
            f"上站费={record.origin_station_fee_yuan_per_box}元/箱；"
            f"下站费={record.destination_station_fee_yuan_per_box}元/箱；"
            f"篷布费={record.tarpaulin_yuan_per_box}元/箱；"
            f"订单={quantity}箱；总费用={total_cost}元。"
        )
        cost = CostCalculationResult(
            status="valid",
            total_cost_yuan=total_cost,
            rule_id=RAIL_CONTAINER_RULE_ID,
            rule_version=RAIL_CONTAINER_RULE_VERSION,
            calculation_detail=detail,
            price_source=source_reference,
            transport_mode="铁路",
            rate_packaging="集装箱",
            price_unit="元/箱",
            message="已按铁路集装箱干线费用组成计算。",
        )
        time = ShippingTimeResult(
            status="resolved",
            duration_hours=record.duration_hours,
            source=source_reference,
            message="已使用维护的铁路完整运输段时效。",
            stage=f"{record.north_station_name}至{record.south_station_name}",
            transport_mode="铁路",
            input_value=str(record.duration_hours),
            input_unit="小时",
            time_scope="complete_segment",
        )
        source_type: CostSourceType = record.source_type
        components = [
            CostComponent("railway_freight", freight_total, source_type, source_reference, RAIL_CONTAINER_RULE_ID, RAIL_CONTAINER_RULE_VERSION, "铁路执行运价×订单箱数。"),
            CostComponent("origin_station_fee", origin_fee_total, source_type, source_reference, RAIL_CONTAINER_RULE_ID, RAIL_CONTAINER_RULE_VERSION, "上站费×订单箱数。"),
            CostComponent("destination_station_fee", destination_fee_total, source_type, source_reference, RAIL_CONTAINER_RULE_ID, RAIL_CONTAINER_RULE_VERSION, "下站费×订单箱数。"),
        ]
        if tarpaulin_total:
            components.append(CostComponent("open_top_tarpaulin_fee", tarpaulin_total, source_type, source_reference, RAIL_CONTAINER_RULE_ID, RAIL_CONTAINER_RULE_VERSION, "敞顶箱篷布费×订单箱数。"))
        edge = build_transport_edge(
            rate,
            cost,
            time,
            commodity=request.commodity,
            data_source=source_reference,
            transport_stage="north_to_south",
            edge_role="trunk",
            cost_components=tuple(components),
        )
        if not edge.is_available:
            return None, RailContainerMatch("manual_review", f"铁路集装箱边未通过 TransportEdge 校验：{edge.unavailable_reason}")
        return edge, match


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise RailContainerError(f"{field_name}不能为空。")
    return text


def _positive_decimal(value: object, field_name: str) -> Decimal:
    decimal_value = _decimal(value, field_name)
    if decimal_value <= 0:
        raise RailContainerError(f"{field_name}必须大于 0。")
    return decimal_value


def _non_negative_decimal(value: object, field_name: str) -> Decimal:
    decimal_value = _decimal(value, field_name)
    if decimal_value < 0:
        raise RailContainerError(f"{field_name}不得小于 0。")
    return decimal_value


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RailContainerError(f"{field_name}必须是有限数值。") from None
    if not decimal_value.is_finite():
        raise RailContainerError(f"{field_name}必须是有限数值。")
    return decimal_value


def _source_reference(record: RailContainerRateTimeRecord) -> str:
    return record.source if record.source_type == "real_data" else f"demo_placeholder:{record.source}"
