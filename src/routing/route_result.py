from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import networkx as nx

try:
    from .route_search import (
        RouteSearchOutcome,
        RouteSearchRecommendations,
        RouteSearchError,
        SearchObjective,
        calculate_graph_weight_signature,
    )
    from .transport_contracts import (
        CostComponent,
        CostComposition,
        TimeScope,
        TransportContractError,
        TransportEdgeRole,
        TransportStage,
        validate_transport_semantics,
    )
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.routing.route_search import (
        RouteSearchError,
        RouteSearchOutcome,
        RouteSearchRecommendations,
        SearchObjective,
        calculate_graph_weight_signature,
    )
    from src.routing.transport_contracts import (
        CostComponent,
        CostComposition,
        TimeScope,
        TransportContractError,
        TransportEdgeRole,
        TransportStage,
        validate_transport_semantics,
    )


RouteResultStatus = Literal["resolved", "no_path", "manual_review"]
RecommendationType = Literal["lowest_cost", "fastest_time"]

RECOMMENDATION_TYPES: dict[SearchObjective, RecommendationType] = {
    "cost": "lowest_cost",
    "time": "fastest_time",
}


class RouteResultError(ValueError):
    """Raised when a route result cannot be represented or explained safely."""


@dataclass(frozen=True)
class RouteSegment:
    segment_no: int
    from_node_id: str
    to_node_id: str
    edge_key: str
    transport_mode: str
    package_type: str
    commodity: str
    cost_yuan: Decimal
    time_hours: Decimal
    raw_price: Decimal
    raw_price_unit: str
    price_source: str
    maintained_at: date | None
    distance_km: Decimal | None
    distance_source: str | None
    time_source: str
    cost_rule_id: str
    cost_rule_version: str
    calculation_detail: str
    data_source: str
    transport_stage: TransportStage | None = None
    edge_role: TransportEdgeRole | None = None
    time_scope: TimeScope | None = None
    cost_components: tuple[CostComponent, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.segment_no, bool) or not isinstance(self.segment_no, int) or self.segment_no <= 0:
            raise RouteResultError("分段序号必须是正整数。")
        for field_name, label in (
            ("from_node_id", "分段起点"),
            ("to_node_id", "分段终点"),
            ("edge_key", "运输边 key"),
            ("transport_mode", "运输方式"),
            ("package_type", "包装方式"),
            ("commodity", "货物品种"),
            ("raw_price_unit", "原始费用单位"),
            ("price_source", "价格来源"),
            ("time_source", "时间来源"),
            ("cost_rule_id", "计费规则编号"),
            ("cost_rule_version", "计费规则版本"),
            ("calculation_detail", "计费过程"),
            ("data_source", "数据来源"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))

        object.__setattr__(self, "cost_yuan", _positive_decimal(self.cost_yuan, "分段费用"))
        object.__setattr__(self, "time_hours", _positive_decimal(self.time_hours, "分段时间"))
        object.__setattr__(self, "raw_price", _positive_decimal(self.raw_price, "分段原始价格"))
        distance = _optional_positive_decimal(self.distance_km, "分段距离")
        distance_source = _optional_text(self.distance_source)
        object.__setattr__(self, "distance_km", distance)
        object.__setattr__(self, "distance_source", distance_source)
        object.__setattr__(self, "transport_stage", _optional_text(self.transport_stage))
        object.__setattr__(self, "edge_role", _optional_text(self.edge_role))
        object.__setattr__(self, "time_scope", _optional_text(self.time_scope))
        try:
            validate_transport_semantics(
                self.transport_stage,
                self.edge_role,
                self.time_scope,
            )
        except TransportContractError as exc:
            raise RouteResultError(str(exc)) from None
        object.__setattr__(self, "cost_components", tuple(self.cost_components))
        if self.cost_components:
            try:
                CostComposition(self.cost_components).validate_total(self.cost_yuan)
            except ValueError as exc:
                raise RouteResultError(str(exc)) from None
        if (distance is None) != (distance_source is None):
            raise RouteResultError("分段距离数值和来源必须同时存在或同时为空。")
        if self.maintained_at is not None and not isinstance(self.maintained_at, date):
            raise RouteResultError("运价维护日期必须是 date 或 None。")

    @property
    def cost(self) -> Decimal:
        return self.cost_yuan


@dataclass(frozen=True)
class RouteResult:
    status: RouteResultStatus
    recommendation_type: RecommendationType
    objective: SearchObjective
    path_node_ids: tuple[str, ...]
    segments: tuple[RouteSegment, ...]
    total_cost_yuan: Decimal | None
    total_time_hours: Decimal | None
    missing_data_flag: bool
    explanation: str

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "no_path", "manual_review"}:
            raise RouteResultError(f"不支持的路线结果状态：{self.status}")
        if self.objective not in RECOMMENDATION_TYPES:
            raise RouteResultError("路线结果目标只能是 cost 或 time。")
        if self.recommendation_type != RECOMMENDATION_TYPES[self.objective]:
            raise RouteResultError("推荐类型与搜索目标不一致。")
        object.__setattr__(self, "path_node_ids", tuple(self.path_node_ids))
        object.__setattr__(self, "segments", tuple(self.segments))
        object.__setattr__(self, "explanation", _required_text(self.explanation, "路线结果说明"))

        if self.status == "resolved":
            if self.missing_data_flag:
                raise RouteResultError("完整路线结果不得标记数据缺失。")
            if not self.path_node_ids:
                raise RouteResultError("完整路线结果必须包含节点路径。")
            if not self.segments:
                raise RouteResultError("完整路线结果必须包含至少一个运输分段。")
            if len(self.segments) != len(self.path_node_ids) - 1:
                raise RouteResultError("路线分段数量必须等于节点数量减一。")

            total_cost = _non_negative_decimal(self.total_cost_yuan, "路线总费用")
            total_time = _non_negative_decimal(self.total_time_hours, "路线总时间")
            expected_cost = sum((segment.cost_yuan for segment in self.segments), Decimal("0"))
            expected_time = sum((segment.time_hours for segment in self.segments), Decimal("0"))
            if total_cost != expected_cost:
                raise RouteResultError("路线总费用必须等于分段费用之和。")
            if total_time != expected_time:
                raise RouteResultError("路线总时间必须等于分段时间之和。")
            _validate_segment_chain(self.path_node_ids, self.segments)
            object.__setattr__(self, "total_cost_yuan", total_cost)
            object.__setattr__(self, "total_time_hours", total_time)
        else:
            if self.path_node_ids or self.segments:
                raise RouteResultError("非完整路线结果不得包含节点或分段。")
            if self.total_cost_yuan is not None or self.total_time_hours is not None:
                raise RouteResultError("非完整路线结果不得包含费用或时间合计。")
            if self.status == "manual_review" and not self.missing_data_flag:
                raise RouteResultError("人工复核结果必须标记数据缺失。")
            if self.status == "no_path" and self.missing_data_flag:
                raise RouteResultError("无路径不应自动标记为数据缺失。")

    @property
    def total_cost(self) -> Decimal | None:
        return self.total_cost_yuan

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


@dataclass(frozen=True)
class RouteRecommendationResults:
    lowest_cost: RouteResult
    fastest_time: RouteResult


def build_route_result(
    graph: nx.MultiDiGraph,
    search_outcome: RouteSearchOutcome,
) -> RouteResult:
    """Hydrate one search outcome into fully traceable route segments."""
    if not isinstance(graph, nx.MultiDiGraph):
        raise RouteResultError("路线结果必须从 nx.MultiDiGraph 还原。")

    recommendation_type = RECOMMENDATION_TYPES[search_outcome.objective]
    build_issues = tuple(graph.graph.get("build_issues", ()))
    if build_issues:
        issue_messages = "；".join(str(getattr(issue, "message", issue)) for issue in build_issues)
        return _manual_review_result(
            recommendation_type,
            search_outcome.objective,
            f"正式图构建时排除了 {len(build_issues)} 条记录，不能确认当前推荐完整：{issue_messages}",
        )

    if search_outcome.status in {"found", "no_path"}:
        try:
            current_signature = calculate_graph_weight_signature(
                graph,
                search_outcome.weight_name,
            )
        except (KeyError, RouteSearchError) as exc:
            return _manual_review_result(
                recommendation_type,
                search_outcome.objective,
                f"搜索后图权重无法复核：{exc}",
            )
        if current_signature != search_outcome.graph_signature:
            return _manual_review_result(
                recommendation_type,
                search_outcome.objective,
                "搜索完成后图节点、运输边或目标权重已变化，必须重新搜索。",
            )

    if search_outcome.status != "found":
        return RouteResult(
            status="no_path" if search_outcome.status == "no_path" else "manual_review",
            recommendation_type=recommendation_type,
            objective=search_outcome.objective,
            path_node_ids=(),
            segments=(),
            total_cost_yuan=None,
            total_time_hours=None,
            missing_data_flag=search_outcome.status == "manual_review",
            explanation=search_outcome.message,
        )

    try:
        segments = tuple(
            _build_segment(graph, step, segment_no)
            for segment_no, step in enumerate(search_outcome.edge_steps, start=1)
        )
        total_cost = sum((segment.cost_yuan for segment in segments), Decimal("0"))
        total_time = sum((segment.time_hours for segment in segments), Decimal("0"))
        objective_total = total_cost if search_outcome.objective == "cost" else total_time
        referenced_total = sum(
            (step.objective_weight for step in search_outcome.edge_steps),
            Decimal("0"),
        )
        if objective_total != referenced_total or objective_total != search_outcome.optimized_total:
            raise RouteResultError("搜索目标合计与当前运输边权重不一致，必须重新搜索。")

        objective_description = "成本最低" if search_outcome.objective == "cost" else "时效最优"
        return RouteResult(
            status="resolved",
            recommendation_type=recommendation_type,
            objective=search_outcome.objective,
            path_node_ids=search_outcome.node_ids,
            segments=segments,
            total_cost_yuan=total_cost,
            total_time_hours=total_time,
            missing_data_flag=False,
            explanation=(
                f"{objective_description}路径由 {len(segments)} 段组成；"
                f"总费用 {total_cost} 元，总时间 {total_time} 小时。"
                f"搜索按 {search_outcome.weight_name} 单独优化，费用与时间未合并。"
            ),
        )
    except RouteResultError as exc:
        return _manual_review_result(
            recommendation_type,
            search_outcome.objective,
            f"搜索结果不能还原为可解释路线：{exc}",
        )


def build_route_recommendations(
    graph: nx.MultiDiGraph,
    searches: RouteSearchRecommendations,
) -> RouteRecommendationResults:
    return RouteRecommendationResults(
        lowest_cost=build_route_result(graph, searches.lowest_cost),
        fastest_time=build_route_result(graph, searches.fastest_time),
    )


def route_result_to_rows(result: RouteResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = " -> ".join(result.path_node_ids)
    route_fields = {
        "status": result.status,
        "recommendation_type": result.recommendation_type,
        "objective": result.objective,
        "missing_data_flag": result.missing_data_flag,
        "route_total_cost_yuan": result.total_cost_yuan,
        "route_total_time_hours": result.total_time_hours,
        "path": path,
        "explanation": result.explanation,
    }
    if not result.segments:
        return [
            {
                **route_fields,
                "segment_no": None,
                "from_node_id": None,
                "to_node_id": None,
                "edge_key": None,
                "transport_mode": None,
                "package_type": None,
                "commodity": None,
                "segment_cost_yuan": None,
                "segment_time_hours": None,
                "raw_price": None,
                "raw_price_unit": None,
                "price_source": None,
                "maintained_at": None,
                "distance_km": None,
                "distance_source": None,
                "time_source": None,
                "cost_rule_id": None,
                "cost_rule_version": None,
                "calculation_detail": None,
                "data_source": None,
            }
        ]

    for segment in result.segments:
        rows.append(
            {
                **route_fields,
                "segment_no": segment.segment_no,
                "from_node_id": segment.from_node_id,
                "to_node_id": segment.to_node_id,
                "edge_key": segment.edge_key,
                "transport_mode": segment.transport_mode,
                "package_type": segment.package_type,
                "commodity": segment.commodity,
                "segment_cost_yuan": segment.cost_yuan,
                "segment_time_hours": segment.time_hours,
                "raw_price": segment.raw_price,
                "raw_price_unit": segment.raw_price_unit,
                "price_source": segment.price_source,
                "maintained_at": (
                    segment.maintained_at.isoformat() if segment.maintained_at is not None else None
                ),
                "distance_km": segment.distance_km,
                "distance_source": segment.distance_source,
                "time_source": segment.time_source,
                "cost_rule_id": segment.cost_rule_id,
                "cost_rule_version": segment.cost_rule_version,
                "calculation_detail": segment.calculation_detail,
                "data_source": segment.data_source,
                "transport_stage": segment.transport_stage,
                "edge_role": segment.edge_role,
                "time_scope": segment.time_scope,
            }
        )
    return rows


def _manual_review_result(
    recommendation_type: RecommendationType,
    objective: SearchObjective,
    explanation: str,
) -> RouteResult:
    return RouteResult(
        status="manual_review",
        recommendation_type=recommendation_type,
        objective=objective,
        path_node_ids=(),
        segments=(),
        total_cost_yuan=None,
        total_time_hours=None,
        missing_data_flag=True,
        explanation=explanation,
    )


def _build_segment(
    graph: nx.MultiDiGraph,
    step: Any,
    segment_no: int,
) -> RouteSegment:
    if not graph.has_edge(step.from_node_id, step.to_node_id, key=step.edge_key):
        raise RouteResultError(
            f"找不到搜索选中的运输边 {step.from_node_id} -> {step.to_node_id} "
            f"(key={step.edge_key})。"
        )

    attributes = graph[step.from_node_id][step.to_node_id][step.edge_key]
    edge_id = _required_attribute(attributes, "edge_id", step.edge_key)
    if edge_id != step.edge_key:
        raise RouteResultError(f"运输边 key={step.edge_key} 与 edge_id={edge_id} 不一致。")
    if _required_attribute(attributes, "status", step.edge_key) != "available":
        raise RouteResultError(f"运输边 {step.edge_key} 当前不是 available 状态。")

    return RouteSegment(
        segment_no=segment_no,
        from_node_id=step.from_node_id,
        to_node_id=step.to_node_id,
        edge_key=step.edge_key,
        transport_mode=_required_attribute(attributes, "transport_mode", step.edge_key),
        package_type=_required_attribute(attributes, "package_type", step.edge_key),
        commodity=_required_attribute(attributes, "commodity", step.edge_key),
        cost_yuan=_required_attribute(attributes, "cost", step.edge_key),
        time_hours=_required_attribute(attributes, "time_hours", step.edge_key),
        raw_price=_required_attribute(attributes, "raw_price", step.edge_key),
        raw_price_unit=_required_attribute(attributes, "raw_price_unit", step.edge_key),
        price_source=_required_attribute(attributes, "price_source", step.edge_key),
        maintained_at=attributes.get("maintained_at"),
        distance_km=attributes.get("distance_km"),
        distance_source=attributes.get("distance_source"),
        time_source=_required_attribute(attributes, "time_source", step.edge_key),
        cost_rule_id=_required_attribute(attributes, "cost_rule_id", step.edge_key),
        cost_rule_version=_required_attribute(attributes, "cost_rule_version", step.edge_key),
        calculation_detail=_required_attribute(attributes, "calculation_detail", step.edge_key),
        data_source=_required_attribute(attributes, "data_source", step.edge_key),
        transport_stage=attributes.get("transport_stage"),
        edge_role=attributes.get("edge_role"),
        time_scope=attributes.get("time_scope"),
        cost_components=tuple(attributes.get("cost_components") or ()),
    )


def _required_attribute(attributes: dict[str, Any], name: str, edge_key: str) -> Any:
    if name not in attributes or attributes[name] is None:
        raise RouteResultError(f"运输边 {edge_key} 缺少 {name}。")
    value = attributes[name]
    if isinstance(value, str) and not value.strip():
        raise RouteResultError(f"运输边 {edge_key} 缺少 {name}。")
    return value


def _validate_segment_chain(
    path_node_ids: tuple[str, ...],
    segments: tuple[RouteSegment, ...],
) -> None:
    for index, segment in enumerate(segments):
        if segment.segment_no != index + 1:
            raise RouteResultError("路线分段序号必须从 1 连续递增。")
        if segment.from_node_id != path_node_ids[index]:
            raise RouteResultError("路线分段起点与节点路径不一致。")
        if segment.to_node_id != path_node_ids[index + 1]:
            raise RouteResultError("路线分段终点与节点路径不一致。")


def _optional_positive_decimal(value: object | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _positive_decimal(value, field_name)


def _positive_decimal(value: object, field_name: str) -> Decimal:
    number = _decimal(value, field_name)
    if number <= 0:
        raise RouteResultError(f"{field_name}必须是大于 0 的有限数值。")
    return number


def _non_negative_decimal(value: object, field_name: str) -> Decimal:
    number = _decimal(value, field_name)
    if number < 0:
        raise RouteResultError(f"{field_name}不能为负数。")
    return number


def _decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise RouteResultError(f"{field_name}必须是有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RouteResultError(f"{field_name}必须是有限数值。") from None
    if not number.is_finite():
        raise RouteResultError(f"{field_name}必须是有限数值。")
    return number


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise RouteResultError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
