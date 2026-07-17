from dataclasses import replace
from decimal import Decimal

import networkx as nx
import pytest

from src.route_result import (
    RouteResultError,
    build_route_recommendations,
    build_route_result,
    route_result_to_rows,
)
from src.route_search import NetworkXDijkstraRouteSearchStrategy, search_cost_and_time_paths
from src.transport_edge import TransportEdge
from src.transport_graph import build_transport_multidigraph


def make_edge(edge_id: str, start: str, end: str, cost: str, time: str) -> TransportEdge:
    return TransportEdge(
        edge_id=edge_id,
        status="available",
        from_node_id=start,
        to_node_id=end,
        transport_mode="汽运" if "road" in edge_id else "水运",
        package_type="散粮",
        commodity="玉米",
        cost_yuan=Decimal(cost),
        time_hours=Decimal(time),
        raw_price=Decimal("20"),
        raw_price_unit="元/吨",
        price_source=f"演示价格来源 {edge_id}",
        maintained_at=None,
        distance_km=Decimal("10"),
        distance_source="人工维护距离",
        time_source="manual_shipping_time",
        cost_rule_id="demo_cost_rule",
        cost_rule_version="1.0",
        calculation_detail=f"演示计算过程 {edge_id}",
        data_source=f"sanitized_rates.json#{edge_id}",
    )


def make_choice_graph() -> nx.MultiDiGraph:
    return build_transport_multidigraph(
        [
            make_edge("edge-road-a-b", "node-a", "node-b", "10", "10"),
            make_edge("edge-road-b-d", "node-b", "node-d", "10", "10"),
            make_edge("edge-water-a-c", "node-a", "node-c", "20", "2"),
            make_edge("edge-water-c-d", "node-c", "node-d", "20", "2"),
        ],
        allow_unregistered_nodes=True,
    ).graph


def test_builds_explainable_cost_and_time_recommendations():
    graph = make_choice_graph()
    searches = search_cost_and_time_paths(graph, "node-a", "node-d")

    results = build_route_recommendations(graph, searches)

    lowest_cost = results.lowest_cost
    assert lowest_cost.status == "resolved"
    assert lowest_cost.recommendation_type == "lowest_cost"
    assert lowest_cost.path_node_ids == ("node-a", "node-b", "node-d")
    assert lowest_cost.total_cost_yuan == Decimal("20")
    assert lowest_cost.total_cost == Decimal("20")
    assert lowest_cost.total_time_hours == Decimal("20")
    assert not lowest_cost.missing_data_flag
    assert "费用与时间未合并" in lowest_cost.explanation

    fastest = results.fastest_time
    assert fastest.status == "resolved"
    assert fastest.recommendation_type == "fastest_time"
    assert fastest.path_node_ids == ("node-a", "node-c", "node-d")
    assert fastest.total_cost_yuan == Decimal("40")
    assert fastest.total_time_hours == Decimal("4")


def test_route_segments_preserve_edge_keys_and_trace_fields():
    graph = make_choice_graph()
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-d",
        objective="cost",
    )

    result = build_route_result(graph, search)

    first = result.segments[0]
    assert first.segment_no == 1
    assert first.from_node_id == "node-a"
    assert first.to_node_id == "node-b"
    assert first.edge_key == "edge-road-a-b"
    assert first.transport_mode == "汽运"
    assert first.package_type == "散粮"
    assert first.cost_yuan == Decimal("10")
    assert first.time_hours == Decimal("10")
    assert first.price_source == "演示价格来源 edge-road-a-b"
    assert first.time_source == "manual_shipping_time"
    assert first.cost_rule_id == "demo_cost_rule"
    assert first.cost_rule_version == "1.0"
    assert first.data_source == "sanitized_rates.json#edge-road-a-b"


def test_route_result_rows_include_segment_and_route_totals():
    graph = make_choice_graph()
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-d",
        objective="time",
    )
    result = build_route_result(graph, search)

    rows = route_result_to_rows(result)

    assert len(rows) == 2
    assert rows[0]["recommendation_type"] == "fastest_time"
    assert rows[0]["segment_no"] == 1
    assert rows[0]["edge_key"] == "edge-water-a-c"
    assert rows[0]["segment_cost_yuan"] == Decimal("20")
    assert rows[0]["route_total_cost_yuan"] == Decimal("40")
    assert rows[0]["route_total_time_hours"] == Decimal("4")
    assert rows[0]["path"] == "node-a -> node-c -> node-d"
    assert rows[0]["objective"] == "time"
    assert not rows[0]["missing_data_flag"]


def test_no_path_and_missing_node_preserve_explicit_status():
    graph = make_choice_graph()
    graph.add_node("node-isolated")
    strategy = NetworkXDijkstraRouteSearchStrategy()

    no_path_search = strategy.search(graph, "node-a", "node-isolated", objective="cost")
    no_path_result = build_route_result(graph, no_path_search)
    assert no_path_result.status == "no_path"
    assert not no_path_result.missing_data_flag
    assert no_path_result.total_cost_yuan is None
    no_path_rows = route_result_to_rows(no_path_result)
    assert len(no_path_rows) == 1
    assert no_path_rows[0]["status"] == "no_path"
    assert no_path_rows[0]["segment_no"] is None
    assert no_path_rows[0]["explanation"] == no_path_result.explanation

    review_search = strategy.search(graph, "node-missing", "node-d", objective="cost")
    review_result = build_route_result(graph, review_search)
    assert review_result.status == "manual_review"
    assert review_result.missing_data_flag
    assert "不在正式图中" in review_result.explanation
    review_rows = route_result_to_rows(review_result)
    assert len(review_rows) == 1
    assert review_rows[0]["status"] == "manual_review"
    assert review_rows[0]["missing_data_flag"]


def test_edge_removed_after_search_returns_manual_review_result():
    graph = make_choice_graph()
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-d",
        objective="cost",
    )
    graph.remove_edge("node-a", "node-b", key="edge-road-a-b")

    result = build_route_result(graph, search)

    assert result.status == "manual_review"
    assert result.missing_data_flag
    assert result.segments == ()
    assert "必须重新搜索" in result.explanation


def test_missing_trace_attribute_returns_manual_review_result():
    graph = make_choice_graph()
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-d",
        objective="cost",
    )
    del graph["node-a"]["node-b"]["edge-road-a-b"]["price_source"]

    result = build_route_result(graph, search)

    assert result.status == "manual_review"
    assert "缺少 price_source" in result.explanation


def test_graph_weight_mutation_after_search_requires_new_search():
    graph = make_choice_graph()
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-d",
        objective="cost",
    )
    graph["node-a"]["node-c"]["edge-water-a-c"]["cost"] = Decimal("1")

    result = build_route_result(graph, search)

    assert result.status == "manual_review"
    assert "图节点、运输边或目标权重已变化" in result.explanation


def test_inconsistent_custom_search_outcome_returns_manual_review():
    graph = make_choice_graph()
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-d",
        objective="cost",
    )
    inconsistent = replace(search, node_ids=("node-a", "node-c", "node-d"))

    result = build_route_result(graph, inconsistent)

    assert result.status == "manual_review"
    assert "节点路径不一致" in result.explanation


def test_graph_build_issues_prevent_resolved_recommendation():
    unavailable = make_edge("edge-review", "node-x", "node-y", "5", "2")
    unavailable = replace(
        unavailable,
        status="manual_review",
        cost_yuan=None,
        time_hours=None,
        unavailable_reason="演示缺少确认数据。",
    )
    graph_result = build_transport_multidigraph(
        [make_edge("edge-a-b", "node-a", "node-b", "5", "2"), unavailable],
        allow_unregistered_nodes=True,
    )
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph_result.graph,
        "node-a",
        "node-b",
        objective="cost",
    )

    result = build_route_result(graph_result.graph, search)

    assert result.status == "manual_review"
    assert "正式图构建时排除了 1 条记录" in result.explanation


def test_route_result_rejects_totals_that_do_not_match_segments():
    graph = make_choice_graph()
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-d",
        objective="cost",
    )
    result = build_route_result(graph, search)

    with pytest.raises(RouteResultError, match="总费用必须等于分段费用之和"):
        replace(result, total_cost_yuan=Decimal("999"))


def test_same_node_result_requires_manual_review():
    graph = nx.MultiDiGraph()
    graph.add_node("node-a")
    search = NetworkXDijkstraRouteSearchStrategy().search(
        graph,
        "node-a",
        "node-a",
        objective="time",
    )

    result = build_route_result(graph, search)

    assert result.status == "manual_review"
    assert result.path_node_ids == ()
    assert result.segments == ()
    assert result.total_cost_yuan is None
    assert result.total_time_hours is None
