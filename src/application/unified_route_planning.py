"""One UI-neutral entry point for all currently admitted transport families.

The request deliberately names only a northern location and a customer.  The
order's packaging and billing unit decide which provider families are eligible;
they are never converted merely to make routes comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from src.application.rail_container_planning import (
    RailContainerPlanningRequest,
    RailContainerPlanningResponse,
)
from src.application.route_planning import RoutePlanningRequest, RoutePlanningResponse
from src.domain.route_request import RouteRequest


class UnifiedRoutePlanningError(ValueError):
    """Raised when one endpoint/order request cannot select a legal mode family."""


PlanningFamily = Literal["bulk", "rail_container"]
TransportPreference = Literal["散粮", "铁路", "混合"]


@dataclass(frozen=True)
class UnifiedRoutePlanningRequest:
    northern_location: str
    customer_name: str
    request: RouteRequest
    region: str = "全国"
    selected_south_port: str | None = None
    container_type: Literal["顶开门箱", "敞顶箱"] | None = None
    transport_preference: TransportPreference = "混合"

    def __post_init__(self) -> None:
        object.__setattr__(self, "northern_location", _required(self.northern_location, "北方地点"))
        object.__setattr__(self, "customer_name", _required(self.customer_name, "客户工厂"))
        object.__setattr__(self, "region", _required(self.region, "地点检索区域"))
        south = str(self.selected_south_port).strip() if self.selected_south_port is not None else ""
        object.__setattr__(self, "selected_south_port", south or None)
        if not isinstance(self.request, RouteRequest):
            raise UnifiedRoutePlanningError("订单信息必须使用 RouteRequest。")
        if self.container_type is not None and self.container_type not in {"顶开门箱", "敞顶箱"}:
            raise UnifiedRoutePlanningError("集装箱箱型必须为“顶开门箱”或“敞顶箱”。")
        if self.transport_preference not in {"散粮", "铁路", "混合"}:
            raise UnifiedRoutePlanningError("运输方案范围必须为“散粮”“铁路”或“混合”。")


@dataclass(frozen=True)
class UnifiedRoutePlanningResponse:
    request: UnifiedRoutePlanningRequest
    selected_family: PlanningFamily
    bulk_response: RoutePlanningResponse | None = None
    rail_response: RailContainerPlanningResponse | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnifiedRoutePlanningService:
    """Dispatch by order compatibility while keeping concrete engines injectable."""

    bulk_engine: Callable[[RoutePlanningRequest], RoutePlanningResponse]
    rail_engine: Callable[[RailContainerPlanningRequest], RailContainerPlanningResponse]

    def plan(self, request: UnifiedRoutePlanningRequest) -> UnifiedRoutePlanningResponse:
        if not isinstance(request, UnifiedRoutePlanningRequest):
            raise UnifiedRoutePlanningError("统一规划服务只接受 UnifiedRoutePlanningRequest。")
        order = request.request
        if request.transport_preference == "散粮" and not (
            order.package_type == "散粮" and order.quantity_unit == "吨"
        ):
            raise UnifiedRoutePlanningError("选择散粮方案时，订单必须使用散粮/吨口径。")
        if request.transport_preference == "铁路" and not (
            order.package_type == "集装箱" and order.quantity_unit == "箱"
        ):
            raise UnifiedRoutePlanningError("选择铁路方案时，订单必须使用集装箱/箱口径。")
        if order.package_type == "散粮" and order.quantity_unit == "吨":
            response = self.bulk_engine(
                RoutePlanningRequest(
                    origin=request.northern_location,
                    destination=request.customer_name,
                    south_port=request.selected_south_port,
                    region=request.region,
                    request=order,
                )
            )
            if not isinstance(response, RoutePlanningResponse):
                raise UnifiedRoutePlanningError("散粮引擎必须返回 RoutePlanningResponse。")
            return UnifiedRoutePlanningResponse(request, "bulk", bulk_response=response)
        if order.package_type == "集装箱" and order.quantity_unit == "箱":
            if request.container_type is None:
                raise UnifiedRoutePlanningError("集装箱订单必须选择箱型，才能筛选兼容铁路方案。")
            response = self.rail_engine(
                RailContainerPlanningRequest(
                    north_station_name=request.northern_location,
                    customer_name=request.customer_name,
                    south_station_name=request.selected_south_port,
                    request=order,
                    container_type=request.container_type,
                )
            )
            if not isinstance(response, RailContainerPlanningResponse):
                raise UnifiedRoutePlanningError("铁路集装箱引擎必须返回 RailContainerPlanningResponse。")
            return UnifiedRoutePlanningResponse(request, "rail_container", rail_response=response)
        raise UnifiedRoutePlanningError(
            "当前统一入口只允许散粮/吨或集装箱/箱订单；吨、箱、柜不得自动互换，"
            "也不会为了比较路线而跨包装方式套用运价。"
        )


def _required(value: object, label: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise UnifiedRoutePlanningError(f"{label}不能为空。")
    return text
