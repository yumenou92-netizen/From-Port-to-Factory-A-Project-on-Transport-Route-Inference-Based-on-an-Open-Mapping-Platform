from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

try:
    from .coordinate_provider import CoordinateProviderError, CoordinateResolution
    from .distance_provider import (
        GeoPoint,
        RoadRouteRequest,
        RoadRouteResult,
        TruckRouteRequest,
    )
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.geo.coordinate_provider import CoordinateProviderError, CoordinateResolution
    from src.geo.distance_provider import (
        GeoPoint,
        RoadRouteRequest,
        RoadRouteResult,
        TruckRouteRequest,
    )


TENCENT_MAP_API_KEY_ENV = "TENCENT_MAP_API_KEY"
PLACE_SEARCH_URL = "https://apis.map.qq.com/ws/place/v1/search"
DRIVING_ROUTE_URL = "https://apis.map.qq.com/ws/direction/v1/driving/"
TRUCKING_ROUTE_URL = "https://apis.map.qq.com/ws/direction/v1/trucking"
DEFAULT_TIMEOUT_SECONDS = 10.0

HttpGetJson = Callable[[str, Mapping[str, Any], float], Mapping[str, Any]]


class TencentMapProviderError(Exception):
    """Base exception for Tencent Maps provider setup or response parsing errors."""


class TencentMapConfigError(TencentMapProviderError):
    """Raised when Tencent Maps credentials or runtime configuration are missing."""


class TencentMapHttpError(TencentMapProviderError):
    """Raised when the Tencent Maps HTTP request cannot be completed."""


@dataclass(frozen=True)
class TencentMapPlaceCandidate:
    poi_id: str
    title: str
    address: str
    category: str
    longitude: float
    latitude: float
    province: str
    city: str
    district: str


class TencentMapClient:
    """Small Tencent Maps WebService client that keeps the API key out of call sites."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        get_json: HttpGetJson | None = None,
    ) -> None:
        self._api_key = _required_secret(api_key)
        if timeout_seconds <= 0:
            raise TencentMapConfigError("Tencent Maps timeout must be positive.")
        self._timeout_seconds = timeout_seconds
        self._get_json = get_json or _requests_get_json

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = TENCENT_MAP_API_KEY_ENV,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        get_json: HttpGetJson | None = None,
    ) -> TencentMapClient:
        api_key = os.environ.get(env_var)
        if not api_key:
            raise TencentMapConfigError(
                f"Missing environment variable {env_var}; do not hardcode Tencent Maps API keys."
            )
        return cls(api_key, timeout_seconds=timeout_seconds, get_json=get_json)

    def get_json(self, url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        request_params = dict(params)
        request_params["key"] = self._api_key
        return self._get_json(url, request_params, self._timeout_seconds)

    def place_search(
        self,
        *,
        keyword: str,
        region: str,
        auto_extend: int,
        page_size: int,
        page_index: int = 1,
    ) -> Mapping[str, Any]:
        return self.get_json(
            PLACE_SEARCH_URL,
            {
                "keyword": keyword,
                "boundary": f"region({region},{auto_extend})",
                "page_size": page_size,
                "page_index": page_index,
                "output": "json",
            },
        )

    def driving_route(
        self,
        *,
        request: RoadRouteRequest,
        policy: str,
        get_mp: bool,
        get_speed: bool,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {
            "from": request.origin.to_tencent_lat_lng(),
            "to": request.destination.to_tencent_lat_lng(),
            "policy": policy,
            "get_mp": int(get_mp),
            "get_speed": int(get_speed),
            "output": "json",
        }
        if request.driving_profile is not None:
            params.update(request.driving_profile.to_tencent_params())
        return self.get_json(DRIVING_ROUTE_URL, params)

    def trucking_route(
        self,
        *,
        request: TruckRouteRequest,
        policy: int,
        no_step: bool,
        no_polyline: bool,
        tag_mode: int,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {
            "from": request.origin.to_tencent_lat_lng(),
            "to": request.destination.to_tencent_lat_lng(),
            "policy": policy,
            "no_step": int(no_step),
            "no_polyline": int(no_polyline),
            "tag_mode": tag_mode,
            "output": "json",
        }
        if request.truck_profile is not None:
            params.update(request.truck_profile.to_tencent_params())
        return self.get_json(TRUCKING_ROUTE_URL, params)


class TencentMapCoordinateProvider:
    """Tencent Maps place-search based coordinate provider.

    This provider is intended as the fallback after local known-coordinate
    tables fail. It accepts only unique or uniquely exact Tencent candidates.
    Ambiguous search results stay in manual review.
    """

    def __init__(
        self,
        client: TencentMapClient,
        *,
        region: str = "全国",
        auto_extend: int = 0,
        page_size: int = 5,
    ) -> None:
        self._client = client
        self._region = _required_text(region, "region")
        if auto_extend not in {0, 1, 2}:
            raise TencentMapConfigError("Tencent Maps region auto_extend must be 0, 1, or 2.")
        if page_size < 1 or page_size > 20:
            raise TencentMapConfigError("Tencent Maps place-search page_size must be 1 to 20.")
        self._auto_extend = auto_extend
        self._page_size = page_size

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = TENCENT_MAP_API_KEY_ENV,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        region: str = "全国",
        auto_extend: int = 0,
        page_size: int = 5,
        get_json: HttpGetJson | None = None,
    ) -> TencentMapCoordinateProvider:
        client = TencentMapClient.from_env(
            env_var=env_var,
            timeout_seconds=timeout_seconds,
            get_json=get_json,
        )
        return cls(client, region=region, auto_extend=auto_extend, page_size=page_size)

    def resolve(self, name: str) -> CoordinateResolution:
        query_name = _required_location_name(name)
        try:
            payload = self._client.place_search(
                keyword=query_name,
                region=self._region,
                auto_extend=self._auto_extend,
                page_size=self._page_size,
            )
        except TencentMapProviderError as exc:
            return _coordinate_manual_review(query_name, f"腾讯地图地点搜索请求失败: {exc}")

        status = _payload_status(payload)
        if status != 0:
            return _coordinate_manual_review(
                query_name,
                f"腾讯地图地点搜索返回异常状态 {status}: {_payload_message(payload)}",
            )

        candidates = _parse_place_candidates(payload)
        if not candidates:
            return _coordinate_manual_review(query_name, "腾讯地图地点搜索未返回可用候选坐标。")

        selected, reason = _select_coordinate_candidate(query_name, candidates)
        if selected is None:
            return _coordinate_manual_review(
                query_name,
                f"腾讯地图地点搜索返回 {len(candidates)} 个候选，{reason}，需要人工确认坐标。",
            )

        return CoordinateResolution(
            status="resolved",
            query_name=query_name,
            node_id=None,
            canonical_name=selected.title,
            longitude=selected.longitude,
            latitude=selected.latitude,
            source="tencent_map_place_search",
            message=reason,
        )


class TencentMapDrivingRouteProvider:
    """Tencent Maps driving-route provider for road distance and travel time."""

    def __init__(
        self,
        client: TencentMapClient,
        *,
        policy: str = "LEAST_TIME",
        get_mp: bool = False,
        get_speed: bool = False,
    ) -> None:
        self._client = client
        self._policy = _required_text(policy, "policy")
        self._get_mp = get_mp
        self._get_speed = get_speed

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = TENCENT_MAP_API_KEY_ENV,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        policy: str = "LEAST_TIME",
        get_json: HttpGetJson | None = None,
    ) -> TencentMapDrivingRouteProvider:
        client = TencentMapClient.from_env(
            env_var=env_var,
            timeout_seconds=timeout_seconds,
            get_json=get_json,
        )
        return cls(client, policy=policy)

    def get_route(self, request: RoadRouteRequest) -> RoadRouteResult:
        try:
            payload = self._client.driving_route(
                request=request,
                policy=self._policy,
                get_mp=self._get_mp,
                get_speed=self._get_speed,
            )
        except TencentMapProviderError as exc:
            return _route_manual_review("tencent_map_driving_route", f"腾讯地图驾车路线请求失败: {exc}")

        return _route_result_from_payload(
            payload,
            source="tencent_map_driving_route",
            api_name="腾讯地图驾车路线",
            success_message="已从腾讯地图驾车路线规划获取汽车行驶距离和预估耗时。",
        )


class TencentMapTruckingRouteProvider:
    """Tencent Maps truck-route provider for road distance and travel time."""

    def __init__(
        self,
        client: TencentMapClient,
        *,
        policy: int = 1,
        no_step: bool = True,
        no_polyline: bool = True,
        tag_mode: int = 1,
    ) -> None:
        self._client = client
        self._policy = _positive_int(policy, "policy")
        self._no_step = no_step
        self._no_polyline = no_polyline
        if tag_mode not in {0, 1}:
            raise TencentMapConfigError("Tencent Maps route tag_mode must be 0 or 1.")
        self._tag_mode = tag_mode

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = TENCENT_MAP_API_KEY_ENV,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        policy: int = 1,
        get_json: HttpGetJson | None = None,
    ) -> TencentMapTruckingRouteProvider:
        client = TencentMapClient.from_env(
            env_var=env_var,
            timeout_seconds=timeout_seconds,
            get_json=get_json,
        )
        return cls(client, policy=policy)

    def get_truck_route(self, request: TruckRouteRequest) -> RoadRouteResult:
        try:
            payload = self._client.trucking_route(
                request=request,
                policy=self._policy,
                no_step=self._no_step,
                no_polyline=self._no_polyline,
                tag_mode=self._tag_mode,
            )
        except TencentMapProviderError as exc:
            return _route_manual_review("tencent_map_trucking_route", f"腾讯地图货车路线请求失败: {exc}")

        return _route_result_from_payload(
            payload,
            source="tencent_map_trucking_route",
            api_name="腾讯地图货车路线",
            success_message="已从腾讯地图货车路线规划获取道路距离和预估耗时。",
        )


def make_geo_point(longitude: object, latitude: object) -> GeoPoint:
    return GeoPoint(longitude=_to_decimal(longitude, "longitude"), latitude=_to_decimal(latitude, "latitude"))


def _requests_get_json(url: str, params: Mapping[str, Any], timeout_seconds: float) -> Mapping[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise TencentMapConfigError("Python package requests is required for Tencent Maps API calls.") from exc

    try:
        response = requests.get(url, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise TencentMapHttpError(f"HTTP request failed for {url}") from exc
    except ValueError as exc:
        raise TencentMapHttpError(f"HTTP response from {url} is not valid JSON") from exc

    if not isinstance(payload, Mapping):
        raise TencentMapHttpError(f"HTTP response from {url} is not a JSON object")
    return payload


def _required_secret(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise TencentMapConfigError("Tencent Maps API key is empty.")
    return text


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise TencentMapConfigError(f"{field_name} cannot be empty.")
    return text


def _required_location_name(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise CoordinateProviderError("地点名称不能为空。")
    return text


def _payload_status(payload: Mapping[str, Any]) -> int:
    try:
        return int(payload.get("status", -1))
    except (TypeError, ValueError):
        return -1


def _payload_message(payload: Mapping[str, Any]) -> str:
    message = str(payload.get("message", "")).strip()
    return message or "no message"


def _parse_place_candidates(payload: Mapping[str, Any]) -> list[TencentMapPlaceCandidate]:
    raw_items = payload.get("data", [])
    if not isinstance(raw_items, list):
        return []

    candidates: list[TencentMapPlaceCandidate] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        location = item.get("location")
        if not isinstance(location, Mapping):
            continue
        try:
            longitude = float(location["lng"])
            latitude = float(location["lat"])
        except (KeyError, TypeError, ValueError):
            continue

        ad_info = item.get("ad_info")
        if not isinstance(ad_info, Mapping):
            ad_info = {}

        candidates.append(
            TencentMapPlaceCandidate(
                poi_id=str(item.get("id", "")).strip(),
                title=str(item.get("title", "")).strip(),
                address=str(item.get("address", "")).strip(),
                category=str(item.get("category", "")).strip(),
                longitude=longitude,
                latitude=latitude,
                province=str(ad_info.get("province", "")).strip(),
                city=str(ad_info.get("city", "")).strip(),
                district=str(ad_info.get("district", "")).strip(),
            )
        )
    return [candidate for candidate in candidates if candidate.title]


def _select_coordinate_candidate(
    query_name: str,
    candidates: list[TencentMapPlaceCandidate],
) -> tuple[TencentMapPlaceCandidate | None, str]:
    normalized_query = _normalize_title(query_name)
    exact_matches = [
        candidate for candidate in candidates if _normalize_title(candidate.title) == normalized_query
    ]
    if len(exact_matches) == 1:
        return exact_matches[0], "腾讯地图地点搜索返回唯一精确名称匹配。"
    if len(exact_matches) > 1:
        return None, "其中存在多个精确名称匹配"
    if len(candidates) == 1:
        return candidates[0], "腾讯地图地点搜索返回唯一候选地点。"
    return None, "且没有唯一精确名称匹配"


def _normalize_title(value: str) -> str:
    return "".join(str(value).split())


def _coordinate_manual_review(query_name: str, message: str) -> CoordinateResolution:
    return CoordinateResolution(
        status="manual_review",
        query_name=query_name,
        node_id=None,
        canonical_name=None,
        longitude=None,
        latitude=None,
        source="tencent_map_place_search",
        message=message,
    )


def _payload_routes(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return []
    routes = result.get("routes")
    if not isinstance(routes, list):
        return []
    return [route for route in routes if isinstance(route, Mapping)]


def _route_result_from_payload(
    payload: Mapping[str, Any],
    *,
    source: str,
    api_name: str,
    success_message: str,
) -> RoadRouteResult:
    status = _payload_status(payload)
    if status != 0:
        return _route_manual_review(
            source,
            f"{api_name}返回异常状态 {status}: {_payload_message(payload)}",
        )

    routes = _payload_routes(payload)
    if not routes:
        return _route_manual_review(source, f"{api_name}未返回可用路线方案。")

    route = routes[0]
    try:
        distance_meters = _positive_int(route.get("distance"), "distance")
        duration_minutes = _positive_int(route.get("duration"), "duration")
        toll_yuan = _optional_decimal(route.get("toll"), "toll")
    except TencentMapProviderError as exc:
        return _route_manual_review(source, f"{api_name}响应字段异常: {exc}")

    distance_km = Decimal(distance_meters) / Decimal("1000")
    duration_hours = Decimal(duration_minutes) / Decimal("60")
    return RoadRouteResult(
        status="resolved",
        distance_km=distance_km,
        duration_hours=duration_hours,
        source=source,
        message=success_message,
        raw_distance_meters=distance_meters,
        raw_duration_minutes=duration_minutes,
        toll_yuan=toll_yuan,
        route_tags=_parse_route_tags(route),
    )


def _route_manual_review(source: str, message: str) -> RoadRouteResult:
    return RoadRouteResult(
        status="manual_review",
        distance_km=None,
        duration_hours=None,
        source=source,
        message=message,
    )


def _parse_route_tags(route: Mapping[str, Any]) -> tuple[str, ...]:
    tags = route.get("tags", ())
    if not isinstance(tags, list):
        return ()
    return tuple(str(tag).strip() for tag in tags if str(tag).strip())


def _positive_int(value: object, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise TencentMapProviderError(f"{field_name} must be an integer.") from None
    if number <= 0:
        raise TencentMapProviderError(f"{field_name} must be positive.")
    return number


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    return _to_decimal(value, field_name)


def _to_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise TencentMapProviderError(f"{field_name} must be numeric.")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise TencentMapProviderError(f"{field_name} must be numeric.") from None
    if not number.is_finite():
        raise TencentMapProviderError(f"{field_name} must be finite.")
    return number
