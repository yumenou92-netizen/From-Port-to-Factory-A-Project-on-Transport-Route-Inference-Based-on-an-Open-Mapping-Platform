from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Sequence

from src.data.loaders import (
    DataLoadError,
    RealDataBundle,
    data_dir_from_env,
    load_real_data_bundle,
    make_node_id,
)
from src.domain.cost_rules import DEFAULT_COST_RULE_ENGINE, is_truck_transport_mode
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
from src.routing.route_result import RouteRecommendationResults, RouteResult, build_route_recommendations
from src.routing.route_search import search_cost_and_time_paths
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_edge import TransportEdge, build_transport_edge, make_transport_edge_id
from src.routing.transport_graph import build_transport_multidigraph


ORDER_QUANTITY = Decimal("500")
ORDER_QUANTITY_UNIT = "吨"
ORDER_PACKAGE_TYPE = "散粮"
ORDER_COMMODITY = "玉米"
MAX_TRANSFER_PORTS = 3

SOURCE_REAL_DATA = "real_business_data"
SOURCE_TENCENT = "tencent_map"
SOURCE_CONFIRMED_RULE = "confirmed_cost_rule"
SOURCE_DEMO_PLACEHOLDER = "demo_placeholder"


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


@dataclass(frozen=True)
class TransferPort:
    node_id: str
    name: str
    point: GeoPoint
    straight_line_km_to_factory: Decimal


@dataclass(frozen=True)
class EdgeSourceTrace:
    edge_id: str
    labels: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class FullFlowDemoResult:
    origin_name: str
    destination_name: str
    origin_resolution: CoordinateResolution
    destination_resolution: CoordinateResolution
    request: RouteRequest
    candidate_ports: tuple[TransferPort, ...]
    graph_edge_count: int
    recommendations: RouteRecommendationResults
    node_names: dict[str, str]
    edge_sources: dict[str, EdgeSourceTrace]
    warnings: tuple[str, ...]
    additional_fee_count: int


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(_module_args() if argv is None else argv)
    origin_name = args.origin or _prompt_required("请输入北港点 A：")
    destination_name = args.destination or _prompt_required("请输入客户工厂 B：")

    try:
        bundle = load_real_data_bundle(data_dir_from_env())
        registry = bundle.node_registry
        coordinate_provider = LocalFirstCoordinateProvider(
            registry,
            fallback_provider=TencentMapCoordinateProvider.from_env(region=args.region),
        )
        result = build_full_flow_demo(
            origin_name,
            destination_name,
            bundle=bundle,
            coordinate_provider=coordinate_provider,
            road_route_provider=TencentMapDrivingRouteProvider.from_env(),
        )
    except (DataLoadError, TencentMapProviderError, FullFlowDemoError) as exc:
        raise SystemExit(f"全流程演示未完成：{exc}") from exc

    print_full_flow_result(result)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="北港至客户工厂全流程展示_第一版验证Demo_First_Version_07_24")
    parser.add_argument("--origin", help="北港点 A；不提供时进入交互输入。")
    parser.add_argument("--destination", help="客户工厂 B；不提供时进入交互输入。")
    parser.add_argument("--region", default="全国", help="腾讯地点搜索区域，默认全国。")
    return parser.parse_args(list(argv))


def build_full_flow_demo(
    origin_name: str,
    destination_name: str,
    *,
    bundle: RealDataBundle,
    coordinate_provider: CoordinateProvider,
    road_route_provider: RoadRouteProvider,
    candidate_limit: int = MAX_TRANSFER_PORTS,
) -> FullFlowDemoResult:
    request = RouteRequest(
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
    known_rates, conflicted_origins = _known_last_mile_rates(
        bundle.freight_rates,
        request,
        destination,
        registry,
    )
    candidate_ports = _select_transfer_ports(
        bundle,
        request,
        destination_point,
        origin_node_id=origin_node_id,
        excluded_node_ids=conflicted_origins,
        preferred_node_ids=set(known_rates),
        limit=candidate_limit,
    )
    if not candidate_ports:
        raise FullFlowDemoError("真实运价始发端中没有可用于本次订单的候选南港节点。")

    edges: list[TransportEdge] = []
    edge_sources: dict[str, EdgeSourceTrace] = {}
    warnings: list[str] = []
    usable_ports: list[TransferPort] = []

    for rank, port in enumerate(candidate_ports):
        road_result = road_route_provider.get_route(
            RoadRouteRequest(origin=port.point, destination=destination_point)
        )
        if not road_result.is_resolved:
            warnings.append(f"候选节点 {port.name} 未形成道路运输段：{road_result.message}")
            continue

        trunk_edge = _build_demo_trunk_edge(
            origin_node_id,
            port,
            request,
            DEMO_TRUNK_PROFILES[rank % len(DEMO_TRUNK_PROFILES)],
        )
        last_mile_edge, source_trace = _build_last_mile_edge(
            port,
            destination_node_id,
            destination_name,
            request,
            road_result,
            known_rate=known_rates.get(port.node_id),
        )
        edges.extend((trunk_edge, last_mile_edge))
        usable_ports.append(port)
        edge_sources[trunk_edge.edge_id] = EdgeSourceTrace(
            edge_id=trunk_edge.edge_id,
            labels=(SOURCE_DEMO_PLACEHOLDER,),
            explanation="北港至南港正式船运费用和时间尚缺，使用独立演示占位值。",
        )
        edge_sources[last_mile_edge.edge_id] = source_trace

    if not usable_ports:
        detail = "；".join(warnings) or "候选南港均缺少可用道路距离和时间。"
        raise FullFlowDemoError(detail)

    graph_result = build_transport_multidigraph(edges, allow_unregistered_nodes=True)
    searches = search_cost_and_time_paths(graph_result.graph, origin_node_id, destination_node_id)
    recommendations = build_route_recommendations(graph_result.graph, searches)
    if not recommendations.lowest_cost.is_resolved or not recommendations.fastest_time.is_resolved:
        raise FullFlowDemoError("正式图未能同时形成费用最低和时间最短推荐。")

    node_names = {
        origin_node_id: origin.canonical_name or origin.query_name,
        destination_node_id: destination.canonical_name or destination.query_name,
        **{port.node_id: port.name for port in usable_ports},
    }
    if conflicted_origins:
        warnings.append("同日运价冲突的真实路线已排除，未用陌生路线公式覆盖冲突记录。")

    return FullFlowDemoResult(
        origin_name=origin_name,
        destination_name=destination_name,
        origin_resolution=origin,
        destination_resolution=destination,
        request=request,
        candidate_ports=tuple(usable_ports),
        graph_edge_count=graph_result.added_edge_count,
        recommendations=recommendations,
        node_names=node_names,
        edge_sources=edge_sources,
        warnings=tuple(warnings),
        additional_fee_count=len(bundle.additional_fees),
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


def _select_transfer_ports(
    bundle: RealDataBundle,
    request: RouteRequest,
    destination: GeoPoint,
    *,
    origin_node_id: str,
    excluded_node_ids: set[str],
    preferred_node_ids: set[str],
    limit: int,
) -> tuple[TransferPort, ...]:
    if limit <= 0:
        raise FullFlowDemoError("候选南港数量必须大于 0。")
    registry = bundle.node_registry or build_node_registry(bundle.nodes)
    origins: dict[str, TransferPort] = {}
    for rate in bundle.freight_rates:
        if (
            not is_truck_transport_mode(rate.transport_mode)
            or rate.package_type != request.package_type
            or not rate.supports_commodity(request.commodity)
            or rate.from_node_id is None
            or rate.from_node_id == origin_node_id
            or rate.from_node_id in excluded_node_ids
        ):
            continue
        node = registry.nodes.get(rate.from_node_id)
        if node is None:
            continue
        point = GeoPoint(Decimal(str(node.longitude)), Decimal(str(node.latitude)))
        origins.setdefault(
            node.node_id,
            TransferPort(
                node_id=node.node_id,
                name=node.canonical_name,
                point=point,
                straight_line_km_to_factory=_haversine_km(point, destination),
            ),
        )

    all_candidates = list(origins.values())
    port_like = [port for port in all_candidates if "港" in port.name or "码头" in port.name]
    candidates = port_like if len(port_like) >= min(2, limit) else all_candidates
    candidate_ids = {port.node_id for port in candidates}
    candidates.extend(
        port
        for port in all_candidates
        if port.node_id in preferred_node_ids and port.node_id not in candidate_ids
    )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.node_id not in preferred_node_ids,
                item.straight_line_km_to_factory,
                item.name,
            ),
        )[:limit]
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
        transport_mode="水运",
        package_type=request.package_type,
        commodity=request.commodity,
        cost_yuan=total_cost,
        time_hours=profile.duration_hours,
        data_source=data_source,
    )
    return TransportEdge(
        edge_id=edge_id,
        status="available",
        from_node_id=origin_node_id,
        to_node_id=port.node_id,
        transport_mode="水运",
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
    )


def _build_last_mile_edge(
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
    )
    edge = build_transport_edge(
        bound_rate,
        cost_result,
        time_result,
        commodity=request.commodity,
        distance_km=road_result.distance_km,
        distance_source=road_result.source,
        data_source=data_source,
    )
    if not edge.is_available:
        raise FullFlowDemoError(f"候选节点 {port.name} 未形成可搜索运输边：{edge.unavailable_reason}")
    return edge, EdgeSourceTrace(edge.edge_id, source_labels, source_explanation)


def print_full_flow_result(result: FullFlowDemoResult) -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("第一版全流程领导 Demo")
    print("=" * 64)
    print(f"输入：北港 A={result.origin_name}；客户工厂 B={result.destination_name}")
    print(
        f"演示订单：{result.request.quantity}{result.request.quantity_unit}，"
        f"{result.request.package_type}，{result.request.commodity}；客户画像=无自有码头（演示默认）"
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
        f"候选南港={len(result.candidate_ports)} 个；正式图运输边={result.graph_edge_count} 条；"
        f"已加载 AdditionalFee={result.additional_fee_count} 条（归属未确认，本次不计入）"
    )

    print("\n一、费用最低路线")
    _print_route(result.recommendations.lowest_cost, result)
    print("\n二、时间最短路线")
    _print_route(result.recommendations.fastest_time, result)

    if (
        result.recommendations.lowest_cost.path_node_ids
        == result.recommendations.fastest_time.path_node_ids
    ):
        print("\n说明：本次费用最低和时间最短指向同一条物理路线，系统按真实搜索结果展示。")

    print("\n三、关于测试版的说明 about Test Version.7_24")
    print("- Data_REAL First 真实优先：本地节点、真实维护运价、腾讯地图距离与驾车时间、已确认计费规则。")
    print("- Smooth present First 演示占位：仅北港至候选南港的船运费用、船运时间，以及无自有码头画像。")
    print("- Not yet completed 暂不计入：AdditionalFee；未确认归属前不默认为 0，也不伪造归属。")
    for warning in result.warnings:
        print(f"- 运行提示：{warning}")


def _print_route(route: RouteResult, result: FullFlowDemoResult) -> None:
    names = [result.node_names.get(node_id, node_id) for node_id in route.path_node_ids]
    print(f"推荐路径：{' -> '.join(names)}")
    print(f"总费用：{route.total_cost_yuan} 元；总时间：{route.total_time_hours} 小时")
    for segment in route.segments:
        source = result.edge_sources[segment.edge_key]
        labels = "、".join(_source_label_text(label) for label in source.labels)
        start = result.node_names.get(segment.from_node_id, segment.from_node_id)
        end = result.node_names.get(segment.to_node_id, segment.to_node_id)
        print(
            f"  {segment.segment_no}. {start} -> {end}；方式={segment.transport_mode}；"
            f"费用={segment.cost_yuan}元；时间={segment.time_hours}小时"
        )
        print(f"     数据口径={labels}；{source.explanation}")
        print(f"     计费规则={segment.cost_rule_id}/{segment.cost_rule_version}")


def _source_label_text(label: str) -> str:
    return {
        SOURCE_REAL_DATA: "真实业务数据",
        SOURCE_TENCENT: "腾讯地图",
        SOURCE_CONFIRMED_RULE: "已确认计费规则",
        SOURCE_DEMO_PLACEHOLDER: "演示占位数据",
    }[label]


def _real_rate_source(rate: FreightRate) -> str:
    if rate.source_file and rate.source_row_number is not None:
        return f"real_business_data:{rate.source_file}#row={rate.source_row_number}"
    return "real_business_data:maintained_freight_rate"


def _require_coordinate(result: CoordinateResolution, label: str) -> CoordinateResolution:
    if result.status != "resolved":
        raise FullFlowDemoError(f"{label}坐标未确认：{result.message}")
    return result


def _point_from_resolution(result: CoordinateResolution) -> GeoPoint:
    if result.longitude is None or result.latitude is None:
        raise FullFlowDemoError(f"地点 {result.query_name} 缺少经纬度。")
    return GeoPoint(result.longitude, result.latitude)


def _haversine_km(left: GeoPoint, right: GeoPoint) -> Decimal:
    radius_km = 6371.0088
    lat1 = math.radians(float(left.latitude))
    lat2 = math.radians(float(right.latitude))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(float(right.longitude - left.longitude))
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    distance = 2 * radius_km * math.asin(math.sqrt(value))
    return Decimal(str(round(distance, 3)))


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
