from __future__ import annotations

from cost_rules import calculate_bulk_shipping_total_cost, calculate_bulk_shipping_unit_price
from unit_conversion import UnitConversionError, calculate_total_cost


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
    print("\n三、场景 2：北港到南港散船指数测算")
    coal_index = 100
    quantity = 500
    unit_price = calculate_bulk_shipping_unit_price(coal_index)
    total_cost = calculate_bulk_shipping_total_cost(
        price_mode="index",
        coal_index=coal_index,
        quantity=quantity,
        quantity_unit="吨",
    )

    print(f"输入：煤炭指数={coal_index}，计费数量={quantity}吨")
    print("规则：单位运费 = 煤炭指数 x 1.12 + 2元港驶费 + 5元利润")
    print(f"系统计算：单位运费 = {unit_price}元/吨")
    print(f"系统计算：总运费 = {total_cost}元")
    print("结论：第一段散船费用已经可以按明确公式形成可解释金额。")


def show_manual_quote_case() -> None:
    print("\n四、场景 3：人工报价")

    unit_quote_total = calculate_total_cost(250, "元/吨", 500, "吨")
    total_quote = calculate_bulk_shipping_total_cost(
        price_mode="manual",
        manual_quote_price=88888,
        manual_price_type="total_price",
        manual_price_unit=None,
        quantity=500,
        quantity_unit="吨",
    )

    print(f"人工单价报价：500吨 x 250元/吨 = {unit_quote_total}元")
    print(f"人工总价报价：业务人员录入总价 {total_quote}元，系统直接采用。")
    print("结论：人工报价必须区分单价和总价，避免重复乘算。")


def show_invalid_unit_case() -> None:
    print("\n五、场景 4：单位不匹配，系统拒绝计算")
    print("错误输入示例：订单数量为 500吨，但运价是 250元/箱。")

    try:
        calculate_total_cost(250, "元/箱", 500, "吨")
    except UnitConversionError as exc:
        print(f"系统拦截：{exc}")

    print("结论：系统不会把吨和箱直接相乘，避免错误费用进入路径推荐。")


def show_current_boundary() -> None:
    print("\n六、当前边界")
    print("当前 demo 展示的是费用计算防错能力。")
    print("它尚未接入完整路径搜索、客户自有码头规则、腾讯地图距离和最后一公里陌生路线计费。")
    print("下一步开发会把这些费用结果承载到 RouteRequest、FreightRate、TransportEdge 等标准数据结构中。")


if __name__ == "__main__":
    main()
