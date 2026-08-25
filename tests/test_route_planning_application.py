from decimal import Decimal
from typing import cast

import pytest

from src.application.route_planning import (
    RoutePlanningContractError,
    RoutePlanningRequest,
    RoutePlanningResponse,
    RoutePlanningService,
)
from src.domain.route_request import RouteRequest
from src.geo.coordinate_provider import CoordinateResolution
from src.routing.route_result import RouteRecommendationResults


def test_route_planning_request_normalizes_transport_conditions():
    order = RouteRequest(Decimal("2450"), "吨", "散粮", "玉米")

    request = RoutePlanningRequest(
        origin="  北良港 ",
        destination=" 广西百跃农牧发展有限公司  ",
        south_port="  钦州港 ",
        region="  全国 ",
        request=order,
    )

    assert request.origin == "北良港"
    assert request.destination == "广西百跃农牧发展有限公司"
    assert request.south_port == "钦州港"
    assert request.region == "全国"
    assert request.request is order


def test_route_planning_request_rejects_missing_transport_endpoint():
    order = RouteRequest(Decimal("2450"), "吨", "散粮", "玉米")

    with pytest.raises(RoutePlanningContractError, match="出发北港不能为空"):
        RoutePlanningRequest(
            origin=" ",
            destination="客户工厂",
            request=order,
        )


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("destination", " ", "客户工厂不能为空"),
        ("region", None, "地点检索区域不能为空"),
    ],
)
def test_route_planning_request_rejects_other_required_text(
    field_name,
    value,
    message,
):
    values = {
        "origin": "北良港",
        "destination": "客户工厂",
        "region": "全国",
    }
    values[field_name] = value

    with pytest.raises(RoutePlanningContractError, match=message):
        RoutePlanningRequest(
            **values,
            request=RouteRequest(Decimal("2450"), "吨", "散粮", "玉米"),
        )


def test_route_planning_request_normalizes_blank_optional_south_port():
    request = RoutePlanningRequest(
        origin="北良港",
        destination="客户工厂",
        south_port=" ",
        request=RouteRequest(Decimal("2450"), "吨", "散粮", "玉米"),
    )

    assert request.south_port is None


def test_route_planning_request_rejects_non_order_payload():
    with pytest.raises(
        RoutePlanningContractError,
        match="订单信息必须使用 RouteRequest",
    ):
        RoutePlanningRequest(
            origin="北良港",
            destination="客户工厂",
            request=object(),  # type: ignore[arg-type]
        )


def test_route_planning_service_delegates_ui_independent_request():
    order = RouteRequest(Decimal("2450"), "吨", "散粮", "小麦")
    request = RoutePlanningRequest(
        origin="北良港",
        destination="福建湘大骆驼饲料有限公司",
        request=order,
    )
    response = _make_response(order)
    received: list[RoutePlanningRequest] = []

    def engine(value: RoutePlanningRequest) -> RoutePlanningResponse:
        received.append(value)
        return response

    service = RoutePlanningService(engine)

    assert service.plan(request) is response
    assert received == [request]


def test_route_planning_service_rejects_invalid_request_and_response():
    order = RouteRequest(Decimal("2450"), "吨", "散粮", "小麦")
    request = RoutePlanningRequest(
        origin="北良港",
        destination="客户工厂",
        request=order,
    )

    service = RoutePlanningService(
        lambda _request: cast(RoutePlanningResponse, object()),
    )
    with pytest.raises(
        RoutePlanningContractError,
        match="必须返回 RoutePlanningResponse",
    ):
        service.plan(request)

    valid_service = RoutePlanningService(lambda _request: _make_response(order))
    with pytest.raises(
        RoutePlanningContractError,
        match="只接受 RoutePlanningRequest",
    ):
        valid_service.plan(object())  # type: ignore[arg-type]


def _make_response(order: RouteRequest) -> RoutePlanningResponse:
    resolution = CoordinateResolution(
        status="resolved",
        query_name="测试节点",
        node_id="node-test",
        canonical_name="测试节点",
        longitude=113.1,
        latitude=22.8,
        source="test",
        message="测试坐标。",
    )
    return RoutePlanningResponse(
        origin_name="北良港",
        destination_name="客户工厂",
        selected_south_port=None,
        origin_resolution=resolution,
        destination_resolution=resolution,
        request=order,
        candidate_ports=(),
        intermediate_ports=(),
        graph_edge_count=0,
        recommendations=cast(RouteRecommendationResults, object()),
        node_names={},
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
