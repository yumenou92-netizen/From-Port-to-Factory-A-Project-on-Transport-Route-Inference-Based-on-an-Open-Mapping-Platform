from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

import networkx as nx

try:
    from .node_registry import NodeRegistry
    from .transport_edge import TransportEdge
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.domain.node_registry import NodeRegistry
    from src.routing.transport_edge import TransportEdge


TransportGraphIssueCode = Literal[
    "unavailable_edge",
    "duplicate_edge_id",
    "unknown_node",
]


class TransportGraphError(ValueError):
    """Raised when the formal transport graph cannot be built safely."""


@dataclass(frozen=True)
class TransportGraphIssue:
    code: TransportGraphIssueCode
    edge_id: str
    message: str


@dataclass(frozen=True)
class TransportGraphBuildResult:
    graph: nx.MultiDiGraph
    added_edge_ids: tuple[str, ...]
    issues: tuple[TransportGraphIssue, ...]

    @property
    def added_edge_count(self) -> int:
        return len(self.added_edge_ids)

    @property
    def excluded_edge_count(self) -> int:
        return len(self.issues)


def build_transport_multidigraph(
    edges: Iterable[TransportEdge],
    *,
    node_registry: NodeRegistry | None = None,
    allow_unregistered_nodes: bool = False,
) -> TransportGraphBuildResult:
    """Build the formal graph using edge IDs as MultiDiGraph keys."""
    if node_registry is None and not allow_unregistered_nodes:
        raise TransportGraphError(
            "正式图必须提供 node_registry；脱敏演示或单元测试可显式设置 "
            "allow_unregistered_nodes=True。"
        )

    graph = nx.MultiDiGraph(
        graph_type="formal_transport_multidigraph",
        cost_weight="cost",
        time_weight="time_hours",
        node_validation_mode=(
            "registry" if node_registry is not None else "explicit_unregistered_allowed"
        ),
    )
    if node_registry is not None:
        _add_registry_nodes(graph, node_registry)

    added_edge_ids: list[str] = []
    issues: list[TransportGraphIssue] = []
    added_edge_id_set: set[str] = set()

    for edge in edges:
        if not isinstance(edge, TransportEdge):
            raise TransportGraphError("正式图只能接收 TransportEdge 对象。")

        if not edge.is_available:
            issues.append(
                TransportGraphIssue(
                    code="unavailable_edge",
                    edge_id=edge.edge_id,
                    message=f"运输边未进入正式图：{edge.unavailable_reason}",
                )
            )
            continue

        if edge.edge_id in added_edge_id_set:
            issues.append(
                TransportGraphIssue(
                    code="duplicate_edge_id",
                    edge_id=edge.edge_id,
                    message=f"运输边编号重复，已保留首次记录并跳过后续记录：{edge.edge_id}",
                )
            )
            continue

        if node_registry is not None:
            missing_node_ids = [
                node_id
                for node_id in (edge.from_node_id, edge.to_node_id)
                if node_id not in node_registry.nodes
            ]
            if missing_node_ids:
                issues.append(
                    TransportGraphIssue(
                        code="unknown_node",
                        edge_id=edge.edge_id,
                        message=f"运输边引用了未注册节点：{'、'.join(missing_node_ids)}",
                    )
                )
                continue

        graph.add_edge(
            edge.from_node_id,
            edge.to_node_id,
            key=edge.edge_key,
            **edge.to_graph_attributes(),
        )
        graph.nodes[edge.from_node_id].setdefault("node_id", edge.from_node_id)
        graph.nodes[edge.to_node_id].setdefault("node_id", edge.to_node_id)
        added_edge_ids.append(edge.edge_id)
        added_edge_id_set.add(edge.edge_id)

    graph.graph["build_issues"] = tuple(issues)
    graph.graph["build_complete"] = not issues
    return TransportGraphBuildResult(
        graph=graph,
        added_edge_ids=tuple(added_edge_ids),
        issues=tuple(issues),
    )


def _add_registry_nodes(graph: nx.MultiDiGraph, node_registry: NodeRegistry) -> None:
    for node_id, node in node_registry.nodes.items():
        graph.add_node(
            node_id,
            node_id=node.node_id,
            canonical_name=node.canonical_name,
            aliases=node.aliases,
            longitude=node.longitude,
            latitude=node.latitude,
            source_record_count=node.source_record_count,
        )
