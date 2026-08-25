from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Literal, Protocol, Sequence

from src.domain.cost_rules import CostCalculationResult
from src.domain.freight_rate import create_freight_rate
from src.domain.route_request import RouteRequest
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_contracts import (
    CostComponent,
    TimeScope,
    TransportEdgeRole,
    TransportStage,
)
from src.routing.transport_edge import TransportEdge, build_transport_edge


InlandWaterwayStatus = Literal["generated", "not_applicable", "manual_review"]

DEMO_INLAND_WATERWAY_RULE_ID = "demo_placeholder_inland_barge_rate_time"
DEMO_INLAND_WATERWAY_RULE_VERSION = "0.1"
SUPPORTED_DEMO_INLAND_REGIONS = {"fujian_minjiang", "pearl_river_delta"}
MINJIANG_MAINTAINED_ENDPOINTS = frozenset({"南平港", "军航码头"})


class InlandWaterwayProviderError(ValueError):
    """Raised when inland-waterway interface records are internally inconsistent."""


@dataclass(frozen=True)
class InlandWaterwayTimeRecord:
    """One source-backed regional barge time rule independent of barge freight.

    Time and freight deliberately remain separate: a resolved time record does
    not authorize a searchable barge edge while the applicable freight is
    missing.
    """

    origin_region_code: str
    destination_region_code: str
    duration_value: Decimal
    duration_unit: str
    time_scope: TimeScope
    bidirectional: bool
    source_type: Literal["real_data", "demo_placeholder"]
    source: str
    rule_id: str
    rule_version: str
    maintained_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "origin_region_code",
            _required_text(self.origin_region_code, "驳船时效起点区域编码"),
        )
        object.__setattr__(
            self,
            "destination_region_code",
            _required_text(self.destination_region_code, "驳船时效终点区域编码"),
        )
        object.__setattr__(
            self,
            "duration_value",
            _positive_decimal(self.duration_value, "驳船运输时效"),
        )
        object.__setattr__(self, "duration_unit", _required_text(self.duration_unit, "驳船时效单位"))
        _ = self.duration_hours
        if self.time_scope != "complete_segment":
            raise InlandWaterwayProviderError(
                f"驳船运输时效在当前简化模型中必须是 complete_segment：{self.time_scope}"
            )
        if not isinstance(self.bidirectional, bool):
            raise InlandWaterwayProviderError("驳船时效双向标记必须是布尔值。")
        if self.source_type not in {"real_data", "demo_placeholder"}:
            raise InlandWaterwayProviderError(
                f"不支持的驳船时效来源类型：{self.source_type}"
            )
        object.__setattr__(self, "source", _required_text(self.source, "驳船时效来源"))
        object.__setattr__(self, "rule_id", _required_text(self.rule_id, "驳船时效规则编号"))
        object.__setattr__(
            self,
            "rule_version",
            _required_text(self.rule_version, "驳船时效规则版本"),
        )
        object.__setattr__(self, "maintained_at", _optional_text(self.maintained_at))

    @property
    def duration_hours(self) -> Decimal:
        unit = self.duration_unit.strip().lower()
        if unit in {"小时", "时", "hour", "hours", "h"}:
            return self.duration_value
        if unit in {"天", "日", "day", "days", "d"}:
            return self.duration_value * Decimal("24")
        raise InlandWaterwayProviderError(f"不支持的驳船时效单位：{self.duration_unit}")

    def matches(self, origin_region_code: str, destination_region_code: str) -> bool:
        origin = _required_text(origin_region_code, "请求起点区域编码")
        destination = _required_text(destination_region_code, "请求终点区域编码")
        if (
            origin == self.origin_region_code
            and destination == self.destination_region_code
        ):
            return True
        return (
            self.bidirectional
            and origin == self.destination_region_code
            and destination == self.origin_region_code
        )


class TableInlandWaterwayTimeProvider:
    """Resolve regional barge time without fabricating a corresponding fare."""

    def __init__(self, records: Sequence[InlandWaterwayTimeRecord]) -> None:
        self.records = tuple(records)

    def get_time(
        self,
        *,
        origin_region_code: str,
        destination_region_code: str,
        origin_name: str,
        destination_name: str,
    ) -> ShippingTimeResult:
        matches = [
            record
            for record in self.records
            if record.matches(origin_region_code, destination_region_code)
        ]
        stage = f"{_required_text(origin_name, '驳船起点名称')}至{_required_text(destination_name, '驳船终点名称')}"
        if not matches:
            return ShippingTimeResult(
                status="manual_review",
                duration_hours=None,
                source="inland_waterway_time_table",
                message=(
                    f"没有匹配 {origin_region_code} 至 {destination_region_code} "
                    "的驳船运输时效规则。"
                ),
                stage=stage,
                transport_mode="驳船",
                time_scope=None,
            )
        if len(matches) > 1:
            sources = "；".join(record.source for record in matches)
            return ShippingTimeResult(
                status="manual_review",
                duration_hours=None,
                source="inland_waterway_time_table",
                message=f"匹配到多条驳船运输时效规则，请人工去重：{sources}",
                stage=stage,
                transport_mode="驳船",
                time_scope=None,
            )

        record = matches[0]
        source = _source_ref(record.source_type, record.source)
        return ShippingTimeResult(
            status="resolved",
            duration_hours=record.duration_hours,
            source=source,
            message=(
                "采用区域映射驳船航运总时间，模型不拆分等待、装卸和航行组成；"
                "该结果只解决时效，不代表驳船航费已经具备。"
            ),
            stage=stage,
            transport_mode="驳船",
            input_value=str(record.duration_value),
            input_unit=record.duration_unit,
            time_scope=record.time_scope,
        )


@dataclass(frozen=True)
class PortCapabilityRecord:
    """Interface row for a future port capability table.

    The row describes what one physical node can handle. In production this should
    be keyed by standard node_id; the demo provider also accepts aliases so the
    interface can be exercised before the formal capability table is complete.
    """

    node_id: str | None
    canonical_name: str
    region_code: str | None
    can_handle_barge: bool | None
    supported_package_types: tuple[str, ...] | None
    supported_commodities: tuple[str, ...] | None
    source: str
    aliases: tuple[str, ...] = ()
    infrastructure_type: str = "unknown"
    can_receive_bulk_shipping: bool | None = None
    is_transfer_port: bool | None = None
    supported_transport_modes: tuple[str, ...] | None = None
    city: str | None = None
    shipping_time_region: str | None = None
    confirmation_status: Literal["confirmed", "manual_review"] = "manual_review"
    maintained_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _optional_text(self.node_id))
        object.__setattr__(self, "canonical_name", _required_text(self.canonical_name, "港口能力名称"))
        object.__setattr__(self, "region_code", _optional_text(self.region_code))
        object.__setattr__(self, "city", _optional_text(self.city))
        object.__setattr__(self, "shipping_time_region", _optional_text(self.shipping_time_region))
        object.__setattr__(self, "maintained_at", _optional_text(self.maintained_at))
        object.__setattr__(self, "source", _required_text(self.source, "港口能力来源"))
        object.__setattr__(
            self,
            "infrastructure_type",
            _required_text(self.infrastructure_type, "基础设施类型"),
        )
        object.__setattr__(
            self,
            "supported_package_types",
            _normalized_optional_text_tuple(self.supported_package_types, "港口支持包装方式"),
        )
        object.__setattr__(
            self,
            "supported_commodities",
            _normalized_optional_text_tuple(self.supported_commodities, "港口支持货物品种"),
        )
        object.__setattr__(
            self,
            "supported_transport_modes",
            _normalized_optional_text_tuple(self.supported_transport_modes, "港口支持运输方式"),
        )
        object.__setattr__(
            self,
            "aliases",
            _normalized_text_tuple(self.aliases, "港口能力别名", allow_empty=True),
        )
        if self.can_handle_barge is not None and not isinstance(self.can_handle_barge, bool):
            raise InlandWaterwayProviderError("can_handle_barge 必须是布尔值或 None。")
        if self.can_receive_bulk_shipping is not None and not isinstance(
            self.can_receive_bulk_shipping,
            bool,
        ):
            raise InlandWaterwayProviderError("can_receive_bulk_shipping 必须是布尔值或 None。")
        if self.is_transfer_port is not None and not isinstance(
            self.is_transfer_port,
            bool,
        ):
            raise InlandWaterwayProviderError("is_transfer_port 必须是布尔值或 None。")
        if self.confirmation_status not in {"confirmed", "manual_review"}:
            raise InlandWaterwayProviderError(
                f"不支持的港口能力确认状态：{self.confirmation_status}"
            )

    def matches(self, *, node_id: str | None, name: str) -> bool:
        normalized_id = _optional_text(node_id)
        if self.node_id is not None and normalized_id == self.node_id:
            return True
        normalized_name = _required_text(name, "地点名称")
        candidates = (self.canonical_name, *self.aliases)
        return any(candidate in normalized_name for candidate in candidates)

    def supports_order(self, request: RouteRequest) -> bool:
        return (
            self.can_handle_barge is True
            and self.supported_package_types is not None
            and self.supported_commodities is not None
            and request.package_type in self.supported_package_types
            and (
                request.commodity in self.supported_commodities
                or "*" in self.supported_commodities
            )
        )

    @property
    def capability_data_confirmed(self) -> bool:
        return (
            self.confirmation_status == "confirmed"
            and self.can_handle_barge is not None
            and self.can_receive_bulk_shipping is not None
            and self.supported_package_types is not None
            and self.supported_commodities is not None
            and self.supported_transport_modes is not None
        )

    @property
    def transfer_port_role_confirmed(self) -> bool:
        """Whether source-backed W3 data explicitly confirms transfer use."""

        return self.confirmation_status == "confirmed" and self.is_transfer_port is True


@dataclass(frozen=True)
class RegionMappingRecord:
    """Interface row for mapping nodes/cities to freight and time regions."""

    region_code: str
    region_name: str
    city_keywords: tuple[str, ...]
    port_keywords: tuple[str, ...]
    source: str
    bulk_rate_destination_group: str | None = None
    bulk_time_region: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_code", _required_text(self.region_code, "区域编码"))
        object.__setattr__(self, "region_name", _required_text(self.region_name, "区域名称"))
        object.__setattr__(self, "source", _required_text(self.source, "区域映射来源"))
        object.__setattr__(
            self,
            "city_keywords",
            _normalized_text_tuple(self.city_keywords, "区域城市关键词"),
        )
        object.__setattr__(
            self,
            "port_keywords",
            _normalized_text_tuple(self.port_keywords, "区域港口关键词"),
        )
        object.__setattr__(
            self,
            "bulk_rate_destination_group",
            _optional_text(self.bulk_rate_destination_group),
        )
        object.__setattr__(self, "bulk_time_region", _optional_text(self.bulk_time_region))

    def matches(self, name: str) -> bool:
        normalized_name = _required_text(name, "地点名称")
        return any(keyword in normalized_name for keyword in (*self.city_keywords, *self.port_keywords))


@dataclass(frozen=True)
class InlandWaterwayRateTimeRecord:
    """Interface row for inland-waterway barge fee and sailing-time data."""

    region_code: str
    package_type: str
    commodity_scope: tuple[str, ...]
    unit_rate_yuan_per_ton: Decimal
    duration_hours: Decimal
    source_type: Literal["real_data", "demo_placeholder"]
    source: str
    rule_id: str
    rule_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_code", _required_text(self.region_code, "内河航运区域编码"))
        object.__setattr__(self, "package_type", _required_text(self.package_type, "内河航运包装方式"))
        object.__setattr__(
            self,
            "commodity_scope",
            _normalized_text_tuple(self.commodity_scope, "内河航运货物范围"),
        )
        object.__setattr__(
            self,
            "unit_rate_yuan_per_ton",
            _positive_decimal(self.unit_rate_yuan_per_ton, "内河航运单价"),
        )
        object.__setattr__(
            self,
            "duration_hours",
            _positive_decimal(self.duration_hours, "内河航运航行时间"),
        )
        if self.source_type not in {"real_data", "demo_placeholder"}:
            raise InlandWaterwayProviderError(f"不支持的内河航运数据来源类型：{self.source_type}")
        object.__setattr__(self, "source", _required_text(self.source, "内河航运数据来源"))
        object.__setattr__(self, "rule_id", _required_text(self.rule_id, "内河航运规则编号"))
        object.__setattr__(self, "rule_version", _required_text(self.rule_version, "内河航运规则版本"))

    def supports_order(self, request: RouteRequest) -> bool:
        return (
            request.quantity_unit == "吨"
            and request.package_type == self.package_type
            and (request.commodity in self.commodity_scope or "*" in self.commodity_scope)
        )


@dataclass(frozen=True)
class InlandWaterwayEdgeResult:
    status: InlandWaterwayStatus
    message: str
    edge: TransportEdge | None = None
    region_code: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"generated", "not_applicable", "manual_review"}:
            raise InlandWaterwayProviderError(f"不支持的内河航运结果状态：{self.status}")
        object.__setattr__(self, "message", _required_text(self.message, "内河航运结果说明"))
        object.__setattr__(self, "region_code", _optional_text(self.region_code))
        object.__setattr__(
            self,
            "source_refs",
            _normalized_text_tuple(self.source_refs, "内河航运来源引用", allow_empty=True),
        )
        if self.status == "generated" and self.edge is None:
            raise InlandWaterwayProviderError("generated 结果必须包含 TransportEdge。")
        if self.status != "generated" and self.edge is not None:
            raise InlandWaterwayProviderError("非 generated 结果不得包含 TransportEdge。")

    @property
    def is_generated(self) -> bool:
        return self.status == "generated"


@dataclass(frozen=True)
class InlandWaterwayEndpointCandidate:
    """One capability-backed endpoint that the orchestration layer may register in a path.

    This is deliberately a node/capability reference rather than a fixed route
    template.  The caller still has to resolve the standard node and ask the
    Provider to build an applicable edge for the current origin and order.
    """

    node_id: str | None
    canonical_name: str
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _optional_text(self.node_id))
        object.__setattr__(
            self,
            "canonical_name",
            _required_text(self.canonical_name, "内河候选端点名称"),
        )
        object.__setattr__(self, "source", _required_text(self.source, "内河候选端点来源"))


class InlandWaterwayBargeProvider(Protocol):
    def list_destination_candidates(
        self,
        *,
        origin_node_id: str,
        origin_name: str,
        request: RouteRequest,
    ) -> tuple[InlandWaterwayEndpointCandidate, ...]:
        """Return capability-backed endpoints; it must not hard-code one demo path."""

    def build_barge_edge(
        self,
        *,
        origin_node_id: str,
        origin_name: str,
        destination_node_id: str,
        destination_name: str,
        request: RouteRequest,
        transport_stage: TransportStage = "south_to_customer",
        edge_role: TransportEdgeRole = "transfer",
    ) -> InlandWaterwayEdgeResult:
        """Build one barge edge when inland-waterway data is available and applicable."""


class DemoInlandWaterwayBargeProvider:
    """Minimal explicit placeholder provider for Fujian and Pearl Delta barge edges."""

    def __init__(
        self,
        *,
        port_capabilities: Sequence[PortCapabilityRecord] = (),
        region_mappings: Sequence[RegionMappingRecord] = (),
        rate_time_records: Sequence[InlandWaterwayRateTimeRecord] = (),
    ) -> None:
        self.port_capabilities = tuple(port_capabilities) or DEFAULT_PORT_CAPABILITY_RECORDS
        self.region_mappings = tuple(region_mappings) or DEFAULT_REGION_MAPPING_RECORDS
        self.rate_time_records = tuple(rate_time_records) or DEFAULT_INLAND_WATERWAY_RATE_TIME_RECORDS

    def list_destination_candidates(
        self,
        *,
        origin_node_id: str,
        origin_name: str,
        request: RouteRequest,
    ) -> tuple[InlandWaterwayEndpointCandidate, ...]:
        return list_capability_backed_destinations(
            port_capabilities=self.port_capabilities,
            region_mappings=self.region_mappings,
            origin_node_id=origin_node_id,
            origin_name=origin_name,
            request=request,
        )

    def build_barge_edge(
        self,
        *,
        origin_node_id: str,
        origin_name: str,
        destination_node_id: str,
        destination_name: str,
        request: RouteRequest,
        transport_stage: TransportStage = "south_to_customer",
        edge_role: TransportEdgeRole = "transfer",
    ) -> InlandWaterwayEdgeResult:
        origin_region = self._match_region(origin_name)
        destination_region = self._match_region(destination_name)
        if origin_region is None or destination_region is None:
            return self._not_applicable("仅福建闽江和珠三角内河航运场景生成 demo_placeholder 驳船边；本次起终点未同时匹配到支持区域。")
        if origin_region.region_code != destination_region.region_code:
            return self._not_applicable("起点和终点不属于同一内河航运区域，demo_placeholder 驳船边不生成。")
        if origin_region.region_code not in SUPPORTED_DEMO_INLAND_REGIONS:
            return self._not_applicable("当前 Demo Provider 仅支持福建闽江和珠三角内河航运区域。")
        if not is_maintained_inland_waterway_pair(
            origin_region_code=origin_region.region_code,
            destination_region_code=destination_region.region_code,
            origin_name=origin_name,
            destination_name=destination_name,
        ):
            return self._not_applicable(
                "当前闽江航线只维护南平港与军航码头双向运输，其他闽江端点组合不生成驳船边。"
            )

        origin_capability = self._match_capability(
            node_id=origin_node_id,
            name=origin_name,
            region_code=origin_region.region_code,
        )
        destination_capability = self._match_capability(
            node_id=destination_node_id,
            name=destination_name,
            region_code=destination_region.region_code,
        )
        if origin_capability is None or destination_capability is None:
            return self._not_applicable("港口能力表未确认起终点均可形成内河驳船段，demo_placeholder 驳船边不生成。")
        if edge_role == "transfer" and destination_capability.is_transfer_port is not True:
            return self._not_applicable(
                f"节点 {destination_name} 未标记为中转港，demo_placeholder 驳船中转边不生成。"
            )
        if not origin_capability.supports_order(request) or not destination_capability.supports_order(request):
            return self._not_applicable("港口能力表显示起终点不同时支持当前订单包装/品种的驳船作业。")

        rate_time = self._match_rate_time(origin_region.region_code, request)
        if rate_time is None:
            return self._not_applicable("内河航运航费/航时表没有匹配当前订单的记录，驳船边不生成。")

        total_cost = rate_time.unit_rate_yuan_per_ton * Decimal(str(request.quantity))
        price_source = _source_ref(rate_time.source_type, rate_time.source)
        rate = create_freight_rate(
            origin_name=origin_name,
            destination_name=destination_name,
            transport_mode="驳船",
            package_type=request.package_type,
            commodity_scope=request.commodity,
            raw_price=rate_time.unit_rate_yuan_per_ton,
            raw_price_unit="元/吨",
            price_type="unit_price",
            price_source=price_source,
            from_node_id=origin_node_id,
            to_node_id=destination_node_id,
            source_file=rate_time.source,
        )
        cost_result = CostCalculationResult(
            status="valid",
            total_cost_yuan=total_cost,
            rule_id=rate_time.rule_id,
            rule_version=rate_time.rule_version,
            calculation_detail=(
                f"demo_placeholder 内河驳船：{rate_time.unit_rate_yuan_per_ton}元/吨×"
                f"{request.quantity}{request.quantity_unit}={total_cost}元；"
                f"区域={origin_region.region_name}。"
            ),
            price_source=price_source,
            transport_mode="驳船",
            rate_packaging=request.package_type,
            price_unit="元/吨",
            message="已生成明确标记的 demo_placeholder 内河驳船航费。",
        )
        time_result = ShippingTimeResult(
            status="resolved",
            duration_hours=rate_time.duration_hours,
            source=price_source,
            message=(
                "已生成明确标记的 demo_placeholder 内河驳船航运总时间；"
                "当前简化模型不拆分等待、装卸和航行组成。"
            ),
            stage=f"{origin_name}至{destination_name}",
            transport_mode="驳船",
            input_value=str(rate_time.duration_hours),
            input_unit="小时",
            time_scope="complete_segment",
        )
        cost_component = CostComponent(
            component_type="barge_freight",
            amount_yuan=total_cost,
            source_type=rate_time.source_type,
            source=rate_time.source,
            rule_id=rate_time.rule_id,
            rule_version=rate_time.rule_version,
            calculation_detail=cost_result.calculation_detail,
        )
        edge = build_transport_edge(
            rate,
            cost_result,
            time_result,
            commodity=request.commodity,
            data_source=price_source,
            transport_stage=transport_stage,
            edge_role=edge_role,
            cost_components=(cost_component,),
        )
        if not edge.is_available:
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=f"内河驳船 demo_placeholder 边未通过 TransportEdge 校验：{edge.unavailable_reason}",
                region_code=origin_region.region_code,
                source_refs=(origin_region.source, origin_capability.source, destination_capability.source, rate_time.source),
            )
        return InlandWaterwayEdgeResult(
            status="generated",
            edge=edge,
            message="已生成明确 demo_placeholder 内河驳船边。",
            region_code=origin_region.region_code,
            source_refs=(origin_region.source, origin_capability.source, destination_capability.source, rate_time.source),
        )

    def _match_region(self, name: str) -> RegionMappingRecord | None:
        matches = [record for record in self.region_mappings if record.matches(name)]
        if len(matches) != 1:
            return None
        return matches[0]

    def _match_capability(
        self,
        *,
        node_id: str | None,
        name: str,
        region_code: str,
    ) -> PortCapabilityRecord | None:
        matches = [
            record
            for record in self.port_capabilities
            if record.region_code == region_code and record.matches(node_id=node_id, name=name)
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def _match_rate_time(
        self,
        region_code: str,
        request: RouteRequest,
    ) -> InlandWaterwayRateTimeRecord | None:
        matches = [
            record
            for record in self.rate_time_records
            if record.source_type == "demo_placeholder"
            and record.region_code == region_code
            and record.supports_order(request)
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    @staticmethod
    def _not_applicable(message: str) -> InlandWaterwayEdgeResult:
        return InlandWaterwayEdgeResult(status="not_applicable", edge=None, message=message)


def is_maintained_inland_waterway_pair(
    *,
    origin_region_code: str,
    destination_region_code: str,
    origin_name: str,
    destination_name: str,
) -> bool:
    """Apply the explicitly maintained endpoint boundary for the Min River."""

    if "fujian_minjiang" not in {
        origin_region_code,
        destination_region_code,
    }:
        return True
    if origin_region_code != "fujian_minjiang" or destination_region_code != "fujian_minjiang":
        return False
    endpoints = {
        _canonical_minjiang_endpoint(origin_name),
        _canonical_minjiang_endpoint(destination_name),
    }
    return None not in endpoints and endpoints == MINJIANG_MAINTAINED_ENDPOINTS


def list_capability_backed_destinations(
    *,
    port_capabilities: Sequence[PortCapabilityRecord],
    region_mappings: Sequence[RegionMappingRecord],
    origin_node_id: str,
    origin_name: str,
    request: RouteRequest,
) -> tuple[InlandWaterwayEndpointCandidate, ...]:
    """List data-driven barge endpoints without asserting that an edge is usable."""

    origin_regions = [record for record in region_mappings if record.matches(origin_name)]
    if len(origin_regions) != 1:
        return ()
    origin_region = origin_regions[0]

    candidates: list[InlandWaterwayEndpointCandidate] = []
    seen: set[tuple[str | None, str]] = set()
    for capability in port_capabilities:
        if capability.matches(node_id=origin_node_id, name=origin_name):
            continue
        if (
            capability.region_code is None
            or capability.is_transfer_port is not True
            or not capability.supports_order(request)
        ):
            continue
        if not is_maintained_inland_waterway_pair(
            origin_region_code=origin_region.region_code,
            destination_region_code=capability.region_code,
            origin_name=origin_name,
            destination_name=capability.canonical_name,
        ):
            continue
        key = (capability.node_id, capability.canonical_name)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            InlandWaterwayEndpointCandidate(
                node_id=capability.node_id,
                canonical_name=capability.canonical_name,
                source=capability.source,
            )
        )
    return tuple(candidates)


def _canonical_minjiang_endpoint(name: str) -> str | None:
    normalized = re.sub(r"\s+", "", str(name).strip())
    if normalized == "南平港":
        return "南平港"
    if normalized in {"军航码头", "福建军航码头"}:
        return "军航码头"
    return None


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise InlandWaterwayProviderError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_text_tuple(
    values: Sequence[object],
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    try:
        normalized = tuple(_required_text(value, field_name) for value in values)
    except TypeError:
        raise InlandWaterwayProviderError(f"{field_name}必须是可迭代文本。") from None
    if not normalized and not allow_empty:
        raise InlandWaterwayProviderError(f"{field_name}不能为空。")
    return tuple(dict.fromkeys(normalized))


def _normalized_optional_text_tuple(
    values: Sequence[object] | None,
    field_name: str,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    return _normalized_text_tuple(values, field_name, allow_empty=True)


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise InlandWaterwayProviderError(f"{field_name}必须是大于 0 的有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise InlandWaterwayProviderError(f"{field_name}必须是大于 0 的有限数值。") from None
    if not number.is_finite() or number <= 0:
        raise InlandWaterwayProviderError(f"{field_name}必须是大于 0 的有限数值。")
    return number


def _source_ref(source_type: str, source: str) -> str:
    normalized_source = _required_text(source, "来源")
    prefix = f"{source_type}:"
    return normalized_source if normalized_source.startswith(prefix) else f"{prefix}{normalized_source}"


DEFAULT_REGION_MAPPING_RECORDS = (
    RegionMappingRecord(
        region_code="fujian_minjiang",
        region_name="福建闽江内河",
        city_keywords=("南平港", "军航码头"),
        port_keywords=("南平港", "军航码头"),
        bulk_rate_destination_group="马尾",
        bulk_time_region="福建",
        source="business_confirmation_2026-07-29",
    ),
    RegionMappingRecord(
        region_code="pearl_river_delta",
        region_name="珠三角内河",
        city_keywords=("广州", "深圳", "东莞", "佛山", "肇庆", "江门", "中山", "珠海"),
        port_keywords=(
            "广州新港",
            "黄埔",
            "深圳蛇口",
            "蛇口",
            "东莞新沙",
            "新沙",
            "麻涌",
            "佛山",
            "肇庆",
            "江门",
            "中山",
            "珠海",
        ),
        bulk_rate_destination_group="珠三角",
        bulk_time_region="珠三角",
        source="demo_placeholder:region_mapping:pearl_river_delta",
    ),
)

DEFAULT_PORT_CAPABILITY_RECORDS = (
    PortCapabilityRecord(
        node_id=None,
        canonical_name="南平港",
        region_code="fujian_minjiang",
        can_handle_barge=True,
        supported_package_types=("散粮", "集装箱"),
        supported_commodities=("玉米", "小麦"),
        source="business_confirmation_2026-07-29",
        aliases=(),
        infrastructure_type="inland_port",
        can_receive_bulk_shipping=False,
        is_transfer_port=True,
        supported_transport_modes=("驳船", "铁路"),
        city="南平",
        shipping_time_region=None,
        confirmation_status="confirmed",
        maintained_at="2026-07-29",
    ),
    PortCapabilityRecord(
        node_id=None,
        canonical_name="军航码头",
        region_code="fujian_minjiang",
        can_handle_barge=True,
        supported_package_types=("散粮",),
        supported_commodities=("玉米", "小麦"),
        source="business_confirmation_2026-07-29",
        aliases=(),
        infrastructure_type="sea_river_integrated_port",
        can_receive_bulk_shipping=True,
        is_transfer_port=True,
        supported_transport_modes=("散船", "驳船"),
        city="福州",
        shipping_time_region="福建",
        confirmation_status="confirmed",
        maintained_at="2026-07-29",
    ),
    PortCapabilityRecord(
        node_id=None,
        canonical_name="珠三角内河 Demo 能力",
        region_code="pearl_river_delta",
        can_handle_barge=True,
        supported_package_types=("散粮",),
        supported_commodities=("*",),
        source="demo_placeholder:port_capability:pearl_river_delta",
        aliases=(
            "广州",
            "深圳",
            "东莞",
            "佛山",
            "肇庆",
            "江门",
            "中山",
            "珠海",
            "黄埔",
            "蛇口",
            "新沙",
            "麻涌",
        ),
        infrastructure_type="sea_river_integrated_port_or_customer_terminal",
        can_receive_bulk_shipping=True,
        is_transfer_port=True,
    ),
)

DEFAULT_INLAND_WATERWAY_RATE_TIME_RECORDS = (
    InlandWaterwayRateTimeRecord(
        region_code="fujian_minjiang",
        package_type="散粮",
        commodity_scope=("*",),
        unit_rate_yuan_per_ton=Decimal("12"),
        duration_hours=Decimal("8"),
        source_type="demo_placeholder",
        source="demo_placeholder:inland_barge_rate_time:fujian_minjiang",
        rule_id=DEMO_INLAND_WATERWAY_RULE_ID,
        rule_version=DEMO_INLAND_WATERWAY_RULE_VERSION,
    ),
    InlandWaterwayRateTimeRecord(
        region_code="pearl_river_delta",
        package_type="散粮",
        commodity_scope=("*",),
        unit_rate_yuan_per_ton=Decimal("10"),
        duration_hours=Decimal("6"),
        source_type="demo_placeholder",
        source="demo_placeholder:inland_barge_rate_time:pearl_river_delta",
        rule_id=DEMO_INLAND_WATERWAY_RULE_ID,
        rule_version=DEMO_INLAND_WATERWAY_RULE_VERSION,
    ),
)
