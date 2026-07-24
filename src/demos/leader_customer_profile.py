from __future__ import annotations

from src.routing.customer_profile import (
    CustomerProfile,
    TransferPortCandidate,
    evaluate_customer_compatibility,
    prefilter_transfer_ports,
    resolve_customer_route,
)


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("客户画像与路线分支展示")
    print("=" * 52)
    print("本次展示使用虚构节点，只说明客户规则如何过滤路线，不代表真实客户数据已接入。")

    private_profile = make_profile(
        customer_id="customer-private-demo",
        customer_name="演示自有码头客户",
        has_private_terminal=True,
        private_terminal_node_id="node-private-terminal-demo",
        private_terminal_node_source="人工确认码头表",
    )
    transfer_profile = make_profile(
        customer_id="customer-transfer-demo",
        customer_name="演示中转客户",
        has_private_terminal=False,
    )

    show_route_branches(private_profile, transfer_profile)
    show_candidate_prefilter(private_profile, transfer_profile)
    show_compatibility(transfer_profile)
    show_missing_data_review()
    show_current_boundary()


def make_profile(
    *,
    customer_id: str,
    customer_name: str,
    has_private_terminal: bool | None,
    private_terminal_node_id: str | None = None,
    private_terminal_node_source: str | None = None,
) -> CustomerProfile:
    return CustomerProfile(
        customer_id=customer_id,
        customer_name=customer_name,
        factory_node_id=f"node-factory-{customer_id}",
        has_private_terminal=has_private_terminal,
        profile_source="人工确认演示档案",
        private_terminal_node_id=private_terminal_node_id,
        private_terminal_flag_source="人工确认表" if has_private_terminal is not None else None,
        private_terminal_node_source=private_terminal_node_source,
        allowed_package_types=("散粮", "集装箱"),
        allowed_commodities=("玉米", "小麦"),
        allowed_transport_modes=("散船", "驳船", "汽运"),
        confirmation_status=("confirmed" if has_private_terminal is not None else "manual_review"),
    )


def show_route_branches(
    private_profile: CustomerProfile,
    transfer_profile: CustomerProfile,
) -> None:
    print("\n一、客户路线分支严格互斥")
    for profile in (private_profile, transfer_profile):
        decision = resolve_customer_route(profile, south_port_node_id="node-south-port-demo")
        print(
            f"{profile.customer_name}: 状态={decision.status}，分支={decision.branch}，"
            f"需要中转港={decision.requires_transfer_port}"
        )
        print(f"  说明：{decision.message}")


def show_candidate_prefilter(
    private_profile: CustomerProfile,
    transfer_profile: CustomerProfile,
) -> None:
    print("\n二、候选中转港距离只用于前 K 预筛")
    candidates = [
        TransferPortCandidate("node-transfer-port-c", "30", "地图确认结果"),
        TransferPortCandidate("node-transfer-port-b", "12", "熟悉路线台账"),
        TransferPortCandidate("node-transfer-port-a", "12", "熟悉路线台账"),
    ]
    private_decision = resolve_customer_route(private_profile, south_port_node_id="node-south-port-demo")
    private_selection = prefilter_transfer_ports(private_decision, candidates, k=2)
    print(f"自有码头客户：状态={private_selection.status}；{private_selection.message}")

    transfer_decision = resolve_customer_route(transfer_profile, south_port_node_id="node-south-port-demo")
    transfer_selection = prefilter_transfer_ports(transfer_decision, candidates, k=2)
    selected = "、".join(
        f"{item.port_node_id}({item.distance_km}km, {item.distance_source})"
        for item in transfer_selection.selected_candidates
    )
    print(f"无自有码头客户：状态={transfer_selection.status}，候选={selected}")
    print(f"  说明：{transfer_selection.message}")


def show_compatibility(profile: CustomerProfile) -> None:
    print("\n三、包装方式和货物品种显式过滤")
    for package_type, commodity in (("散粮", "玉米"), ("袋装", "大豆")):
        result = evaluate_customer_compatibility(
            profile,
            package_type=package_type,
            commodity=commodity,
        )
        print(f"{package_type}/{commodity}: 状态={result.status}；{result.message}")


def show_missing_data_review() -> None:
    print("\n四、缺少客户自有码头数据时停止推荐")
    unknown_profile = make_profile(
        customer_id="customer-unknown-demo",
        customer_name="演示待确认客户",
        has_private_terminal=None,
    )
    decision = resolve_customer_route(unknown_profile, south_port_node_id="node-south-port-demo")
    print(f"状态={decision.status}，分支={decision.branch}；{decision.message}")


def show_current_boundary() -> None:
    print("\n五、当前边界")
    print("CustomerProfile 第一版已提供可追溯的人工档案模型和路线过滤规则。")
    print("正式客户数据源尚未确认，因此程序不会猜测客户是否有自有码头。")
    print("候选港预筛结果仍需进入后续 TransportEdge，分别比较全链路费用和时间。")


if __name__ == "__main__":
    main()
