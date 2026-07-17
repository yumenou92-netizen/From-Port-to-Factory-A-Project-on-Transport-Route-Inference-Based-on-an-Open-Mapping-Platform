from __future__ import annotations

from decimal import Decimal

import pytest

from src.geo.distance_provider import DrivingProfile, GeoPoint, RoadRouteRequest
from src.geo.tencent_map_provider import (
    DRIVING_ROUTE_URL,
    PLACE_SEARCH_URL,
    TENCENT_MAP_API_KEY_ENV,
    TencentMapClient,
    TencentMapConfigError,
    TencentMapCoordinateProvider,
    TencentMapDrivingRouteProvider,
    TencentMapHttpError,
    make_geo_point,
)


def test_tencent_coordinate_provider_resolves_unique_exact_candidate():
    seen: dict[str, object] = {}

    def fake_get_json(url, params, timeout_seconds):
        seen.update(params)
        assert url == PLACE_SEARCH_URL
        return {
            "status": 0,
            "message": "query ok",
            "data": [
                {
                    "id": "poi-1",
                    "title": "客户A",
                    "address": "测试地址",
                    "category": "公司企业",
                    "location": {"lat": 23.1, "lng": 113.2},
                    "ad_info": {"province": "广东省", "city": "广州市", "district": "南沙区"},
                }
            ],
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapCoordinateProvider(client, region="广州", auto_extend=0, page_size=5)

    result = provider.resolve("客户A")

    assert result.is_resolved
    assert result.canonical_name == "客户A"
    assert result.longitude == 113.2
    assert result.latitude == 23.1
    assert result.source == "tencent_map_place_search"
    assert seen["keyword"] == "客户A"
    assert seen["boundary"] == "region(广州,0)"
    assert seen["key"] == "fake-secret"


def test_tencent_coordinate_provider_keeps_ambiguous_candidates_for_manual_review():
    def fake_get_json(url, params, timeout_seconds):
        return {
            "status": 0,
            "message": "query ok",
            "data": [
                {
                    "id": "poi-1",
                    "title": "客户A南门",
                    "location": {"lat": 23.1, "lng": 113.2},
                    "ad_info": {"city": "广州市"},
                },
                {
                    "id": "poi-2",
                    "title": "客户A东门",
                    "location": {"lat": 23.2, "lng": 113.3},
                    "ad_info": {"city": "广州市"},
                },
            ],
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapCoordinateProvider(client, region="广州")

    result = provider.resolve("客户A")

    assert not result.is_resolved
    assert result.status == "manual_review"
    assert "返回 2 个候选" in result.message
    assert result.longitude is None
    assert result.latitude is None


def test_tencent_coordinate_provider_api_error_does_not_leak_key():
    def fake_get_json(url, params, timeout_seconds):
        return {"status": 121, "message": "key invalid"}

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapCoordinateProvider(client, region="广州")

    result = provider.resolve("客户A")

    assert result.status == "manual_review"
    assert "121" in result.message
    assert "fake-secret" not in result.message


def test_tencent_driving_route_provider_converts_meters_minutes_to_km_hours():
    seen: dict[str, object] = {}

    def fake_get_json(url, params, timeout_seconds):
        seen.update(params)
        assert url == DRIVING_ROUTE_URL
        return {
            "status": 0,
            "message": "query ok",
            "result": {
                "routes": [
                    {
                        "mode": "DRIVING",
                        "distance": 12345,
                        "duration": 90,
                        "toll": 12.5,
                        "tags": ["距离短", "收费少"],
                    }
                ]
            },
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapDrivingRouteProvider(client, policy="LEAST_TIME")
    request = RoadRouteRequest(
        origin=GeoPoint(longitude="113.2", latitude="23.1"),
        destination=GeoPoint(longitude="114.3", latitude="24.2"),
        driving_profile=DrivingProfile(plate_number="粤A12345", cartype=0),
    )

    result = provider.get_route(request)

    assert result.is_resolved
    assert result.distance_km == Decimal("12.345")
    assert result.duration_hours == Decimal("1.5")
    assert result.raw_distance_meters == 12345
    assert result.raw_duration_minutes == 90
    assert result.toll_yuan == Decimal("12.5")
    assert result.route_tags == ("距离短", "收费少")
    assert seen["from"] == "23.1,113.2"
    assert seen["to"] == "24.2,114.3"
    assert seen["policy"] == "LEAST_TIME"
    assert seen["get_mp"] == 0
    assert seen["get_speed"] == 0
    assert seen["plate_number"] == "粤A12345"
    assert seen["cartype"] == 0


def test_tencent_driving_route_provider_returns_manual_review_on_api_error():
    def fake_get_json(url, params, timeout_seconds):
        return {"status": 373, "message": "service not enabled"}

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapDrivingRouteProvider(client)

    result = provider.get_route(
        RoadRouteRequest(
            origin=make_geo_point("113.2", "23.1"),
            destination=make_geo_point("114.3", "24.2"),
        )
    )

    assert result.status == "manual_review"
    assert "373" in result.message
    assert "fake-secret" not in result.message


def test_tencent_client_from_env_requires_api_key(monkeypatch):
    monkeypatch.delenv(TENCENT_MAP_API_KEY_ENV, raising=False)

    with pytest.raises(TencentMapConfigError) as exc:
        TencentMapClient.from_env()

    assert TENCENT_MAP_API_KEY_ENV in str(exc.value)
    assert "hardcode" in str(exc.value)


def test_tencent_client_http_error_detail_does_not_leak_key(monkeypatch):
    requests = pytest.importorskip("requests")

    class FakeResponse:
        status_code = 403
        reason = "Forbidden"

        def raise_for_status(self):
            raise requests.HTTPError(
                "403 Client Error with key=fake-secret",
                response=self,
            )

    def fake_get(url, params, timeout):
        assert params["key"] == "fake-secret"
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    client = TencentMapClient("fake-secret")

    with pytest.raises(TencentMapHttpError) as exc:
        client.place_search(
            keyword="瀹㈡埛A",
            region="骞垮窞",
            auto_extend=0,
            page_size=5,
        )

    message = str(exc.value)
    assert "HTTPError" in message
    assert "status_code=403" in message
    assert "Forbidden" in message
    assert "fake-secret" not in message
