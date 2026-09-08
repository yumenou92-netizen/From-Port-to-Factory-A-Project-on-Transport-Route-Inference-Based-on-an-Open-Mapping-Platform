from decimal import Decimal

from src.demos.rail_container_interactive_demo import RailContainerDemoInput, build_demo_result
from src.geo.coordinate_provider import CoordinateResolution
from src.geo.distance_provider import RoadRouteResult


def base_input(**overrides):
    values = {
        "north_station_name": "北站A",
        "south_station_name": "南站A",
        "customer_name": "客户A",
        "commodity": "玉米",
        "trade_type": "内贸",
        "container_type": "敞顶箱",
        "quantity_boxes": Decimal("2"),
        "trunk_base_freight_yuan_per_box": Decimal("1000"),
        "trunk_discount_ratio": Decimal("0.1"),
        "origin_station_fee_yuan_per_box": Decimal("195"),
        "destination_station_fee_yuan_per_box": Decimal("195"),
        "trunk_duration_hours": Decimal("168"),
        "terminal_plan_type": "direct_truck",
        "terminal_distance_km": Decimal("10"),
        "terminal_duration_hours": Decimal("2"),
    }
    values.update(overrides)
    return RailContainerDemoInput(**values)


def test_interactive_demo_builds_isolated_direct_truck_placeholder_chain():
    result = build_demo_result(base_input())

    assert result.total_cost_yuan == Decimal("3980")
    assert result.total_time_hours == Decimal("170")
    assert [edge.edge_role for edge in result.all_edges] == ["trunk", "delivery"]
    assert all(edge.data_source.startswith("demo_placeholder:") for edge in result.all_edges)


def test_interactive_demo_keeps_third_party_terminal_as_two_explicit_edges():
    result = build_demo_result(
        base_input(
            terminal_plan_type="third_party_dedicated_siding",
            third_party_name="第三方专用线A",
            third_party_rail_unit_fee_yuan_per_box=Decimal("160"),
            third_party_rail_duration_hours=Decimal("3"),
            third_party_delivery_transport_mode="汽运",
            third_party_delivery_unit_fee_yuan_per_box=Decimal("80"),
            third_party_delivery_duration_hours=Decimal("1"),
        )
    )

    assert [edge.edge_role for edge in result.all_edges] == ["trunk", "transfer", "delivery"]
    assert result.total_cost_yuan == Decimal("3560")
    assert result.total_time_hours == Decimal("172")


class FakeCoordinateProvider:
    def resolve(self, name: str) -> CoordinateResolution:
        values = {
            "南站A": ("rail_south_a", 113.0, 23.0),
            "客户A": ("customer_a", 113.2, 23.2),
        }
        node_id, longitude, latitude = values[name]
        return CoordinateResolution(
            status="resolved",
            query_name=name,
            node_id=node_id,
            canonical_name=name,
            longitude=longitude,
            latitude=latitude,
            source="node_registry",
            message="测试本地节点。",
        )


class FakeRailStationSuffixCoordinateProvider(FakeCoordinateProvider):
    def resolve(self, name: str) -> CoordinateResolution:
        if name == "南站简称":
            return CoordinateResolution(
                status="manual_review",
                query_name=name,
                node_id=None,
                canonical_name=None,
                longitude=None,
                latitude=None,
                source="missing_local_coordinate",
                message="原始简称未命中。",
            )
        if name == "南站简称站":
            return super().resolve("南站A")
        return super().resolve(name)


class FakeRoadRouteProvider:
    def get_route(self, request) -> RoadRouteResult:
        return RoadRouteResult(
            status="resolved",
            distance_km=Decimal("25"),
            duration_hours=Decimal("1.5"),
            source="tencent_map_driving_route",
            message="测试道路结果。",
        )


def test_interactive_demo_reuses_geo_and_confirmed_terminal_truck_rule():
    result = build_demo_result(
        base_input(direct_truck_input_mode="auto_geo", terminal_distance_km=None, terminal_duration_hours=None),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
    )

    assert result.total_cost_yuan == Decimal("4260")
    assert result.total_time_hours == Decimal("169.5")
    assert result.all_edges[0].data_source.startswith("demo_placeholder:")
    delivery = result.all_edges[1]
    assert delivery.from_node_id == "rail_south_a"
    assert delivery.to_node_id == "customer_a"
    assert delivery.distance_km == Decimal("25")
    assert delivery.time_hours == Decimal("1.5")
    assert delivery.data_source.startswith("南站坐标=node_registry")


def test_interactive_demo_does_not_fabricate_auto_geo_failure():
    result = build_demo_result(base_input(direct_truck_input_mode="auto_geo"))

    assert not result.is_complete
    assert result.terminal_result.status == "manual_review"
    assert result.terminal_result.edges == ()


def test_interactive_demo_accepts_rail_station_shorthand_for_local_lookup():
    result = build_demo_result(
        base_input(
            south_station_name="南站简称",
            direct_truck_input_mode="auto_geo",
            terminal_distance_km=None,
            terminal_duration_hours=None,
        ),
        coordinate_provider=FakeRailStationSuffixCoordinateProvider(),
        local_station_coordinate_provider=FakeRailStationSuffixCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
    )

    assert result.is_complete
    assert result.all_edges[1].from_node_id == "rail_south_a"
