"""UI-neutral railway-container planning application service.

This service accepts a platform-style order request plus injected, typed
railway data.  It does not read local workbooks or invent missing data: a data
adapter is responsible for constructing the providers from a future platform
or local table snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.domain.node_registry import NodeRegistry
from src.domain.route_request import RouteRequest
from src.routing.rail_container_provider import TableRailContainerProvider
from src.routing.rail_customer_delivery_provider import (
    RailCustomerDeliveryPlanResult,
    RailCustomerDeliveryProvider,
)
from src.routing.route_result import RouteRecommendationResults, build_route_recommendations
from src.routing.route_search import search_cost_and_time_paths
from src.routing.transport_edge import TransportEdge
from src.routing.transport_graph import build_transport_multidigraph


class RailContainerPlanningError(ValueError):
    """Raised when a railway-container platform request is malformed."""


@dataclass(frozen=True)
class RailContainerPlanningRequest:
    """Transport conditions a future platform submits for one rail order."""

    north_station_name: str
    customer_name: str
    request: RouteRequest
    container_type: Literal["顶开门箱", "敞顶箱"]
    south_station_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "north_station_name", _required_text(self.north_station_name, "北站"))
        object.__setattr__(self, "customer_name", _required_text(self.customer_name, "客户工厂"))
        south = str(self.south_station_name).strip() if self.south_station_name is not None else ""
        object.__setattr__(self, "south_station_name", south or None)
        if not isinstance(self.request, RouteRequest):
            raise RailContainerPlanningError("订单必须使用 RouteRequest。")
        if self.request.package_type != "集装箱" or self.request.quantity_unit != "箱":
            raise RailContainerPlanningError("铁路集装箱规划仅支持“集装箱/箱”订单；“柜”不得自动换算。")
        if self.container_type not in {"顶开门箱", "敞顶箱"}:
            raise RailContainerPlanningError("箱型必须为“顶开门箱”或“敞顶箱”。")


@dataclass(frozen=True)
class RailContainerPlanningData:
    """Typed data dependencies supplied by a table/API adapter."""

    node_registry: NodeRegistry
    trunk_provider: TableRailContainerProvider
    terminal_provider: RailCustomerDeliveryProvider


@dataclass(frozen=True)
class RailContainerCandidateOutcome:
    south_station_name: str
    status: Literal["included", "manual_review"]
    message: str


@dataclass(frozen=True)
class RailContainerPlanningResponse:
    request: RailContainerPlanningRequest
    graph_edge_count: int
    recommendations: RouteRecommendationResults
    candidate_outcomes: tuple[RailContainerCandidateOutcome, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RailContainerPlanningService:
    """Compose rail trunk and terminal providers into one formal graph search."""

    data: RailContainerPlanningData

    def plan(self, request: RailContainerPlanningRequest) -> RailContainerPlanningResponse:
        if not isinstance(request, RailContainerPlanningRequest):
            raise RailContainerPlanningError("铁路集装箱服务只接受 RailContainerPlanningRequest。")
        start = self.data.node_registry.lookup(request.north_station_name)
        customer = self.data.node_registry.lookup(request.customer_name)
        if start is None or customer is None:
            missing = "北站" if start is None else "客户工厂"
            raise RailContainerPlanningError(f"平台请求的{missing}未注册为标准节点，不能构建正式图。")

        candidate_records = [
            record
            for record in self.data.trunk_provider.records
            if record.north_station_name == request.north_station_name
            and (request.south_station_name is None or record.south_station_name == request.south_station_name)
            and record.container_type == request.container_type
            and record.supports_request(request.request)
        ]
        if not candidate_records:
            return self._no_candidate_response(request, start.node_id, customer.node_id)

        edges: list[TransportEdge] = []
        outcomes: list[RailContainerCandidateOutcome] = []
        warnings: list[str] = []
        for record in candidate_records:
            trunk_edge, trunk_match = self.data.trunk_provider.build_edge(
                north_station_name=request.north_station_name,
                south_station_name=record.south_station_name,
                request=request.request,
                container_type=request.container_type,
            )
            if trunk_edge is None:
                outcomes.append(RailContainerCandidateOutcome(record.south_station_name, "manual_review", trunk_match.message))
                continue
            terminal = self.data.terminal_provider.build_direct_truck(
                south_station_name=record.south_station_name,
                customer_name=request.customer_name,
                request=request.request,
                container_type=request.container_type,
            )
            if terminal.status != "resolved":
                outcomes.append(RailContainerCandidateOutcome(record.south_station_name, "manual_review", terminal.message))
                continue
            if len(terminal.edges) != 1:
                outcomes.append(RailContainerCandidateOutcome(record.south_station_name, "manual_review", "直达拖车方案未返回唯一交付边。"))
                continue
            edges.extend((trunk_edge, terminal.edges[0]))
            outcomes.append(RailContainerCandidateOutcome(record.south_station_name, "included", "已构建铁路干线和直达拖车交付边。"))

        graph_result = build_transport_multidigraph(edges, node_registry=self.data.node_registry)
        warnings.extend(issue.message for issue in graph_result.issues)
        searches = search_cost_and_time_paths(graph_result.graph, start.node_id, customer.node_id)
        return RailContainerPlanningResponse(
            request=request,
            graph_edge_count=graph_result.added_edge_count,
            recommendations=build_route_recommendations(graph_result.graph, searches),
            candidate_outcomes=tuple(outcomes),
            warnings=tuple(warnings),
        )

    def _no_candidate_response(
        self,
        request: RailContainerPlanningRequest,
        start_node_id: str,
        customer_node_id: str,
    ) -> RailContainerPlanningResponse:
        graph_result = build_transport_multidigraph((), node_registry=self.data.node_registry)
        searches = search_cost_and_time_paths(graph_result.graph, start_node_id, customer_node_id)
        scope = request.south_station_name or "全部已维护南站"
        return RailContainerPlanningResponse(
            request=request,
            graph_edge_count=0,
            recommendations=build_route_recommendations(graph_result.graph, searches),
            candidate_outcomes=(),
            warnings=(f"未找到北站至{scope}的精确铁路集装箱干线记录；不构边。",),
        )


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise RailContainerPlanningError(f"{field_name}不能为空。")
    return text
