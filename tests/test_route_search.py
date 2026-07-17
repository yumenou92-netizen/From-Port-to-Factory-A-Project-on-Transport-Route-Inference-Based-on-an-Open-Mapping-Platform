from decimal import Decimal

import networkx as nx
import pytest

from src.routing.route_search import (
    NetworkXDijkstraRouteSearchStrategy,
    RouteSearchError,
    search_cost_and_time_paths,
)
from src.routing.transport_edge import TransportEdge
from src.routing.transport_graph import build_transport_multidigraph


def make_edge(edge_id: str, start: str, end: str, cost: str, time: str) -> TransportEdge:
    return TransportEdge(
        edge_id=edge_id,
        status="available",
        from_node_id=start,
        to_node_id=end,
        transport_mode="汽运",
        package_type="散粮",
        commodity="玉米",
        cost_yuan=Decimal(cost),
        time_hours=Decimal(time),
        raw_price=Decimal("20"),
        raw_price_unit="元/吨",
        price_source=f"演示来源 {edge_id}",
        maintained_at=None,
        distance_km=Decimal("10"),
        distance_source="人工维护距离",
        time_source="manual_shipping_time",
        cost_rule_id="known_truck_maintained_rate",
        cost_rule_version="1.0",
        calculation_detail=f"演示计算 {edge_id}",
        data_source=f"sanitized_rates.json#{edge_id}",
    )


def make_choice_graph() -> nx.MultiDiGraph:
    edges = [
        make_edge("edge-a-b-cheap", "node-a", "node-b", "10", "10"),
        make_edge("edge-b-d-cheap", "node-b", "node-d", "10", "10"),
        make_edge("edge-a-c-fast", "node-a", "node-c", "20", "2"),
        make_edge("edge-c-d-fast", "node-c", "node-d", "20", "2"),
        make_edge("edge-a-b-fast", "node-a", "node-b", "15", "1"),
    ]
    return build_transport_multidigraph(edges, allow_unregistered_nodes=True).graph


def test_cost_and_time_search_can_return_different_paths_and_edge_keys():
    recommendations = search_cost_and_time_paths(
        make_choice_graph(),
        "node-a",
        "node-d",
    )

    cost_path = recommendations.lowest_cost
    assert cost_path.status == "found"
    assert cost_path.node_ids == ("node-a", "node-b", "node-d")
    assert cost_path.edge_keys == ("edge-a-b-cheap", "edge-b-d-cheap")
    assert cost_path.optimized_total == Decimal("20")
    assert cost_path.weight_name == "cost"

    time_path = recommendations.fastest_time
    assert time_path.status == "found"
    assert time_path.node_ids == ("node-a", "node-c", "node-d")
    assert time_path.edge_keys == ("edge-a-c-fast", "edge-c-d-fast")
    assert time_path.optimized_total == Decimal("4")
    assert time_path.weight_name == "time_hours"


def test_parallel_edges_select_specific_key_for_each_objective():
    graph = build_transport_multidigraph(
        [
            make_edge("edge-cheap-slow", "node-a", "node-b", "5", "8"),
            make_edge("edge-fast-costly", "node-a", "node-b", "9", "2"),
        ],
        allow_unregistered_nodes=True,
    ).graph
    strategy = NetworkXDijkstraRouteSearchStrategy()

    cost_path = strategy.search(graph, "node-a", "node-b", objective="cost")
    time_path = strategy.search(graph, "node-a", "node-b", objective="time")

    assert cost_path.edge_keys == ("edge-cheap-slow",)
    assert time_path.edge_keys == ("edge-fast-costly",)
    assert cost_path.edge_steps[0].from_node_id == "node-a"
    assert cost_path.edge_steps[0].to_node_id == "node-b"


def test_no_path_returns_explicit_no_path_result():
    graph = build_transport_multidigraph(
        [make_edge("edge-a-b", "node-a", "node-b", "5", "2")],
        allow_unregistered_nodes=True,
    ).graph
    graph.add_node("node-c")

    result = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-c",
        objective="cost",
    )

    assert result.status == "no_path"
    assert result.node_ids == ()
    assert result.edge_keys == ()
    assert result.optimized_total is None
    assert "不存在可达路径" in result.message


def test_missing_start_or_end_node_requires_manual_review():
    graph = build_transport_multidigraph(
        [make_edge("edge-a-b", "node-a", "node-b", "5", "2")],
        allow_unregistered_nodes=True,
    ).graph

    result = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-missing",
        "node-b",
        objective="time",
    )

    assert result.status == "manual_review"
    assert result.optimized_total is None
    assert "不在正式图中" in result.message


def test_missing_weight_requires_review_instead_of_defaulting_to_one():
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "node-a",
        "node-b",
        key="edge-missing-time",
        edge_id="edge-missing-time",
        cost=Decimal("10"),
    )

    result = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-b",
        objective="time",
    )

    assert result.status == "manual_review"
    assert result.edge_keys == ()
    assert "缺少 time_hours" in result.message


@pytest.mark.parametrize("value", [0, "-1", "not-a-number", float("nan")])
def test_invalid_graph_weight_requires_review(value):
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "node-a",
        "node-b",
        key="edge-invalid",
        edge_id="edge-invalid",
        cost=value,
        time_hours=Decimal("2"),
    )

    result = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-b",
        objective="cost",
    )

    assert result.status == "manual_review"
    assert "大于 0 的有限数值" in result.message


def test_same_start_and_end_requires_manual_review():
    graph = nx.MultiDiGraph()
    graph.add_node("node-a")

    result = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-a",
        objective="cost",
    )

    assert result.status == "manual_review"
    assert result.node_ids == ()
    assert result.edge_steps == ()
    assert result.optimized_total is None
    assert "起点与终点相同" in result.message


def test_search_rejects_unsupported_objective_and_non_multidigraph():
    strategy = NetworkXDijkstraRouteSearchStrategy()

    with pytest.raises(RouteSearchError, match="cost 或 time"):
        strategy.search(nx.MultiDiGraph(), "node-a", "node-b", objective="combined")
    with pytest.raises(RouteSearchError, match="MultiDiGraph"):
        strategy.search(nx.DiGraph(), "node-a", "node-b", objective="cost")
