from __future__ import annotations

from src.domain.cost_rules import DEFAULT_COST_RULE_ENGINE
from src.domain.freight_rate import create_freight_rate
from src.domain.route_request import RouteRequest
from src.domain.unit_conversion import UnitConversionError, calculate_total_cost


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("费用计算能力展示 Demo")
    print("=" * 52)
    print("展示目标：说明系统如何把不同运价单位换算成统一金额，并拦截明显错误输入。")

    show_business_context()
    show_valid_unit_conversion()
    show_bulk_shipping_index_case()
    show_manual_quote_case()
    show_invalid_unit_case()
    show_truck_route_policy()
    show_current_boundary()


def show_business_context() -> None:
    print("\n一、业务背景")
    print("当前运价台账中同时存在 元/吨、元/箱、元/柜 等单位。")
    print("系统不能直接把这些原始数值相加，必须先结合订单数量换算为统一金额：元。")


def show_valid_unit_conversion() -> None:
    print("\n二、场景 1：单位匹配，系统接受计算")
    examples = [
        ("散粮订单", 500, "吨", 250, "元/吨"),
        ("集装箱订单", 500, "箱", 250, "元/箱"),
        ("柜量订单", 500, "柜", 250, "元/柜"),
    ]

    for label, quantity, quantity_unit, price, price_unit in examples:
        total_cost = calculate_total_cost(price, price_unit, quantity, quantity_unit)
        print(f"{label}: {quantity}{quantity_unit} x {price}{price_unit} = {total_cost}元")

    print("结论：只要订单数量单位和运价单位匹配，系统可以得到统一总金额。")


def show_bulk_shipping_index_case() -> None:
    print("\n三、场景 2：散船指数规则预留演示")
    coal_index = 100
    quantity = 500
    request = RouteRequest(quantity, "吨", "散粮", "测试粮种")
    result = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="index",
        coal_index=coal_index,
    )

    print(f"输入：煤炭指数={coal_index}，计费数量={quantity}吨")
    print("规则：单位运费 = 煤炭指数 x 1.12 + 2元港驶费 + 5元利润")
    print(f"规则编号/版本：{result.rule_id} / {result.rule_version}")
    print(f"系统计算：{result.calculation_detail}")
    print(f"系统计算：总运费 = {result.total_cost_yuan}元")
    print("结论：公式已经进入统一计费引擎，但尚未接入北港至南港真实数据。")


def show_manual_quote_case() -> None:
    print("\n四、场景 3：人工报价")

    request = RouteRequest(500, "吨", "散粮", "测试粮种")
    unit_quote = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="manual",
        manual_quote_price=250,
        manual_price_type="unit_price",
        manual_price_unit="元/吨",
    )
    total_quote = DEFAULT_COST_RULE_ENGINE.calculate_bulk_shipping(
        request,
        price_mode="manual",
        manual_quote_price=88888,
        manual_price_type="total_price",
        manual_price_unit=None,
    )

    print(f"人工单价报价：{unit_quote.calculation_detail}")
    print(f"人工总价报价：{total_quote.calculation_detail}")
    print("结论：人工报价必须区分单价和总价，避免重复乘算。")


def show_invalid_unit_case() -> None:
    print("\n五、场景 4：单位不匹配，系统拒绝计算")
    print("错误输入示例：订单数量为 500吨，但运价是 250元/箱。")

    try:
        calculate_total_cost(250, "元/箱", 500, "吨")
    except UnitConversionError as exc:
        print(f"系统拦截：{exc}")

    print("结论：系统不会把吨和箱直接相乘，避免错误费用进入路径推荐。")


def show_truck_route_policy() -> None:
    print("\n六、场景 5：最后一公里汽运规则修正")
    print("业务口径：熟悉路线优先取维护运价；陌生散粮路线可使用确认后的普通驾车距离计费。")

    request = RouteRequest(500, "吨", "散粮", "测试粮种")
    known_rate = create_freight_rate(
        origin_name="测试南港",
        destination_name="测试客户工厂",
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="测试粮种",
        raw_price=20,
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="测试既定汽运运价",
        maintained_at="2026-04-15",
    )
    known_result = DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(
        request,
        known_rate=known_rate,
    )
    unknown_without_distance = DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(request)
    unknown_with_distance = DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(
        request,
        distance_km=120,
        distance_source="tencent_map_driving_route",
    )

    print(f"熟悉路线：{known_result.calculation_detail}")
    print(f"熟悉路线总费用：{known_result.total_cost_yuan}元")
    print(f"陌生路线缺距离：{unknown_without_distance.message}")
    print(f"陌生路线有距离：{unknown_with_distance.calculation_detail}")
    print(f"陌生路线总费用：{unknown_with_distance.total_cost_yuan}元")
    print("结论：费用层只消费 geo 层确认后的距离，不直接调用地图 API。")


def show_current_boundary() -> None:
    print("\n七、当前边界")
    print("当前 demo 展示的是费用计算防错能力。")
    print("完整路径搜索、客户自有码头规则和运输时间接口已由独立 Demo 展示。")
    print("真实数据链已能把具备费用、节点和人工时间的 EdgeCandidate 转换为 TransportEdge。")


if __name__ == "__main__":
    main()
