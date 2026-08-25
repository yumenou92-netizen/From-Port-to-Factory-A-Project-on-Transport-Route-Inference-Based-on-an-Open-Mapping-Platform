from decimal import Decimal
from types import SimpleNamespace

import pytest

import src.web.server as web_server
from src.application.route_planning import (
    EdgeGeometryTrace,
    RoutePlanningRequest,
    RoutePlanningResponse,
)
from src.domain.route_request import RouteRequest
from src.geo.coordinate_provider import CoordinateResolution
from src.geo.distance_provider import GeoPoint
from src.web.server import (
    STATIC_DIR,
    RouteWebContext,
    _serialize_segment_geometry,
    parse_route_web_request,
)


def test_web_request_parses_optional_south_port_and_order_dimensions():
    parsed = parse_route_web_request(
        {
            "origin": "北良港",
            "destination": "客户工厂",
            "southPort": "漳州港",
            "region": "全国",
            "quantity": "2450",
            "quantityUnit": "吨",
            "packageType": "散粮",
            "commodity": "小麦",
            "tradeType": "内贸",
        }
    )

    assert isinstance(parsed, RoutePlanningRequest)
    assert parsed.origin == "北良港"
    assert parsed.south_port == "漳州港"
    assert parsed.request.quantity == Decimal("2450")
    assert parsed.request.commodity == "小麦"


def test_web_request_does_not_guess_missing_billing_unit():
    with pytest.raises(ValueError, match="计费单位不能为空"):
        parse_route_web_request(
            {
                "origin": "北良港",
                "destination": "客户工厂",
                "quantity": "2450",
                "packageType": "散粮",
                "commodity": "玉米",
            }
        )


def test_web_request_rejects_not_yet_connected_trunk_transport_mode():
    with pytest.raises(ValueError, match="仅开放北港至南港散船运输"):
        parse_route_web_request(
            {
                "origin": "北良港",
                "destination": "客户工厂",
                "transportMode": "铁路",
                "quantity": "2450",
                "quantityUnit": "吨",
                "packageType": "散粮",
                "commodity": "玉米",
            }
        )


def test_web_context_passes_parsed_application_request_through_service(monkeypatch):
    captured = {}
    response = _route_planning_response()

    def fake_plan_full_flow(request, **dependencies):
        captured["request"] = request
        captured["dependencies"] = dependencies
        return response

    monkeypatch.setattr(web_server, "plan_full_flow", fake_plan_full_flow)
    monkeypatch.setattr(
        web_server.TencentMapDrivingRouteProvider,
        "from_env",
        lambda: object(),
    )
    context = RouteWebContext(bundle=SimpleNamespace(node_registry=object()))

    serialized = context.calculate(
        {
            "origin": "北良港",
            "destination": "客户工厂",
            "southPort": "钦州港",
            "region": "广东",
            "quantity": "2450",
            "quantityUnit": "吨",
            "packageType": "散粮",
            "commodity": "玉米",
            "tradeType": "内贸",
        }
    )

    request = captured["request"]
    assert isinstance(request, RoutePlanningRequest)
    assert request.origin == "北良港"
    assert request.destination == "客户工厂"
    assert request.south_port == "钦州港"
    assert request.region == "广东"
    assert captured["dependencies"]["bundle"] is context.bundle
    assert set(serialized) == {
        "status",
        "request",
        "routes",
        "candidates",
        "candidateDecisions",
        "intermediatePorts",
        "runInfo",
    }
    assert serialized["request"] == {
        "origin": "北良港",
        "destination": "客户工厂",
        "southPort": "钦州港",
        "quantity": "2450",
        "quantityUnit": "吨",
        "packageType": "散粮",
        "commodity": "玉米",
        "tradeType": "内贸",
    }
    assert set(serialized["routes"]) == {"lowestCost", "fastestTime"}
    assert serialized["runInfo"]["graphEdgeCount"] == 0
    assert serialized["runInfo"]["warnings"] == []
    assert serialized["candidateDecisions"] == []


def test_web_result_visibility_honors_hidden_attribute():
    css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert "[hidden]" in css
    assert "display: none !important" in css


def test_web_serializes_tencent_driving_polyline_for_truck_segment():
    geometry = EdgeGeometryTrace(
        edge_id="truck-edge",
        kind="tencent_driving_polyline",
        source="tencent_map_driving_route",
        points=(
            GeoPoint(longitude=Decimal("113.1"), latitude=Decimal("22.8")),
            GeoPoint(longitude=Decimal("113.2"), latitude=Decimal("22.9")),
        ),
        is_schematic=False,
        message="同一次腾讯驾车响应。",
    )
    segment = SimpleNamespace(
        transport_mode="汽运",
        edge_key="truck-edge",
        from_node_id="port",
        to_node_id="factory",
    )
    result = SimpleNamespace(
        edge_geometries={"truck-edge": geometry},
        node_names={"port": "南港", "factory": "客户工厂"},
    )

    serialized = _serialize_segment_geometry(
        segment,
        result,
        _points(),
    )

    assert serialized["kind"] == "tencent_driving_polyline"
    assert serialized["isSchematic"] is False
    assert serialized["source"] == "tencent_map_driving_route"
    assert serialized["points"][1] == {
        "longitude": 113.2,
        "latitude": 22.9,
    }


def test_web_uses_each_selected_edge_key_for_its_road_geometry():
    first = EdgeGeometryTrace(
        edge_id="cost-edge",
        kind="tencent_driving_polyline",
        source="tencent_map_driving_route",
        points=(
            GeoPoint(longitude=Decimal("113.1"), latitude=Decimal("22.8")),
            GeoPoint(longitude=Decimal("113.15"), latitude=Decimal("22.85")),
        ),
        is_schematic=False,
        message="费用最低边。",
    )
    second = EdgeGeometryTrace(
        edge_id="time-edge",
        kind="tencent_driving_polyline",
        source="tencent_map_driving_route",
        points=(
            GeoPoint(longitude=Decimal("113.1"), latitude=Decimal("22.8")),
            GeoPoint(longitude=Decimal("113.25"), latitude=Decimal("22.95")),
        ),
        is_schematic=False,
        message="时间最短边。",
    )
    result = SimpleNamespace(
        edge_geometries={
            first.edge_id: first,
            second.edge_id: second,
        },
        node_names={"port": "南港", "factory": "客户工厂"},
    )

    cost_geometry = _serialize_segment_geometry(
        SimpleNamespace(
            transport_mode="汽运",
            edge_key=first.edge_id,
            from_node_id="port",
            to_node_id="factory",
        ),
        result,
        _points(),
    )
    time_geometry = _serialize_segment_geometry(
        SimpleNamespace(
            transport_mode="汽运",
            edge_key=second.edge_id,
            from_node_id="port",
            to_node_id="factory",
        ),
        result,
        _points(),
    )

    assert cost_geometry["points"][-1]["longitude"] == 113.15
    assert time_geometry["points"][-1]["longitude"] == 113.25


def test_web_serializes_bulk_shipping_as_explicit_schematic():
    segment = SimpleNamespace(
        transport_mode="散船",
        edge_key="bulk-edge",
        from_node_id="north",
        to_node_id="port",
    )
    result = SimpleNamespace(
        edge_geometries={},
        node_names={"north": "北良港", "port": "钦州港"},
    )
    points = {
        "north": {
            "longitude": 121.72,
            "latitude": 39.02,
        },
        "port": _points()["port"],
    }

    serialized = _serialize_segment_geometry(segment, result, points)

    assert serialized["kind"] == "bulk_shipping_schematic"
    assert serialized["isSchematic"] is True
    assert len(serialized["points"]) > 4
    assert "不代表真实航道" in serialized["message"]


def test_frontend_draws_segment_geometry_with_distinct_line_styles():
    javascript = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "segment.geometry" in javascript
    assert 'segment.transportStage === "north_to_south"' in javascript
    assert "segment.segmentNo === 1" not in javascript
    assert "geometry.kind === \"bulk_shipping_schematic\"" in javascript
    assert "styleOptions.dashArray = [14, 10]" in javascript
    assert "enableGeodesic: isSchematic" in javascript
    assert "paths: route.points.map" not in javascript
    assert "function clearMapRoutes()" in javascript
    assert "state.result = null;\n    clearMapRoutes();" in javascript
    assert 'elements.edgeCount.textContent = "本次未形成搜索图";' in javascript
    assert "if (state.result) renderMapRoutes();" in javascript
    assert "state.result.candidateDecisions || []" in javascript
    assert "候选南港 ${decision.name}" in javascript
    assert "info.routeControlPointCount" in javascript
    assert "实际端点接入最近的已维护航线控制点" in javascript
    assert "function formatDays(hours)" in javascript
    assert "function formatCostWithUnit(costYuan)" in javascript
    assert "元/吨" in javascript


def _points():
    return {
        "port": {
            "longitude": 113.1,
            "latitude": 22.8,
        },
        "factory": {
            "longitude": 113.2,
            "latitude": 22.9,
        },
    }


def _route_planning_response() -> RoutePlanningResponse:
    origin = CoordinateResolution(
        status="resolved",
        query_name="北良港",
        node_id="node-origin",
        canonical_name="北良港",
        longitude=121.72,
        latitude=39.02,
        source="test",
        message="测试坐标。",
    )
    destination = CoordinateResolution(
        status="resolved",
        query_name="客户工厂",
        node_id="node-destination",
        canonical_name="客户工厂",
        longitude=113.2,
        latitude=22.9,
        source="test",
        message="测试坐标。",
    )
    route = SimpleNamespace(
        status="resolved",
        total_cost_yuan=Decimal("100"),
        total_time_hours=Decimal("10"),
        path_node_ids=("node-origin", "node-destination"),
        segments=(),
    )
    return RoutePlanningResponse(
        origin_name="北良港",
        destination_name="客户工厂",
        selected_south_port="钦州港",
        origin_resolution=origin,
        destination_resolution=destination,
        request=RouteRequest(Decimal("2450"), "吨", "散粮", "玉米"),
        candidate_ports=(),
        intermediate_ports=(),
        graph_edge_count=0,
        recommendations=SimpleNamespace(  # type: ignore[arg-type]
            lowest_cost=route,
            fastest_time=route,
        ),
        node_names={
            "node-origin": "北良港",
            "node-destination": "客户工厂",
        },
        edge_sources={},
        edge_geometries={},
        warnings=(),
        additional_fee_count=0,
        trunk_edge_count=0,
        port_operation_fee_source=None,
        port_operation_fee_included_count=0,
        port_operation_fee_not_applicable_count=0,
        inland_waterway_source=None,
        barge_edge_count=0,
        barge_placeholder_capability_count=0,
        truck_edge_count=0,
        south_to_customer_options_by_port={},
    )
