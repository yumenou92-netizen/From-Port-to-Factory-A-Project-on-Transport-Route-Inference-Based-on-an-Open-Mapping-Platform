from __future__ import annotations

import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable, Mapping

try:
    from .coordinate_provider import (
        CoordinateCandidate,
        CoordinateProviderError,
        CoordinateResolution,
    )
    from .distance_provider import (
        GeoPoint,
        RoadRouteRequest,
        RoadRouteResult,
        TruckRouteRequest,
    )
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.geo.coordinate_provider import (
        CoordinateCandidate,
        CoordinateProviderError,
        CoordinateResolution,
    )
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
MANUAL_REVIEW_CANDIDATE_LIMIT = 5
AUTO_SIMILAR_TOP_COUNT = 3
AUTO_SIMILARITY_THRESHOLD = 0.9
AUTO_TOP1_NEARBY_RADIUS_METERS = 300
EARTH_RADIUS_METERS = 6371000

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


@dataclass(frozen=True)
class CoordinateCandidateSelection:
    selected: TencentMapPlaceCandidate | None
    reason: str
    source_confidence: str | None
    review_candidates: tuple[CoordinateCandidate, ...] = ()


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
    tables fail. It accepts unique candidates and conservatively auto-selects
    highly similar top Tencent candidates. Other ambiguous results stay in
    manual review with structured candidate details.
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

        selection = _select_coordinate_candidate(query_name, candidates)
        if selection.selected is None:
            return _coordinate_manual_review(
                query_name,
                f"腾讯地图地点搜索返回 {len(candidates)} 个候选，{selection.reason}，需要人工确认坐标。",
                source_confidence=selection.source_confidence,
                candidates=selection.review_candidates,
            )

        selected = selection.selected
        return CoordinateResolution(
            status="resolved",
            query_name=query_name,
            node_id=None,
            canonical_name=selected.title,
            longitude=selected.longitude,
            latitude=selected.latitude,
            source="tencent_map_place_search",
            message=selection.reason,
            source_confidence=selection.source_confidence,
            candidates=selection.review_candidates,
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
        raise TencentMapHttpError(
            f"HTTP request failed for {url}: {_safe_request_error_detail(exc)}"
        ) from exc
    except ValueError as exc:
        raise TencentMapHttpError(f"HTTP response from {url} is not valid JSON") from exc

    if not isinstance(payload, Mapping):
        raise TencentMapHttpError(f"HTTP response from {url} is not a JSON object")
    return payload


def _safe_request_error_detail(exc: Exception) -> str:
    parts = [exc.__class__.__name__]
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    reason = str(getattr(response, "reason", "") or "").strip()
    if status_code is not None:
        parts.append(f"status_code={status_code}")
    if reason:
        parts.append(f"reason={reason}")
    return "; ".join(parts)


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
) -> CoordinateCandidateSelection:
    normalized_query = _normalize_title(query_name)
    exact_matches = [
        candidate for candidate in candidates if _normalize_title(candidate.title) == normalized_query
    ]
    if len(exact_matches) == 1:
        return CoordinateCandidateSelection(
            selected=exact_matches[0],
            reason="腾讯地图地点搜索返回唯一精确名称匹配。",
            source_confidence="exact_unique",
            review_candidates=_to_coordinate_candidates(candidates),
        )
    if len(exact_matches) > 1:
        exact_selection = _auto_select_similar_top_candidate(
            query_name,
            exact_matches,
            reason_prefix="腾讯地图地点搜索返回多个精确名称匹配",
        )
        if exact_selection.selected is not None:
            return exact_selection
        return _auto_select_top_candidate(
            query_name,
            exact_matches,
            review_candidates=candidates,
            reason_prefix="Tencent Maps returned multiple exact-name matches",
        )
    if len(candidates) == 1:
        return CoordinateCandidateSelection(
            selected=candidates[0],
            reason="腾讯地图地点搜索返回唯一候选地点。",
            source_confidence="unique_candidate",
            review_candidates=_to_coordinate_candidates(candidates),
        )

    similar_selection = _auto_select_similar_top_candidate(
        query_name,
        candidates,
        reason_prefix="腾讯地图地点搜索返回多条高度相似候选",
    )
    if similar_selection.selected is not None:
        return similar_selection

    return _auto_select_top_candidate(
        query_name,
        candidates,
        review_candidates=candidates,
        reason_prefix=(
            "Tencent Maps returned multiple candidates without an exact unique "
            "or conservative similar-cluster match"
        ),
    )



def _normalize_title(value: str) -> str:
    return re.sub(r"[\s（）()\[\]【】<>《》·.,，、:：;；'\"-]+", "", str(value)).lower()


def _auto_select_similar_top_candidate(
    query_name: str,
    candidates: list[TencentMapPlaceCandidate],
    *,
    reason_prefix: str,
) -> CoordinateCandidateSelection:
    top_candidates = candidates[: min(AUTO_SIMILAR_TOP_COUNT, len(candidates))]
    if len(top_candidates) < 2:
        return CoordinateCandidateSelection(None, "候选数量不足以判断相似聚类", None)

    selected = top_candidates[0]
    if not _same_city_and_district(top_candidates):
        return CoordinateCandidateSelection(None, "前排候选不在同一城市或行政区", None)
    if not _all_titles_similar(query_name, selected.title, top_candidates):
        return CoordinateCandidateSelection(None, "前排候选名称相似度不足", None)

    return CoordinateCandidateSelection(
        selected=selected,
        reason=(
            f"{reason_prefix}，前 {len(top_candidates)} 个候选名称、城市和行政区一致性较高，"
            "已自动采用首位候选。"
        ),
        source_confidence="auto_top1_name_match",
        review_candidates=_to_coordinate_candidates(candidates),
    )


def _auto_select_top_candidate(
    query_name: str,
    candidates: list[TencentMapPlaceCandidate],
    *,
    review_candidates: list[TencentMapPlaceCandidate],
    reason_prefix: str,
) -> CoordinateCandidateSelection:
    selected = candidates[0]
    normalized_query = _normalize_title(query_name)
    normalized_title = _normalize_title(selected.title)
    trace = _to_coordinate_candidates(review_candidates)

    if _titles_match(normalized_title, normalized_query):
        confidence = "auto_top1_name_match"
        reason_suffix = "top1 title matches the query"
    elif _has_nearby_candidate(selected, candidates[1:3]):
        confidence = "auto_top1_nearby_cluster"
        reason_suffix = (
            f"top1 has another leading candidate within {AUTO_TOP1_NEARBY_RADIUS_METERS} meters"
        )
    else:
        confidence = "auto_top1_unclustered"
        reason_suffix = "top1 is selected by provider ranking and should be spot-checked"

    return CoordinateCandidateSelection(
        selected=selected,
        reason=(
            f"{reason_prefix}; prototype policy auto-selected top1 ({selected.title}); "
            f"{reason_suffix}."
        ),
        source_confidence=confidence,
        review_candidates=trace,
    )


def _has_nearby_candidate(
    selected: TencentMapPlaceCandidate,
    candidates: list[TencentMapPlaceCandidate],
) -> bool:
    return any(
        _distance_meters(selected, candidate) <= AUTO_TOP1_NEARBY_RADIUS_METERS
        for candidate in candidates
    )


def _distance_meters(
    left: TencentMapPlaceCandidate,
    right: TencentMapPlaceCandidate,
) -> float:
    left_lat = radians(left.latitude)
    right_lat = radians(right.latitude)
    delta_lat = radians(right.latitude - left.latitude)
    delta_lon = radians(right.longitude - left.longitude)
    a = sin(delta_lat / 2) ** 2 + cos(left_lat) * cos(right_lat) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * asin(sqrt(a))


def _same_city_and_district(candidates: list[TencentMapPlaceCandidate]) -> bool:
    cities = {_normalize_title(candidate.city) for candidate in candidates if candidate.city}
    districts = {
        _normalize_title(candidate.district)
        for candidate in candidates
        if candidate.district
    }
    return len(cities) <= 1 and len(districts) <= 1


def _all_titles_similar(
    query_name: str,
    selected_title: str,
    candidates: list[TencentMapPlaceCandidate],
) -> bool:
    normalized_query = _normalize_title(query_name)
    normalized_selected = _normalize_title(selected_title)
    if not _titles_match(normalized_selected, normalized_query):
        return False
    for candidate in candidates:
        normalized_title = _normalize_title(candidate.title)
        if not _titles_match(normalized_title, normalized_selected):
            return False
    return True


def _titles_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True
    return _title_similarity(left, right) >= AUTO_SIMILARITY_THRESHOLD


def _title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0
    if left == right:
        return 1
    return SequenceMatcher(None, left, right).ratio()


def _to_coordinate_candidates(
    candidates: list[TencentMapPlaceCandidate],
    *,
    limit: int = MANUAL_REVIEW_CANDIDATE_LIMIT,
) -> tuple[CoordinateCandidate, ...]:
    return tuple(
        CoordinateCandidate(
            rank=index,
            title=candidate.title,
            address=candidate.address,
            category=candidate.category,
            longitude=candidate.longitude,
            latitude=candidate.latitude,
            province=candidate.province,
            city=candidate.city,
            district=candidate.district,
            source_id=candidate.poi_id,
        )
        for index, candidate in enumerate(candidates[:limit], start=1)
    )


def _coordinate_manual_review(
    query_name: str,
    message: str,
    *,
    source_confidence: str | None = "manual_review",
    candidates: tuple[CoordinateCandidate, ...] = (),
) -> CoordinateResolution:
    return CoordinateResolution(
        status="manual_review",
        query_name=query_name,
        node_id=None,
        canonical_name=None,
        longitude=None,
        latitude=None,
        source="tencent_map_place_search",
        message=message,
        source_confidence=source_confidence,
        candidates=candidates,
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
