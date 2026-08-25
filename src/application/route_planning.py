from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from src.domain.route_request import RouteRequest
from src.geo.coordinate_provider import CoordinateResolution
from src.geo.distance_provider import GeoPoint
from src.routing.route_result import RouteRecommendationResults


class RoutePlanningContractError(ValueError):
    """Raised when an application request is incomplete or ambiguous."""


CandidateDecisionStatus = Literal["shortlisted", "included", "excluded", "not_selected"]
CandidateDecisionStage = Literal[
    "identity",
    "ranking",
    "north_to_south",
    "port_operation_fee",
    "south_to_customer",
    "graph",
]


@dataclass(frozen=True)
class RoutePlanningRequest:
    """Transport conditions accepted consistently by every presentation adapter."""

    origin: str
    destination: str
    request: RouteRequest
    south_port: str | None = None
    region: str = "全国"

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", _required_text(self.origin, "出发北港"))
        object.__setattr__(
            self,
            "destination",
            _required_text(self.destination, "客户工厂"),
        )
        object.__setattr__(self, "south_port", _optional_text(self.south_port))
        object.__setattr__(self, "region", _required_text(self.region, "地点检索区域"))
        if not isinstance(self.request, RouteRequest):
            raise RoutePlanningContractError("订单信息必须使用 RouteRequest。")


@dataclass(frozen=True)
class TransferPort:
    node_id: str
    name: str
    point: GeoPoint
    straight_line_km_to_factory: Decimal


@dataclass(frozen=True)
class EdgeSourceTrace:
    edge_id: str
    labels: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class EdgeGeometryTrace:
    edge_id: str
    kind: str
    source: str
    points: tuple[GeoPoint, ...]
    is_schematic: bool
    message: str


@dataclass(frozen=True)
class SouthPortCandidateDecision:
    """Trace one south-port candidate from identity screening to graph admission."""

    node_id: str
    name: str
    status: CandidateDecisionStatus
    stage: CandidateDecisionStage
    reason: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutePlanningResponse:
    """UI-neutral response consumed by CLI, Web, and future database/API adapters."""

    origin_name: str
    destination_name: str
    selected_south_port: str | None
    origin_resolution: CoordinateResolution
    destination_resolution: CoordinateResolution
    request: RouteRequest
    candidate_ports: tuple[TransferPort, ...]
    intermediate_ports: tuple[TransferPort, ...]
    graph_edge_count: int
    recommendations: RouteRecommendationResults
    node_names: dict[str, str]
    edge_sources: dict[str, EdgeSourceTrace]
    edge_geometries: dict[str, EdgeGeometryTrace]
    warnings: tuple[str, ...]
    additional_fee_count: int
    trunk_edge_count: int
    port_operation_fee_source: str | None
    port_operation_fee_included_count: int
    port_operation_fee_not_applicable_count: int
    inland_waterway_source: str | None
    barge_edge_count: int
    barge_placeholder_capability_count: int
    truck_edge_count: int
    south_to_customer_options_by_port: dict[str, tuple[str, ...]]
    candidate_decisions: tuple[SouthPortCandidateDecision, ...] = ()


class RoutePlanningEngine(Protocol):
    def __call__(self, request: RoutePlanningRequest) -> RoutePlanningResponse:
        """Execute one route-planning request."""
        ...


@dataclass(frozen=True)
class RoutePlanningService:
    """Stable application entry point around an injected planning engine."""

    engine: RoutePlanningEngine

    def plan(self, request: RoutePlanningRequest) -> RoutePlanningResponse:
        if not isinstance(request, RoutePlanningRequest):
            raise RoutePlanningContractError(
                "路线规划服务只接受 RoutePlanningRequest。"
            )
        response = self.engine(request)
        if not isinstance(response, RoutePlanningResponse):
            raise RoutePlanningContractError(
                "路线规划引擎必须返回 RoutePlanningResponse。"
            )
        return response


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise RoutePlanningContractError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
