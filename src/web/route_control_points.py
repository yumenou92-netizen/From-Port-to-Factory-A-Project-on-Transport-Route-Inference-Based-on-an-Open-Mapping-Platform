from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import heapq
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Iterable

from src.geo.distance_provider import GeoPoint


CONTROL_POINT_FILENAME = "航线控制点_全点版.json"
SUPPORTED_COORDINATE_SYSTEM = "GCJ-02"

_DEFAULT_ROUTE_MODES = {
    "ROUTE_001": frozenset({"散船"}),
    "ROUTE_002": frozenset({"驳船"}),
    "ROUTE_003": frozenset({"散船"}),
    "ROUTE_004": frozenset({"驳船"}),
    "ROUTE_005": frozenset({"散船"}),
}


class RouteControlPointError(ValueError):
    """Raised when the local route-control-point file is ambiguous or invalid."""


@dataclass(frozen=True)
class ControlPointRoute:
    route_id: str
    route_name: str
    transport_modes: frozenset[str]
    points: tuple[GeoPoint, ...]


@dataclass(frozen=True)
class ControlPointPath:
    points: tuple[GeoPoint, ...]
    route_ids: tuple[str, ...]
    origin_connector_km: Decimal
    destination_connector_km: Decimal


@dataclass(frozen=True)
class RouteControlPointNetwork:
    source_file: Path
    schema_version: str
    coordinate_system: str
    routes: tuple[ControlPointRoute, ...]

    @property
    def point_count(self) -> int:
        return sum(len(route.points) for route in self.routes)

    def path_for(
        self,
        transport_mode: str,
        origin: GeoPoint,
        destination: GeoPoint,
    ) -> ControlPointPath | None:
        routes = tuple(
            route
            for route in self.routes
            if transport_mode in route.transport_modes
        )
        if not routes:
            return None

        adjacency: dict[
            tuple[Decimal, Decimal],
            list[tuple[float, tuple[Decimal, Decimal], str]],
        ] = {}
        point_by_key: dict[tuple[Decimal, Decimal], GeoPoint] = {}
        for route in routes:
            for point in route.points:
                key = _point_key(point)
                point_by_key[key] = point
                adjacency.setdefault(key, [])
            for left, right in zip(route.points, route.points[1:]):
                left_key = _point_key(left)
                right_key = _point_key(right)
                distance_km = _distance_km(left, right)
                adjacency[left_key].append((distance_km, right_key, route.route_id))
                adjacency[right_key].append((distance_km, left_key, route.route_id))

        best: tuple[
            tuple[float, float],
            tuple[Decimal, Decimal],
            tuple[Decimal, Decimal],
            list[tuple[Decimal, Decimal]],
            set[str],
        ] | None = None
        for component in _connected_components(adjacency):
            origin_key = min(
                component,
                key=lambda key: _distance_km(origin, point_by_key[key]),
            )
            destination_key = min(
                component,
                key=lambda key: _distance_km(destination, point_by_key[key]),
            )
            network_distance, keys, route_ids = _shortest_path(
                adjacency,
                origin_key,
                destination_key,
                allowed_nodes=component,
            )
            connector_distance = (
                _distance_km(origin, point_by_key[origin_key])
                + _distance_km(destination, point_by_key[destination_key])
            )
            score = (connector_distance, network_distance)
            if best is None or score < best[0]:
                best = (
                    score,
                    origin_key,
                    destination_key,
                    keys,
                    route_ids,
                )

        if best is None:
            return None
        _, origin_key, destination_key, keys, route_ids = best
        control_points = tuple(point_by_key[key] for key in keys)
        points = _deduplicate_points((origin, *control_points, destination))
        return ControlPointPath(
            points=points,
            route_ids=tuple(sorted(route_ids)),
            origin_connector_km=_decimal_km(
                _distance_km(origin, point_by_key[origin_key])
            ),
            destination_connector_km=_decimal_km(
                _distance_km(destination, point_by_key[destination_key])
            ),
        )


def find_route_control_point_file(data_dir: Path) -> Path | None:
    matches = sorted(data_dir.rglob(CONTROL_POINT_FILENAME))
    if not matches:
        return None
    if len(matches) > 1:
        joined = "、".join(str(path) for path in matches)
        raise RouteControlPointError(
            f"DATA_DIR 下存在多个 {CONTROL_POINT_FILENAME}：{joined}"
        )
    return matches[0]


def load_route_control_point_network(
    path: Path,
) -> RouteControlPointNetwork:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouteControlPointError(f"航线控制点文件读取失败：{path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RouteControlPointError("航线控制点文件根节点必须是 JSON 对象。")
    schema_version = _required_text(payload, "schema_version")
    coordinate_system = _required_text(payload, "coordinate_system").upper()
    if coordinate_system != SUPPORTED_COORDINATE_SYSTEM:
        raise RouteControlPointError(
            "航线控制点坐标系必须为 GCJ-02，"
            f"当前为 {coordinate_system or '空值'}。"
        )
    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise RouteControlPointError("航线控制点 routes 必须是非空数组。")

    routes = tuple(_parse_route(raw_route) for raw_route in raw_routes)
    route_ids = [route.route_id for route in routes]
    if len(route_ids) != len(set(route_ids)):
        raise RouteControlPointError("航线控制点 route_id 不得重复。")
    return RouteControlPointNetwork(
        source_file=path,
        schema_version=schema_version,
        coordinate_system=coordinate_system,
        routes=routes,
    )


def _parse_route(raw_route: Any) -> ControlPointRoute:
    if not isinstance(raw_route, dict):
        raise RouteControlPointError("每条航线必须是 JSON 对象。")
    route_id = _required_text(raw_route, "route_id")
    route_name = _required_text(raw_route, "route_name")
    transport_modes = _parse_transport_modes(raw_route, route_id)
    raw_points = raw_route.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise RouteControlPointError(f"航线 {route_id} 至少需要两个控制点。")

    ordered_points: list[tuple[int, GeoPoint]] = []
    seen_orders: set[int] = set()
    for raw_point in raw_points:
        if not isinstance(raw_point, dict):
            raise RouteControlPointError(f"航线 {route_id} 的控制点必须是对象。")
        try:
            point_order = int(raw_point["point_order"])
            longitude = Decimal(str(raw_point["longitude"]))
            latitude = Decimal(str(raw_point["latitude"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RouteControlPointError(
                f"航线 {route_id} 存在无效控制点字段。"
            ) from exc
        if point_order <= 0 or point_order in seen_orders:
            raise RouteControlPointError(
                f"航线 {route_id} 的 point_order 必须为不重复正整数。"
            )
        if not Decimal("-180") <= longitude <= Decimal("180"):
            raise RouteControlPointError(f"航线 {route_id} 存在无效经度。")
        if not Decimal("-90") <= latitude <= Decimal("90"):
            raise RouteControlPointError(f"航线 {route_id} 存在无效纬度。")
        seen_orders.add(point_order)
        ordered_points.append(
            (
                point_order,
                GeoPoint(longitude=longitude, latitude=latitude),
            )
        )
    ordered_points.sort(key=lambda item: item[0])
    return ControlPointRoute(
        route_id=route_id,
        route_name=route_name,
        transport_modes=transport_modes,
        points=tuple(point for _, point in ordered_points),
    )


def _parse_transport_modes(
    raw_route: dict[str, Any],
    route_id: str,
) -> frozenset[str]:
    raw_modes = raw_route.get("transport_modes")
    if raw_modes is None:
        modes = _DEFAULT_ROUTE_MODES.get(route_id)
        if modes is None:
            raise RouteControlPointError(
                f"航线 {route_id} 缺少 transport_modes，且没有受控默认映射。"
            )
        return modes
    if not isinstance(raw_modes, list) or not raw_modes:
        raise RouteControlPointError(
            f"航线 {route_id} 的 transport_modes 必须是非空数组。"
        )
    modes = frozenset(str(value).strip() for value in raw_modes if str(value).strip())
    unsupported = modes - {"散船", "驳船"}
    if unsupported:
        raise RouteControlPointError(
            f"航线 {route_id} 存在不支持的运输方式：{sorted(unsupported)}"
        )
    return modes


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise RouteControlPointError(f"航线控制点缺少字段 {key}。")
    return value


def _point_key(point: GeoPoint) -> tuple[Decimal, Decimal]:
    return point.longitude, point.latitude


def _connected_components(
    adjacency: dict[
        tuple[Decimal, Decimal],
        list[tuple[float, tuple[Decimal, Decimal], str]],
    ],
) -> Iterable[set[tuple[Decimal, Decimal]]]:
    remaining = set(adjacency)
    while remaining:
        start = next(iter(remaining))
        component = {start}
        stack = [start]
        remaining.remove(start)
        while stack:
            current = stack.pop()
            for _, neighbor, _ in adjacency[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        yield component


def _shortest_path(
    adjacency: dict[
        tuple[Decimal, Decimal],
        list[tuple[float, tuple[Decimal, Decimal], str]],
    ],
    start: tuple[Decimal, Decimal],
    target: tuple[Decimal, Decimal],
    *,
    allowed_nodes: set[tuple[Decimal, Decimal]],
) -> tuple[float, list[tuple[Decimal, Decimal]], set[str]]:
    distances = {start: 0.0}
    previous: dict[
        tuple[Decimal, Decimal],
        tuple[tuple[Decimal, Decimal], str],
    ] = {}
    queue = [(0.0, start)]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance != distances.get(current):
            continue
        if current == target:
            break
        for edge_distance, neighbor, route_id in adjacency[current]:
            if neighbor not in allowed_nodes:
                continue
            next_distance = distance + edge_distance
            if next_distance >= distances.get(neighbor, float("inf")):
                continue
            distances[neighbor] = next_distance
            previous[neighbor] = (current, route_id)
            heapq.heappush(queue, (next_distance, neighbor))

    if target not in distances:
        raise RouteControlPointError("航线控制点网络内部不连通。")
    keys = [target]
    route_ids: set[str] = set()
    while keys[-1] != start:
        parent, route_id = previous[keys[-1]]
        route_ids.add(route_id)
        keys.append(parent)
    keys.reverse()
    return distances[target], keys, route_ids


def _distance_km(left: GeoPoint, right: GeoPoint) -> float:
    earth_radius_km = 6371.0088
    left_latitude = radians(float(left.latitude))
    right_latitude = radians(float(right.latitude))
    delta_latitude = right_latitude - left_latitude
    delta_longitude = radians(float(right.longitude - left.longitude))
    haversine = (
        sin(delta_latitude / 2) ** 2
        + cos(left_latitude)
        * cos(right_latitude)
        * sin(delta_longitude / 2) ** 2
    )
    return 2 * earth_radius_km * asin(sqrt(haversine))


def _decimal_km(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def _deduplicate_points(points: Iterable[GeoPoint]) -> tuple[GeoPoint, ...]:
    result: list[GeoPoint] = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    return tuple(result)
