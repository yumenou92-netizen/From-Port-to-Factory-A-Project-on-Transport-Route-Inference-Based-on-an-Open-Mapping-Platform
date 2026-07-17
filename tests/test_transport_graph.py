from decimal import Decimal

import networkx as nx
import pytest

from src.domain.node_registry import NodeRegistry, StandardNode
from src.routing.transport_edge import TransportEdge
from src.routing.transport_graph import TransportGraphError, build_transport_multidigraph


def make_edge(**overrides) -> TransportEdge:
    values = {
        "edge_id": "edge-demo-a",
        "status": "available",
        "from_node_id": "node-a",
        "to_node_id": "node-b",
        "transport_mode": "汽运",
        "package_type": "散粮",
        "commodity": "玉米",
        "cost_yuan": Decimal("1000"),
        "time_hours": Decimal("4"),
        "raw_price": Decimal("20"),
        "raw_price_unit": "元/吨",
        "price_source": "演示台账 A",
        "maintained_at": None,
        "distance_km": Decimal("80"),
        "distance_source": "人工维护距离",
        "time_source": "manual_shipping_time",
        "cost_rule_id": "known_truck_maintained_rate",
        "cost_rule_version": "1.0",
        "calculation_detail": "演示计费过程",
        "data_source": "sanitized_rates.json#row=1",
        "unavailable_reason": None,
    }
    values.update(overrides)
    return TransportEdge(**values)


def make_registry() -> NodeRegistry:
    nodes = {
        "node-a": StandardNode("node-a", "演示节点 A", ("演示节点 A",), 113.1, 23.1, 1),
        "node-b": StandardNode("node-b", "演示节点 B", ("演示节点 B",), 113.2, 23.2, 1),
        "node-c": StandardNode("node-c", "演示节点 C", ("演示节点 C",), 113.3, 23.3, 1),
    }
    return NodeRegistry(
        nodes=nodes,
        name_to_node_id={name: node_id for node_id, node in nodes.items() for name in node.aliases},
        alias_groups=(),
        alias_review_groups=(),
        coordinate_conflicts=(),
    )


def test_builds_multidigraph_and_preserves_parallel_edges():
    first = make_edge()
    second = make_edge(
        edge_id="edge-demo-b",
        transport_mode="水运",
        cost_yuan="800",
        time_hours="8",
        price_source="演示台账 B",
        data_source="sanitized_rates.json#row=2",
    )

    result = build_transport_multidigraph([first, second], allow_unregistered_nodes=True)

    assert isinstance(result.graph, nx.MultiDiGraph)
    assert result.added_edge_ids == ("edge-demo-a", "edge-demo-b")
    assert result.graph.number_of_edges("node-a", "node-b") == 2
    assert set(result.graph["node-a"]["node-b"]) == {"edge-demo-a", "edge-demo-b"}
    assert result.graph["node-a"]["node-b"]["edge-demo-a"]["cost"] == Decimal("1000")
    assert result.graph["node-a"]["node-b"]["edge-demo-b"]["time_hours"] == Decimal("8")


def test_graph_declares_independent_cost_and_time_weights():
    result = build_transport_multidigraph([make_edge()], allow_unregistered_nodes=True)

    assert result.graph.graph["cost_weight"] == "cost"
    assert result.graph.graph["time_weight"] == "time_hours"
    assert "combined_weight" not in result.graph.graph


def test_unavailable_edges_are_excluded_with_traceable_issue():
    unavailable = make_edge(
        edge_id="edge-review",
        status="manual_review",
        cost_yuan=None,
        time_hours=None,
        unavailable_reason="缺少费用和时间。",
    )

    result = build_transport_multidigraph([unavailable], allow_unregistered_nodes=True)

    assert result.graph.number_of_edges() == 0
    assert result.added_edge_ids == ()
    assert result.issues[0].code == "unavailable_edge"
    assert result.issues[0].edge_id == "edge-review"
    assert "缺少费用和时间" in result.issues[0].message


def test_duplicate_edge_key_is_not_silently_overwritten():
    first = make_edge()
    duplicate = make_edge(cost_yuan="1200", calculation_detail="另一计算过程")

    result = build_transport_multidigraph([first, duplicate], allow_unregistered_nodes=True)

    assert result.graph.number_of_edges() == 1
    assert result.graph["node-a"]["node-b"]["edge-demo-a"]["cost"] == Decimal("1000")
    assert result.issues[0].code == "duplicate_edge_id"
    assert "重复" in result.issues[0].message


def test_registry_nodes_are_added_with_coordinates_and_unknown_edge_is_excluded():
    registry = make_registry()
    known = make_edge()
    unknown = make_edge(
        edge_id="edge-unknown",
        from_node_id="node-missing",
        to_node_id="node-c",
    )

    result = build_transport_multidigraph([known, unknown], node_registry=registry)

    assert result.graph.number_of_nodes() == 3
    assert result.graph.nodes["node-a"]["canonical_name"] == "演示节点 A"
    assert result.graph.nodes["node-a"]["longitude"] == 113.1
    assert result.graph.number_of_edges() == 1
    assert result.issues[0].code == "unknown_node"
    assert "node-missing" in result.issues[0].message


def test_no_missing_cost_or_time_defaults_are_created():
    edge = make_edge()

    result = build_transport_multidigraph([edge], allow_unregistered_nodes=True)
    attributes = result.graph["node-a"]["node-b"][edge.edge_key]

    assert attributes["cost"] == Decimal("1000")
    assert attributes["time_hours"] == Decimal("4")
    assert attributes["cost"] != 0
    assert attributes["time_hours"] != 0


def test_transport_graph_rejects_non_transport_edge_values():
    with pytest.raises(TransportGraphError, match="TransportEdge"):
        build_transport_multidigraph(
            [{"from": "node-a", "to": "node-b"}],
            allow_unregistered_nodes=True,
        )


def test_formal_graph_requires_registry_unless_explicitly_allowed():
    with pytest.raises(TransportGraphError, match="node_registry"):
        build_transport_multidigraph([make_edge()])


def test_graph_records_build_completeness_and_issues():
    unavailable = make_edge(
        edge_id="edge-review",
        status="manual_review",
        cost_yuan=None,
        time_hours=None,
        unavailable_reason="缺少费用和时间。",
    )

    result = build_transport_multidigraph(
        [make_edge(), unavailable],
        allow_unregistered_nodes=True,
    )

    assert not result.graph.graph["build_complete"]
    assert result.graph.graph["build_issues"] == result.issues
    assert result.graph.graph["node_validation_mode"] == "explicit_unregistered_allowed"
