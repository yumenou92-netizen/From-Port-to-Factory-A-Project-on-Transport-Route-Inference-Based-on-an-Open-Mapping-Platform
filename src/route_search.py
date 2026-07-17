from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

import networkx as nx


SearchObjective = Literal["cost", "time"]
SearchStatus = Literal["found", "no_path", "manual_review"]

OBJECTIVE_WEIGHTS: dict[SearchObjective, str] = {
    "cost": "cost",
    "time": "time_hours",
}


class RouteSearchError(ValueError):
    """Raised when a route search request is structurally invalid."""


@dataclass(frozen=True)
class RouteEdgeReference:
    from_node_id: str
    to_node_id: str
    edge_key: str
    objective_weight: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_node_id", _required_text(self.from_node_id, "分段起点"))
        object.__setattr__(self, "to_node_id", _required_text(self.to_node_id, "分段终点"))
        object.__setattr__(self, "edge_key", _required_text(self.edge_key, "运输边 key"))
        object.__setattr__(
            self,
            "objective_weight",
            _positive_decimal(self.objective_weight, "分段目标权重"),
        )


@dataclass(frozen=True)
class RouteSearchOutcome:
    status: SearchStatus
    objective: SearchObjective
    weight_name: str
    node_ids: tuple[str, ...]
    edge_steps: tuple[RouteEdgeReference, ...]
    optimized_total: Decimal | None
    message: str
    graph_signature: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"found", "no_path", "manual_review"}:
            raise RouteSearchError(f"不支持的路径搜索状态：{self.status}")
        if self.objective not in OBJECTIVE_WEIGHTS:
            raise RouteSearchError("搜索目标只能是 cost 或 time。")
        if self.weight_name != OBJECTIVE_WEIGHTS[self.objective]:
            raise RouteSearchError("搜索权重字段与搜索目标不一致。")
        object.__setattr__(self, "message", _required_text(self.message, "搜索结果说明"))

        if self.status == "found":
            if not self.node_ids:
                raise RouteSearchError("已找到路径必须包含节点。")
            if len(self.edge_steps) != len(self.node_ids) - 1:
                raise RouteSearchError("路径分段数量必须等于节点数量减一。")
            if self.optimized_total is None:
                raise RouteSearchError("已找到路径必须包含目标权重合计。")
            total = _non_negative_decimal(self.optimized_total, "路径目标权重合计")
            object.__setattr__(self, "optimized_total", total)
        elif self.node_ids or self.edge_steps or self.optimized_total is not None:
            raise RouteSearchError("未找到可执行路径时不得包含节点、分段或权重合计。")

        if self.status in {"found", "no_path"}:
            object.__setattr__(
                self,
                "graph_signature",
                _required_text(self.graph_signature, "搜索图权重签名"),
            )
        elif self.graph_signature is not None:
            raise RouteSearchError("人工复核搜索结果不得包含可执行图签名。")

    @property
    def edge_keys(self) -> tuple[str, ...]:
        return tuple(step.edge_key for step in self.edge_steps)

    @property
    def is_found(self) -> bool:
        return self.status == "found"

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


@dataclass(frozen=True)
class RouteSearchRecommendations:
    lowest_cost: RouteSearchOutcome
    fastest_time: RouteSearchOutcome


class RouteSearchStrategy(Protocol):
    def search(
        self,
        graph: nx.MultiDiGraph,
        start_node_id: str,
        end_node_id: str,
        *,
        objective: SearchObjective,
    ) -> RouteSearchOutcome:
        """Search one objective and retain the selected edge key per segment."""


class NetworkXDijkstraRouteSearchStrategy:
    """Baseline route search using NetworkX Dijkstra on a MultiDiGraph."""

    def search(
        self,
        graph: nx.MultiDiGraph,
        start_node_id: str,
        end_node_id: str,
        *,
        objective: SearchObjective,
    ) -> RouteSearchOutcome:
        if objective not in OBJECTIVE_WEIGHTS:
            raise RouteSearchError("搜索目标只能是 cost 或 time。")
        if not isinstance(graph, nx.MultiDiGraph):
            raise RouteSearchError("正式路径搜索必须使用 nx.MultiDiGraph。")

        start = _required_text(start_node_id, "搜索起点")
        end = _required_text(end_node_id, "搜索终点")
        weight_name = OBJECTIVE_WEIGHTS[objective]

        missing_nodes = [node_id for node_id in (start, end) if node_id not in graph]
        if missing_nodes:
            return _empty_outcome(
                status="manual_review",
                objective=objective,
                message=f"搜索节点不在正式图中：{'、'.join(missing_nodes)}",
            )

        if start == end:
            return _empty_outcome(
                status="manual_review",
                objective=objective,
                message="搜索起点与终点相同，需确认节点映射或明确零运输业务语义。",
            )

        weight_issue = _validate_graph_weights(graph, weight_name)
        if weight_issue is not None:
            return _empty_outcome(
                status="manual_review",
                objective=objective,
                message=weight_issue,
            )
        graph_signature = calculate_graph_weight_signature(graph, weight_name)

        try:
            node_path = nx.dijkstra_path(
                graph,
                source=start,
                target=end,
                weight=lambda left, right, edge_data: _minimum_parallel_weight(
                    edge_data,
                    weight_name,
                ),
            )
        except nx.NetworkXNoPath:
            return _empty_outcome(
                status="no_path",
                objective=objective,
                message=f"从 {start} 到 {end} 不存在可达路径。",
                graph_signature=graph_signature,
            )

        edge_steps: list[RouteEdgeReference] = []
        optimized_total = Decimal("0")
        for from_node_id, to_node_id in zip(node_path, node_path[1:]):
            edge_key, weight = _select_parallel_edge(
                graph[from_node_id][to_node_id],
                weight_name,
            )
            edge_steps.append(
                RouteEdgeReference(
                    from_node_id=from_node_id,
                    to_node_id=to_node_id,
                    edge_key=edge_key,
                    objective_weight=weight,
                )
            )
            optimized_total += weight

        objective_description = "总费用最低" if objective == "cost" else "总时间最短"
        return RouteSearchOutcome(
            status="found",
            objective=objective,
            weight_name=weight_name,
            node_ids=tuple(node_path),
            edge_steps=tuple(edge_steps),
            optimized_total=optimized_total,
            message=f"已使用 NetworkX Dijkstra 找到{objective_description}路径，并保留每段 edge key。",
            graph_signature=graph_signature,
        )


def search_cost_and_time_paths(
    graph: nx.MultiDiGraph,
    start_node_id: str,
    end_node_id: str,
    *,
    strategy: RouteSearchStrategy | None = None,
) -> RouteSearchRecommendations:
    selected_strategy = strategy or NetworkXDijkstraRouteSearchStrategy()
    return RouteSearchRecommendations(
        lowest_cost=selected_strategy.search(
            graph,
            start_node_id,
            end_node_id,
            objective="cost",
        ),
        fastest_time=selected_strategy.search(
            graph,
            start_node_id,
            end_node_id,
            objective="time",
        ),
    )


def _validate_graph_weights(graph: nx.MultiDiGraph, weight_name: str) -> str | None:
    for from_node_id, to_node_id, edge_key, attributes in graph.edges(
        keys=True,
        data=True,
    ):
        if weight_name not in attributes:
            return (
                f"运输边 {edge_key}（{from_node_id} -> {to_node_id}）缺少 {weight_name}，"
                "不能使用缺省权重搜索。"
            )
        try:
            _positive_decimal(attributes[weight_name], weight_name)
        except RouteSearchError:
            return (
                f"运输边 {edge_key}（{from_node_id} -> {to_node_id}）的 {weight_name} "
                "必须是大于 0 的有限数值。"
            )
        if not isinstance(edge_key, str) or not edge_key.strip():
            return f"运输边 {from_node_id} -> {to_node_id} 缺少可追溯的字符串 edge key。"
    return None


def calculate_graph_weight_signature(graph: nx.MultiDiGraph, weight_name: str) -> str:
    """Return a deterministic signature of nodes, edges, and one objective weight."""
    if not isinstance(graph, nx.MultiDiGraph):
        raise RouteSearchError("图权重签名只能从 nx.MultiDiGraph 生成。")
    records = sorted(
        (
            repr(from_node_id),
            repr(to_node_id),
            str(edge_key),
            format(_positive_decimal(attributes[weight_name], weight_name), "f"),
        )
        for from_node_id, to_node_id, edge_key, attributes in graph.edges(
            keys=True,
            data=True,
        )
    )
    payload = repr((weight_name, sorted(repr(node_id) for node_id in graph.nodes), records))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _minimum_parallel_weight(
    edge_data: dict[str, dict[str, object]],
    weight_name: str,
) -> Decimal:
    return min(_positive_decimal(attributes[weight_name], weight_name) for attributes in edge_data.values())


def _select_parallel_edge(
    edge_data: dict[str, dict[str, object]],
    weight_name: str,
) -> tuple[str, Decimal]:
    weighted_edges = [
        (edge_key, _positive_decimal(attributes[weight_name], weight_name))
        for edge_key, attributes in edge_data.items()
    ]
    edge_key, weight = min(weighted_edges, key=lambda item: (item[1], item[0]))
    return edge_key, weight


def _empty_outcome(
    *,
    status: Literal["no_path", "manual_review"],
    objective: SearchObjective,
    message: str,
    graph_signature: str | None = None,
) -> RouteSearchOutcome:
    return RouteSearchOutcome(
        status=status,
        objective=objective,
        weight_name=OBJECTIVE_WEIGHTS[objective],
        node_ids=(),
        edge_steps=(),
        optimized_total=None,
        message=message,
        graph_signature=graph_signature,
    )


def _positive_decimal(value: object, field_name: str) -> Decimal:
    number = _decimal(value, field_name)
    if number <= 0:
        raise RouteSearchError(f"{field_name}必须是大于 0 的有限数值。")
    return number


def _non_negative_decimal(value: object, field_name: str) -> Decimal:
    number = _decimal(value, field_name)
    if number < 0:
        raise RouteSearchError(f"{field_name}不能为负数。")
    return number


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise RouteSearchError(f"{field_name}必须是有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RouteSearchError(f"{field_name}必须是有限数值。") from None
    if not number.is_finite():
        raise RouteSearchError(f"{field_name}必须是有限数值。")
    return number


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise RouteSearchError(f"{field_name}不能为空。")
    return text
