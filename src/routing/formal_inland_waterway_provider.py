from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.data.node_master_capabilities import is_barge_rate
from src.domain.cost_rules import (
    DEFAULT_COST_RULE_ENGINE,
    CostCalculationResult,
)
from src.domain.freight_rate import FreightRate, create_freight_rate
from src.domain.latest_rate_selector import (
    LatestRateSelectionIssue,
    select_latest_freight_rates,
)
from src.domain.route_request import RouteRequest
from src.routing.inland_waterway_freight_provider import (
    InlandWaterwayFreightRecord,
    TableInlandWaterwayFreightProvider,
)
from src.routing.inland_waterway_provider import (
    InlandWaterwayEdgeResult,
    InlandWaterwayBargeProvider,
    InlandWaterwayEndpointCandidate,
    InlandWaterwayTimeRecord,
    PortCapabilityRecord,
    RegionMappingRecord,
    TableInlandWaterwayTimeProvider,
    is_maintained_inland_waterway_pair,
    list_capability_backed_destinations,
)
from src.routing.transport_contracts import (
    CostComponent,
    TransportEdgeRole,
    TransportStage,
)
from src.routing.transport_edge import build_transport_edge


@dataclass(frozen=True)
class InlandWaterwayEndpointResolution:
    status: str
    message: str
    region: RegionMappingRecord | None = None
    capability: PortCapabilityRecord | None = None

    @property
    def is_resolved(self) -> bool:
        return (
            self.status == "resolved"
            and self.region is not None
            and self.capability is not None
        )


class TableInlandWaterwayBargeProvider:
    """Build source-backed barge edges from storage-independent records.

    The provider deliberately consumes typed records instead of opening local
    files itself. A future database adapter can therefore return the same
    records without changing routing or graph code.
    """

    def __init__(
        self,
        *,
        port_capabilities: Sequence[PortCapabilityRecord],
        region_mappings: Sequence[RegionMappingRecord],
        freight_records: Sequence[InlandWaterwayFreightRecord],
        time_records: Sequence[InlandWaterwayTimeRecord],
        allow_placeholder_capabilities: bool = False,
    ) -> None:
        self.port_capabilities = tuple(port_capabilities)
        self.region_mappings = tuple(region_mappings)
        self.freight_provider = TableInlandWaterwayFreightProvider(freight_records)
        self.time_provider = TableInlandWaterwayTimeProvider(time_records)
        self.allow_placeholder_capabilities = allow_placeholder_capabilities

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
        origin = self._resolve_endpoint(
            node_id=origin_node_id,
            name=origin_name,
            request=request,
        )
        destination = self._resolve_endpoint(
            node_id=destination_node_id,
            name=destination_name,
            request=request,
        )
        if not origin.is_resolved or not destination.is_resolved:
            messages = "；".join(
                resolution.message
                for resolution in (origin, destination)
                if not resolution.is_resolved
            )
            status = (
                "manual_review"
                if "manual_review" in {origin.status, destination.status}
                else "not_applicable"
            )
            return InlandWaterwayEdgeResult(
                status=status,
                edge=None,
                message=(
                    f"驳船端点能力或区域尚未确认：{messages}"
                    if status == "manual_review"
                    else f"起终点不属于当前已维护驳船区域：{messages}"
                ),
            )

        assert origin.region is not None
        assert destination.region is not None
        assert origin.capability is not None
        assert destination.capability is not None
        if (
            edge_role == "transfer"
            and destination.capability.is_transfer_port is not True
        ):
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=(
                    f"节点 {destination_name} 尚未确认中转港功能角色，"
                    "不能作为第二业务段驳船中转边终点。"
                ),
                region_code=origin.region.region_code,
                source_refs=(
                    origin.capability.source,
                    destination.capability.source,
                ),
            )
        if not is_maintained_inland_waterway_pair(
            origin_region_code=origin.region.region_code,
            destination_region_code=destination.region.region_code,
            origin_name=origin_name,
            destination_name=destination_name,
        ):
            return InlandWaterwayEdgeResult(
                status="not_applicable",
                edge=None,
                message=(
                    "当前闽江航线只维护南平港与军航码头双向运输，"
                    "其他闽江端点组合不生成驳船边。"
                ),
                region_code=origin.region.region_code,
                source_refs=(
                    origin.region.source,
                    destination.region.source,
                    origin.capability.source,
                    destination.capability.source,
                ),
            )
        freight = self.freight_provider.quote(
            origin_region_code=origin.region.region_code,
            destination_region_code=destination.region.region_code,
            request=request,
        )
        if not freight.is_resolved or freight.record is None:
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=freight.message,
                region_code=origin.region.region_code,
                source_refs=(
                    origin.region.source,
                    destination.region.source,
                    origin.capability.source,
                    destination.capability.source,
                ),
            )

        time = self.time_provider.get_time(
            origin_region_code=origin.region.region_code,
            destination_region_code=destination.region.region_code,
            origin_name=origin_name,
            destination_name=destination_name,
        )
        if not time.is_resolved or time.duration_hours is None:
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=time.message,
                region_code=origin.region.region_code,
                source_refs=(
                    freight.record.source,
                    origin.region.source,
                    destination.region.source,
                ),
            )

        total_cost = freight.total_cost_yuan
        if total_cost is None:
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message="驳船费率已匹配但缺少可计入总费用的金额。",
            )
        rate_record = freight.record
        rate = create_freight_rate(
            origin_name=origin_name,
            destination_name=destination_name,
            transport_mode="驳船",
            package_type=request.package_type,
            commodity_scope=request.commodity,
            raw_price=rate_record.unit_price_yuan_per_ton,
            raw_price_unit=rate_record.fee_unit,
            price_type="unit_price",
            price_source=rate_record.source_ref,
            from_node_id=origin_node_id,
            to_node_id=destination_node_id,
            source_file=rate_record.source,
        )
        capability_trace = self._capability_trace(
            origin.capability,
            destination.capability,
        )
        calculation_detail = (
            f"内河驳船：{rate_record.unit_price_yuan_per_ton}元/吨×"
            f"{request.quantity}{request.quantity_unit}={total_cost}元；"
            f"区域={origin.region.region_code}->{destination.region.region_code}；"
            f"来源={rate_record.source_ref}；{capability_trace}"
        )
        cost_result = CostCalculationResult(
            status="valid",
            total_cost_yuan=total_cost,
            rule_id=rate_record.rule_id,
            rule_version=rate_record.rule_version,
            calculation_detail=calculation_detail,
            price_source=rate_record.source_ref,
            transport_mode="驳船",
            rate_packaging=request.package_type,
            price_unit=rate_record.fee_unit,
            message="已按正式驳船费率计算南港至客户码头运输费用。",
        )
        component = CostComponent(
            component_type="barge_freight",
            amount_yuan=total_cost,
            source_type=rate_record.source_type,
            source=rate_record.source_ref,
            rule_id=rate_record.rule_id,
            rule_version=rate_record.rule_version,
            calculation_detail=calculation_detail,
        )
        edge = build_transport_edge(
            rate,
            cost_result,
            time,
            commodity=request.commodity,
            data_source=(
                f"{rate_record.source_ref};time={time.source};"
                f"capability={capability_trace}"
            ),
            transport_stage=transport_stage,
            edge_role=edge_role,
            cost_components=(component,),
        )
        if not edge.is_available:
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=f"驳船边未通过 TransportEdge 校验：{edge.unavailable_reason}",
                region_code=origin.region.region_code,
            )
        source_refs = (
            origin.region.source,
            destination.region.source,
            origin.capability.source,
            destination.capability.source,
            rate_record.source_ref,
            time.source,
        )
        placeholder_capability = any(
            capability.source.startswith("demo_placeholder:")
            for capability in (origin.capability, destination.capability)
        )
        message = "已生成可搜索驳船边。"
        if placeholder_capability:
            message += (
                "费率和航时来自已确认业务数据；港口/客户驳船能力仍为 "
                "demo_placeholder，展示时必须保留该边界说明。"
            )
        return InlandWaterwayEdgeResult(
            status="generated",
            edge=edge,
            message=message,
            region_code=origin.region.region_code,
            source_refs=source_refs,
        )

    def _resolve_endpoint(
        self,
        *,
        node_id: str,
        name: str,
        request: RouteRequest,
    ) -> InlandWaterwayEndpointResolution:
        regions = [record for record in self.region_mappings if record.matches(name)]
        if len(regions) != 1:
            return InlandWaterwayEndpointResolution(
                status="not_applicable" if not regions else "manual_review",
                message=(
                    f"节点 {name} "
                    + ("未匹配区域" if not regions else "同时匹配多个区域")
                ),
            )
        region = regions[0]
        matching_capabilities = [
            record
            for record in self.port_capabilities
            if record.region_code == region.region_code
            and record.matches(node_id=node_id, name=name)
            and record.supports_order(request)
        ]
        if len(matching_capabilities) != 1:
            return InlandWaterwayEndpointResolution(
                status="manual_review",
                message=(
                    f"节点 {name} "
                    + (
                        "未匹配唯一港口/客户码头能力记录"
                        if not matching_capabilities
                        else "匹配到多条港口/客户码头能力记录"
                    )
                ),
            )
        capability = matching_capabilities[0]
        if (
            not self.allow_placeholder_capabilities
            and not capability.capability_data_confirmed
        ):
            return InlandWaterwayEndpointResolution(
                status="manual_review",
                message=f"节点 {name} 的驳船能力尚未正式确认",
            )
        return InlandWaterwayEndpointResolution(
            status="resolved",
            message=f"节点 {name} 已匹配区域和驳船能力。",
            region=region,
            capability=capability,
        )

    @staticmethod
    def _capability_trace(
        origin: PortCapabilityRecord,
        destination: PortCapabilityRecord,
    ) -> str:
        return (
            f"起点能力来源={origin.source}；"
            f"终点能力来源={destination.source}"
        )


class ExactOdInlandWaterwayBargeProvider:
    """Prefer exact maintained OD barge rates over regional freight proxies.

    The formal storage adapter remains outside this provider. The loader
    supplies typed `FreightRate` records from the preferred maintained workbook
    or the JSON compatibility source, so a future database adapter can provide
    the same contract without changing graph construction.
    """

    supports_direct_delivery = True

    def __init__(
        self,
        *,
        port_capabilities: Sequence[PortCapabilityRecord],
        exact_od_rates: Sequence[FreightRate],
        time_records: Sequence[InlandWaterwayTimeRecord],
        fallback_provider: InlandWaterwayBargeProvider | None = None,
    ) -> None:
        self.port_capabilities = tuple(port_capabilities)
        self.exact_od_rates = tuple(
            rate for rate in exact_od_rates if is_barge_rate(rate)
        )
        selection = select_latest_freight_rates(self.exact_od_rates)
        self.selected_rates = selection.selected_rates
        self.review_issues = selection.review_issues
        self.superseded_rate_count = selection.superseded_rate_count
        self.duplicate_rate_count = selection.duplicate_rate_count
        self.defaulted_date_count = selection.defaulted_date_count
        self.time_provider = TableInlandWaterwayTimeProvider(time_records)
        self.fallback_provider = fallback_provider

    def list_destination_candidates(
        self,
        *,
        origin_node_id: str,
        origin_name: str,
        request: RouteRequest,
    ) -> tuple[InlandWaterwayEndpointCandidate, ...]:
        if request.trade_type != "内贸":
            return ()
        candidates: list[InlandWaterwayEndpointCandidate] = []
        seen_node_ids: set[str] = set()
        for rate in self.selected_rates:
            if (
                rate.from_node_id != origin_node_id
                or rate.to_node_id is None
                or not _rate_supports_request(rate, request)
            ):
                continue
            capability = self._find_capability(
                node_id=rate.to_node_id,
                name=rate.destination_name,
                request=request,
            )
            if (
                capability is None
                or capability.is_transfer_port is not True
                or not capability.capability_data_confirmed
                or rate.to_node_id in seen_node_ids
            ):
                continue
            seen_node_ids.add(rate.to_node_id)
            candidates.append(
                InlandWaterwayEndpointCandidate(
                    node_id=rate.to_node_id,
                    canonical_name=capability.canonical_name,
                    source=(
                        f"{capability.source};"
                        f"{_exact_rate_source(rate)}"
                    ),
                )
            )

        for issue in self.review_issues:
            conflicting_rates = [
                rate
                for rate in issue.rates
                if rate.from_node_id == origin_node_id
                and rate.to_node_id is not None
                and _rate_supports_request(rate, request)
            ]
            if not conflicting_rates:
                continue
            rate = conflicting_rates[0]
            assert rate.to_node_id is not None
            capability = self._find_capability(
                node_id=rate.to_node_id,
                name=rate.destination_name,
                request=request,
            )
            if (
                capability is None
                or capability.is_transfer_port is not True
                or rate.to_node_id in seen_node_ids
            ):
                continue
            seen_node_ids.add(rate.to_node_id)
            candidates.append(
                InlandWaterwayEndpointCandidate(
                    node_id=rate.to_node_id,
                    canonical_name=capability.canonical_name,
                    source=(
                        f"{capability.source};manual_review:"
                        f"{issue.code}"
                    ),
                )
            )

        if self.fallback_provider is not None:
            for candidate in self.fallback_provider.list_destination_candidates(
                origin_node_id=origin_node_id,
                origin_name=origin_name,
                request=request,
            ):
                if candidate.node_id is None:
                    continue
                if candidate.node_id in seen_node_ids:
                    continue
                if self._has_any_exact_od_rate(
                    origin_node_id=origin_node_id,
                    destination_node_id=candidate.node_id,
                ):
                    continue
                seen_node_ids.add(candidate.node_id)
                candidates.append(candidate)
        return tuple(candidates)

    def applicable_origin_node_ids(
        self,
        request: RouteRequest,
    ) -> frozenset[str]:
        """Return South-port origins with at least one buildable exact OD option."""

        if request.trade_type != "内贸":
            return frozenset()
        result: set[str] = set()
        for rate in self.selected_rates:
            if (
                rate.from_node_id is None
                or rate.to_node_id is None
                or not _rate_supports_request(rate, request)
            ):
                continue
            origin_capability = self._find_capability(
                node_id=rate.from_node_id,
                name=rate.origin_name,
                request=request,
            )
            destination_capability = self._find_capability(
                node_id=rate.to_node_id,
                name=rate.destination_name,
                request=request,
            )
            if (
                origin_capability is not None
                and destination_capability is not None
            ):
                edge_role: TransportEdgeRole
                if destination_capability.is_transfer_port is True:
                    edge_role = "transfer"
                elif (
                    destination_capability.infrastructure_type
                    == "customer_barge_receiver"
                ):
                    edge_role = "delivery"
                else:
                    continue
                edge_result = self.build_barge_edge(
                    origin_node_id=rate.from_node_id,
                    origin_name=rate.origin_name,
                    destination_node_id=rate.to_node_id,
                    destination_name=rate.destination_name,
                    request=request,
                    edge_role=edge_role,
                )
                if edge_result.is_generated:
                    result.add(rate.from_node_id)
        return frozenset(result)

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
        exact_od_rates = self._exact_od_rates(
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
        )
        if not exact_od_rates:
            if self.fallback_provider is not None and edge_role == "transfer":
                return self.fallback_provider.build_barge_edge(
                    origin_node_id=origin_node_id,
                    origin_name=origin_name,
                    destination_node_id=destination_node_id,
                    destination_name=destination_name,
                    request=request,
                    transport_stage=transport_stage,
                    edge_role=edge_role,
                )
            return InlandWaterwayEdgeResult(
                status="not_applicable",
                edge=None,
                message=(
                    f"正式精确 OD 运价源未维护 {origin_name} 至 {destination_name} "
                    "的精确 OD 驳船运价。"
                ),
            )
        if request.trade_type != "内贸":
            return InlandWaterwayEdgeResult(
                status="not_applicable",
                edge=None,
                message=(
                    "当前正式精确 OD 驳船记录未维护 tradeType；"
                    "本阶段只按已确认内贸口径使用，不推断外贸适用性。"
                ),
            )

        conflicts = self._matching_conflicts(
            exact_od_rates=exact_od_rates,
            request=request,
        )
        if conflicts:
            sources = "；".join(
                _exact_rate_source(rate)
                for issue in conflicts
                for rate in issue.rates
            )
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=(
                    "正式精确 OD 运价源的该路线在同一最新维护日存在冲突报价，"
                    f"不以区域费率覆盖：{sources}"
                ),
                source_refs=tuple(
                    _exact_rate_source(rate)
                    for issue in conflicts
                    for rate in issue.rates
                ),
            )

        matching_rates = [
            rate
            for rate in self.selected_rates
            if rate in exact_od_rates and _rate_supports_request(rate, request)
        ]
        if not matching_rates:
            return InlandWaterwayEdgeResult(
                status="not_applicable",
                edge=None,
                message=(
                    f"{origin_name} 至 {destination_name} 存在精确驳船运价，"
                    f"但不适用 {request.package_type}/{request.commodity}；"
                    "不回退到区域费率。"
                ),
            )
        if len(matching_rates) > 1:
            sources = "；".join(
                _exact_rate_source(rate) for rate in matching_rates
            )
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=(
                    "同一订单匹配到多条不同业务范围的最新精确 OD 驳船运价，"
                    f"需要人工确认：{sources}"
                ),
                source_refs=tuple(
                    _exact_rate_source(rate) for rate in matching_rates
                ),
            )

        origin_capability = self._find_capability(
            node_id=origin_node_id,
            name=origin_name,
            request=request,
        )
        destination_capability = self._find_capability(
            node_id=destination_node_id,
            name=destination_name,
            request=request,
        )
        if origin_capability is None or destination_capability is None:
            missing = [
                name
                for name, capability in (
                    (origin_name, origin_capability),
                    (destination_name, destination_capability),
                )
                if capability is None
            ]
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=(
                    "精确 OD 运价已存在，但端点缺少适用于本订单的能力/区域记录："
                    + "、".join(missing)
                ),
            )
        if (
            edge_role == "transfer"
            and destination_capability.is_transfer_port is not True
        ):
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=(
                    f"节点 {destination_name} 虽有精确驳船运价，"
                    "但不是已确认内河/河海一体中转港，不能作为中转边终点。"
                ),
                source_refs=(
                    origin_capability.source,
                    destination_capability.source,
                ),
            )
        if (
            origin_capability.region_code is None
            or destination_capability.region_code is None
        ):
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message="精确 OD 运价已存在，但端点尚未完成内河时效区域映射。",
            )
        if not is_maintained_inland_waterway_pair(
            origin_region_code=origin_capability.region_code,
            destination_region_code=destination_capability.region_code,
            origin_name=origin_name,
            destination_name=destination_name,
        ):
            return InlandWaterwayEdgeResult(
                status="not_applicable",
                edge=None,
                message=(
                    "当前闽江航线只维护南平港与军航码头双向运输，"
                    "其他闽江端点组合不生成驳船边。"
                ),
            )

        rate = matching_rates[0]
        cost_result = DEFAULT_COST_RULE_ENGINE.evaluate_freight_rate(
            rate, request
        )
        if (
            cost_result.status != "valid"
            or cost_result.total_cost_yuan is None
        ):
            return InlandWaterwayEdgeResult(
                status=(
                    "not_applicable"
                    if cost_result.status == "not_applicable"
                    else "manual_review"
                ),
                edge=None,
                message=(
                    "精确 OD 驳船运价无法计算当前订单总费用："
                    f"{cost_result.message}"
                ),
                source_refs=(_exact_rate_source(rate),),
            )
        time = self.time_provider.get_time(
            origin_region_code=origin_capability.region_code,
            destination_region_code=destination_capability.region_code,
            origin_name=origin_name,
            destination_name=destination_name,
        )
        if not time.is_resolved or time.duration_hours is None:
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=(
                    "精确 OD 驳船运价已可计费，但缺少适用的区域航运总时效："
                    f"{time.message}"
                ),
                region_code=origin_capability.region_code,
                source_refs=(
                    _exact_rate_source(rate),
                    origin_capability.source,
                    destination_capability.source,
                ),
            )

        total_cost = cost_result.total_cost_yuan
        source_ref = _exact_rate_source(rate)
        component = CostComponent(
            component_type="barge_freight",
            amount_yuan=total_cost,
            source_type="real_data",
            source=source_ref,
            rule_id=cost_result.rule_id,
            rule_version=cost_result.rule_version,
            calculation_detail=cost_result.calculation_detail,
        )
        edge = build_transport_edge(
            rate,
            cost_result,
            time,
            commodity=request.commodity,
            data_source=(
                f"real_data:{source_ref};time={time.source};"
                f"origin_capability={origin_capability.source};"
                f"destination_capability={destination_capability.source}"
            ),
            transport_stage=transport_stage,
            edge_role=edge_role,
            cost_components=(component,),
        )
        if not edge.is_available:
            return InlandWaterwayEdgeResult(
                status="manual_review",
                edge=None,
                message=(
                    "精确 OD 驳船边未通过 TransportEdge 校验："
                    f"{edge.unavailable_reason}"
                ),
                region_code=origin_capability.region_code,
                source_refs=(source_ref, time.source),
            )
        return InlandWaterwayEdgeResult(
            status="generated",
            edge=edge,
            message=(
                "已使用正式运价源最新无冲突精确 OD 驳船运价和"
                "已确认区域航运总时效生成可搜索驳船边。"
            ),
            region_code=origin_capability.region_code,
            source_refs=(
                source_ref,
                time.source,
                origin_capability.source,
                destination_capability.source,
            ),
        )

    def _find_capability(
        self,
        *,
        node_id: str,
        name: str,
        request: RouteRequest,
    ) -> PortCapabilityRecord | None:
        node_id_matches = [
            capability
            for capability in self.port_capabilities
            if capability.node_id == node_id
            and capability.supports_order(request)
            and capability.capability_data_confirmed
        ]
        if node_id_matches:
            return (
                node_id_matches[0]
                if len(node_id_matches) == 1
                else None
            )
        matches = [
            capability
            for capability in self.port_capabilities
            if capability.matches(node_id=None, name=name)
            and capability.supports_order(request)
            and capability.capability_data_confirmed
        ]
        return matches[0] if len(matches) == 1 else None

    def _exact_od_rates(
        self,
        *,
        origin_node_id: str,
        destination_node_id: str,
    ) -> tuple[FreightRate, ...]:
        return tuple(
            rate
            for rate in self.exact_od_rates
            if rate.from_node_id == origin_node_id
            and rate.to_node_id == destination_node_id
        )

    def _has_any_exact_od_rate(
        self,
        *,
        origin_node_id: str,
        destination_node_id: str,
    ) -> bool:
        return any(
            rate.from_node_id == origin_node_id
            and rate.to_node_id == destination_node_id
            for rate in self.exact_od_rates
        )

    def _matching_conflicts(
        self,
        *,
        exact_od_rates: Sequence[FreightRate],
        request: RouteRequest,
    ) -> tuple[LatestRateSelectionIssue, ...]:
        exact_ids = {id(rate) for rate in exact_od_rates}
        return tuple(
            issue
            for issue in self.review_issues
            if any(
                id(rate) in exact_ids and _rate_supports_request(rate, request)
                for rate in issue.rates
            )
        )


def _rate_supports_request(
    rate: FreightRate,
    request: RouteRequest,
) -> bool:
    return (
        rate.package_type == request.package_type
        and rate.supports_commodity(request.commodity)
    )


def _exact_rate_source(rate: FreightRate) -> str:
    location = rate.source_file or "运价表.json"
    if rate.source_row_number is not None:
        location = f"{location}#{rate.source_row_number}"
    maintenance = (
        rate.maintained_at.isoformat()
        if rate.maintained_at is not None
        else "1970-01-01(default)"
    )
    return (
        f"{location};price_source={rate.price_source};"
        f"maintained_at={maintenance}"
    )
