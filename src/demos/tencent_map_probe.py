from __future__ import annotations

import os
import sys

from src.dev.runtime_env import DEFAULT_ENV_FILE, load_runtime_env

try:
    from .distance_provider import RoadRouteRequest
    from .tencent_map_provider import (
        TENCENT_MAP_API_KEY_ENV,
        TencentMapConfigError,
        TencentMapCoordinateProvider,
        TencentMapDrivingRouteProvider,
        make_geo_point,
    )
except ImportError:  # Support direct script execution fallback.
    from src.geo.distance_provider import RoadRouteRequest
    from src.geo.tencent_map_provider import (
        TENCENT_MAP_API_KEY_ENV,
        TencentMapConfigError,
        TencentMapCoordinateProvider,
        TencentMapDrivingRouteProvider,
        make_geo_point,
    )


def main() -> None:
    """Run a non-business Tencent Maps smoke test with public POIs."""
    env_result = load_runtime_env(DEFAULT_ENV_FILE)
    _sync_pythonpath_to_sys_path()
    print("Tencent Map runtime env")
    print(f"- env file: {env_result.env_file}")
    print(f"- using example template: {env_result.used_example}")

    try:
        coordinate_provider = TencentMapCoordinateProvider.from_env(region="北京", page_size=20)
        route_provider = TencentMapDrivingRouteProvider.from_env()
    except TencentMapConfigError as exc:
        print(f"Tencent Map probe skipped: {exc}")
        print(f"Set {TENCENT_MAP_API_KEY_ENV} locally before running this probe.")
        return

    origin = coordinate_provider.resolve("北京大学")
    destination = coordinate_provider.resolve("北京站")

    print("Tencent Map coordinate probe")
    print(f"- origin status: {origin.status}, source: {origin.source}, name: {origin.canonical_name}")
    print(f"- origin message: {origin.message}")
    print(
        f"- destination status: {destination.status}, "
        f"source: {destination.source}, name: {destination.canonical_name}"
    )
    print(f"- destination message: {destination.message}")

    if not origin.is_resolved or not destination.is_resolved:
        print("Tencent Map route probe skipped: coordinate probe did not produce two unique points.")
        return

    route = route_provider.get_route(
        RoadRouteRequest(
            origin=make_geo_point(origin.longitude, origin.latitude),
            destination=make_geo_point(destination.longitude, destination.latitude),
        )
    )

    print("Tencent Map driving route probe")
    print(f"- route status: {route.status}, source: {route.source}")
    if route.is_resolved:
        print(f"- distance_km: {route.distance_km}")
        print(f"- duration_hours: {route.duration_hours}")
        print(f"- toll_yuan: {route.toll_yuan}")
        print(f"- tags: {', '.join(route.route_tags) if route.route_tags else 'none'}")
    else:
        print(f"- message: {route.message}")


def _sync_pythonpath_to_sys_path() -> None:
    for path_text in reversed(os.environ.get("PYTHONPATH", "").split(os.pathsep)):
        if path_text and path_text not in sys.path:
            sys.path.insert(0, path_text)


if __name__ == "__main__":
    main()
