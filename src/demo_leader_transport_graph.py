from __future__ import annotations

from decimal import Decimal

from transport_edge import TransportEdge
from transport_graph import build_transport_multidigraph


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("正式 MultiDiGraph 展示")
    print("=" * 52)
    print("本次展示使用虚构节点和运输边，说明平行边如何保留并参与后续搜索。")

    first = make_edge(
        edge_id="edge-road-demo",
        transport_mode="汽运",
        cost_yuan="1000",
        time_hours="4",
        price_source="演示台账 A",
        data_source="sanitized_rates.json#row=1",
    )
    second = make_edge(
        edge_id="edge-water-demo",
        transport_mode="水运",
        cost_yuan="800",
        time_hours="8",
        price_source="演示台账 B",
        data_source="sanitized_rates.json#row=2",
    )
    review = make_edge(
        edge_id="edge-review-demo",
        status="manual_review",
        cost_yuan=None,
        time_hours=None,
        unavailable_reason="缺少费用和运输时间。",
    )

    result = build_transport_multidigraph(
        [first, second, review],
        allow_unregistered_nodes=True,
    )
    graph = result.graph

    print("\n一、同一节点对保留平行运输边")
    print(f"图类型={type(graph).__name__}，节点数={graph.number_of_nodes()}，边数={graph.number_of_edges()}")
    for edge_key, attributes in graph["node-a"]["node-b"].items():
        print(
            f"key={edge_key}，方式={attributes['transport_mode']}，"
            f"费用={attributes['cost']}元，时间={attributes['time_hours']}小时"
        )

    print("\n二、成本和时间是两套独立权重")
    print(
        f"cost_weight={graph.graph['cost_weight']}，"
        f"time_weight={graph.graph['time_weight']}"
    )

    print("\n三、不可用候选不进入正式图")
    for issue in result.issues:
        print(f"{issue.edge_id}: code={issue.code}；{issue.message}")

    print("\n四、当前边界")
    print("正式图使用 edge_id 作为 key，不会覆盖同一节点对的其他运输方案。")
    print("旧 graph_builder.py 的 DataFrame/DiGraph 接口仅保留兼容，不作为正式业务图。")
    print("RouteSearchStrategy 双目标搜索已实现；下一步是接入真实候选并处理建图排除项。")


def make_edge(**overrides) -> TransportEdge:
    values = {
        "edge_id": "edge-demo",
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
        "price_source": "演示台账",
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


if __name__ == "__main__":
    main()
