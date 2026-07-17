from __future__ import annotations

from route_request import RouteRequest, evaluate_freight_charge


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("订单输入与计费校验展示")
    print("=" * 52)
    print("本次展示聚焦订单校验和运输段总费用；完整搜索能力由 route-search 展示。")

    show_valid_examples()
    show_manual_review_examples()
    show_transport_mode_source()
    show_current_boundary()


def show_valid_examples() -> None:
    print("\n一、单位精确匹配时计算总费用")
    scenarios = [
        ("散粮", "吨", "元/吨"),
        ("集装箱", "箱", "元/箱"),
        ("集装箱", "柜", "元/柜"),
    ]
    for package_type, quantity_unit, price_unit in scenarios:
        request = make_request(package_type, quantity_unit)
        evaluation = evaluate_freight_charge(
            request,
            transport_mode="汽运",
            rate_packaging=package_type,
            raw_price=250,
            price_unit=price_unit,
        )
        print(
            f"{package_type}: 500{quantity_unit} x 250{price_unit} "
            f"= {evaluation.total_cost}元，状态={evaluation.status}"
        )


def show_manual_review_examples() -> None:
    print("\n二、单位不匹配时转人工确认")
    scenarios = [
        ("集装箱", "柜", "元/箱"),
        ("集装箱", "箱", "元/柜"),
        ("散粮", "吨", "元/箱"),
    ]
    for package_type, quantity_unit, price_unit in scenarios:
        request = make_request(package_type, quantity_unit)
        evaluation = evaluate_freight_charge(
            request,
            transport_mode="汽运",
            rate_packaging=package_type,
            raw_price=250,
            price_unit=price_unit,
        )
        print(f"{package_type}: 500{quantity_unit} 对应 250{price_unit}")
        print(f"状态={evaluation.status}；提示={evaluation.message}")


def show_transport_mode_source() -> None:
    print("\n三、运输方式来源")
    request = make_request("集装箱", "柜")
    evaluation = evaluate_freight_charge(
        request,
        transport_mode="驳船",
        rate_packaging="集装箱",
        raw_price=250,
        price_unit="元/柜",
    )
    print(f"本条运价表记录的运输方式为：{evaluation.transport_mode}")
    print("包装方式只辅助校验计费口径，不用于推断汽运、驳船或铁路。")


def show_current_boundary() -> None:
    print("\n四、当前边界")
    print("当前已形成订单结构、精确单位校验和人工确认状态。")
    print("客户画像、运输时效、标准TransportEdge和真实路径搜索仍属于后续阶段。")


def make_request(package_type: str, quantity_unit: str) -> RouteRequest:
    return RouteRequest(
        quantity=500,
        quantity_unit=quantity_unit,
        package_type=package_type,
        commodity="玉米",
        origin_port_id="NP_DEMO",
        south_port_id="SP_DEMO",
        customer_id="CUSTOMER_DEMO",
    )


if __name__ == "__main__":
    main()
