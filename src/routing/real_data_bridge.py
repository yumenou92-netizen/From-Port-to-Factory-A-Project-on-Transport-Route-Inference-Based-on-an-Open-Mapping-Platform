from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping

from src.data.loaders import EdgeCandidate
from src.domain.node_registry import NodeRegistry
from src.routing.route_result import RouteRecommendationResults, build_route_recommendations
from src.routing.route_search import search_cost_and_time_paths
from src.routing.shipping_time_provider import (
    ManualShippingTimeProvider,
    ShippingTimeRequest,
)
from src.routing.transport_edge import (
    TransportEdge,
    TransportEdgeStatus,
    make_transport_edge_id,
)
from src.routing.transport_graph import TransportGraphBuildResult, build_transport_multidigraph


@dataclass(frozen=True)
class ManualTimeInput:
    duration_value: object | None
    duration_unit: str = "小时"
    source: str = "manual_input"


@dataclass(frozen=True)
class RealCandidateRouteBuildResult:
    transport_edges: tuple[TransportEdge, ...]
    graph_result: TransportGraphBuildResult
    recommendations: RouteRecommendationResults | None

    @property
    def available_edge_count(self) -> int:
        return sum(1 for edge in self.transport_edges if edge.is_available)

    @property
    def manual_review_edge_count(self) -> int:
        return sum(1 for edge in self.transport_edges if edge.requires_manual_review)


def build_transport_edge_from_candidate(
    candidate: EdgeCandidate,
    *,
    commodity: str,
    manual_time_input: ManualTimeInput | None = None,
) -> TransportEdge:
    """Convert one billed real-data candidate into the formal edge model."""
    stage = f"{candidate.origin} 至 {candidate.destination}"
    selected_time_input = manual_time_input or ManualTimeInput(duration_value=None)
    time_result = ManualShippingTimeProvider().get_shipping_time(
        ShippingTimeRequest(
            stage=stage,
            transport_mode=candidate.transport_mode,
            duration_value=selected_time_input.duration_value,
            duration_unit=selected_time_input.duration_unit,
            source=selected_time_input.source,
        )
    )

    review_reasons: list[str] = []
    if candidate.from_node_id is None:
        review_reasons.append("缺少起点节点 ID。")
    if candidate.to_node_id is None:
        review_reasons.append("缺少终点节点 ID。")
    if time_result.requires_manual_review:
        review_reasons.append(time_result.message)

    status: TransportEdgeStatus = "manual_review" if review_reasons else "available"
    data_source = _candidate_data_source(candidate)
    edge_id = make_transport_edge_id(
        rate_id=candidate.rate_id,
        from_node_id=candidate.from_node_id,
        to_node_id=candidate.to_node_id,
        transport_mode=candidate.transport_mode,
        package_type=candidate.packaging,
        commodity=commodity,
        cost_yuan=candidate.total_cost,
        time_hours=time_result.duration_hours,
        price_source=candidate.price_source,
        time_source=time_result.source,
        cost_rule_id=candidate.calculation_rule_id,
        cost_rule_version=candidate.calculation_rule_version,
        data_source=data_source,
    )

    return TransportEdge(
        edge_id=edge_id,
        status=status,
        from_node_id=candidate.from_node_id,
        to_node_id=candidate.to_node_id,
        transport_mode=candidate.transport_mode,
        package_type=candidate.packaging,
        commodity=commodity,
        cost_yuan=candidate.total_cost,
        time_hours=time_result.duration_hours,
        raw_price=candidate.raw_price,
        raw_price_unit=candidate.raw_price_unit,
        price_source=candidate.price_source,
        maintained_at=_parse_optional_date(candidate.maintenance_date),
        distance_km=None,
        distance_source=None,
        time_source=time_result.source,
        cost_rule_id=candidate.calculation_rule_id,
        cost_rule_version=candidate.calculation_rule_version,
        calculation_detail=candidate.calculation_detail,
        data_source=data_source,
        unavailable_reason="；".join(review_reasons) if review_reasons else None,
    )


def build_transport_edges_from_candidates(
    candidates: list[EdgeCandidate] | tuple[EdgeCandidate, ...],
    *,
    commodity: str,
    manual_time_by_rate_id: Mapping[str, ManualTimeInput] | None = None,
    default_manual_time: ManualTimeInput | None = None,
) -> tuple[TransportEdge, ...]:
    time_inputs = manual_time_by_rate_id or {}
    return tuple(
        build_transport_edge_from_candidate(
            candidate,
            commodity=commodity,
            manual_time_input=time_inputs.get(candidate.rate_id, default_manual_time),
        )
        for candidate in candidates
    )


def build_real_candidate_route_recommendations(
    candidates: list[EdgeCandidate] | tuple[EdgeCandidate, ...],
    *,
    commodity: str,
    node_registry: NodeRegistry,
    start_node_id: str,
    end_node_id: str,
    manual_time_by_rate_id: Mapping[str, ManualTimeInput] | None = None,
    default_manual_time: ManualTimeInput | None = None,
) -> RealCandidateRouteBuildResult:
    edges = build_transport_edges_from_candidates(
        candidates,
        commodity=commodity,
        manual_time_by_rate_id=manual_time_by_rate_id,
        default_manual_time=default_manual_time,
    )
    graph_result = build_transport_multidigraph(edges, node_registry=node_registry)
    searches = search_cost_and_time_paths(
        graph_result.graph,
        start_node_id,
        end_node_id,
    )
    return RealCandidateRouteBuildResult(
        transport_edges=edges,
        graph_result=graph_result,
        recommendations=build_route_recommendations(graph_result.graph, searches),
    )


def _candidate_data_source(candidate: EdgeCandidate) -> str:
    if candidate.source_file and candidate.source_row_number is not None:
        return f"{candidate.source_file}#row={candidate.source_row_number}"
    if candidate.source_file:
        return candidate.source_file
    return candidate.price_source


def _parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)
