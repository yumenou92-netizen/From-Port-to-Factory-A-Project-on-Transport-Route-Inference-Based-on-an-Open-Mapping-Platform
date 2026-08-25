from decimal import Decimal

from src.geo.distance_provider import GeoPoint
from src.web.route_geometry import (
    SCHEMATIC_SOURCE,
    build_barge_schematic,
    build_bulk_shipping_schematic,
)
from src.web.route_control_points import (
    ControlPointRoute,
    RouteControlPointNetwork,
)


def test_guangxi_bulk_shipping_schematic_uses_qiongzhou_strait():
    origin = GeoPoint(longitude=Decimal("121.72"), latitude=Decimal("39.02"))
    destination = GeoPoint(
        longitude=Decimal("108.65"),
        latitude=Decimal("21.75"),
    )

    geometry = build_bulk_shipping_schematic(
        origin,
        destination,
        destination_name="钦州港",
    )

    assert geometry.kind == "bulk_shipping_schematic"
    assert geometry.source == SCHEMATIC_SOURCE
    assert geometry.is_schematic is True
    assert geometry.points[0] == origin
    assert geometry.points[-1] == destination
    qiongzhou_points = [
        point
        for point in geometry.points[1:-1]
        if (
            Decimal("109.5") <= point.longitude <= Decimal("110.6")
            and Decimal("20.1") <= point.latitude <= Decimal("20.4")
        )
    ]
    assert qiongzhou_points
    assert all(point.latitude >= Decimal("20.1") for point in geometry.points[1:-1])
    assert "经琼州海峡进入北部湾" in geometry.message
    assert "不代表真实航道" in geometry.message


def test_bulk_shipping_coastal_corridor_stays_nearer_mainland():
    origin = GeoPoint(longitude=Decimal("121.72"), latitude=Decimal("39.02"))
    destination = GeoPoint(
        longitude=Decimal("113.58"),
        latitude=Decimal("22.72"),
    )

    geometry = build_bulk_shipping_schematic(
        origin,
        destination,
        destination_name="广州南沙港",
    )

    east_china_sea_points = [
        point
        for point in geometry.points
        if Decimal("27") <= point.latitude <= Decimal("34")
    ]
    south_china_sea_points = [
        point
        for point in geometry.points
        if Decimal("21") <= point.latitude < Decimal("24")
    ]
    assert east_china_sea_points
    assert max(point.longitude for point in east_china_sea_points) <= Decimal("122.5")
    assert south_china_sea_points
    assert min(point.latitude for point in south_china_sea_points) >= Decimal("21.2")


def test_bulk_shipping_coastal_corridor_keeps_ningbo_section_offshore():
    origin = GeoPoint(longitude=Decimal("121.72"), latitude=Decimal("39.02"))
    destination = GeoPoint(
        longitude=Decimal("108.65"),
        latitude=Decimal("21.75"),
    )

    geometry = build_bulk_shipping_schematic(
        origin,
        destination,
        destination_name="Qinzhou Port",
    )

    ningbo_latitude_points = [
        point
        for point in geometry.points
        if Decimal("29") <= point.latitude <= Decimal("30")
    ]
    assert ningbo_latitude_points
    assert min(point.longitude for point in ningbo_latitude_points) >= Decimal("122.4")


def test_fujian_bulk_shipping_schematic_approaches_from_offshore():
    origin = GeoPoint(longitude=Decimal("121.72"), latitude=Decimal("39.02"))
    destination = GeoPoint(
        longitude=Decimal("117.72"),
        latitude=Decimal("24.42"),
    )

    geometry = build_bulk_shipping_schematic(
        origin,
        destination,
        destination_name="漳州港",
    )

    approach = geometry.points[-2]
    assert approach.longitude > destination.longitude
    assert geometry.points[-1] == destination


def test_bulk_shipping_schematic_accepts_human_control_points():
    origin = GeoPoint(longitude=Decimal("121"), latitude=Decimal("39"))
    destination = GeoPoint(longitude=Decimal("113"), latitude=Decimal("22"))
    manual_point = GeoPoint(longitude=Decimal("122"), latitude=Decimal("30"))

    geometry = build_bulk_shipping_schematic(
        origin,
        destination,
        control_points=(manual_point,),
    )

    assert geometry.points == (origin, manual_point, destination)
    assert "manual_control_points" in geometry.source
    assert "人工控制点校正" in geometry.message


def test_bulk_shipping_schematic_uses_loaded_control_point_network(tmp_path):
    network = _control_point_network(tmp_path)
    origin = GeoPoint(longitude=Decimal("120.1"), latitude=Decimal("30.1"))
    destination = GeoPoint(longitude=Decimal("116.1"), latitude=Decimal("22.1"))

    geometry = build_bulk_shipping_schematic(
        origin,
        destination,
        control_point_network=network,
    )

    assert geometry.points[0] == origin
    assert geometry.points[-1] == destination
    assert geometry.points[1] == _point("120", "30")
    assert "route_control_points_json/test-1" in geometry.source
    assert "实际端点连接至最近航线控制点" in geometry.message


def test_barge_schematic_uses_loaded_inland_control_point_network(tmp_path):
    network = _control_point_network(tmp_path)
    origin = GeoPoint(longitude=Decimal("113.1"), latitude=Decimal("23.1"))
    destination = GeoPoint(longitude=Decimal("109.1"), latitude=Decimal("23.1"))

    geometry = build_barge_schematic(
        origin,
        destination,
        control_point_network=network,
    )

    assert geometry.points[0] == origin
    assert geometry.points[-1] == destination
    assert _point("113", "23") in geometry.points
    assert _point("109", "23") in geometry.points
    assert "routes=ROUTE_004" in geometry.source
    assert "最近内河控制点" in geometry.message


def _control_point_network(tmp_path):
    return RouteControlPointNetwork(
        source_file=tmp_path / "control-points.json",
        schema_version="test-1",
        coordinate_system="GCJ-02",
        routes=(
            ControlPointRoute(
                route_id="ROUTE_001",
                route_name="南北主走廊",
                transport_modes=frozenset({"散船"}),
                points=(_point("120", "30"), _point("118", "26")),
            ),
            ControlPointRoute(
                route_id="ROUTE_003",
                route_name="福建-珠三角走廊",
                transport_modes=frozenset({"散船"}),
                points=(_point("118", "26"), _point("116", "22")),
            ),
            ControlPointRoute(
                route_id="ROUTE_004",
                route_name="西江主航线",
                transport_modes=frozenset({"驳船"}),
                points=(_point("113", "23"), _point("109", "23")),
            ),
        ),
    )


def _point(longitude: str, latitude: str) -> GeoPoint:
    return GeoPoint(
        longitude=Decimal(longitude),
        latitude=Decimal(latitude),
    )
