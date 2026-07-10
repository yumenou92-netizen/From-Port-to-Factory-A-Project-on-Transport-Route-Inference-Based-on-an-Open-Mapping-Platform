from __future__ import annotations

from cost_rules import (
    CostRuleError,
    calculate_bulk_shipping_total_cost,
    calculate_bulk_shipping_unit_price,
    calculate_manual_shipping_cost,
)
from unit_conversion import UnitConversionError, calculate_total_cost


def main() -> None:
    print("费用规则 Demo")
    print("=" * 40)

    show_unit_conversion_examples()
    show_bulk_shipping_examples()
    show_manual_quote_examples()
    show_rejected_unit_mismatch()


def show_unit_conversion_examples() -> None:
    print("\n1. 单位匹配和总费用换算")
    examples = [
        {"quantity": 500, "quantity_unit": "吨", "price": 250, "price_unit": "元/吨"},
        {"quantity": 500, "quantity_unit": "箱", "price": 250, "price_unit": "元/箱"},
        {"quantity": 500, "quantity_unit": "柜", "price": 250, "price_unit": "元/柜"},
    ]

    for item in examples:
        total_cost = calculate_total_cost(
            raw_price=item["price"],
            price_unit=item["price_unit"],
            quantity=item["quantity"],
            quantity_unit=item["quantity_unit"],
        )
        print(
            f"- {item['quantity']} {item['quantity_unit']} x "
            f"{item['price']} {item['price_unit']} = {total_cost} 元"
        )


def show_bulk_shipping_examples() -> None:
    print("\n2. 第一段散船指数测算")
    coal_index = 100
    quantity = 500
    unit_price = calculate_bulk_shipping_unit_price(coal_index=coal_index)
    total_cost = calculate_bulk_shipping_total_cost(
        price_mode="index",
        coal_index=coal_index,
        quantity=quantity,
        quantity_unit="吨",
    )
    print(f"- 煤炭指数: {coal_index}")
    print("- 单位运费 = 煤炭指数 x 1.12 + 2 元港驶费 + 5 元利润")
    print(f"- 单位运费 = {unit_price} 元/吨")
    print(f"- {quantity} 吨总运费 = {total_cost} 元")


def show_manual_quote_examples() -> None:
    print("\n3. 第一段散船人工报价")
    unit_price_total = calculate_manual_shipping_cost(
        manual_quote_price=250,
        manual_price_type="unit_price",
        manual_price_unit="元/吨",
        quantity=500,
        quantity_unit="吨",
    )
    total_price = calculate_manual_shipping_cost(
        manual_quote_price=88888,
        manual_price_type="total_price",
        manual_price_unit=None,
        quantity=500,
        quantity_unit="吨",
    )
    print(f"- 人工单价报价: 500 吨 x 250 元/吨 = {unit_price_total} 元")
    print(f"- 人工总价报价: 直接采用 {total_price} 元")


def show_rejected_unit_mismatch() -> None:
    print("\n4. 单位不匹配时拒绝计算")
    try:
        calculate_total_cost(raw_price=250, price_unit="元/箱", quantity=500, quantity_unit="吨")
    except (UnitConversionError, CostRuleError) as exc:
        print(f"- 500 吨 x 250 元/箱 -> 拒绝：{exc}")


if __name__ == "__main__":
    main()
