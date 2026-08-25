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
    _requests_get_json,
    make_geo_point,
)


def _place_candidate(
    title: str,
    *,
    poi_id: str = "poi-1",
    address: str = "test address",
    category: str = "test category",
    longitude: float = 113.2,
    latitude: float = 23.1,
    city: str = "Shenzhen",
    district: str = "Nanshan",
) -> dict[str, object]:
    return {
        "id": poi_id,
        "title": title,
        "address": address,
        "category": category,
        "location": {"lat": latitude, "lng": longitude},
        "ad_info": {"city": city, "district": district},
    }


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
    assert result.source_confidence == "exact_unique"
    assert len(result.candidates) == 1
    assert result.candidates[0].address == "测试地址"
    assert result.candidates[0].category == "公司企业"
    assert result.candidates[0].source_id == "poi-1"
    assert seen["keyword"] == "客户A"
    assert seen["boundary"] == "region(广州,0)"
    assert seen["key"] == "fake-secret"


def test_tencent_coordinate_provider_keeps_trace_for_single_nonexact_candidate():
    def fake_get_json(url, params, timeout_seconds):
        return {
            "status": 0,
            "message": "query ok",
            "data": [
                _place_candidate(
                    "测试西港码头",
                    poi_id="poi-west",
                    address="测试港区一号路",
                    category="交通设施:港口码头",
                )
            ],
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapCoordinateProvider(client, region="测试市")

    result = provider.resolve("测试西港")

    assert result.is_resolved
    assert result.source_confidence == "unique_candidate"
    assert len(result.candidates) == 1
    assert result.candidates[0].address == "测试港区一号路"
    assert result.candidates[0].category == "交通设施:港口码头"
    assert result.candidates[0].source_id == "poi-west"


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

    assert result.is_resolved
    assert result.status == "resolved"
    assert result.canonical_name == result.candidates[0].title
    assert result.source_confidence == "auto_top1_name_match"
    assert len(result.candidates) == 2
    assert result.candidates[0].rank == 1
    assert result.candidates[1].rank == 2
    assert result.longitude == 113.2
    assert result.latitude == 23.1


def test_tencent_coordinate_provider_auto_selects_similar_top_candidate():
    def fake_get_json(url, params, timeout_seconds):
        return {
            "status": 0,
            "message": "query ok",
            "data": [
                _place_candidate("Shenzhen University Yuehai Campus", poi_id="poi-1"),
                _place_candidate("Shenzhen-University Yuehai Campus", poi_id="poi-2"),
                _place_candidate("Shenzhen University Yuehai Campus ", poi_id="poi-3"),
            ],
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapCoordinateProvider(client, region="Shenzhen", page_size=20)

    result = provider.resolve("Shenzhen University Yuehai Campus")

    assert result.is_resolved
    assert result.canonical_name == "Shenzhen University Yuehai Campus"
    assert result.source_confidence == "auto_top1_name_match"
    assert result.longitude == 113.2
    assert result.latitude == 23.1
    assert len(result.candidates) == 3


def test_tencent_coordinate_provider_returns_top5_for_manual_candidate_review():
    def fake_get_json(url, params, timeout_seconds):
        return {
            "status": 0,
            "message": "query ok",
            "data": [
                _place_candidate(
                    f"Candidate {index}",
                    poi_id=f"poi-{index}",
                    longitude=113.0 + index,
                    latitude=23.0 + index,
                )
                for index in range(1, 7)
            ],
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapCoordinateProvider(client, region="Shenzhen", page_size=20)

    result = provider.resolve("Different Place")

    assert result.is_resolved
    assert result.status == "resolved"
    assert result.canonical_name == "Candidate 1"
    assert result.source_confidence == "auto_top1_unclustered"
    assert result.longitude == 114.0
    assert result.latitude == 24.0
    assert len(result.candidates) == 5
    assert [candidate.rank for candidate in result.candidates] == [1, 2, 3, 4, 5]
    assert [candidate.title for candidate in result.candidates] == [
        "Candidate 1",
        "Candidate 2",
        "Candidate 3",
        "Candidate 4",
        "Candidate 5",
    ]
    assert result.candidates[0].source_id == "poi-1"
    assert result.candidates[-1].source_id == "poi-5"


def test_tencent_coordinate_provider_marks_nearby_multi_candidate_top1_cluster():
    def fake_get_json(url, params, timeout_seconds):
        return {
            "status": 0,
            "message": "query ok",
            "data": [
                _place_candidate("Candidate One", poi_id="poi-1"),
                _place_candidate(
                    "Nearby Company",
                    poi_id="poi-2",
                    longitude=113.201,
                    latitude=23.101,
                ),
                _place_candidate(
                    "Far Warehouse",
                    poi_id="poi-3",
                    longitude=114.2,
                    latitude=24.1,
                ),
            ],
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapCoordinateProvider(client, region="Shenzhen", page_size=20)

    result = provider.resolve("Different Place")

    assert result.is_resolved
    assert result.canonical_name == "Candidate One"
    assert result.source_confidence == "auto_top1_nearby_cluster"
    assert len(result.candidates) == 3


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
                        "polyline": [
                            23.1,
                            113.2,
                            100000,
                            -200000,
                            -50000,
                            300000,
                        ],
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
    assert result.polyline_points == (
        GeoPoint(longitude="113.2", latitude="23.1"),
        GeoPoint(longitude="113.0", latitude="23.2"),
        GeoPoint(longitude="113.3", latitude="23.15"),
    )
    assert result.route_tags == ("距离短", "收费少")
    assert seen["from"] == "23.1,113.2"
    assert seen["to"] == "24.2,114.3"
    assert seen["policy"] == "LEAST_TIME"
    assert seen["get_mp"] == 0
    assert seen["get_speed"] == 0
    assert seen["plate_number"] == "粤A12345"
    assert seen["cartype"] == 0


@pytest.mark.parametrize(
    "route_extra",
    [
        {},
        {"polyline": [23.1, 113.2]},
        {"polyline": [23.1, 113.2, 100000]},
        {"polyline": [23.1, "invalid"]},
    ],
    ids=["missing", "single-point", "odd-length", "non-numeric"],
)
def test_tencent_driving_route_provider_keeps_valid_metrics_when_polyline_is_unusable(
    route_extra,
):
    def fake_get_json(url, params, timeout_seconds):
        return {
            "status": 0,
            "message": "query ok",
            "result": {
                "routes": [
                    {
                        "mode": "DRIVING",
                        "distance": 12345,
                        "duration": 90,
                        **route_extra,
                    }
                ]
            },
        }

    client = TencentMapClient("fake-secret", get_json=fake_get_json)
    provider = TencentMapDrivingRouteProvider(client)

    result = provider.get_route(
        RoadRouteRequest(
            origin=GeoPoint(longitude="113.2", latitude="23.1"),
            destination=GeoPoint(longitude="114.3", latitude="24.2"),
        )
    )

    assert result.is_resolved
    assert result.distance_km == Decimal("12.345")
    assert result.duration_hours == Decimal("1.5")
    assert result.polyline_points == ()


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
    for proxy_key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(proxy_key, raising=False)

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


def test_tencent_http_bypasses_only_loopback_proxy(monkeypatch):
    requests = pytest.importorskip("requests")
    for proxy_key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(proxy_key, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": 0, "data": []}

    class FakeSession:
        trust_env = True

        def get(self, url, params, timeout):
            assert self.trust_env is False
            assert url == PLACE_SEARCH_URL
            assert params == {"keyword": "北良港"}
            assert timeout == 3
            return FakeResponse()

    fake_session = FakeSession()
    monkeypatch.setattr(requests, "Session", lambda: fake_session)

    assert _requests_get_json(PLACE_SEARCH_URL, {"keyword": "北良港"}, 3) == {
        "status": 0,
        "data": [],
    }
