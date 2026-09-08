"""Interactive railway-container calculation demo.

The demo stays outside the formal full-flow pipeline, but deliberately reuses
the project's common last-mile capability when the terminal plan is direct
truck delivery: local-node-first coordinate resolution, Tencent ordinary
driving distance/time, and the confirmed railway terminal truck rule.

Railway trunk prices, station fees, dedicated-siding records, and other
unmaintained business inputs remain isolated test inputs.  They are always
labelled ``demo_placeholder`` and are never written back into formal data.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Literal

from src.data.loaders import DataLoadError, data_dir_from_env, load_real_data_bundle, make_node_id
from src.dev.runtime_env import RuntimeEnvError, load_runtime_env
from src.domain.route_request import RouteRequest
from src.geo.coordinate_provider import CoordinateProvider, CoordinateResolution, LocalFirstCoordinateProvider
from src.geo.distance_provider import GeoPoint, RoadRouteProvider, RoadRouteRequest
from src.geo.tencent_map_provider import (
    TencentMapCoordinateProvider,
    TencentMapDrivingRouteProvider,
    TencentMapProviderError,
)
from src.routing.rail_container_provider import RailContainerRateTimeRecord, TableRailContainerProvider
from src.routing.rail_customer_delivery_provider import (
    CustomerDedicatedSidingRecord,
    DirectTruckDeliveryRecord,
    RailCustomerDeliveryPlanResult,
    RailCustomerDeliveryProvider,
    RailTerminalScope,
    ThirdPartyDedicatedSidingRecord,
)
from src.routing.transport_edge import TransportEdge


TerminalPlanType = Literal["direct_truck", "customer_dedicated_siding", "third_party_dedicated_siding"]
DirectTruckInputMode = Literal["auto_geo", "manual"]


@dataclass(frozen=True)
class RailContainerDemoInput:
    north_station_name: str
    south_station_name: str
    customer_name: str
    commodity: str
    trade_type: str
    container_type: Literal["顶开门箱", "敞顶箱"]
    quantity_boxes: Decimal
    trunk_base_freight_yuan_per_box: Decimal
    trunk_discount_ratio: Decimal
    origin_station_fee_yuan_per_box: Decimal
    destination_station_fee_yuan_per_box: Decimal
    trunk_duration_hours: Decimal
    terminal_plan_type: TerminalPlanType
    direct_truck_input_mode: DirectTruckInputMode = "manual"
    geo_region: str = "全国"
    terminal_distance_km: Decimal | None = None
    terminal_duration_hours: Decimal | None = None
    terminal_unit_fee_yuan_per_box: Decimal | None = None
    third_party_name: str | None = None
    third_party_rail_unit_fee_yuan_per_box: Decimal | None = None
    third_party_rail_duration_hours: Decimal | None = None
    third_party_delivery_transport_mode: Literal["汽运", "铁路"] | None = None
    third_party_delivery_unit_fee_yuan_per_box: Decimal | None = None
    third_party_delivery_duration_hours: Decimal | None = None


@dataclass(frozen=True)
class RailContainerDemoResult:
    trunk_edge: TransportEdge
    terminal_result: RailCustomerDeliveryPlanResult

    @property
    def all_edges(self) -> tuple[TransportEdge, ...]:
        return (self.trunk_edge, *self.terminal_result.edges)

    @property
    def is_complete(self) -> bool:
        """Whether the requested terminal plan formed every required edge."""
        return self.terminal_result.status == "resolved"

    @property
    def total_cost_yuan(self) -> Decimal:
        return sum((edge.cost_yuan for edge in self.all_edges if edge.cost_yuan is not None), Decimal("0"))

    @property
    def total_time_hours(self) -> Decimal:
        return sum((edge.time_hours for edge in self.all_edges if edge.time_hours is not None), Decimal("0"))


def build_demo_result(
    data: RailContainerDemoInput,
    *,
    coordinate_provider: CoordinateProvider | None = None,
    local_station_coordinate_provider: CoordinateProvider | None = None,
    road_route_provider: RoadRouteProvider | None = None,
) -> RailContainerDemoResult | RailCustomerDeliveryPlanResult:
    """Build one isolated railway-container scenario.

    The trunk remains a manually supplied ``demo_placeholder``.  In
    ``auto_geo`` direct-truck mode, only the terminal road segment is built
    from shared coordinate/road providers; unavailable external results stop
    that segment in ``manual_review`` rather than falling back to zero.
    """
    request = RouteRequest(
        quantity=data.quantity_boxes,
        quantity_unit="箱",
        package_type="集装箱",
        commodity=data.commodity,
        trade_type=data.trade_type,
    )
    north_id = make_node_id(data.north_station_name)
    south_id = make_node_id(data.south_station_name)
    customer_id = make_node_id(data.customer_name)
    scope = RailTerminalScope(
        commodity_scope=(data.commodity,),
        trade_type=data.trade_type,
        container_type=data.container_type,
        source="interactive_rail_container_demo",
        source_type="demo_placeholder",
    )
    trunk_provider = TableRailContainerProvider(
        (
            RailContainerRateTimeRecord(
                north_station_name=data.north_station_name,
                south_station_name=data.south_station_name,
                north_station_node_id=north_id,
                south_station_node_id=south_id,
                commodity_scope=(data.commodity,),
                trade_type=data.trade_type,
                container_type=data.container_type,
                base_freight_yuan_per_box=data.trunk_base_freight_yuan_per_box,
                discount_ratio=data.trunk_discount_ratio,
                origin_station_fee_yuan_per_box=data.origin_station_fee_yuan_per_box,
                destination_station_fee_yuan_per_box=data.destination_station_fee_yuan_per_box,
                duration_hours=data.trunk_duration_hours,
                source="interactive_rail_container_demo",
                source_type="demo_placeholder",
            ),
        )
    )
    trunk_edge, trunk_match = trunk_provider.build_edge(
        north_station_name=data.north_station_name,
        south_station_name=data.south_station_name,
        request=request,
        container_type=data.container_type,
    )
    if trunk_edge is None:
        return RailCustomerDeliveryPlanResult(
            "direct_truck",
            trunk_match.status,
            f"演示干线未能构边：{trunk_match.message}",
        )

    if data.terminal_plan_type == "direct_truck":
        if data.direct_truck_input_mode == "auto_geo":
            terminal = _build_auto_geo_direct_truck(
                data=data,
                request=request,
                fallback_south_id=south_id,
                fallback_customer_id=customer_id,
                coordinate_provider=coordinate_provider,
                local_station_coordinate_provider=local_station_coordinate_provider,
                road_route_provider=road_route_provider,
            )
            return RailContainerDemoResult(trunk_edge, terminal)
        terminal_provider = _terminal_provider(data, south_id, customer_id, scope)
        terminal = terminal_provider.build_direct_truck(
            south_station_name=data.south_station_name,
            customer_name=data.customer_name,
            request=request,
            container_type=data.container_type,
        )
    elif data.terminal_plan_type == "customer_dedicated_siding":
        terminal_provider = _terminal_provider(data, south_id, customer_id, scope)
        terminal = terminal_provider.build_customer_dedicated_siding(
            south_station_name=data.south_station_name,
            customer_name=data.customer_name,
            request=request,
            container_type=data.container_type,
        )
    else:
        terminal_provider = _terminal_provider(data, south_id, customer_id, scope)
        terminal = terminal_provider.build_third_party_dedicated_siding(
            south_station_name=data.south_station_name,
            customer_name=data.customer_name,
            request=request,
            container_type=data.container_type,
        )
    return RailContainerDemoResult(trunk_edge, terminal)


def _build_auto_geo_direct_truck(
    *,
    data: RailContainerDemoInput,
    request: RouteRequest,
    fallback_south_id: str,
    fallback_customer_id: str,
    coordinate_provider: CoordinateProvider | None,
    local_station_coordinate_provider: CoordinateProvider | None,
    road_route_provider: RoadRouteProvider | None,
) -> RailCustomerDeliveryPlanResult:
    """Build one direct-truck delivery edge from shared geo services."""
    if coordinate_provider is None or road_route_provider is None:
        return RailCustomerDeliveryPlanResult(
            "direct_truck",
            "manual_review",
            "自动末端汽运未配置坐标或道路 Provider；不能将缺失距离、时效补为 0。",
        )
    south = _resolve_rail_station_coordinate(
        fallback_provider=coordinate_provider,
        local_provider=local_station_coordinate_provider,
        station_name=data.south_station_name,
    )
    customer = coordinate_provider.resolve(data.customer_name)
    unresolved = [
        resolution.message
        for resolution in (south, customer)
        if not resolution.is_resolved
    ]
    if unresolved:
        return RailCustomerDeliveryPlanResult(
            "direct_truck",
            "manual_review",
            "自动末端汽运未形成：" + "；".join(unresolved),
        )
    assert south.longitude is not None and south.latitude is not None
    assert customer.longitude is not None and customer.latitude is not None
    route = road_route_provider.get_route(
        RoadRouteRequest(
            origin=GeoPoint(Decimal(str(south.longitude)), Decimal(str(south.latitude))),
            destination=GeoPoint(Decimal(str(customer.longitude)), Decimal(str(customer.latitude))),
        )
    )
    if not route.is_resolved:
        return RailCustomerDeliveryPlanResult(
            "direct_truck",
            "manual_review",
            f"自动末端汽运未形成：{route.message}",
        )
    assert route.distance_km is not None and route.duration_hours is not None
    scope = RailTerminalScope(
        commodity_scope=(data.commodity,),
        trade_type=data.trade_type,
        container_type=data.container_type,
        source=(
            f"南站坐标={south.source}；客户坐标={customer.source}；"
            f"道路距离与时效={route.source}；铁路末端拖车规则=confirmed"
        ),
        source_type="real_data",
    )
    provider = RailCustomerDeliveryProvider(
        direct_truck_records=(
            DirectTruckDeliveryRecord(
                data.south_station_name,
                south.node_id or fallback_south_id,
                data.customer_name,
                customer.node_id or fallback_customer_id,
                scope,
                route.distance_km,
                route.source,
                route.duration_hours,
                route.source,
            ),
        ),
    )
    return provider.build_direct_truck(
        south_station_name=data.south_station_name,
        customer_name=data.customer_name,
        request=request,
        container_type=data.container_type,
    )


def _resolve_rail_station_coordinate(
    *,
    fallback_provider: CoordinateProvider,
    local_provider: CoordinateProvider | None,
    station_name: str,
) -> CoordinateResolution:
    """Resolve a railway-station shorthand without changing generic place rules.

    Railway master data and display control points may respectively include or
    omit the ``站`` suffix.  Try the entered name first, then the conventional
    suffix only if it is absent and the first lookup is unresolved.
    """
    resolution = (local_provider or fallback_provider).resolve(station_name)
    if resolution.is_resolved or station_name.endswith("站"):
        return resolution
    station_resolution = (local_provider or fallback_provider).resolve(f"{station_name}站")
    if station_resolution.is_resolved:
        return station_resolution
    return fallback_provider.resolve(station_name) if local_provider is not None else resolution


def _terminal_provider(
    data: RailContainerDemoInput,
    south_id: str,
    customer_id: str,
    scope: RailTerminalScope,
) -> RailCustomerDeliveryProvider:
    if data.terminal_plan_type == "direct_truck":
        return RailCustomerDeliveryProvider(
            direct_truck_records=(
                DirectTruckDeliveryRecord(
                    data.south_station_name,
                    south_id,
                    data.customer_name,
                    customer_id,
                    scope,
                    _required_decimal(data.terminal_distance_km, "直达拖车距离"),
                    "interactive_demo_confirmed_distance",
                    _required_decimal(data.terminal_duration_hours, "直达拖车时效"),
                    "interactive_demo_confirmed_time",
                ),
            ),
        )
    if data.terminal_plan_type == "customer_dedicated_siding":
        return RailCustomerDeliveryProvider(
            customer_dedicated_siding_records=(
                CustomerDedicatedSidingRecord(
                    data.south_station_name,
                    south_id,
                    data.customer_name,
                    customer_id,
                    scope,
                    _required_decimal(data.terminal_unit_fee_yuan_per_box, "客户专用线单箱费用"),
                    _required_decimal(data.terminal_duration_hours, "客户专用线时效"),
                    "interactive_demo_confirmed_time",
                ),
            ),
        )
    third_party_name = _required_text(data.third_party_name, "第三方专用线名称")
    return RailCustomerDeliveryProvider(
        third_party_dedicated_siding_records=(
            ThirdPartyDedicatedSidingRecord(
                data.south_station_name,
                south_id,
                third_party_name,
                make_node_id(third_party_name),
                data.customer_name,
                customer_id,
                scope,
                _required_decimal(data.third_party_rail_unit_fee_yuan_per_box, "南站至第三方单箱铁路费用"),
                _required_decimal(data.third_party_rail_duration_hours, "南站至第三方铁路时效"),
                "interactive_demo_confirmed_time",
                data.third_party_delivery_transport_mode or "汽运",
                _required_decimal(data.third_party_delivery_unit_fee_yuan_per_box, "第三方至客户单箱交付费用"),
                _required_decimal(data.third_party_delivery_duration_hours, "第三方至客户交付时效"),
                "interactive_demo_confirmed_time",
            ),
        ),
    )


def main(input_func: Callable[[str], str] = input) -> None:
    print("铁路—集装箱交互式试算 Demo（隔离测试版）")
    print("=" * 62)
    print("干线试算参数只生成 demo_placeholder 边；不写入正式数据或正式图。")
    print("末端直达汽运默认复用本地节点、腾讯道路距离/时效和既有铁路拖车规则。")
    try:
        data = _collect_input(input_func)
        coordinate_provider, local_station_coordinate_provider, road_route_provider = _runtime_geo_providers(data)
        result = build_demo_result(
            data,
            coordinate_provider=coordinate_provider,
            local_station_coordinate_provider=local_station_coordinate_provider,
            road_route_provider=road_route_provider,
        )
    except (ValueError, InvalidOperation, DataLoadError, RuntimeEnvError, TencentMapProviderError) as exc:
        print(f"\n试算未完成：{exc}")
        return

    if isinstance(result, RailCustomerDeliveryPlanResult):
        print(f"\n试算未完成：{result.message}")
        return
    _print_result(data, result)


def _collect_input(input_func: Callable[[str], str]) -> RailContainerDemoInput:
    north = _ask_text(input_func, "北站名称")
    south = _ask_text(input_func, "南站名称")
    customer = _ask_text(input_func, "客户工厂名称")
    commodity = _ask_text(input_func, "粮食品种", "玉米")
    trade_type = _ask_choice(input_func, "贸易类型", {"1": "内贸", "2": "外贸"}, "1")
    container_type = _ask_choice(input_func, "箱型", {"1": "顶开门箱", "2": "敞顶箱"}, "2")
    quantity = _ask_decimal(input_func, "订单数量（箱）")
    base_freight = _ask_decimal(input_func, "北站至南站铁路基础运价（元/箱）")
    discount = _ask_decimal(input_func, "铁路下浮比例（例如 0.1；无下浮填 0）", allow_zero=True)
    origin_fee = _ask_decimal(input_func, "上站费（元/箱）")
    destination_fee = _ask_decimal(input_func, "下站费（元/箱）")
    trunk_time = _ask_decimal(input_func, "北站至南站完整时效（小时）")
    plan = _ask_choice(
        input_func,
        "南站至客户方案",
        {"1": "direct_truck", "2": "customer_dedicated_siding", "3": "third_party_dedicated_siding"},
        "1",
    )
    common = dict(
        north_station_name=north,
        south_station_name=south,
        customer_name=customer,
        commodity=commodity,
        trade_type=trade_type,
        container_type=container_type,
        quantity_boxes=quantity,
        trunk_base_freight_yuan_per_box=base_freight,
        trunk_discount_ratio=discount,
        origin_station_fee_yuan_per_box=origin_fee,
        destination_station_fee_yuan_per_box=destination_fee,
        trunk_duration_hours=trunk_time,
        terminal_plan_type=plan,
    )
    if plan == "direct_truck":
        input_mode = _ask_choice(
            input_func,
            "末端直达汽运数据来源",
            {"1": "auto_geo", "2": "manual"},
            "1",
        )
        if input_mode == "auto_geo":
            return RailContainerDemoInput(
                **common,
                direct_truck_input_mode="auto_geo",
                geo_region=_ask_text(input_func, "腾讯地点检索区域", "全国"),
            )
        return RailContainerDemoInput(
            **common,
            direct_truck_input_mode="manual",
            terminal_distance_km=_ask_decimal(input_func, "南站至客户确认道路距离（公里）"),
            terminal_duration_hours=_ask_decimal(input_func, "南站至客户驾车时效（小时）"),
        )
    if plan == "customer_dedicated_siding":
        return RailContainerDemoInput(
            **common,
            terminal_unit_fee_yuan_per_box=_ask_decimal(input_func, "客户专用线费用（元/箱）"),
            terminal_duration_hours=_ask_decimal(input_func, "客户专用线完整时效（小时）"),
        )
    return RailContainerDemoInput(
        **common,
        third_party_name=_ask_text(input_func, "第三方专用线名称"),
        third_party_rail_unit_fee_yuan_per_box=_ask_decimal(input_func, "南站至第三方铁路费用（元/箱）"),
        third_party_rail_duration_hours=_ask_decimal(input_func, "南站至第三方铁路时效（小时）"),
        third_party_delivery_transport_mode=_ask_choice(input_func, "第三方至客户交付方式", {"1": "汽运", "2": "铁路"}, "1"),
        third_party_delivery_unit_fee_yuan_per_box=_ask_decimal(input_func, "第三方至客户交付费用（元/箱）"),
        third_party_delivery_duration_hours=_ask_decimal(input_func, "第三方至客户交付时效（小时）"),
    )


def _print_result(data: RailContainerDemoInput, result: RailContainerDemoResult) -> None:
    print("\n试算结果（干线试算为 demo_placeholder；末端按实际来源分别展示）")
    print("-" * 62)
    print(f"订单：{data.quantity_boxes}箱，{data.container_type}，{data.commodity}，{data.trade_type}")
    for index, edge in enumerate(result.all_edges, start=1):
        print(
            f"{index}. {edge.transport_mode} {edge.from_node_id} -> {edge.to_node_id}；"
            f"费用={edge.cost_yuan}元；时效={edge.time_hours}小时；"
            f"角色={edge.edge_role}；规则={edge.cost_rule_id}"
        )
        for component in edge.cost_components:
            print(f"   - {component.component_type}: {component.amount_yuan}元；来源={component.source_type}；{component.source}")
    if not result.is_complete:
        print(f"\n末端方案未构边（{result.terminal_result.status}）：{result.terminal_result.message}")
        print(f"已构建干线小计：费用={result.trunk_edge.cost_yuan}元；时效={result.trunk_edge.time_hours}小时")
        print("本次未形成北站—南站—客户的完整链路，不输出全链路总费用、总时效或单箱费用。")
        return
    print(f"总费用：{result.total_cost_yuan}元")
    print(f"总时效：{result.total_time_hours}小时")
    print(f"折合单箱费用：{result.total_cost_yuan / data.quantity_boxes}元/箱")
    print("注意：干线费率、站点费与干线时效仍是试算输入；本结果不是正式报价、运力承诺或正式路线推荐。")


def _runtime_geo_providers(
    data: RailContainerDemoInput,
) -> tuple[CoordinateProvider | None, CoordinateProvider | None, RoadRouteProvider | None]:
    """Load common geo services only when auto direct-truck mode asks for them."""
    if data.terminal_plan_type != "direct_truck" or data.direct_truck_input_mode != "auto_geo":
        return None, None, None
    load_runtime_env()
    bundle = load_real_data_bundle(data_dir_from_env())
    local_provider = LocalFirstCoordinateProvider(bundle.node_registry)
    coordinate_provider = LocalFirstCoordinateProvider(
        bundle.node_registry,
        fallback_provider=TencentMapCoordinateProvider.from_env(region=data.geo_region),
    )
    return coordinate_provider, local_provider, TencentMapDrivingRouteProvider.from_env()


def _ask_text(input_func: Callable[[str], str], label: str, default: str | None = None) -> str:
    suffix = f"（默认 {default}）" if default is not None else ""
    value = input_func(f"{label}{suffix}：").strip()
    return value or _required_text(default, label)


def _ask_choice(input_func: Callable[[str], str], label: str, options: dict[str, str], default: str) -> str:
    description = "；".join(f"{key}={value}" for key, value in options.items())
    selected = input_func(f"{label}（{description}；默认 {default}）：").strip() or default
    if selected not in options:
        raise ValueError(f"{label}必须选择：{'、'.join(options)}。")
    return options[selected]


def _ask_decimal(input_func: Callable[[str], str], label: str, *, allow_zero: bool = False) -> Decimal:
    text = input_func(f"{label}：").strip()
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{label}必须是数值。") from None
    if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
        qualifier = "大于等于 0" if allow_zero else "大于 0"
        raise ValueError(f"{label}必须{qualifier}。")
    return value


def _required_decimal(value: Decimal | None, label: str) -> Decimal:
    if value is None:
        raise ValueError(f"{label}不能为空。")
    return value


def _required_text(value: str | None, label: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{label}不能为空。")
    return text


if __name__ == "__main__":
    main()
