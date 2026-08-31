"""Rail-container south-station-to-customer delivery contracts.

The provider is deliberately isolated from the active full-flow pipeline.  It
models three future railway-container terminal plans without inventing missing
business data: direct truck delivery, a customer dedicated siding, and a
third-party dedicated siding followed by an explicit delivery leg.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Sequence

from src.domain.cost_rules import (
    CostCalculationResult,
    RAIL_CONTAINER_DELIVERY_TRUCK_RULE,
    calculate_rail_container_delivery_truck_unit_price,
)
from src.domain.freight_rate import create_freight_rate
from src.domain.route_request import RouteRequest
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_contracts import CostComponent, CostSourceType, TransportEdgeRole
from src.routing.transport_edge import TransportEdge, build_transport_edge


RAIL_CUSTOMER_DEDICATED_SIDING_RULE_ID = "rail_container_customer_dedicated_siding"
RAIL_THIRD_PARTY_DEDICATED_SIDING_RULE_ID = "rail_container_third_party_dedicated_siding"
RAIL_TERMINAL_RULE_VERSION = "0.1"
RailTerminalSourceType = Literal["real_data", "demo_placeholder"]
ContainerType = Literal["顶开门箱", "敞顶箱"]


class RailCustomerDeliveryError(ValueError):
    """Raised for malformed future railway terminal-plan records."""


@dataclass(frozen=True)
class RailTerminalScope:
    """Shared order scope for one terminal delivery plan."""

    commodity_scope: tuple[str, ...]
    trade_type: str
    container_type: ContainerType
    source: str
    source_type: RailTerminalSourceType

    def __post_init__(self) -> None:
        commodities = tuple(_required_text(value, "commodity_scope") for value in self.commodity_scope)
        if not commodities:
            raise RailCustomerDeliveryError("commodity_scope 不能为空。")
        object.__setattr__(self, "commodity_scope", commodities)
        if self.trade_type not in {"内贸", "外贸"}:
            raise RailCustomerDeliveryError("trade_type 必须为“内贸”或“外贸”。")
        if self.container_type not in {"顶开门箱", "敞顶箱"}:
            raise RailCustomerDeliveryError("container_type 必须为“顶开门箱”或“敞顶箱”。")
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        if self.source_type not in {"real_data", "demo_placeholder"}:
            raise RailCustomerDeliveryError("source_type 必须为 real_data 或 demo_placeholder。")

    def supports(self, request: RouteRequest, container_type: str) -> bool:
        return (
            request.package_type == "集装箱"
            and request.quantity_unit == "箱"
            and request.trade_type == self.trade_type
            and request.commodity in self.commodity_scope
            and container_type == self.container_type
        )


@dataclass(frozen=True)
class DirectTruckDeliveryRecord:
    south_station_name: str
    south_station_node_id: str
    customer_name: str
    customer_node_id: str
    scope: RailTerminalScope
    distance_km: Decimal
    distance_source: str
    duration_hours: Decimal
    time_source: str

    def __post_init__(self) -> None:
        _validate_endpoints(self, "south_station_name", "south_station_node_id", "customer_name", "customer_node_id")
        object.__setattr__(self, "distance_km", _positive_decimal(self.distance_km, "直达拖车距离"))
        object.__setattr__(self, "distance_source", _required_text(self.distance_source, "distance_source"))
        object.__setattr__(self, "duration_hours", _positive_decimal(self.duration_hours, "直达拖车时效"))
        object.__setattr__(self, "time_source", _required_text(self.time_source, "time_source"))


@dataclass(frozen=True)
class CustomerDedicatedSidingRecord:
    south_station_name: str
    south_station_node_id: str
    customer_name: str
    customer_node_id: str
    scope: RailTerminalScope
    unit_fee_yuan_per_box: Decimal
    duration_hours: Decimal
    time_source: str

    def __post_init__(self) -> None:
        _validate_endpoints(self, "south_station_name", "south_station_node_id", "customer_name", "customer_node_id")
        object.__setattr__(self, "unit_fee_yuan_per_box", _positive_decimal(self.unit_fee_yuan_per_box, "客户专用线费用"))
        object.__setattr__(self, "duration_hours", _positive_decimal(self.duration_hours, "客户专用线时效"))
        object.__setattr__(self, "time_source", _required_text(self.time_source, "time_source"))


@dataclass(frozen=True)
class ThirdPartyDedicatedSidingRecord:
    south_station_name: str
    south_station_node_id: str
    third_party_name: str
    third_party_node_id: str
    customer_name: str
    customer_node_id: str
    scope: RailTerminalScope
    rail_unit_fee_yuan_per_box: Decimal
    rail_duration_hours: Decimal
    rail_time_source: str
    delivery_transport_mode: Literal["汽运", "铁路"]
    delivery_unit_fee_yuan_per_box: Decimal
    delivery_duration_hours: Decimal
    delivery_time_source: str

    def __post_init__(self) -> None:
        _validate_endpoints(
            self,
            "south_station_name",
            "south_station_node_id",
            "third_party_name",
            "third_party_node_id",
            "customer_name",
            "customer_node_id",
        )
        object.__setattr__(self, "rail_unit_fee_yuan_per_box", _positive_decimal(self.rail_unit_fee_yuan_per_box, "第三方专用线铁路费用"))
        object.__setattr__(self, "rail_duration_hours", _positive_decimal(self.rail_duration_hours, "第三方专用线铁路时效"))
        object.__setattr__(self, "rail_time_source", _required_text(self.rail_time_source, "rail_time_source"))
        if self.delivery_transport_mode not in {"汽运", "铁路"}:
            raise RailCustomerDeliveryError("第三方专用线交付方式必须为“汽运”或“铁路”。")
        object.__setattr__(self, "delivery_unit_fee_yuan_per_box", _positive_decimal(self.delivery_unit_fee_yuan_per_box, "第三方专用线交付费用"))
        object.__setattr__(self, "delivery_duration_hours", _positive_decimal(self.delivery_duration_hours, "第三方专用线交付时效"))
        object.__setattr__(self, "delivery_time_source", _required_text(self.delivery_time_source, "delivery_time_source"))


@dataclass(frozen=True)
class RailCustomerDeliveryPlanResult:
    plan_type: Literal["direct_truck", "customer_dedicated_siding", "third_party_dedicated_siding"]
    status: Literal["resolved", "not_applicable", "manual_review"]
    message: str
    edges: tuple[TransportEdge, ...] = ()


class RailCustomerDeliveryProvider:
    """Build isolated terminal-plan edges only from fully specified records."""

    def __init__(
        self,
        *,
        direct_truck_records: Sequence[DirectTruckDeliveryRecord] = (),
        customer_dedicated_siding_records: Sequence[CustomerDedicatedSidingRecord] = (),
        third_party_dedicated_siding_records: Sequence[ThirdPartyDedicatedSidingRecord] = (),
    ) -> None:
        self.direct_truck_records = tuple(direct_truck_records)
        self.customer_dedicated_siding_records = tuple(customer_dedicated_siding_records)
        self.third_party_dedicated_siding_records = tuple(third_party_dedicated_siding_records)

    def build_direct_truck(
        self, *, south_station_name: str, customer_name: str, request: RouteRequest, container_type: str
    ) -> RailCustomerDeliveryPlanResult:
        record = self._one_match(
            self.direct_truck_records, south_station_name, customer_name, request, container_type, "direct_truck"
        )
        if isinstance(record, RailCustomerDeliveryPlanResult):
            return record
        unit_fee = calculate_rail_container_delivery_truck_unit_price(record.distance_km)
        total = unit_fee * request.quantity
        source = _source_reference(record.scope)
        edge = _build_edge(
            origin_name=record.south_station_name,
            origin_node_id=record.south_station_node_id,
            destination_name=record.customer_name,
            destination_node_id=record.customer_node_id,
            request=request,
            transport_mode="汽运",
            unit_fee=unit_fee,
            total_fee=total,
            duration_hours=record.duration_hours,
            time_source=record.time_source,
            scope=record.scope,
            rule_id=RAIL_CONTAINER_DELIVERY_TRUCK_RULE.rule_id,
            rule_version=RAIL_CONTAINER_DELIVERY_TRUCK_RULE.rule_version,
            component_type="rail_terminal_direct_truck",
            component_detail="铁路南站至客户直达拖车单箱费用×订单箱数。",
            edge_role="delivery",
            distance_km=record.distance_km,
            distance_source=record.distance_source,
            time_scope="road_driving",
        )
        return RailCustomerDeliveryPlanResult("direct_truck", "resolved", "已形成铁路南站至客户直达拖车边。", (edge,))

    def build_customer_dedicated_siding(
        self, *, south_station_name: str, customer_name: str, request: RouteRequest, container_type: str
    ) -> RailCustomerDeliveryPlanResult:
        record = self._one_match(
            self.customer_dedicated_siding_records, south_station_name, customer_name, request, container_type, "customer_dedicated_siding"
        )
        if isinstance(record, RailCustomerDeliveryPlanResult):
            return record
        edge = _build_edge(
            origin_name=record.south_station_name,
            origin_node_id=record.south_station_node_id,
            destination_name=record.customer_name,
            destination_node_id=record.customer_node_id,
            request=request,
            transport_mode="铁路",
            unit_fee=record.unit_fee_yuan_per_box,
            total_fee=record.unit_fee_yuan_per_box * request.quantity,
            duration_hours=record.duration_hours,
            time_source=record.time_source,
            scope=record.scope,
            rule_id=RAIL_CUSTOMER_DEDICATED_SIDING_RULE_ID,
            rule_version=RAIL_TERMINAL_RULE_VERSION,
            component_type="customer_dedicated_siding_fee",
            component_detail="客户专用线单箱费用×订单箱数。",
            edge_role="delivery",
            time_scope="complete_segment",
        )
        return RailCustomerDeliveryPlanResult("customer_dedicated_siding", "resolved", "已形成南站至客户专用线交付边。", (edge,))

    def build_third_party_dedicated_siding(
        self, *, south_station_name: str, customer_name: str, request: RouteRequest, container_type: str
    ) -> RailCustomerDeliveryPlanResult:
        record = self._one_match(
            self.third_party_dedicated_siding_records, south_station_name, customer_name, request, container_type, "third_party_dedicated_siding"
        )
        if isinstance(record, RailCustomerDeliveryPlanResult):
            return record
        transfer = _build_edge(
            origin_name=record.south_station_name,
            origin_node_id=record.south_station_node_id,
            destination_name=record.third_party_name,
            destination_node_id=record.third_party_node_id,
            request=request,
            transport_mode="铁路",
            unit_fee=record.rail_unit_fee_yuan_per_box,
            total_fee=record.rail_unit_fee_yuan_per_box * request.quantity,
            duration_hours=record.rail_duration_hours,
            time_source=record.rail_time_source,
            scope=record.scope,
            rule_id=RAIL_THIRD_PARTY_DEDICATED_SIDING_RULE_ID,
            rule_version=RAIL_TERMINAL_RULE_VERSION,
            component_type="third_party_dedicated_siding_rail_fee",
            component_detail="南站至第三方专用线铁路单箱费用×订单箱数。",
            edge_role="transfer",
            time_scope="complete_segment",
        )
        delivery = _build_edge(
            origin_name=record.third_party_name,
            origin_node_id=record.third_party_node_id,
            destination_name=record.customer_name,
            destination_node_id=record.customer_node_id,
            request=request,
            transport_mode=record.delivery_transport_mode,
            unit_fee=record.delivery_unit_fee_yuan_per_box,
            total_fee=record.delivery_unit_fee_yuan_per_box * request.quantity,
            duration_hours=record.delivery_duration_hours,
            time_source=record.delivery_time_source,
            scope=record.scope,
            rule_id=RAIL_THIRD_PARTY_DEDICATED_SIDING_RULE_ID,
            rule_version=RAIL_TERMINAL_RULE_VERSION,
            component_type="third_party_siding_delivery_fee",
            component_detail="第三方专用线至客户交付单箱费用×订单箱数。",
            edge_role="delivery",
            time_scope="complete_segment" if record.delivery_transport_mode == "铁路" else "road_driving",
        )
        return RailCustomerDeliveryPlanResult(
            "third_party_dedicated_siding",
            "resolved",
            "已形成南站至第三方专用线中转及客户交付两条边。",
            (transfer, delivery),
        )

    def _one_match(self, records: Sequence[object], south_station_name: str, customer_name: str, request: RouteRequest, container_type: str, plan_type: Literal["direct_truck", "customer_dedicated_siding", "third_party_dedicated_siding"]) -> object | RailCustomerDeliveryPlanResult:
        if request.package_type != "集装箱" or request.quantity_unit != "箱":
            return RailCustomerDeliveryPlanResult(plan_type, "not_applicable", "铁路集装箱末端方案仅支持“集装箱/箱”订单；“柜”不得自动换算。")
        matches = [
            record for record in records
            if record.south_station_name == south_station_name
            and record.customer_name == customer_name
            and record.scope.supports(request, container_type)
        ]
        if not matches:
            return RailCustomerDeliveryPlanResult(plan_type, "manual_review", "未找到同时具备费用、完整时效和订单适用范围的末端方案记录；不构边。")
        if len(matches) != 1:
            return RailCustomerDeliveryPlanResult(plan_type, "manual_review", "末端方案记录无法唯一匹配，请人工确认后再构边。")
        return matches[0]


def _build_edge(
    *,
    origin_name: str,
    origin_node_id: str,
    destination_name: str,
    destination_node_id: str,
    request: RouteRequest,
    transport_mode: str,
    unit_fee: Decimal,
    total_fee: Decimal,
    duration_hours: Decimal,
    time_source: str,
    scope: RailTerminalScope,
    rule_id: str,
    rule_version: str,
    component_type: str,
    component_detail: str,
    edge_role: TransportEdgeRole,
    time_scope: Literal["complete_segment", "road_driving"],
    distance_km: Decimal | None = None,
    distance_source: str | None = None,
) -> TransportEdge:
    source = _source_reference(scope)
    rate = create_freight_rate(
        origin_name=origin_name,
        destination_name=destination_name,
        transport_mode=transport_mode,
        package_type="集装箱",
        commodity_scope="、".join(scope.commodity_scope),
        raw_price=unit_fee,
        raw_price_unit="元/箱",
        price_type="unit_price",
        price_source=source,
        from_node_id=origin_node_id,
        to_node_id=destination_node_id,
    )
    cost = CostCalculationResult(
        status="valid",
        total_cost_yuan=total_fee,
        rule_id=rule_id,
        rule_version=rule_version,
        calculation_detail=f"单箱费用={unit_fee}元/箱；订单={request.quantity}箱；总费用={total_fee}元。",
        price_source=source,
        transport_mode=transport_mode,
        rate_packaging="集装箱",
        price_unit="元/箱",
        message="已按维护的铁路集装箱末端方案记录计算费用。",
    )
    time = ShippingTimeResult(
        status="resolved",
        duration_hours=duration_hours,
        source=time_source,
        message="已使用维护的铁路集装箱末端方案完整时效。",
        stage=f"{origin_name}至{destination_name}",
        transport_mode=transport_mode,
        input_value=str(duration_hours),
        input_unit="小时",
        time_scope=time_scope,
    )
    source_type: CostSourceType = scope.source_type
    component = CostComponent(component_type, total_fee, source_type, source, rule_id, rule_version, component_detail)
    edge = build_transport_edge(
        rate,
        cost,
        time,
        commodity=request.commodity,
        distance_km=distance_km,
        distance_source=distance_source,
        data_source=source,
        transport_stage="south_to_customer",
        edge_role=edge_role,
        cost_components=(component,),
    )
    if not edge.is_available:
        raise RailCustomerDeliveryError(f"末端方案边未通过 TransportEdge 校验：{edge.unavailable_reason}")
    return edge


def _source_reference(scope: RailTerminalScope) -> str:
    return scope.source if scope.source_type == "real_data" else f"demo_placeholder:{scope.source}"


def _validate_endpoints(record: object, *fields: str) -> None:
    for field in fields:
        object.__setattr__(record, field, _required_text(getattr(record, field), field))


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise RailCustomerDeliveryError(f"{field_name}不能为空。")
    return text


def _positive_decimal(value: object, field_name: str) -> Decimal:
    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RailCustomerDeliveryError(f"{field_name}必须是有限数值。") from None
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise RailCustomerDeliveryError(f"{field_name}必须大于 0。")
    return decimal_value
