from __future__ import annotations

from decimal import Decimal

from src.domain.cost_rules import CostCalculationResult
from src.domain.freight_rate import create_freight_rate
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_edge import build_transport_edge


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("标准 TransportEdge 展示")
    print("=" * 52)
    print("本次展示使用虚构运价和节点，说明费用、时间和来源如何进入正式运输边。")

    rate = make_rate()
    cost_result = make_cost_result()
    time_result = make_time_result()

    print("\n一、完整结果形成可用运输边")
    available = build_transport_edge(
        rate,
        cost_result,
        time_result,
        commodity="玉米",
        distance_km="35.2",
        distance_source="人工确认道路距离",
    )
    print(
        f"edge_key={available.edge_key}，状态={available.status}，"
        f"费用={available.cost_yuan}元，时间={available.time_hours}小时"
    )
    print(
        f"计费规则={available.cost_rule_id}/{available.cost_rule_version}，"
        f"价格来源={available.price_source}，时间来源={available.time_source}"
    )

    print("\n二、缺少时间时不生成可搜索边")
    missing_time = build_transport_edge(
        rate,
        cost_result,
        make_time_result(
            status="manual_review",
            duration_hours=None,
            message="缺少人工运输时间。",
        ),
        commodity="玉米",
    )
    print(
        f"状态={missing_time.status}，费用保留={missing_time.cost_yuan}，"
        f"时间={missing_time.time_hours}；原因={missing_time.unavailable_reason}"
    )

    print("\n三、缺少节点时不伪造节点")
    unresolved_rate = make_rate(from_node_id=None)
    missing_node = build_transport_edge(
        unresolved_rate,
        cost_result,
        time_result,
        commodity="玉米",
    )
    print(
        f"状态={missing_node.status}，起点={missing_node.from_node_id}，"
        f"终点={missing_node.to_node_id}；原因={missing_node.unavailable_reason}"
    )

    print("\n四、当前边界")
    print("只有 available 的 TransportEdge 可以导出到正式图。")
    print("cost 与 time_hours 保持为两套独立权重，不生成未经确认的综合权重。")
    print("正式 MultiDiGraph 已实现；下一步是接入真实候选、节点注册和时效数据。")


def make_rate(**overrides):
    values = {
        "origin_name": "演示中转港",
        "destination_name": "演示客户工厂",
        "transport_mode": "汽运",
        "package_type": "散粮",
        "commodity_scope": "玉米、小麦",
        "raw_price": "20",
        "raw_price_unit": "元/吨",
        "price_type": "unit_price",
        "price_source": "演示熟悉路线台账",
        "maintained_at": "2026-07-01",
        "from_node_id": "node-transfer-port-demo",
        "to_node_id": "node-factory-demo",
        "source_file": "sanitized_rates.json",
        "source_row_number": 8,
    }
    values.update(overrides)
    return create_freight_rate(**values)


def make_cost_result() -> CostCalculationResult:
    return CostCalculationResult(
        status="valid",
        total_cost_yuan=Decimal("10000"),
        rule_id="known_truck_maintained_rate",
        rule_version="1.0",
        calculation_detail="20元/吨 × 500吨 = 10000元",
        price_source="演示熟悉路线台账",
        transport_mode="汽运",
        rate_packaging="散粮",
        price_unit="元/吨",
        message="已按维护运价计算当前订单运输段总费用。",
    )


def make_time_result(**overrides) -> ShippingTimeResult:
    values = {
        "status": "resolved",
        "duration_hours": Decimal("2.5"),
        "source": "manual_shipping_time",
        "message": "已采用人工确认运输时间。",
        "stage": "中转港至客户工厂",
        "transport_mode": "汽运",
        "input_value": "2.5",
        "input_unit": "小时",
    }
    values.update(overrides)
    return ShippingTimeResult(**values)


if __name__ == "__main__":
    main()
