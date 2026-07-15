from __future__ import annotations

from freight_rate import create_freight_rate
from route_request import RouteRequest


def main() -> None:
    print("全链路运输路径推断原型")
    print("标准运价记录展示")
    print("=" * 52)
    print("本次展示说明一条运价如何被标准化、追溯并换算成当前订单运输段总费用。")

    request = RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="散粮",
        commodity="测试粮种",
    )
    unit_rate = create_freight_rate(
        origin_name="测试南港",
        destination_name="测试客户工厂",
        transport_mode="驳船",
        package_type="散粮",
        commodity_scope="测试粮种、测试麦种",
        raw_price=20,
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="脱敏测试台账",
        maintained_at="2026-04-15",
        source_file="测试运价表.json",
        source_row_number=1,
    ).bind_node_ids("NODE_SOUTH_PORT_DEMO", "NODE_CUSTOMER_DEMO")
    unit_evaluation = unit_rate.evaluate_for_request(request)

    print("\n一、台账单价记录")
    print(f"费率编号: {unit_rate.rate_id}")
    print(f"运输方式: {unit_rate.transport_mode}（直接来自运价记录）")
    print(f"价格口径: {unit_rate.price_type}")
    print(f"原始价格: {unit_rate.raw_price} {unit_rate.raw_price_unit}")
    print(f"维护日期: {unit_rate.maintained_at}")
    print(f"计费规则: {unit_evaluation.rule_id} / {unit_evaluation.rule_version}")
    print(f"计算过程: {unit_evaluation.calculation_detail}")
    print(f"节点状态: {'已绑定标准节点' if unit_rate.is_node_resolved else '待匹配节点'}")
    print(f"500 吨订单对应运输段总费用: {unit_evaluation.total_cost} 元")

    total_rate = create_freight_rate(
        origin_name="测试南港",
        destination_name="测试客户工厂",
        transport_mode="驳船",
        package_type="散粮",
        commodity_scope="测试粮种",
        raw_price=88000,
        raw_price_unit="元",
        price_type="total_price",
        price_source="脱敏人工报价",
        maintained_at="2026-04-16",
    )
    total_evaluation = total_rate.evaluate_for_request(request)

    print("\n二、人工总价记录")
    print(f"价格口径: {total_rate.price_type}")
    print(f"人工报价: {total_rate.raw_price} {total_rate.raw_price_unit}")
    print(f"计费规则: {total_evaluation.rule_id} / {total_evaluation.rule_version}")
    print(f"计算过程: {total_evaluation.calculation_detail}")
    print(f"订单运输段总费用: {total_evaluation.total_cost} 元（不再乘以 500 吨）")

    print("\n三、当前边界")
    print("本模块已经统一运价结构、价格口径、日期、来源行和节点绑定状态。")
    print("同一路线多次维护时选择哪一条最新记录，将在下一阶段单独实现和验收。")


if __name__ == "__main__":
    main()
