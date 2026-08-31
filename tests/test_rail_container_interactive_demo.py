from decimal import Decimal

from src.demos.rail_container_interactive_demo import RailContainerDemoInput, build_demo_result


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

    assert result.total_cost_yuan == Decimal("3530")
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
    assert result.total_cost_yuan == Decimal("3110")
    assert result.total_time_hours == Decimal("172")
