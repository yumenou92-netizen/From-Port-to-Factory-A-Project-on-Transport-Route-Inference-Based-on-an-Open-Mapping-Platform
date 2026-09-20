from decimal import Decimal

import pytest

from src.application.rail_container_planning import RailContainerPlanningRequest, RailContainerPlanningResponse
from src.application.route_planning import RoutePlanningRequest, RoutePlanningResponse
from src.application.unified_route_planning import (
    UnifiedRoutePlanningError,
    UnifiedRoutePlanningRequest,
    UnifiedRoutePlanningService,
)
from src.domain.route_request import RouteRequest


def _service():
    return UnifiedRoutePlanningService(
        bulk_engine=lambda _request: RoutePlanningResponse.__new__(RoutePlanningResponse),
        rail_engine=lambda _request: RailContainerPlanningResponse.__new__(RailContainerPlanningResponse),
    )


def test_unified_service_routes_bulk_order_to_port_engine():
    seen = []
    service = UnifiedRoutePlanningService(
        bulk_engine=lambda request: seen.append(request) or RoutePlanningResponse.__new__(RoutePlanningResponse),
        rail_engine=lambda _request: RailContainerPlanningResponse.__new__(RailContainerPlanningResponse),
    )

    result = service.plan(
        UnifiedRoutePlanningRequest("北良港", "客户", RouteRequest(Decimal("500"), "吨", "散粮", "玉米"))
    )

    assert result.selected_family == "bulk"
    assert isinstance(seen[0], RoutePlanningRequest)
    assert seen[0].origin == "北良港"


def test_unified_service_routes_container_order_to_rail_engine():
    seen = []
    service = UnifiedRoutePlanningService(
        bulk_engine=lambda _request: RoutePlanningResponse.__new__(RoutePlanningResponse),
        rail_engine=lambda request: seen.append(request) or RailContainerPlanningResponse.__new__(RailContainerPlanningResponse),
    )

    result = service.plan(
        UnifiedRoutePlanningRequest("乌兰浩特北", "客户", RouteRequest(Decimal("500"), "箱", "集装箱", "玉米"), container_type="敞顶箱")
    )

    assert result.selected_family == "rail_container"
    assert isinstance(seen[0], RailContainerPlanningRequest)
    assert seen[0].north_station_name == "乌兰浩特北"


def test_unified_service_rejects_cross_package_unit_conversion():
    with pytest.raises(UnifiedRoutePlanningError, match="吨、箱、柜不得自动互换"):
        _service().plan(
            UnifiedRoutePlanningRequest("北方地点", "客户", RouteRequest(Decimal("500"), "吨", "集装箱", "玉米"), container_type="敞顶箱")
        )


def test_unified_service_rejects_rail_preference_for_bulk_order():
    with pytest.raises(UnifiedRoutePlanningError, match="铁路方案.*集装箱/箱"):
        _service().plan(
            UnifiedRoutePlanningRequest(
                "北方地点",
                "客户",
                RouteRequest(Decimal("500"), "吨", "散粮", "玉米"),
                transport_preference="铁路",
            )
        )


def test_mixed_preference_still_dispatches_by_package_and_unit():
    result = _service().plan(
        UnifiedRoutePlanningRequest(
            "北方地点",
            "客户",
            RouteRequest(Decimal("500"), "吨", "散粮", "玉米"),
            transport_preference="混合",
        )
    )

    assert result.selected_family == "bulk"
