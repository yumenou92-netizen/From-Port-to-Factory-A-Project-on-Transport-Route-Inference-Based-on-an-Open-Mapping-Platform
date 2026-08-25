from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable, Sequence

from src.application.route_planning import (
    CandidateDecisionStage,
    CandidateDecisionStatus,
    EdgeGeometryTrace,
    EdgeSourceTrace,
    RoutePlanningContractError,
    RoutePlanningRequest,
    RoutePlanningResponse,
    RoutePlanningService,
    SouthPortCandidateDecision,
    TransferPort,
)
from src.application.south_port_selection import (
    SouthPortSelectionError,
    haversine_km,
    select_automatic_south_ports,
    select_requested_south_port,
)
from src.data.loaders import (
    DataLoadError,
    RealDataBundle,
    data_dir_from_env,
    load_real_data_bundle,
    make_node_id,
)
from src.data.node_master_capabilities import (
    NodeMasterCapabilityError,
    build_barge_capabilities_from_node_master,
)
from src.data.inland_waterway_freight import (
    InlandWaterwayFreightLoadError,
    find_optional_inland_waterway_freight_file,
    load_inland_waterway_freight_records,
)
from src.data.inland_waterway_time import (
    InlandWaterwayTimeLoadError,
    find_optional_inland_waterway_time_file,
    load_inland_waterway_time_records,
)
from src.data.port_reference import PortReferenceLoadError, load_port_reference_tables
from src.domain.cost_rules import CostCalculationResult, DEFAULT_COST_RULE_ENGINE, is_truck_transport_mode
from src.routing.bulk_shipping_provider import (
    BulkShippingWorkbook,
    make_bulk_shipping_cost_component,
    make_bulk_shipping_cost_result,
    make_bulk_shipping_rate,
    make_bulk_shipping_time_result,
)
from src.routing.formal_inland_waterway_provider import (
    ExactOdInlandWaterwayBargeProvider,
    TableInlandWaterwayBargeProvider,
)
from src.routing.inland_waterway_provider import (
    DEFAULT_PORT_CAPABILITY_RECORDS,
    DEFAULT_REGION_MAPPING_RECORDS,
    InlandWaterwayBargeProvider,
    PortCapabilityRecord,
)
from src.domain.freight_rate import FreightRate, create_freight_rate
from src.domain.latest_rate_selector import select_latest_freight_rates
from src.domain.node_registry import NodeRegistry, build_node_registry, normalize_lookup_name
from src.domain.route_request import RouteRequest
from src.geo.coordinate_provider import CoordinateProvider, CoordinateResolution, LocalFirstCoordinateProvider
from src.geo.distance_provider import GeoPoint, RoadRouteProvider, RoadRouteRequest, RoadRouteResult
from src.geo.tencent_map_provider import (
    TencentMapCoordinateProvider,
    TencentMapDrivingRouteProvider,
    TencentMapProviderError,
)
from src.routing.port_operation_fee_provider import (
    PortOperationFeeError,
    PortOperationFeeQuote,
    SouthPortOperationFeeProvider,
    TablePortOperationFeeProvider,
    find_optional_port_operation_fee_file,
)
from src.routing.route_result import RouteRecommendationResults, RouteResult, build_route_recommendations
from src.routing.route_search import search_cost_and_time_paths
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_edge import TransportEdge, build_transport_edge, make_transport_edge_id
from src.routing.transport_graph import build_transport_multidigraph


ORDER_QUANTITY = Decimal("3160")
ORDER_QUANTITY_UNIT = "吨"
ORDER_PACKAGE_TYPE = "散粮"
ORDER_COMMODITY = "玉米"
MAX_TRANSFER_PORTS = 7
MAX_INLAND_TRANSFER_PORTS_PER_SOUTH_PORT = 3

SOURCE_REAL_DATA = "real_business_data"
SOURCE_TENCENT = "tencent_map"
SOURCE_CONFIRMED_RULE = "confirmed_cost_rule"
SOURCE_DEMO_PLACEHOLDER = "demo_placeholder"
SOURCE_CONFIRMED_TIME = "confirmed_shipping_total_time"


class FullFlowDemoError(RuntimeError):
    """Raised when the leader demo cannot form a defensible complete route."""


@dataclass(frozen=True)
class DemoTrunkProfile:
    name: str
    unit_price_yuan_per_ton: Decimal
    duration_hours: Decimal


DEMO_TRUNK_PROFILES = (
    DemoTrunkProfile("演示经济型船运", Decimal("60"), Decimal("72")),
    DemoTrunkProfile("演示快速型船运", Decimal("75"), Decimal("48")),
    DemoTrunkProfile("演示均衡型船运", Decimal("68"), Decimal("60")),
)


# Transitional import name retained while current Demo callers migrate to the
# application-owned response type.
FullFlowDemoResult = RoutePlanningResponse


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(_module_args() if argv is None else argv)
    origin_name = args.origin or _prompt_required("请输入北港运输起点 O：")
    destination_name = args.destination or _prompt_required("请输入客户工厂终点 D：")

    try:
        planning_request = RoutePlanningRequest(
            origin=origin_name,
            destination=destination_name,
            south_port=args.south_port,
            region=args.region,
            request=RouteRequest(
                quantity=ORDER_QUANTITY,
                quantity_unit=ORDER_QUANTITY_UNIT,
                package_type=ORDER_PACKAGE_TYPE,
                commodity=ORDER_COMMODITY,
            ),
        )
        bundle = load_real_data_bundle(data_dir_from_env())
        registry = bundle.node_registry
        service = RoutePlanningService(
            lambda request: plan_full_flow(
                request,
                bundle=bundle,
                coordinate_provider_factory=lambda region: (
                    LocalFirstCoordinateProvider(
                        registry,
                        fallback_provider=TencentMapCoordinateProvider.from_env(
                            region=region
                        ),
                    )
                ),
                road_route_provider=TencentMapDrivingRouteProvider.from_env(),
            )
        )
        result = service.plan(planning_request)
    except (
        DataLoadError,
        RoutePlanningContractError,
        TencentMapProviderError,
        FullFlowDemoError,
    ) as exc:
        raise SystemExit(f"全流程演示未完成：{exc}") from exc

    print_full_flow_result(result)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="北港至客户工厂全流程展示_第一版验证Demo_First_Version_07_24")
    parser.add_argument("--origin", help="北港点 A；不提供时进入交互输入。")
    parser.add_argument("--destination", help="客户工厂 B；不提供时进入交互输入。")
    parser.add_argument("--south-port", help="可选南港；提供后仅测算该南港，不再自动筛选。")
    parser.add_argument("--region", default="全国", help="腾讯地点搜索区域，默认全国。")
    return parser.parse_args(list(argv))


def plan_full_flow(
    planning_request: RoutePlanningRequest,
    *,
    bundle: RealDataBundle,
    coordinate_provider_factory: Callable[[str], CoordinateProvider],
    road_route_provider: RoadRouteProvider,
    candidate_limit: int = MAX_TRANSFER_PORTS,
    bulk_workbook: BulkShippingWorkbook | None = None,
    port_operation_fee_provider: SouthPortOperationFeeProvider | None = None,
    port_operation_fee_source: str | None = None,
    inland_waterway_provider: InlandWaterwayBargeProvider | None = None,
    inland_waterway_source: str | None = None,
) -> RoutePlanningResponse:
    """Run the existing full-flow engine through the application contract."""

    coordinate_provider = coordinate_provider_factory(planning_request.region)
    return build_full_flow_demo(
        planning_request.origin,
        planning_request.destination,
        bundle=bundle,
        coordinate_provider=coordinate_provider,
        road_route_provider=road_route_provider,
        candidate_limit=candidate_limit,
        bulk_workbook=bulk_workbook,
        port_operation_fee_provider=port_operation_fee_provider,
        port_operation_fee_source=port_operation_fee_source,
        inland_waterway_provider=inland_waterway_provider,
        inland_waterway_source=inland_waterway_source,
        selected_south_port=planning_request.south_port,
        request=planning_request.request,
    )


def build_full_flow_demo(
    origin_name: str,
    destination_name: str,
    *,
    bundle: RealDataBundle,
    coordinate_provider: CoordinateProvider,
    road_route_provider: RoadRouteProvider,
    candidate_limit: int = MAX_TRANSFER_PORTS,
    bulk_workbook: BulkShippingWorkbook | None = None,
    port_operation_fee_provider: SouthPortOperationFeeProvider | None = None,
    port_operation_fee_source: str | None = None,
    inland_waterway_provider: InlandWaterwayBargeProvider | None = None,
    inland_waterway_source: str | None = None,
    selected_south_port: str | None = None,
    request: RouteRequest | None = None,
) -> RoutePlanningResponse:
    request = request or RouteRequest(
        quantity=ORDER_QUANTITY,
        quantity_unit=ORDER_QUANTITY_UNIT,
        package_type=ORDER_PACKAGE_TYPE,
        commodity=ORDER_COMMODITY,
    )
    origin = _require_coordinate(coordinate_provider.resolve(origin_name), "北港点 A")
    destination = _require_coordinate(coordinate_provider.resolve(destination_name), "客户工厂 B")
    _point_from_resolution(origin)
    destination_point = _point_from_resolution(destination)
    origin_node_id = origin.node_id or make_node_id(f"demo-origin:{origin.query_name}")
    destination_node_id = destination.node_id or make_node_id(
        f"demo-destination:{destination.query_name}"
    )

    registry = bundle.node_registry or build_node_registry(bundle.nodes)
    if port_operation_fee_provider is None:
        (
            port_operation_fee_provider,
            port_operation_fee_source,
        ) = _load_optional_port_operation_fee_provider(bundle.data_dir, registry)
    elif port_operation_fee_source is None:
        port_operation_fee_source = "injected_provider"
    if inland_waterway_provider is None:
        (
            inland_waterway_provider,
            inland_waterway_source,
        ) = _load_optional_inland_waterway_provider(bundle, registry)
    elif inland_waterway_source is None:
        inland_waterway_source = "injected_provider"

    known_rates, conflicted_origins = _known_last_mile_rates(
        bundle.freight_rates,
        request,
        destination,
        registry,
    )
    alternative_transport_origin_node_ids = set()
    applicable_origin_node_ids = getattr(
        inland_waterway_provider,
        "applicable_origin_node_ids",
        None,
    )
    if callable(applicable_origin_node_ids):
        alternative_transport_origin_node_ids = set(
            applicable_origin_node_ids(request)
        )
    try:
        if selected_south_port:
            selection = select_requested_south_port(
                selected_south_port,
                registry=registry,
                freight_rates=bundle.freight_rates,
                request=request,
                destination=destination_point,
                origin_node_id=origin_node_id,
                excluded_node_ids=conflicted_origins,
                node_master_entries=bundle.node_master_entries,
                port_node_entries=bundle.port_node_entries,
            )
        else:
            selection = select_automatic_south_ports(
                bundle,
                request,
                destination_point,
                origin_node_id=origin_node_id,
                excluded_node_ids=conflicted_origins,
                preferred_node_ids=set(known_rates),
                limit=candidate_limit,
                alternative_transport_origin_node_ids=(
                    alternative_transport_origin_node_ids
                ),
            )
    except SouthPortSelectionError as exc:
        raise FullFlowDemoError(str(exc)) from exc
    candidate_ports = selection.ports
    candidate_decisions = selection.decisions
    if not candidate_ports:
        raise FullFlowDemoError("真实运价始发端中没有可用于本次订单的候选南港节点。")

    bulk_workbook = bulk_workbook or BulkShippingWorkbook.load(
        _find_bulk_shipping_workbook(bundle.data_dir)
    )
    edges: list[TransportEdge] = []
    edge_sources: dict[str, EdgeSourceTrace] = {}
    edge_geometries: dict[str, EdgeGeometryTrace] = {}
    warnings: list[str] = []
    candidate_decisions_by_node = {
        decision.node_id: decision for decision in candidate_decisions
    }
    candidate_decision_order = tuple(
        decision.node_id for decision in candidate_decisions
    )
    usable_ports: list[TransferPort] = []
    included_operation_fee_count = 0
    not_applicable_operation_fee_count = 0
    barge_edge_count = 0
    truck_edge_count = 0
    barge_placeholder_capability_count = 0
    south_to_customer_options_by_port: dict[str, tuple[str, ...]] = {}
    intermediate_node_names: dict[str, str] = {}
    used_intermediate_ports: dict[str, TransferPort] = {}
    for port in candidate_ports:
        trunk_match = bulk_workbook.match(port.name, request)
        if not trunk_match.is_resolved:
            _update_candidate_decision(
                candidate_decisions_by_node,
                port,
                status="excluded",
                stage="north_to_south",
                reason=trunk_match.message,
            )
            warnings.append(f"候选节点 {port.name} 未形成散船干线段：{trunk_match.message}")
            continue
        operation_fee_quote: PortOperationFeeQuote | None = None
        if port_operation_fee_provider is not None:
            operation_fee_quote = port_operation_fee_provider.quote(
                port_name=port.name,
                port_node_id=port.node_id,
                request=request,
            )
            if not operation_fee_quote.allows_route:
                _update_candidate_decision(
                    candidate_decisions_by_node,
                    port,
                    status="excluded",
                    stage="port_operation_fee",
                    reason=operation_fee_quote.message,
                )
                warnings.append(
                    f"候选节点 {port.name} 未形成散船干线段："
                    f"南港码头作业费未确认，{operation_fee_quote.message}"
                )
                continue
        trunk_edge = _build_real_trunk_edge(
            origin.canonical_name or origin.query_name,
            origin_node_id,
            port,
            request,
            bulk_workbook,
            operation_fee_quote=operation_fee_quote,
        )
        south_to_customer_edges: list[TransportEdge] = []
        south_to_customer_sources: list[EdgeSourceTrace] = []
        south_to_customer_options: list[str] = []

        road_result = road_route_provider.get_route(
            RoadRouteRequest(origin=port.point, destination=destination_point)
        )
        if road_result.is_resolved:
            customer_road_edge, source_trace = _build_customer_delivery_road_edge(
                port,
                destination_node_id,
                destination_name,
                request,
                road_result,
                known_rate=known_rates.get(port.node_id),
            )
            south_to_customer_edges.append(customer_road_edge)
            south_to_customer_sources.append(source_trace)
            south_to_customer_options.append("汽运")
            truck_edge_count += 1
            if road_result.polyline_points:
                edge_geometries[customer_road_edge.edge_id] = EdgeGeometryTrace(
                    edge_id=customer_road_edge.edge_id,
                    kind="tencent_driving_polyline",
                    source=road_result.source,
                    points=road_result.polyline_points,
                    is_schematic=False,
                    message=(
                        "道路折线与本次费用、时效测算使用同一次腾讯驾车响应；"
                        "仅用于地图展示，不参与路径搜索。"
                    ),
                )
            else:
                warnings.append(
                    f"候选节点 {port.name} 的腾讯驾车结果未返回可用道路折线；"
                    "费用和时效仍可用，Web 地图不以端点直线冒充真实道路。"
                )
        else:
            warnings.append(
                f"候选节点 {port.name} 未形成道路运输段：{road_result.message}"
            )

        if inland_waterway_provider is not None:
            if getattr(
                inland_waterway_provider,
                "supports_direct_delivery",
                False,
            ):
                direct_barge_result = (
                    inland_waterway_provider.build_barge_edge(
                        origin_node_id=port.node_id,
                        origin_name=port.name,
                        destination_node_id=destination_node_id,
                        destination_name=destination_name,
                        request=request,
                        transport_stage="south_to_customer",
                        edge_role="delivery",
                    )
                )
                if (
                    direct_barge_result.is_generated
                    and direct_barge_result.edge is not None
                ):
                    south_to_customer_edges.append(
                        direct_barge_result.edge
                    )
                    south_to_customer_options.append("驳船直达客户")
                    barge_edge_count += 1
                    south_to_customer_sources.append(
                        EdgeSourceTrace(
                            edge_id=direct_barge_result.edge.edge_id,
                            labels=(
                                SOURCE_REAL_DATA,
                                SOURCE_CONFIRMED_TIME,
                            ),
                            explanation=(
                                f"{direct_barge_result.message}"
                                "终点为本次客户节点，不赋予中转港角色；"
                                f"来源追溯={'；'.join(direct_barge_result.source_refs)}"
                            ),
                        )
                    )
                elif direct_barge_result.status == "manual_review":
                    warnings.append(
                        f"候选节点 {port.name} 至客户 {destination_name} "
                        f"的直达驳船段待确认：{direct_barge_result.message}"
                    )

            inland_transfer_ports, endpoint_warnings = _provider_inland_transfer_ports(
                inland_waterway_provider,
                registry=registry,
                origin_port=port,
                destination=destination_point,
                request=request,
            )
            warnings.extend(endpoint_warnings)
            completed_transfer_path_count = 0
            inspected_transfer_port_count = 0
            for inland_port in inland_transfer_ports:
                if (
                    completed_transfer_path_count
                    >= MAX_INLAND_TRANSFER_PORTS_PER_SOUTH_PORT
                ):
                    break
                inspected_transfer_port_count += 1
                barge_result = inland_waterway_provider.build_barge_edge(
                    origin_node_id=port.node_id,
                    origin_name=port.name,
                    destination_node_id=inland_port.node_id,
                    destination_name=inland_port.name,
                    request=request,
                    transport_stage="south_to_customer",
                    edge_role="transfer",
                )
                if barge_result.is_generated and barge_result.edge is not None:
                    inland_road_result = road_route_provider.get_route(
                        RoadRouteRequest(
                            origin=inland_port.point,
                            destination=destination_point,
                        )
                    )
                    if not inland_road_result.is_resolved:
                        warnings.append(
                            f"候选节点 {port.name} 经 {inland_port.name} 的驳船中转未形成完整路径："
                            f"{inland_road_result.message}"
                        )
                        continue
                    inland_truck_edge, inland_truck_source = _build_customer_delivery_road_edge(
                        inland_port,
                        destination_node_id,
                        destination_name,
                        request,
                        inland_road_result,
                        known_rate=known_rates.get(inland_port.node_id),
                    )
                    south_to_customer_edges.extend(
                        (barge_result.edge, inland_truck_edge)
                    )
                    completed_transfer_path_count += 1
                    south_to_customer_options.append(f"驳船经{inland_port.name}中转")
                    barge_edge_count += 1
                    truck_edge_count += 1
                    intermediate_node_names[inland_port.node_id] = inland_port.name
                    used_intermediate_ports[inland_port.node_id] = inland_port
                    uses_placeholder_capability = (
                        "demo_placeholder" in barge_result.message
                    )
                    if uses_placeholder_capability:
                        barge_placeholder_capability_count += 1
                    labels = [SOURCE_REAL_DATA, SOURCE_CONFIRMED_TIME]
                    if uses_placeholder_capability:
                        labels.append(SOURCE_DEMO_PLACEHOLDER)
                    south_to_customer_sources.append(
                        EdgeSourceTrace(
                            edge_id=barge_result.edge.edge_id,
                            labels=tuple(labels),
                            explanation=(
                                f"{barge_result.message}"
                                f"来源追溯={'；'.join(barge_result.source_refs)}"
                            ),
                        )
                    )
                    south_to_customer_sources.append(inland_truck_source)
                    if inland_road_result.polyline_points:
                        edge_geometries[
                            inland_truck_edge.edge_id
                        ] = EdgeGeometryTrace(
                            edge_id=inland_truck_edge.edge_id,
                            kind="tencent_driving_polyline",
                            source=inland_road_result.source,
                            points=inland_road_result.polyline_points,
                            is_schematic=False,
                            message=(
                                f"{inland_port.name}至客户的道路折线与费用、时效测算"
                                "使用同一次腾讯驾车响应；仅用于地图展示。"
                            ),
                        )
                elif barge_result.status == "manual_review":
                    warnings.append(
                        f"候选节点 {port.name} 至 {inland_port.name} 的驳船中转段待确认："
                        f"{barge_result.message}"
                    )
            if len(inland_transfer_ports) > inspected_transfer_port_count:
                warnings.append(
                    f"候选南港 {port.name} 有 {len(inland_transfer_ports)} 个"
                    "精确 OD 驳船端点；本次按离客户直线距离依次检查，"
                    f"已形成 {completed_transfer_path_count} 条完整驳船中转路径，"
                    f"达到上限 {MAX_INLAND_TRANSFER_PORTS_PER_SOUTH_PORT} 后停止展开；"
                    "其余端点仍保留在离线全量审计范围。"
                )

        if not south_to_customer_edges:
            _update_candidate_decision(
                candidate_decisions_by_node,
                port,
                status="excluded",
                stage="south_to_customer",
                reason="未形成可到达客户工厂的汽运或驳船中转运输边。",
            )
            continue
        if operation_fee_quote is not None and operation_fee_quote.is_resolved:
            included_operation_fee_count += 1
        elif operation_fee_quote is not None and operation_fee_quote.is_not_applicable:
            not_applicable_operation_fee_count += 1
        edges.append(trunk_edge)
        edges.extend(south_to_customer_edges)
        usable_ports.append(port)
        _update_candidate_decision(
            candidate_decisions_by_node,
            port,
            status="included",
            stage="graph",
            reason="北港散船干线和至少一种南港后运输方案均已形成可搜索边。",
        )
        south_to_customer_options_by_port[port.node_id] = tuple(
            south_to_customer_options
        )
        trunk_explanation = (
            "费用来自真实散船运价表最新行；时间按领导确认分区航运总时效换算为小时，"
            "模型不拆分等待、装卸和航行组成。"
        )
        if operation_fee_quote is not None and operation_fee_quote.is_resolved:
            trunk_explanation += "南港码头作业费已通过正式 Provider 作为独立费用组成计入。"
        elif operation_fee_quote is not None and operation_fee_quote.is_not_applicable:
            trunk_explanation += operation_fee_quote.message
        edge_sources[trunk_edge.edge_id] = EdgeSourceTrace(
            edge_id=trunk_edge.edge_id,
            labels=(SOURCE_REAL_DATA, SOURCE_CONFIRMED_TIME),
            explanation=trunk_explanation,
        )
        for source_trace in south_to_customer_sources:
            edge_sources[source_trace.edge_id] = source_trace

    if not usable_ports:
        detail = "；".join(warnings) or "候选南港均缺少可用道路距离和时间。"
        raise FullFlowDemoError(detail)

    unique_edges = {edge.edge_id: edge for edge in edges}
    duplicate_edge_count = len(edges) - len(unique_edges)
    edges = list(unique_edges.values())
    if duplicate_edge_count:
        warnings.append(
            f"本次有 {duplicate_edge_count} 条重复图边已按 edge_id 合并；"
            "常见原因是多个南港共享同一中转港至客户的后续运输段。"
        )
    barge_edge_count = sum(
        edge.transport_stage == "south_to_customer"
        and edge.transport_mode == "驳船"
        for edge in edges
    )
    truck_edge_count = sum(
        edge.transport_stage == "south_to_customer"
        and edge.transport_mode == "汽运"
        for edge in edges
    )

    graph_result = build_transport_multidigraph(edges, allow_unregistered_nodes=True)
    searches = search_cost_and_time_paths(graph_result.graph, origin_node_id, destination_node_id)
    recommendations = build_route_recommendations(graph_result.graph, searches)
    if not recommendations.lowest_cost.is_resolved or not recommendations.fastest_time.is_resolved:
        raise FullFlowDemoError("正式图未能同时形成费用最低和时间最短推荐。")

    node_names = {
        origin_node_id: origin.canonical_name or origin.query_name,
        destination_node_id: destination.canonical_name or destination.query_name,
        **{port.node_id: port.name for port in usable_ports},
        **intermediate_node_names,
    }
    if conflicted_origins:
        warnings.append("同日运价冲突的真实路线已排除，未用陌生路线公式覆盖冲突记录。")

    return RoutePlanningResponse(
        origin_name=origin_name,
        destination_name=destination_name,
        selected_south_port=selected_south_port,
        origin_resolution=origin,
        destination_resolution=destination,
        request=request,
        candidate_ports=tuple(usable_ports),
        intermediate_ports=tuple(used_intermediate_ports.values()),
        graph_edge_count=graph_result.added_edge_count,
        recommendations=recommendations,
        node_names=node_names,
        edge_sources=edge_sources,
        edge_geometries=edge_geometries,
        warnings=tuple(warnings),
        additional_fee_count=len(bundle.additional_fees),
        trunk_edge_count=len(usable_ports),
        port_operation_fee_source=port_operation_fee_source,
        port_operation_fee_included_count=included_operation_fee_count,
        port_operation_fee_not_applicable_count=not_applicable_operation_fee_count,
        inland_waterway_source=inland_waterway_source,
        barge_edge_count=barge_edge_count,
        barge_placeholder_capability_count=barge_placeholder_capability_count,
        truck_edge_count=truck_edge_count,
        south_to_customer_options_by_port=south_to_customer_options_by_port,
        candidate_decisions=tuple(
            candidate_decisions_by_node[node_id]
            for node_id in candidate_decision_order
        ),
    )


def _known_last_mile_rates(
    rates: Sequence[FreightRate],
    request: RouteRequest,
    destination: CoordinateResolution,
    registry: NodeRegistry,
) -> tuple[dict[str, FreightRate], set[str]]:
    destination_node_id = destination.node_id
    destination_names = {
        normalize_lookup_name(destination.query_name),
        normalize_lookup_name(destination.canonical_name or destination.query_name),
    }
    matching = [
        rate
        for rate in rates
        if is_truck_transport_mode(rate.transport_mode)
        and rate.package_type == request.package_type
        and rate.supports_commodity(request.commodity)
        and (
            (destination_node_id is not None and rate.to_node_id == destination_node_id)
            or normalize_lookup_name(rate.destination_name) in destination_names
        )
    ]
    selection = select_latest_freight_rates(matching)
    selected = {
        rate.from_node_id: rate
        for rate in selection.selected_rates
        if rate.from_node_id is not None and registry.nodes.get(rate.from_node_id) is not None
    }
    conflicted = {
        rate.from_node_id
        for issue in selection.review_issues
        for rate in issue.rates
        if rate.from_node_id is not None
    }
    return selected, conflicted


def _provider_inland_transfer_ports(
    provider: InlandWaterwayBargeProvider,
    *,
    registry: NodeRegistry,
    origin_port: TransferPort,
    destination: GeoPoint,
    request: RouteRequest,
) -> tuple[tuple[TransferPort, ...], tuple[str, ...]]:
    """Resolve Provider-declared endpoints to registered graph nodes.

    The orchestration layer does not own a fixed list of transfer ports.  It
    consumes capability-backed endpoint candidates from the active Provider and
    skips candidates that cannot be resolved to one standard node.
    """
    ports: list[TransferPort] = []
    warnings: list[str] = []
    seen_node_ids: set[str] = set()
    for candidate in provider.list_destination_candidates(
        origin_node_id=origin_port.node_id,
        origin_name=origin_port.name,
        request=request,
    ):
        node = (
            registry.nodes.get(candidate.node_id)
            if candidate.node_id is not None
            else registry.lookup(candidate.canonical_name)
        )
        if node is None:
            warnings.append(
                f"驳船 Provider 候选端点 {candidate.canonical_name} "
                "未解析到唯一标准节点，本次未参与构图。"
            )
            continue
        if node.node_id == origin_port.node_id or node.node_id in seen_node_ids:
            continue
        seen_node_ids.add(node.node_id)
        point = GeoPoint(
            Decimal(str(node.longitude)),
            Decimal(str(node.latitude)),
        )
        ports.append(
            TransferPort(
                node_id=node.node_id,
                name=node.canonical_name,
                point=point,
                straight_line_km_to_factory=haversine_km(point, destination),
            )
        )
    ranked_ports = sorted(
        ports,
        key=lambda port: (
            port.straight_line_km_to_factory,
            port.name,
        ),
    )
    return tuple(ranked_ports), tuple(warnings)


def _update_candidate_decision(
    decisions: dict[str, SouthPortCandidateDecision],
    port: TransferPort,
    *,
    status: CandidateDecisionStatus,
    stage: CandidateDecisionStage,
    reason: str,
) -> None:
    current = decisions.get(port.node_id)
    if current is None:
        return
    decisions[port.node_id] = replace(
        current,
        status=status,
        stage=stage,
        reason=reason,
    )


def _build_demo_trunk_edge(
    origin_node_id: str,
    port: TransferPort,
    request: RouteRequest,
    profile: DemoTrunkProfile,
) -> TransportEdge:
    total_cost = profile.unit_price_yuan_per_ton * request.quantity
    data_source = "demo_placeholder:north_to_south_v1"
    edge_id = make_transport_edge_id(
        from_node_id=origin_node_id,
        to_node_id=port.node_id,
        transport_mode="散船",
        package_type=request.package_type,
        commodity=request.commodity,
        cost_yuan=total_cost,
        time_hours=profile.duration_hours,
        data_source=data_source,
        transport_stage="north_to_south",
        edge_role="trunk",
    )
    return TransportEdge(
        edge_id=edge_id,
        status="available",
        from_node_id=origin_node_id,
        to_node_id=port.node_id,
        transport_mode="散船",
        package_type=request.package_type,
        commodity=request.commodity,
        cost_yuan=total_cost,
        time_hours=profile.duration_hours,
        raw_price=profile.unit_price_yuan_per_ton,
        raw_price_unit="元/吨",
        price_source="demo_placeholder:north_to_south_shipping_cost",
        maintained_at=None,
        distance_km=None,
        distance_source=None,
        time_source="demo_placeholder:north_to_south_shipping_time",
        cost_rule_id="demo_placeholder_trunk_shipping",
        cost_rule_version="1.0",
        calculation_detail=(
            f"{profile.name}：{profile.unit_price_yuan_per_ton}元/吨×"
            f"{request.quantity}{request.quantity_unit}={total_cost}元；"
            f"演示运输时间={profile.duration_hours}小时"
        ),
        data_source=data_source,
        transport_stage="north_to_south",
        edge_role="trunk",
    )


def _build_real_trunk_edge(
    origin_name: str,
    origin_node_id: str,
    port: TransferPort,
    request: RouteRequest,
    workbook: BulkShippingWorkbook,
    *,
    operation_fee_quote: PortOperationFeeQuote | None = None,
) -> TransportEdge:
    match = workbook.match(port.name, request)
    if not match.is_resolved:
        raise FullFlowDemoError(f"候选节点 {port.name} 未形成散船干线段：{match.message}")
    rate = make_bulk_shipping_rate(
        origin_name,
        origin_node_id,
        port.name,
        port.node_id,
        request,
        match,
    )
    cost_result = make_bulk_shipping_cost_result(request, match)
    cost_components = [make_bulk_shipping_cost_component(match)]
    if operation_fee_quote is not None:
        if not operation_fee_quote.allows_route:
            raise FullFlowDemoError(f"候选节点 {port.name} 的南港码头作业费未确认：{operation_fee_quote.message}")
        if operation_fee_quote.is_resolved and (
            operation_fee_quote.total_cost_yuan is None
            or operation_fee_quote.component is None
        ):
            raise FullFlowDemoError(f"候选节点 {port.name} 的南港码头作业费结果不完整。")
        if (
            operation_fee_quote.is_resolved
            and cost_result.status == "valid"
            and cost_result.total_cost_yuan is not None
        ):
            total_cost = cost_result.total_cost_yuan + operation_fee_quote.total_cost_yuan
            cost_result = CostCalculationResult(
                status="valid",
                total_cost_yuan=total_cost,
                rule_id=cost_result.rule_id,
                rule_version=cost_result.rule_version,
                calculation_detail=(
                    f"{cost_result.calculation_detail}；"
                    f"{operation_fee_quote.component.calculation_detail}"
                ),
                price_source=cost_result.price_source,
                transport_mode=cost_result.transport_mode,
                rate_packaging=cost_result.rate_packaging,
                price_unit=cost_result.price_unit,
                message=f"{cost_result.message}；{operation_fee_quote.message}",
            )
            cost_components.append(operation_fee_quote.component)
    time_result = make_bulk_shipping_time_result(port.name, match)
    edge = build_transport_edge(
        rate,
        cost_result,
        time_result,
        commodity=request.commodity,
        data_source="real_business_data:bulk_shipping_workbook",
        transport_stage="north_to_south",
        edge_role="trunk",
        cost_components=tuple(cost_components),
    )
    if not edge.is_available:
        raise FullFlowDemoError(f"候选节点 {port.name} 未形成可搜索散船干线边：{edge.unavailable_reason}")
    return edge


def _load_optional_port_operation_fee_provider(
    data_dir: Path,
    registry: NodeRegistry,
) -> tuple[SouthPortOperationFeeProvider | None, str | None]:
    try:
        fee_file = find_optional_port_operation_fee_file(data_dir)
        if fee_file is None:
            return None, None
        port_reference = load_port_reference_tables(data_dir, registry=registry)
        return (
            TablePortOperationFeeProvider.from_csv(
                fee_file,
                registry=registry,
                region_assignments=port_reference.operation_fee_region_assignments,
                region_mappings=port_reference.region_mappings,
            ),
            str(fee_file),
        )
    except (PortOperationFeeError, PortReferenceLoadError) as exc:
        raise FullFlowDemoError(f"南港码头作业费表无法安全加载：{exc}") from exc


def _load_optional_inland_waterway_provider(
    bundle: RealDataBundle,
    registry: NodeRegistry,
) -> tuple[InlandWaterwayBargeProvider | None, str | None]:
    data_dir = bundle.data_dir
    try:
        freight_file = find_optional_inland_waterway_freight_file(data_dir)
        time_file = find_optional_inland_waterway_time_file(data_dir)
        if time_file is None:
            return None, None
        port_reference = load_port_reference_tables(data_dir, registry=registry)
        region_mappings = (
            *(
                record
                for record in port_reference.region_mappings
                if record.region_code != "fujian_minjiang"
            ),
            *(
                record
                for record in DEFAULT_REGION_MAPPING_RECORDS
                if record.region_code == "fujian_minjiang"
            ),
        )
        derived_capabilities = ()
        if bundle.node_master_entries:
            derived_capabilities = (
                build_barge_capabilities_from_node_master(
                    node_master_entries=bundle.node_master_entries,
                    freight_rates=bundle.freight_rates,
                    registry=registry,
                    region_mappings=region_mappings,
                ).capabilities
            )
        capabilities = _merge_port_capabilities(
            derived_capabilities,
            port_reference.port_capabilities,
            DEFAULT_PORT_CAPABILITY_RECORDS,
        )
        time_records = load_inland_waterway_time_records(time_file)
        regional_fallback: InlandWaterwayBargeProvider | None = None
        if freight_file is not None:
            regional_fallback = TableInlandWaterwayBargeProvider(
                port_capabilities=capabilities,
                region_mappings=region_mappings,
                freight_records=load_inland_waterway_freight_records(
                    freight_file
                ),
                time_records=time_records,
                allow_placeholder_capabilities=not bool(
                    derived_capabilities
                    or port_reference.port_capabilities
                ),
            )
        exact_rate_count = sum(
            "驳船" in rate.transport_mode for rate in bundle.freight_rates
        )
        if exact_rate_count:
            exact_source_name = (
                bundle.freight_rate_source.name
                if bundle.freight_rate_source is not None
                else "typed_freight_rates"
            )
            return (
                ExactOdInlandWaterwayBargeProvider(
                    port_capabilities=capabilities,
                    exact_od_rates=bundle.freight_rates,
                    time_records=time_records,
                    fallback_provider=regional_fallback,
                ),
                (
                    f"{exact_source_name}(exact_od={exact_rate_count})+{time_file}"
                    + (
                        f"+regional_fallback={freight_file}"
                        if freight_file is not None
                        else ""
                    )
                ),
            )
        if regional_fallback is None:
            return None, None
        return (
            regional_fallback,
            f"{freight_file}+{time_file}",
        )
    except (
        InlandWaterwayFreightLoadError,
        InlandWaterwayTimeLoadError,
        NodeMasterCapabilityError,
        PortReferenceLoadError,
    ) as exc:
        raise FullFlowDemoError(f"内河驳船数据无法安全加载：{exc}") from exc


def _merge_port_capabilities(
    *groups: Sequence[PortCapabilityRecord],
) -> tuple[PortCapabilityRecord, ...]:
    merged: list[PortCapabilityRecord] = []
    occupied_node_ids: set[str] = set()
    occupied_names: set[str] = set()
    for group in groups:
        for record in group:
            normalized_name = "".join(record.canonical_name.split())
            if (
                record.node_id is not None
                and record.node_id in occupied_node_ids
            ):
                continue
            if normalized_name in occupied_names:
                continue
            merged.append(record)
            if record.node_id is not None:
                occupied_node_ids.add(record.node_id)
            occupied_names.add(normalized_name)
    return tuple(merged)


def _build_customer_delivery_road_edge(
    port: TransferPort,
    destination_node_id: str,
    destination_name: str,
    request: RouteRequest,
    road_result: RoadRouteResult,
    *,
    known_rate: FreightRate | None,
) -> tuple[TransportEdge, EdgeSourceTrace]:
    if road_result.distance_km is None or road_result.duration_hours is None:
        raise FullFlowDemoError(f"候选节点 {port.name} 缺少可用道路距离或时间。")

    if known_rate is not None:
        bound_rate = known_rate.bind_node_ids(port.node_id, destination_node_id)
        cost_result = DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(
            request,
            known_rate=bound_rate,
        )
        source_labels = (SOURCE_REAL_DATA, SOURCE_TENCENT)
        source_explanation = "费用使用真实维护运价；距离和驾车时间来自腾讯地图。"
        data_source = _real_rate_source(bound_rate)
    else:
        cost_result = DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(
            request,
            distance_km=road_result.distance_km,
            distance_source=road_result.source,
            price_source="confirmed_cost_rule:unknown_last_mile_truck",
        )
        if cost_result.status != "valid" or cost_result.total_cost_yuan is None:
            raise FullFlowDemoError(f"候选节点 {port.name} 的陌生汽运费用无法计算：{cost_result.message}")
        unit_price = cost_result.total_cost_yuan / request.quantity
        bound_rate = create_freight_rate(
            origin_name=port.name,
            destination_name=destination_name,
            transport_mode="汽运",
            package_type=request.package_type,
            commodity_scope=request.commodity,
            raw_price=unit_price,
            raw_price_unit=cost_result.price_unit,
            price_type="unit_price",
            price_source=cost_result.price_source,
            from_node_id=port.node_id,
            to_node_id=destination_node_id,
            source_file="confirmed_cost_rule",
        )
        source_labels = (SOURCE_CONFIRMED_RULE, SOURCE_TENCENT)
        source_explanation = "费用使用已确认的陌生汽运规则；距离和驾车时间来自腾讯地图。"
        data_source = "confirmed_cost_rule:unknown_last_mile_truck"

    time_result = ShippingTimeResult(
        status="resolved",
        duration_hours=road_result.duration_hours,
        source=road_result.source,
        message="已采用腾讯地图普通驾车时间作为原型最后一公里时效。",
        stage=f"{port.name}至{destination_name}",
        transport_mode="汽运",
        input_value=str(road_result.duration_hours),
        input_unit="小时",
        time_scope="road_driving",
    )
    edge = build_transport_edge(
        bound_rate,
        cost_result,
        time_result,
        commodity=request.commodity,
        distance_km=road_result.distance_km,
        distance_source=road_result.source,
        data_source=data_source,
        transport_stage="south_to_customer",
        edge_role="delivery",
    )
    if not edge.is_available:
        raise FullFlowDemoError(f"候选节点 {port.name} 未形成可搜索运输边：{edge.unavailable_reason}")
    return edge, EdgeSourceTrace(edge.edge_id, source_labels, source_explanation)


def print_full_flow_result(result: FullFlowDemoResult) -> None:
    has_direct_customer_barge = any(
        "驳船直达客户" in modes
        for modes in result.south_to_customer_options_by_port.values()
    )
    print("北港至客户工厂全链路运输路径推断原型")
    print("第一第二阶段验收Demo")
    print("=" * 64)
    print(
        f"输入：北港 A={result.origin_name}；客户工厂 B={result.destination_name}；"
        f"南港={result.selected_south_port or '系统自动筛选'}"
    )
    print(
        f"演示订单：{result.request.quantity}{result.request.quantity_unit}，"
        f"{result.request.package_type}，{result.request.commodity}，{result.request.trade_type}；"
        + (
            "客户画像=真实精确 OD 运价证明本次客户节点可接收驳船"
            if has_direct_customer_barge
            else "客户画像=无自有码头（演示默认）"
        )
    )
    print(
        f"坐标来源：北港={result.origin_resolution.source}；"
        f"客户工厂={result.destination_resolution.source}"
    )
    print(
        f"坐标置信等级：北港={result.origin_resolution.source_confidence or '未提供'}；"
        f"客户工厂={result.destination_resolution.source_confidence or '未提供'}"
    )
    print(
        f"地点节点：北港={_node_registration_text(result.origin_resolution)}；"
        f"客户工厂={_node_registration_text(result.destination_resolution)}"
    )
    candidate_count = len(result.candidate_ports)
    print(
        f"候选南港={candidate_count} 个；本次搜索图运输边={result.graph_edge_count} 条"
        f"（真实散船干线边={result.trunk_edge_count} 条；"
        f"汽运边={result.truck_edge_count} 条；"
        f"内河驳船边={result.barge_edge_count} 条）"
    )
    print(
        f"AdditionalFee 原始记录={result.additional_fee_count} 条"
        "（仅完成结构化加载，未计入本次总费用；缺失不代表费用为 0）"
    )
    if result.port_operation_fee_source is None:
        print("南港码头作业费表=未接入（当前不计入；缺失不代表费用为 0）")
    else:
        print(
            f"南港码头作业费表={result.port_operation_fee_source}；"
            f"已计入散船干线边={result.port_operation_fee_included_count} 条；"
            f"明确不适用={result.port_operation_fee_not_applicable_count} 条"
            "（缺失或不匹配的候选不入图，不解释为 0）"
        )
    if result.inland_waterway_source is None:
        print("内河驳船费率/航时表=未完整接入（当前不生成正式驳船边）")
    else:
        print(
            f"内河驳船费率/航时表={result.inland_waterway_source}；"
            f"已生成驳船边={result.barge_edge_count} 条；"
            f"其中使用 demo_placeholder 能力标签="
            f"{result.barge_placeholder_capability_count} 条"
        )
    print("候选南港（本次均已形成至少一种可搜索的南港后运输方案）：")
    for index, port in enumerate(result.candidate_ports, start=1):
        modes = "、".join(
            result.south_to_customer_options_by_port.get(port.node_id, ())
        )
        print(
            f"  {index}. {port.name}；"
            f"预筛直线距离={_format_decimal(port.straight_line_km_to_factory)}公里；"
            f"已入图末段方式={modes or '无'}"
        )
    print(
        "候选预筛口径（当前原型启发式）：候选来源于适用当前订单的真实运价始发端；"
        "优先采用节点维护表的节点性质、码头属性和包装能力；"
        "维护标签缺失时才使用名称规则补充识别；"
        "纯内河港和显式散粮能力排除仍优先阻断；"
        "未分类港口可凭散粮始发运价证据准入；"
        "已维护到厂汽运路线优先，并为存在适用精确 OD 驳船运价的南港"
        "保留最多 3 个多式运输候选名额；同优先级按直线距离排序；"
        "最终汽运距离和时间使用腾讯道路结果，费用优先采用已维护运价，否则采用已确认陌生汽运规则。"
    )
    print("候选准入决策（身份筛选、排序与构边结果）：")
    for decision in result.candidate_decisions:
        print(
            f"  - {decision.name}；状态={decision.status}；阶段={decision.stage}；"
            f"原因={decision.reason}"
        )

    print("\n一、费用最低路线")
    _print_route(result.recommendations.lowest_cost, result)
    print("\n二、时间最短路线")
    _print_route(result.recommendations.fastest_time, result)

    if (
        result.recommendations.lowest_cost.path_node_ids
        == result.recommendations.fastest_time.path_node_ids
    ):
        print(
            "\n说明：在本次候选范围和当前真实散船干线参数下，"
            "费用最低与时间最短指向同一条物理路线；两项目标仍由系统独立搜索。"
        )

    print("\n三、数据边界说明")
    print(
        "- 真实输入与规则：本地标准节点、真实散船运价表、"
        "优先正式运费工作簿（缺失时回退 JSON）的最新无冲突精确 OD 驳船运价、"
        "已维护汽运价可用时优先采用；"
        "道路距离和驾车时间来自腾讯地图；陌生汽运使用已确认规则。"
    )
    print("- 北港至南港航运总时效按南港分区天数换算为小时，模型不拆分时间组成。")
    if has_direct_customer_barge:
        print(
            "- 客户水运可达性：本次由真实精确 OD 驳船运价证明，"
            #"不使用“无自有码头”演示占位。"
        )
    else:
        print("- 演示占位数据：仅客户无自有码头画像。")
    print("- 暂未计入：AdditionalFee 仅完成原始记录加载；逐条适用条件未确认前不计入，也不解释为 0。")
    if result.port_operation_fee_source is None:
        print("- 暂未计入：南港码头作业费正式表未接入；当前不计入，也不解释为 0。")
    else:
        print(
            "- 已接入：南港码头作业费表；正数费率计入总费用；"
            "客户自有码头等明确不适用规则按 0 元通过且保留原因；"
            "精确费率缺失时可采用同区域最近适用真实码头费率，并明确标记 regional_proxy；"
            "仍无法解析区域或参考费率的候选南港不入图。"
        )
    if result.inland_waterway_source is None:
        print("- 暂未接入：内河驳船费率/航时表不完整，本次不生成驳船边。")
    elif result.barge_edge_count:
        print(
            "- 已接入：优先正式运费工作簿的最新无冲突精确 OD 驳船运价，"
            "工作簿缺失时兼容回退 JSON；"
            "独立区域费率仅在没有精确 OD 时回退；"
            "符合区域、包装、品种、贸易类型和端点能力条件的驳船边可进入图；"
            "福建闽江已确认费率为 50 元/吨、航运总时间为单程 15 小时，双向同时效。"
        )
        if result.barge_placeholder_capability_count:
            print(
                "- 演示占位：部分驳船边的端点装卸/通航能力仍使用 "
                "demo_placeholder；费率和航时真实不等于端点能力已正式确认。"
            )
    else:
        print(
            "- 已接入接口：内河驳船费率和航时表已加载；本次输入未同时满足"
            "区域、端点能力和订单适用条件，因此未生成驳船边。"
        )
    for warning in result.warnings:
        print(f"- 运行提示：{warning}")


def _print_route(route: RouteResult, result: FullFlowDemoResult) -> None:
    names = [result.node_names.get(node_id, node_id) for node_id in route.path_node_ids]
    print(f"推荐路径：{' -> '.join(names)}")
    print(
        f"总费用：{_format_decimal(route.total_cost_yuan)} 元；"
        f"总时间：{_format_decimal(route.total_time_hours)} 小时"
    )
    cost_per_ton_wan = _cost_per_ton_wan(route.total_cost_yuan, result.request)
    if cost_per_ton_wan is not None:
        print(
            "折合运价："
            f"{_format_decimal(cost_per_ton_wan, places=4)} 万元/吨"
            "（总费用÷订单吨数）"
        )
    _print_cost_breakdown(route, result)
    for segment in route.segments:
        source = result.edge_sources[segment.edge_key]
        labels = "、".join(_source_label_text(label) for label in source.labels)
        start = result.node_names.get(segment.from_node_id, segment.from_node_id)
        end = result.node_names.get(segment.to_node_id, segment.to_node_id)
        print(
            f"  {segment.segment_no}. {start} -> {end}；方式={_transport_mode_text(segment.transport_mode)}；"
            f"费用={_format_decimal(segment.cost_yuan)}元；"
            f"时间={_format_decimal(segment.time_hours)}小时"
        )
        print(f"     数据口径={labels}；{source.explanation}")
        print(f"     计费规则={segment.cost_rule_id}/{segment.cost_rule_version}")
    if _route_has_vessel_time_gap(route):
        print(
            "  时效口径提示：本模型将已确认船运时效直接视为对应航运段总时间，"
            "不再拆分等待、装船、航行、卸船等组成；未配置正式时效的运输段仍不得补零。"
        )


def _print_cost_breakdown(route: RouteResult, result: FullFlowDemoResult) -> None:
    print("总费用组成（已计入）：")
    for segment in route.segments:
        source = result.edge_sources[segment.edge_key]
        labels = "、".join(_source_label_text(label) for label in source.labels)
        start = result.node_names.get(segment.from_node_id, segment.from_node_id)
        end = result.node_names.get(segment.to_node_id, segment.to_node_id)
        print(
            f"  {segment.segment_no}. {_transport_mode_text(segment.transport_mode)}："
            f"{start} -> {end}；{_format_decimal(segment.cost_yuan)}元；"
            f"数据口径={labels}；计费规则={segment.cost_rule_id}/{segment.cost_rule_version}"
        )
        for component in segment.cost_components:
            print(
                f"     - {_cost_component_type_text(component.component_type)}："
                f"{_format_decimal(component.amount_yuan)}元；"
                f"来源={_component_source_type_text(component.source_type)}；"
                f"计费规则={component.rule_id}/{component.rule_version}"
            )
    print(f"  已计入合计：{_format_decimal(route.total_cost_yuan)}元")
    if result.additional_fee_count:
        print("  未计入项：AdditionalFee（原始记录已加载，逐条适用条件未确认）")
    else:
        print("  未计入项：AdditionalFee（当前无原始记录；缺失不解释为 0）")
    if result.port_operation_fee_source is None:
        print("  未计入项：南港码头作业费（正式表未接入；缺失不解释为 0）")


def _source_label_text(label: str) -> str:
    return {
        SOURCE_REAL_DATA: "真实业务数据",
        SOURCE_TENCENT: "腾讯地图",
        SOURCE_CONFIRMED_RULE: "已确认计费规则",
        SOURCE_DEMO_PLACEHOLDER: "演示占位数据",
        SOURCE_CONFIRMED_TIME: "已确认航运总时效",
    }[label]


def _node_registration_text(result: CoordinateResolution) -> str:
    if result.node_id is not None:
        return "已注册标准节点"
    if result.source == "tencent_map_place_search":
        return "腾讯坐标生成的本次运行临时节点（可参与构图）"
    return "坐标解析生成的本次运行临时节点（可参与构图）"


def _transport_mode_text(transport_mode: str) -> str:
    if transport_mode == "散船":
        return "散船干线"
    return transport_mode


def _cost_component_type_text(component_type: str) -> str:
    return {
        "bulk_shipping_freight": "散船运费",
        "south_port_operation_fee": "码头作业费",
        "barge_freight": "驳船运费",
    }.get(component_type, component_type)


def _component_source_type_text(source_type: str) -> str:
    return {
        "real_data": "真实业务数据",
        "confirmed_rule": "已确认计费规则",
        "regional_proxy": "同区域最近码头代理费率",
        "demo_placeholder": "演示占位数据",
    }.get(source_type, source_type)


def _route_has_vessel_time_gap(route: RouteResult) -> bool:
    return any(segment.transport_mode in {"散船", "驳船"} for segment in route.segments)


def _cost_per_ton_wan(total_cost_yuan: Decimal, request: RouteRequest) -> Decimal | None:
    """Return the display-only total route cost in ten-thousand yuan per ton."""

    if request.quantity_unit != "吨":
        return None
    return total_cost_yuan / request.quantity / Decimal("10000")


def _format_decimal(value: Decimal, *, places: int = 2) -> str:
    quantum = Decimal("1").scaleb(-places)
    formatted = format(value.quantize(quantum, rounding=ROUND_HALF_UP), "f")
    if "." not in formatted:
        return formatted
    return formatted.rstrip("0").rstrip(".")


def _real_rate_source(rate: FreightRate) -> str:
    if rate.source_file and rate.source_row_number is not None:
        return f"real_business_data:{rate.source_file}#row={rate.source_row_number}"
    return "real_business_data:maintained_freight_rate"


def _find_bulk_shipping_workbook(data_dir: Path) -> Path:
    matches = sorted(data_dir.rglob("散船运价表.xlsx"))
    if not matches:
        raise FullFlowDemoError("DATA_DIR 下缺少散船运价表.xlsx，不能替换散船干线占位。")
    if len(matches) > 1:
        raise FullFlowDemoError("DATA_DIR 下存在多个散船运价表.xlsx，请先明确散船运价来源。")
    return matches[0]


def _require_coordinate(result: CoordinateResolution, label: str) -> CoordinateResolution:
    if result.status != "resolved":
        raise FullFlowDemoError(f"{label}坐标未确认：{result.message}")
    return result


def _point_from_resolution(result: CoordinateResolution) -> GeoPoint:
    if result.longitude is None or result.latitude is None:
        raise FullFlowDemoError(f"地点 {result.query_name} 缺少经纬度。")
    return GeoPoint(result.longitude, result.latitude)


def _prompt_required(prompt: str, *, input_func: Callable[[str], str] = input) -> str:
    value = input_func(prompt).strip()
    if not value:
        raise SystemExit("地点名称不能为空。")
    return value


def _module_args() -> list[str]:
    args = list(sys.argv[1:])
    if args and args[0] == "full-flow":
        return args[1:]
    return args


if __name__ == "__main__":
    main()
