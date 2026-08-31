"""Interactive, isolated railway-container calculation demo.

This module is intentionally not registered in ``src.demos.leader`` and does
not load local business workbooks, Tencent APIs, WebUI, or the formal route
pipeline.  Every record created here is labelled ``demo_placeholder``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Literal

from src.data.loaders import make_node_id
from src.domain.route_request import RouteRequest
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
    def total_cost_yuan(self) -> Decimal:
        return sum((edge.cost_yuan for edge in self.all_edges if edge.cost_yuan is not None), Decimal("0"))

    @property
    def total_time_hours(self) -> Decimal:
        return sum((edge.time_hours for edge in self.all_edges if edge.time_hours is not None), Decimal("0"))


def build_demo_result(data: RailContainerDemoInput) -> RailContainerDemoResult | RailCustomerDeliveryPlanResult:
    """Build one manually entered placeholder scenario without using real data."""
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

    terminal_provider = _terminal_provider(data, south_id, customer_id, scope)
    if data.terminal_plan_type == "direct_truck":
        terminal = terminal_provider.build_direct_truck(
            south_station_name=data.south_station_name,
            customer_name=data.customer_name,
            request=request,
            container_type=data.container_type,
        )
    elif data.terminal_plan_type == "customer_dedicated_siding":
        terminal = terminal_provider.build_customer_dedicated_siding(
            south_station_name=data.south_station_name,
            customer_name=data.customer_name,
            request=request,
            container_type=data.container_type,
        )
    else:
        terminal = terminal_provider.build_third_party_dedicated_siding(
            south_station_name=data.south_station_name,
            customer_name=data.customer_name,
            request=request,
            container_type=data.container_type,
        )
    return RailContainerDemoResult(trunk_edge, terminal)


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
    print("所有输入只生成 demo_placeholder 边；不读取真实业务数据，不进入全流程、Web 或正式图。")
    print("费用与时效请仅填入已人工确认、用于试验的数值。")
    try:
        data = _collect_input(input_func)
        result = build_demo_result(data)
    except (ValueError, InvalidOperation) as exc:
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
        return RailContainerDemoInput(
            **common,
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
    print("\n试算结果（全部为 demo_placeholder）")
    print("-" * 62)
    print(f"订单：{data.quantity_boxes}箱，{data.container_type}，{data.commodity}，{data.trade_type}")
    for index, edge in enumerate(result.all_edges, start=1):
        print(
            f"{index}. {edge.transport_mode} {edge.from_node_id} -> {edge.to_node_id}；"
            f"费用={edge.cost_yuan}元；时效={edge.time_hours}小时；"
            f"角色={edge.edge_role}；规则={edge.cost_rule_id}"
        )
        for component in edge.cost_components:
            print(f"   - {component.component_type}: {component.amount_yuan}元；来源={component.source_type}")
    print(f"总费用：{result.total_cost_yuan}元")
    print(f"总时效：{result.total_time_hours}小时")
    print(f"折合单箱费用：{result.total_cost_yuan / data.quantity_boxes}元/箱")
    print("注意：本结果仅用于算法验证，不是报价、运力承诺或正式路线推荐。")


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
