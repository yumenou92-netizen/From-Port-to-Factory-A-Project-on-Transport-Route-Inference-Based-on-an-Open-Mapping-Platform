from decimal import Decimal

from src.domain.route_request import RouteRequest
from src.routing.rail_container_provider import (
    RailContainerRateTimeRecord,
    RailContainerTimeRegion,
    TableRailContainerProvider,
    TableRailContainerTimeProvider,
)


def record(**overrides):
    values = {
        "north_station_name": "北站A",
        "south_station_name": "南站A",
        "north_station_node_id": "north-station-a",
        "south_station_node_id": "south-station-a",
        "commodity_scope": ("玉米", "小麦"),
        "trade_type": "内贸",
        "container_type": "敞顶箱",
        "base_freight_yuan_per_box": Decimal("1000"),
        "discount_ratio": Decimal("0.1"),
        "origin_station_fee_yuan_per_box": Decimal("195"),
        "destination_station_fee_yuan_per_box": Decimal("195"),
        "duration_hours": Decimal("168"),
        "source": "test_fixture:rail-container",
        "source_type": "demo_placeholder",
    }
    values.update(overrides)
    return RailContainerRateTimeRecord(**values)


def test_rail_container_provider_builds_traceable_placeholder_trunk_edge():
    provider = TableRailContainerProvider((record(),))
    edge, match = provider.build_edge(
        north_station_name="北站A",
        south_station_name="南站A",
        request=RouteRequest(2, "箱", "集装箱", "玉米", trade_type="内贸"),
        container_type="敞顶箱",
    )

    assert match.status == "resolved"
    assert edge is not None
    assert edge.transport_mode == "铁路"
    assert edge.transport_stage == "north_to_south"
    assert edge.edge_role == "trunk"
    assert edge.time_hours == Decimal("168")
    assert edge.cost_yuan == Decimal("2630")
    assert edge.data_source.startswith("demo_placeholder:")
    assert edge.time_source.startswith("demo_placeholder:")
    assert [item.component_type for item in edge.cost_components] == [
        "railway_freight",
        "origin_station_fee",
        "destination_station_fee",
        "open_top_tarpaulin_fee",
    ]
    assert all(item.source_type == "demo_placeholder" for item in edge.cost_components)


def test_rail_container_provider_does_not_convert_cabinet_or_use_missing_record():
    provider = TableRailContainerProvider((record(),))
    edge, match = provider.build_edge(
        north_station_name="北站A",
        south_station_name="南站A",
        request=RouteRequest(1, "柜", "集装箱", "玉米", trade_type="内贸"),
        container_type="敞顶箱",
    )

    assert edge is None
    assert match.status == "not_applicable"
    assert "不得自动换算" in match.message


def test_rail_container_provider_top_door_box_excludes_tarpaulin_fee():
    provider = TableRailContainerProvider((record(container_type="顶开门箱", duration_hours=Decimal("192")),))
    edge, match = provider.build_edge(
        north_station_name="北站A",
        south_station_name="南站A",
        request=RouteRequest(1, "箱", "集装箱", "小麦", trade_type="内贸"),
        container_type="顶开门箱",
    )

    assert match.status == "resolved"
    assert edge is not None
    assert edge.cost_yuan == Decimal("1290")
    assert "open_top_tarpaulin_fee" not in {item.component_type for item in edge.cost_components}


def test_rail_container_record_rejects_unknown_station_fee_or_invalid_discount():
    try:
        record(origin_station_fee_yuan_per_box=Decimal("0"))
    except ValueError as exc:
        assert "上站费" in str(exc)
    else:
        raise AssertionError("zero station fee must not form a rail edge")

    try:
        record(discount_ratio=Decimal("1"))
    except ValueError as exc:
        assert "下浮比例" in str(exc)
    else:
        raise AssertionError("100 percent discount must not form a rail edge")


def test_rail_container_time_provider_uses_only_confirmed_exact_region_mapping():
    provider = TableRailContainerTimeProvider(
        (
            RailContainerTimeRegion("东北", "福建", Decimal("168"), "business_confirmed:2026-08-20"),
            RailContainerTimeRegion("东北", "广东", Decimal("192"), "business_confirmed:2026-08-20"),
            RailContainerTimeRegion("东北", "广西", Decimal("192"), "business_confirmed:2026-08-20"),
        )
    )

    assert provider.match(origin_region="东北", destination_region="福建").duration_hours == Decimal("168")
    assert provider.match(origin_region="东北", destination_region="广东").duration_hours == Decimal("192")
    assert provider.match(origin_region="东北", destination_region="海南") is None
