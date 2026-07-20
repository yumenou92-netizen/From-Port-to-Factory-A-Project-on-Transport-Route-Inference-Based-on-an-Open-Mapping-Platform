from __future__ import annotations

import os
import sys

from src.dev.runtime_env import DEFAULT_ENV_FILE, load_runtime_env

DEFAULT_PROBE_REGION = "北京"
DEFAULT_PROBE_ORIGIN = "北京大学"
DEFAULT_PROBE_DESTINATION = "北京站"

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
        coordinate_provider = TencentMapCoordinateProvider.from_env(
            region=os.environ.get("TENCENT_MAP_PROBE_REGION", DEFAULT_PROBE_REGION),
            page_size=20,
        )
        route_provider = TencentMapDrivingRouteProvider.from_env()
    except TencentMapConfigError as exc:
        print(f"Tencent Map probe skipped: {exc}")
        print(f"Set {TENCENT_MAP_API_KEY_ENV} locally before running this probe.")
        return

    origin_name = os.environ.get("TENCENT_MAP_PROBE_ORIGIN", DEFAULT_PROBE_ORIGIN)
    destination_name = os.environ.get("TENCENT_MAP_PROBE_DESTINATION", DEFAULT_PROBE_DESTINATION)
    origin = coordinate_provider.resolve(origin_name)
    destination = coordinate_provider.resolve(destination_name)

    print("Tencent Map coordinate probe")
    print(f"- region: {os.environ.get('TENCENT_MAP_PROBE_REGION', DEFAULT_PROBE_REGION)}")
    _print_coordinate_result("origin", origin)
    _print_coordinate_result("destination", destination)

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


def _print_coordinate_result(label: str, result) -> None:
    print(f"- {label} status: {result.status}, source: {result.source}, name: {result.canonical_name}")
    print(f"- {label} confidence: {result.source_confidence or 'none'}")
    print(f"- {label} message: {result.message}")
    if not result.candidates:
        return

    print(f"- {label} manual review candidates:")
    for candidate in result.candidates:
        location = f"{candidate.latitude},{candidate.longitude}"
        area_parts = [value for value in (candidate.city, candidate.district) if value]
        area = "/".join(area_parts) if area_parts else "unknown area"
        print(
            f"  {candidate.rank}. {candidate.title} | {candidate.address or 'no address'} | "
            f"{candidate.category or 'no category'} | {area} | {location}"
        )


if __name__ == "__main__":
    main()
