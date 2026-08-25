from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest

from src.geo.distance_provider import GeoPoint
from src.web.route_control_points import (
    RouteControlPointError,
    find_route_control_point_file,
    load_route_control_point_network,
)


def test_control_point_network_connects_endpoints_to_nearest_corridor_points(
    tmp_path: Path,
):
    path = _write_control_points(tmp_path)
    network = load_route_control_point_network(path)
    origin = _point("120.05", "30.05")
    destination = _point("116.05", "22.05")

    result = network.path_for("散船", origin, destination)

    assert result is not None
    assert result.points[0] == origin
    assert result.points[-1] == destination
    assert result.points[1] == _point("120", "30")
    assert result.points[-2] == _point("116", "22")
    assert result.route_ids == ("ROUTE_001", "ROUTE_003")
    assert result.origin_connector_km < Decimal("10")
    assert result.destination_connector_km < Decimal("10")


def test_control_point_network_selects_nearest_inland_component(
    tmp_path: Path,
):
    path = _write_control_points(tmp_path)
    network = load_route_control_point_network(path)

    result = network.path_for(
        "驳船",
        _point("113.1", "23.1"),
        _point("109.1", "23.1"),
    )

    assert result is not None
    assert result.route_ids == ("ROUTE_004",)
    assert _point("113", "23") in result.points
    assert _point("109", "23") in result.points
    assert _point("119", "26") not in result.points


def test_control_point_loader_requires_gcj02(tmp_path: Path):
    path = _write_control_points(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["coordinate_system"] = "WGS84"
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(RouteControlPointError, match="GCJ-02"):
        load_route_control_point_network(path)


def test_control_point_file_discovery_is_optional(tmp_path: Path):
    assert find_route_control_point_file(tmp_path) is None

    path = _write_control_points(tmp_path)

    assert find_route_control_point_file(tmp_path) == path


def _write_control_points(tmp_path: Path) -> Path:
    path = tmp_path / "航线控制点_全点版.json"
    payload = {
        "schema_version": "test-1",
        "coordinate_system": "GCJ-02",
        "routes": [
            _route(
                "ROUTE_001",
                "南北主走廊",
                [("120", "30"), ("118", "26")],
            ),
            _route(
                "ROUTE_002",
                "福建-闽江内河航线",
                [("119", "26"), ("118", "26.5")],
            ),
            _route(
                "ROUTE_003",
                "福建-珠三角走廊",
                [("118", "26"), ("116", "22")],
            ),
            _route(
                "ROUTE_004",
                "西江主航线",
                [("113", "23"), ("109", "23")],
            ),
            _route(
                "ROUTE_005",
                "珠三角-粤西-海南-广西走廊",
                [("116", "22"), ("109", "21")],
            ),
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _route(
    route_id: str,
    route_name: str,
    points: list[tuple[str, str]],
) -> dict[str, object]:
    return {
        "route_id": route_id,
        "route_name": route_name,
        "points": [
            {
                "point_order": index,
                "longitude": longitude,
                "latitude": latitude,
            }
            for index, (longitude, latitude) in enumerate(points, start=1)
        ],
    }


def _point(longitude: str, latitude: str) -> GeoPoint:
    return GeoPoint(
        longitude=Decimal(longitude),
        latitude=Decimal(latitude),
    )
