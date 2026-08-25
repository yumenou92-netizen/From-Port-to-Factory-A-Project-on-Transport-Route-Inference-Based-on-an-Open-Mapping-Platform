from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.geo.distance_provider import GeoPoint
from src.web.route_control_points import RouteControlPointNetwork


SCHEMATIC_SOURCE = "china_coastal_waters_schematic/1.2"


@dataclass(frozen=True)
class SchematicRouteGeometry:
    kind: str
    source: str
    points: tuple[GeoPoint, ...]
    message: str
    is_schematic: bool = True


def build_bulk_shipping_schematic(
    origin: GeoPoint,
    destination: GeoPoint,
    *,
    destination_name: str = "",
    control_points: Sequence[GeoPoint] | None = None,
    control_point_network: RouteControlPointNetwork | None = None,
) -> SchematicRouteGeometry:
    """Build a display-only offshore route between a north and south port.

    The intermediate points are deliberately kept in broad Chinese coastal
    waters. They are not a navigational route and never enter path search,
    distance, time, or cost calculations. ``control_points`` is the explicit
    hook for later human fine-tuning of an individual port pair.
    """

    if control_points is not None:
        points = _deduplicate_points((origin, *control_points, destination))
        return SchematicRouteGeometry(
            kind="bulk_shipping_schematic",
            source=f"{SCHEMATIC_SOURCE}+manual_control_points",
            points=points,
            message=(
                "散船线为人工控制点校正后的中国近海展示示意；"
                "不代表真实航道，也不参与费用、时效或路径搜索。"
            ),
        )

    if control_point_network is not None:
        matched_path = control_point_network.path_for(
            "散船",
            origin,
            destination,
        )
        if matched_path is not None:
            route_ids = ",".join(matched_path.route_ids)
            return SchematicRouteGeometry(
                kind="bulk_shipping_schematic",
                source=(
                    f"route_control_points_json/{control_point_network.schema_version}"
                    f";routes={route_ids}"
                ),
                points=matched_path.points,
                message=(
                    "散船线由实际端点连接至最近航线控制点，并沿已维护控制点走廊展示；"
                    f"起点接入约 {matched_path.origin_connector_km} 公里，"
                    f"终点接入约 {matched_path.destination_connector_km} 公里。"
                    "该线仅作航线示意，不代表权威航道，也不参与费用、时效或路径搜索。"
                ),
            )

    points: list[GeoPoint] = [origin]
    points.extend(_origin_egress(origin))
    points.extend(_coastal_corridor(origin, destination))
    points.extend(_destination_approach(destination, destination_name))
    points.append(destination)
    regional_note = (
        "广西方向经琼州海峡进入北部湾；"
        if _is_guangxi_destination(destination, destination_name.strip())
        else ""
    )
    return SchematicRouteGeometry(
        kind="bulk_shipping_schematic",
        source=SCHEMATIC_SOURCE,
        points=_deduplicate_points(points),
        message=(
            "散船线使用贴近大陆沿海的中国近海点生成展示虚线；"
            f"{regional_note}"
            "仅首末端连接港口，"
            "仅做运输线路示意，不代表真实航道，也不参与费用、时效或路径搜索。"
        ),
    )


def build_barge_schematic(
    origin: GeoPoint,
    destination: GeoPoint,
    *,
    control_point_network: RouteControlPointNetwork | None = None,
) -> SchematicRouteGeometry:
    """Return an explicitly schematic barge line."""

    if control_point_network is not None:
        matched_path = control_point_network.path_for(
            "驳船",
            origin,
            destination,
        )
        if matched_path is not None:
            route_ids = ",".join(matched_path.route_ids)
            return SchematicRouteGeometry(
                kind="barge_schematic",
                source=(
                    f"route_control_points_json/{control_point_network.schema_version}"
                    f";routes={route_ids}"
                ),
                points=matched_path.points,
                message=(
                    "驳船线由实际端点连接至最近内河控制点，并沿已维护控制点走廊展示；"
                    f"起点接入约 {matched_path.origin_connector_km} 公里，"
                    f"终点接入约 {matched_path.destination_connector_km} 公里。"
                    "该线仅作航线示意，不代表权威航道，也不参与费用、时效或路径搜索。"
                ),
            )

    return SchematicRouteGeometry(
        kind="barge_schematic",
        source="node_to_node_barge_schematic/1.0",
        points=(origin, destination),
        message=(
            "驳船段当前仅按端点绘制示意线；不代表真实内河航道，"
            "也不参与费用、时效或路径搜索。"
        ),
    )


def _origin_egress(origin: GeoPoint) -> tuple[GeoPoint, ...]:
    longitude = origin.longitude
    latitude = origin.latitude
    if latitude >= Decimal("38.5"):
        if longitude < Decimal("121.5"):
            return (
                _point("120.6", "39.2"),
                _point("121.4", "38.2"),
                _point("122.4", "37.4"),
            )
        return (
            _point("122.2", "38.6"),
            _point("122.6", "37.4"),
        )
    if latitude >= Decimal("34"):
        return (
            GeoPoint(
                longitude=max(longitude + Decimal("0.9"), Decimal("123.0")),
                latitude=latitude - Decimal("0.3"),
            ),
        )
    return ()


def _coastal_corridor(
    origin: GeoPoint,
    destination: GeoPoint,
) -> tuple[GeoPoint, ...]:
    corridor = (
        _point("122.8", "35.5"),
        _point("122.5", "33.5"),
        _point("122.1", "31.5"),
        _point("122.5", "29.5"),
        _point("121.2", "27.5"),
        _point("120.2", "25.8"),
        _point("119.2", "24.2"),
        _point("117.8", "22.7"),
        _point("116.2", "21.7"),
        _point("114.3", "21.2"),
    )
    upper = max(origin.latitude, destination.latitude)
    destination_margin = (
        Decimal("0.8")
        if destination.longitude >= Decimal("117")
        else Decimal("-1.8")
    )
    lower = destination.latitude + destination_margin
    return tuple(
        point
        for point in corridor
        if lower < point.latitude < upper - Decimal("0.5")
    )


def _destination_approach(
    destination: GeoPoint,
    destination_name: str,
) -> tuple[GeoPoint, ...]:
    longitude = destination.longitude
    latitude = destination.latitude
    name = destination_name.strip()

    if longitude >= Decimal("117"):
        return (
            GeoPoint(
                longitude=longitude + Decimal("0.9"),
                latitude=latitude - Decimal("0.15"),
            ),
        )

    if longitude >= Decimal("112") and latitude >= Decimal("20.5"):
        return (
            _point("114.2", "21.25"),
            GeoPoint(
                longitude=longitude + Decimal("0.45"),
                latitude=latitude - Decimal("0.25"),
            ),
        )

    if longitude >= Decimal("110.2") and latitude >= Decimal("20.5"):
        return (
            _point("113.0", "20.9"),
            _point("112.0", "20.7"),
            GeoPoint(
                longitude=longitude + Decimal("0.35"),
                latitude=latitude - Decimal("0.25"),
            ),
        )

    if _is_guangxi_destination(destination, name):
        return (
            _point("113.0", "20.9"),
            _point("112.0", "20.7"),
            _point("111.2", "20.45"),
            _point("110.55", "20.30"),
            _point("110.05", "20.18"),
            _point("109.55", "20.25"),
            _point("108.9", "20.65"),
            GeoPoint(
                longitude=longitude + Decimal("0.25"),
                latitude=latitude - Decimal("0.35"),
            ),
        )

    if "海口" in name:
        return (
            _point("112.0", "20.7"),
            _point("111.2", "20.45"),
            _point("110.55", "20.30"),
        )

    if longitude >= Decimal("109.5"):
        return (
            _point("112.0", "18.0"),
            _point("110.8", "17.4"),
            _point("109.0", "17.5"),
            _point("108.7", "19.0"),
            GeoPoint(
                longitude=longitude - Decimal("0.35"),
                latitude=latitude - Decimal("0.1"),
            ),
        )

    return (
        _point("112.0", "18.0"),
        _point("110.8", "17.4"),
        _point("108.4", "17.3"),
        _point("107.2", "19.2"),
        _point("107.7", "20.5"),
        GeoPoint(
            longitude=longitude - Decimal("0.15"),
            latitude=latitude - Decimal("0.45"),
        ),
    )


def _is_guangxi_destination(destination: GeoPoint, name: str) -> bool:
    guangxi_markers = ("广西", "钦州", "防城", "北海", "铁山")
    return any(marker in name for marker in guangxi_markers) or (
        destination.longitude < Decimal("110.2")
        and destination.latitude >= Decimal("20.5")
    )


def _point(longitude: str, latitude: str) -> GeoPoint:
    return GeoPoint(longitude=Decimal(longitude), latitude=Decimal(latitude))


def _deduplicate_points(points: Sequence[GeoPoint]) -> tuple[GeoPoint, ...]:
    result: list[GeoPoint] = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    return tuple(result)
