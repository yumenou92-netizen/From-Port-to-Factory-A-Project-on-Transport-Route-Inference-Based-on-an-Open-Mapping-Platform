from __future__ import annotations

from decimal import Decimal

from src.routing.route_result import build_route_recommendations
from src.routing.route_search import search_cost_and_time_paths
from src.routing.transport_edge import TransportEdge
from src.routing.transport_graph import build_transport_multidigraph


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("MultiDiGraph 路径搜索与解释结果展示")
    print("=" * 60)
    print("本次展示使用虚构节点和脱敏字段，只验证正式图、双目标搜索和分段解释。")

    graph_result = build_transport_multidigraph(
        [
            make_edge("edge-road-a-b", "node-a", "node-b", "10", "10", "汽运"),
            make_edge("edge-road-b-d", "node-b", "node-d", "10", "10", "汽运"),
            make_edge("edge-water-a-c", "node-a", "node-c", "20", "2", "水运"),
            make_edge("edge-water-c-d", "node-c", "node-d", "20", "2", "水运"),
        ],
        allow_unregistered_nodes=True,
    )
    searches = search_cost_and_time_paths(graph_result.graph, "node-a", "node-d")
    results = build_route_recommendations(graph_result.graph, searches)

    print("\n一、成本最低推荐")
    show_result(results.lowest_cost)

    print("\n二、时效最优推荐")
    show_result(results.fastest_time)

    print("\n三、两套权重保持独立")
    print(
        f"成本最低：总费用={results.lowest_cost.total_cost_yuan}元，"
        f"总时间={results.lowest_cost.total_time_hours}小时"
    )
    print(
        f"时效最优：总费用={results.fastest_time.total_cost_yuan}元，"
        f"总时间={results.fastest_time.total_time_hours}小时"
    )

    print("\n四、当前边界")
    print("正式搜索基线使用 NetworkX Dijkstra，并返回每段 MultiDiGraph edge key。")
    print("成本与时间分别搜索，不使用未经业务确认的综合权重。")
    print("本演示不表示真实客户画像、北港至南港运价或完整业务候选已经接入。")


def show_result(result) -> None:
    print(f"状态={result.status}，路径={' -> '.join(result.path_node_ids)}")
    for segment in result.segments:
        print(
            f"  {segment.segment_no}. {segment.from_node_id} -> {segment.to_node_id}，"
            f"key={segment.edge_key}，方式={segment.transport_mode}，"
            f"费用={segment.cost_yuan}元，时间={segment.time_hours}小时"
        )
        print(
            f"     价格来源={segment.price_source}，时间来源={segment.time_source}，"
            f"规则={segment.cost_rule_id}/{segment.cost_rule_version}"
        )
    print(f"说明：{result.explanation}")


def make_edge(
    edge_id: str,
    start: str,
    end: str,
    cost: str,
    time: str,
    transport_mode: str,
) -> TransportEdge:
    return TransportEdge(
        edge_id=edge_id,
        status="available",
        from_node_id=start,
        to_node_id=end,
        transport_mode=transport_mode,
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


if __name__ == "__main__":
    main()
