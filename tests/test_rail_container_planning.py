from decimal import Decimal

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
    CustomerDedicatedSidingRecord,
    DirectTruckDeliveryRecord,
    RailCustomerDeliveryProvider,
    RailTerminalScope,
    ThirdPartyDedicatedSidingRecord,
)


def _registry():
    return build_node_registry(
        (
            NodeRecord(make_node_id("北站"), "北站", 122.0, 46.0),
            NodeRecord(make_node_id("经济南站"), "经济南站", 113.0, 23.0),
            NodeRecord(make_node_id("快速南站"), "快速南站", 114.0, 24.0),
            NodeRecord(make_node_id("客户"), "客户", 113.1, 23.1),
            NodeRecord(make_node_id("第三方专用线"), "第三方专用线", 113.2, 23.2),
        ),
        auto_alias=False,
    )


def _request(**overrides):
    values = {
        "north_station_name": "北站",
        "customer_name": "客户",
        "request": RouteRequest(Decimal("10"), "箱", "集装箱", "玉米", trade_type="内贸"),
        "container_type": "敞顶箱",
    }
    values.update(overrides)
    return RailContainerPlanningRequest(**values)


def _trunk(south: str, *, fee: str, duration: str):
    return RailContainerRateTimeRecord(
        north_station_name="北站",
        south_station_name=south,
        north_station_node_id=make_node_id("北站"),
        south_station_node_id=make_node_id(south),
        commodity_scope=("玉米",),
        trade_type="内贸",
        container_type="敞顶箱",
        base_freight_yuan_per_box=Decimal(fee),
        discount_ratio=Decimal("0"),
        origin_station_fee_yuan_per_box=Decimal("10"),
        destination_station_fee_yuan_per_box=Decimal("10"),
        duration_hours=Decimal(duration),
        source="test_fixture",
        source_type="demo_placeholder",
    )


def _delivery(south: str, *, duration: str):
    return DirectTruckDeliveryRecord(
        south,
        make_node_id(south),
        "客户",
        make_node_id("客户"),
        RailTerminalScope(("玉米",), "内贸", "敞顶箱", "test_fixture", "demo_placeholder"),
        Decimal("10"),
        "test_distance",
        Decimal(duration),
        "test_time",
    )


def _service(deliveries=()):
    return RailContainerPlanningService(
        RailContainerPlanningData(
            node_registry=_registry(),
            trunk_provider=TableRailContainerProvider(
                (_trunk("经济南站", fee="100", duration="192"), _trunk("快速南站", fee="200", duration="168"))
            ),
            terminal_provider=RailCustomerDeliveryProvider(direct_truck_records=deliveries),
        )
    )


def test_platform_service_builds_parallel_rail_routes_and_searches_each_objective():
    response = _service((_delivery("经济南站", duration="2"), _delivery("快速南站", duration="1"))).plan(_request())

    assert response.graph_edge_count == 4
    assert [item.status for item in response.candidate_outcomes if item.terminal_plan_type == "direct_truck"] == ["included", "included"]
    assert response.recommendations.lowest_cost.status == "resolved"
    assert response.recommendations.fastest_time.status == "resolved"
    assert response.recommendations.lowest_cost.path_node_ids[1] == make_node_id("经济南站")
    assert response.recommendations.fastest_time.path_node_ids[1] == make_node_id("快速南站")


def test_platform_service_excludes_a_south_station_without_complete_terminal_data():
    response = _service((_delivery("经济南站", duration="2"),)).plan(_request())

    assert response.graph_edge_count == 2
    assert response.candidate_outcomes[0].status == "included"
    assert response.candidate_outcomes[1].status == "manual_review"
    assert response.recommendations.lowest_cost.path_node_ids[1] == make_node_id("经济南站")


def test_platform_service_honors_an_explicit_south_station_without_proxying():
    response = _service((_delivery("快速南站", duration="1"),)).plan(
        _request(south_station_name="快速南站")
    )

    assert response.graph_edge_count == 2
    assert {item.south_station_name for item in response.candidate_outcomes} == {"快速南站"}


def test_platform_service_adds_each_complete_terminal_plan_as_parallel_edges():
    scope = RailTerminalScope(("玉米",), "内贸", "敞顶箱", "test_fixture", "demo_placeholder")
    provider = RailCustomerDeliveryProvider(
        direct_truck_records=(_delivery("经济南站", duration="2"),),
        customer_dedicated_siding_records=(
            CustomerDedicatedSidingRecord(
                "经济南站", make_node_id("经济南站"), "客户", make_node_id("客户"),
                scope, Decimal("100"), Decimal("3"), "test_time",
            ),
        ),
        third_party_dedicated_siding_records=(
            ThirdPartyDedicatedSidingRecord(
                "经济南站", make_node_id("经济南站"), "第三方专用线", make_node_id("第三方专用线"),
                "客户", make_node_id("客户"), scope, Decimal("80"), Decimal("2"), "test_time",
                "汽运", Decimal("50"), Decimal("1"), "test_time",
            ),
        ),
    )
    response = RailContainerPlanningService(
        RailContainerPlanningData(_registry(), TableRailContainerProvider((_trunk("经济南站", fee="100", duration="192"),)), provider)
    ).plan(_request())

    assert response.graph_edge_count == 5
    assert {item.terminal_plan_type for item in response.candidate_outcomes if item.status == "included"} == {
        "direct_truck", "customer_dedicated_siding", "third_party_dedicated_siding",
    }
