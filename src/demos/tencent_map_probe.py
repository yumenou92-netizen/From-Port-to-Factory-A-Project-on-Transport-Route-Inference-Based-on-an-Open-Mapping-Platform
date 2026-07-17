from __future__ import annotations

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
    try:
        coordinate_provider = TencentMapCoordinateProvider.from_env(region="全国", page_size=5)
        route_provider = TencentMapDrivingRouteProvider.from_env()
    except TencentMapConfigError as exc:
        print(f"Tencent Map probe skipped: {exc}")
        print(f"Set {TENCENT_MAP_API_KEY_ENV} locally before running this probe.")
        return

    origin = coordinate_provider.resolve("福田站")
    destination = coordinate_provider.resolve("故宫博物院")

    print("Tencent Map coordinate probe")
    print(f"- origin status: {origin.status}, source: {origin.source}, name: {origin.canonical_name}")
    print(
        f"- destination status: {destination.status}, "
        f"source: {destination.source}, name: {destination.canonical_name}"
    )

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


if __name__ == "__main__":
    main()
