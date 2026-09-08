"""Run a platform-style, data-driven railway-container graph demo.

The JSON file intentionally separates a user request from table-like node,
trunk-rate and terminal-delivery records.  It is a sanitized fixture, not a
real rate source; a future platform adapter can construct the same typed
objects without changing the application service or graph/search code.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.application.rail_container_planning import (
    RailContainerPlanningData,
    RailContainerPlanningRequest,
    RailContainerPlanningService,
)
from src.data.loaders import NodeRecord, make_node_id
from src.domain.node_registry import build_node_registry
from src.domain.route_request import RouteRequest
from src.routing.rail_container_provider import RailContainerRateTimeRecord, TableRailContainerProvider
from src.routing.rail_customer_delivery_provider import (
    DirectTruckDeliveryRecord,
    RailCustomerDeliveryProvider,
    RailTerminalScope,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "sample_data" / "rail_container_platform_demo.json"


def load_platform_demo(path: str | Path) -> tuple[RailContainerPlanningRequest, RailContainerPlanningData]:
    """Parse the sanitized platform-fixture schema into application objects."""
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("平台演示输入必须是 JSON 对象。")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("平台演示输入必须提供非空 nodes。")
    registry = build_node_registry(
        tuple(
            NodeRecord(make_node_id(_text(row, "name")), _text(row, "name"), float(row["longitude"]), float(row["latitude"]))
            for row in nodes
        ),
        auto_alias=False,
    )
    request_payload = _object(payload, "request")
    order = RouteRequest(
        quantity=_decimal(request_payload, "quantityBoxes"),
        quantity_unit=_text(request_payload, "quantityUnit"),
        package_type=_text(request_payload, "packageType"),
        commodity=_text(request_payload, "commodity"),
        trade_type=_text(request_payload, "tradeType"),
    )
    request = RailContainerPlanningRequest(
        north_station_name=_text(request_payload, "northStation"),
        customer_name=_text(request_payload, "customerFactory"),
        south_station_name=_optional_text(request_payload.get("southStation")),
        request=order,
        container_type=_text(request_payload, "containerType"),
    )
    trunk_records = tuple(_trunk_record(row, registry, source_path.name) for row in _rows(payload, "trunkRates"))
    direct_records = tuple(_direct_record(row, registry, source_path.name) for row in _rows(payload, "directTruckDeliveries"))
    return request, RailContainerPlanningData(
        node_registry=registry,
        trunk_provider=TableRailContainerProvider(trunk_records),
        terminal_provider=RailCustomerDeliveryProvider(direct_truck_records=direct_records),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="铁路—集装箱平台式构图与双目标搜索 Demo")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="脱敏平台请求与数据快照 JSON")
    args = parser.parse_args()
    request, data = load_platform_demo(args.input)
    response = RailContainerPlanningService(data).plan(request)
    print("铁路—集装箱平台式全链路 Demo（脱敏数据夹具）")
    print("=" * 62)
    print(f"请求：北站={request.north_station_name}；客户={request.customer_name}；南站={request.south_station_name or '自动候选'}")
    print(f"订单：{request.request.quantity}箱，{request.container_type}，{request.request.commodity}，{request.request.trade_type}")
    print(f"正式搜索图运输边：{response.graph_edge_count} 条")
    print("候选南站准入：")
    for item in response.candidate_outcomes:
        print(f"- {item.south_station_name}：{item.status}；{item.message}")
    for warning in response.warnings:
        print(f"运行提示：{warning}")
    _print_route("费用最低", response.recommendations.lowest_cost, data.node_registry)
    _print_route("时间最短", response.recommendations.fastest_time, data.node_registry)
    print("说明：夹具中的费率/时效均为 demo_placeholder；正式数据接入时仅替换数据 Adapter，不替换构边、图或搜索算法。")


def _print_route(title: str, result: Any, registry: Any) -> None:
    print(f"\n{title}：{result.status}")
    if result.status != "resolved":
        print(f"  {result.explanation}")
        return
    names = " -> ".join(registry.nodes[node_id].canonical_name for node_id in result.path_node_ids)
    print(f"  路径：{names}")
    print(f"  总费用：{result.total_cost_yuan}元；总时效：{result.total_time_hours}小时")
    for segment in result.segments:
        print(f"  - {segment.transport_mode}：{segment.cost_yuan}元，{segment.time_hours}小时，角色={segment.edge_role}")


def _trunk_record(row: dict[str, Any], registry: Any, source: str) -> RailContainerRateTimeRecord:
    north = _text(row, "northStation")
    south = _text(row, "southStation")
    return RailContainerRateTimeRecord(
        north_station_name=north,
        south_station_name=south,
        north_station_node_id=registry.require(north).node_id,
        south_station_node_id=registry.require(south).node_id,
        commodity_scope=tuple(_rows_text(row, "commodities")),
        trade_type=_text(row, "tradeType"),
        container_type=_text(row, "containerType"),
        base_freight_yuan_per_box=_decimal(row, "baseFreightYuanPerBox"),
        discount_ratio=_decimal(row, "discountRatio"),
        origin_station_fee_yuan_per_box=_decimal(row, "originStationFeeYuanPerBox"),
        destination_station_fee_yuan_per_box=_decimal(row, "destinationStationFeeYuanPerBox"),
        duration_hours=_decimal(row, "durationHours"),
        source=f"platform_demo_fixture:{source}",
        source_type="demo_placeholder",
    )


def _direct_record(row: dict[str, Any], registry: Any, source: str) -> DirectTruckDeliveryRecord:
    south = _text(row, "southStation")
    customer = _text(row, "customerFactory")
    scope = RailTerminalScope(
        commodity_scope=tuple(_rows_text(row, "commodities")),
        trade_type=_text(row, "tradeType"),
        container_type=_text(row, "containerType"),
        source=f"platform_demo_fixture:{source}",
        source_type="demo_placeholder",
    )
    return DirectTruckDeliveryRecord(
        south,
        registry.require(south).node_id,
        customer,
        registry.require(customer).node_id,
        scope,
        _decimal(row, "distanceKm"),
        "demo_placeholder:platform_direct_truck_distance",
        _decimal(row, "durationHours"),
        "demo_placeholder:platform_direct_truck_time",
    )


def _object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field}必须是对象。")
    return value


def _rows(payload: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{field}必须是数组。")
    if not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{field}每项必须是对象。")
    return value


def _text(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field, "")).strip()
    if not value:
        raise ValueError(f"{field}不能为空。")
    return value


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _rows_text(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field}必须是非空数组。")
    return [_text({field: item}, field) for item in value]


def _decimal(payload: dict[str, Any], field: str) -> Decimal:
    try:
        value = Decimal(str(payload[field]))
    except (KeyError, ValueError, InvalidOperation):
        raise ValueError(f"{field}必须是有限数值。") from None
    if not value.is_finite():
        raise ValueError(f"{field}必须是有限数值。")
    return value


if __name__ == "__main__":
    main()
