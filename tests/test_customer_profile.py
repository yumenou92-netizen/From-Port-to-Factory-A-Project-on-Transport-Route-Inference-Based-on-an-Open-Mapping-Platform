from decimal import Decimal

import pytest

from src.routing.customer_profile import (
    CustomerProfile,
    CustomerProfileError,
    CustomerRouteDecision,
    TransferPortCandidate,
    evaluate_customer_compatibility,
    prefilter_transfer_ports,
    resolve_customer_route,
)


def make_profile(**overrides) -> CustomerProfile:
    values = {
        "customer_id": "customer-demo-001",
        "customer_name": "演示客户",
        "factory_node_id": "node-factory-demo",
        "has_private_terminal": False,
        "profile_source": "人工确认客户档案",
        "private_terminal_flag_source": "人工确认表",
        "allowed_package_types": ("散粮", "集装箱"),
        "allowed_commodities": ("玉米", "小麦"),
    }
    values.update(overrides)
    return CustomerProfile(**values)


def test_private_terminal_customer_resolves_direct_waterway_branch():
    profile = make_profile(
        has_private_terminal=True,
        private_terminal_node_id="node-private-terminal-demo",
        private_terminal_node_source="人工确认码头表",
    )

    result = resolve_customer_route(profile, south_port_node_id="node-south-port-demo")

    assert result.status == "resolved"
    assert result.branch == "private_terminal"
    assert not result.requires_transfer_port
    assert result.private_terminal_node_id == "node-private-terminal-demo"
    assert result.private_terminal_flag_source == "人工确认表"
    assert result.private_terminal_node_source == "人工确认码头表"


def test_customer_without_private_terminal_requires_transfer_branch():
    profile = make_profile()

    result = resolve_customer_route(profile, south_port_node_id="node-south-port-demo")

    assert result.status == "resolved"
    assert result.branch == "transfer_terminal"
    assert result.requires_transfer_port
    assert result.factory_node_id == "node-factory-demo"
    assert result.private_terminal_node_id is None


@pytest.mark.parametrize(
    ("overrides", "message_fragment"),
    [
        ({"has_private_terminal": None}, "尚未确认"),
        ({"private_terminal_flag_source": None}, "字段来源"),
        (
            {
                "has_private_terminal": True,
                "private_terminal_node_id": None,
                "private_terminal_node_source": None,
            },
            "码头节点",
        ),
        (
            {
                "has_private_terminal": False,
                "private_terminal_node_id": "node-stale-terminal",
                "private_terminal_node_source": "旧表",
            },
            "矛盾",
        ),
    ],
)
def test_unknown_or_inconsistent_private_terminal_data_requires_review(overrides, message_fragment):
    profile = make_profile(**overrides)

    result = resolve_customer_route(profile, south_port_node_id="node-south-port-demo")

    assert result.status == "manual_review"
    assert result.branch is None
    assert result.requires_manual_review
    assert message_fragment in result.message


def test_customer_compatibility_accepts_explicitly_supported_package_and_commodity():
    result = evaluate_customer_compatibility(
        make_profile(),
        package_type="散粮",
        commodity="玉米",
    )

    assert result.status == "eligible"
    assert result.issues == ()


def test_customer_compatibility_rejects_explicitly_unsupported_values():
    result = evaluate_customer_compatibility(
        make_profile(),
        package_type="袋装",
        commodity="大豆",
    )

    assert result.status == "not_applicable"
    assert len(result.issues) == 2
    assert "袋装" in result.message
    assert "大豆" in result.message


def test_missing_customer_compatibility_rules_require_review():
    profile = make_profile(allowed_package_types=None, allowed_commodities=None)

    result = evaluate_customer_compatibility(profile, package_type="散粮", commodity="玉米")

    assert result.status == "manual_review"
    assert "尚未配置" in result.message


def test_missing_rule_is_not_hidden_by_an_explicitly_unsupported_value():
    profile = make_profile(allowed_package_types=None)

    result = evaluate_customer_compatibility(
        profile,
        package_type="袋装",
        commodity="大豆",
    )

    assert result.status == "manual_review"
    assert "包装方式尚未配置" in result.message
    assert "不支持货物品种" in result.message


def test_public_route_decision_rejects_unknown_executable_branch():
    with pytest.raises(CustomerProfileError, match="不支持的客户路线分支"):
        CustomerRouteDecision(
            status="resolved",
            branch="unknown_branch",
            customer_id="customer-demo-001",
            south_port_node_id="node-south-port-demo",
            factory_node_id="node-factory-demo",
            private_terminal_node_id=None,
            profile_source="人工确认客户档案",
            private_terminal_flag_source="人工确认表",
            private_terminal_node_source=None,
            message="错误分支演示",
        )


def test_public_resolved_route_decision_requires_trace_sources():
    with pytest.raises(CustomerProfileError, match="自有码头标志来源"):
        CustomerRouteDecision(
            status="resolved",
            branch="transfer_terminal",
            customer_id="customer-demo-001",
            south_port_node_id="node-south-port-demo",
            factory_node_id="node-factory-demo",
            private_terminal_node_id=None,
            profile_source="人工确认客户档案",
            private_terminal_flag_source=" ",
            private_terminal_node_source=None,
            message="缺少来源演示",
        )


def test_private_terminal_branch_never_selects_transfer_ports():
    profile = make_profile(
        has_private_terminal=True,
        private_terminal_node_id="node-private-terminal-demo",
        private_terminal_node_source="人工确认码头表",
    )
    decision = resolve_customer_route(profile, south_port_node_id="node-south-port-demo")
    candidate = TransferPortCandidate(
        port_node_id="node-transfer-port-a",
        distance_km="8",
        distance_source="人工维护距离",
    )

    selection = prefilter_transfer_ports(decision, [candidate], k=1)

    assert selection.status == "not_applicable"
    assert selection.selected_candidates == ()
    assert not selection.requires_cost_time_comparison
    assert "不得生成中转港路线" in selection.message


def test_transfer_branch_prefilters_nearest_k_with_traceable_reason():
    decision = resolve_customer_route(make_profile(), south_port_node_id="node-south-port-demo")
    candidates = [
        TransferPortCandidate("node-transfer-port-c", "30", "地图确认结果"),
        TransferPortCandidate("node-transfer-port-b", "12", "熟悉路线台账"),
        TransferPortCandidate("node-transfer-port-a", "12", "熟悉路线台账"),
    ]

    selection = prefilter_transfer_ports(decision, candidates, k=2)

    assert selection.status == "resolved"
    assert [item.port_node_id for item in selection.selected_candidates] == [
        "node-transfer-port-a",
        "node-transfer-port-b",
    ]
    assert selection.requested_k == 2
    assert selection.available_candidate_count == 3
    assert selection.selection_rule == "distance_ascending_then_node_id"
    assert selection.requires_cost_time_comparison
    assert "仅用于预筛" in selection.message
    assert "总费用和总时间" in selection.message


def test_transfer_branch_without_candidates_requires_review():
    decision = resolve_customer_route(make_profile(), south_port_node_id="node-south-port-demo")

    selection = prefilter_transfer_ports(decision, [], k=3)

    assert selection.status == "manual_review"
    assert selection.selected_candidates == ()
    assert "没有可用的候选中转港" in selection.message


def test_manual_review_route_decision_cannot_select_transfer_ports():
    decision = resolve_customer_route(
        make_profile(has_private_terminal=None),
        south_port_node_id="node-south-port-demo",
    )
    candidate = TransferPortCandidate("node-transfer-port-a", "10", "人工维护距离")

    selection = prefilter_transfer_ports(decision, [candidate], k=1)

    assert selection.status == "manual_review"
    assert selection.selected_candidates == ()
    assert "路线分支尚未确认" in selection.message


@pytest.mark.parametrize("distance", [None, 0, "-1", "not-a-number"])
def test_transfer_port_candidate_requires_positive_distance(distance):
    with pytest.raises(CustomerProfileError, match="距离必须是大于 0"):
        TransferPortCandidate(
            port_node_id="node-transfer-port-a",
            distance_km=distance,
            distance_source="人工维护距离",
        )


def test_prefilter_rejects_duplicate_candidate_port_ids():
    decision = resolve_customer_route(make_profile(), south_port_node_id="node-south-port-demo")
    candidates = [
        TransferPortCandidate("node-transfer-port-a", "10", "来源一"),
        TransferPortCandidate("node-transfer-port-a", "11", "来源二"),
    ]

    selection = prefilter_transfer_ports(decision, candidates, k=1)

    assert selection.status == "manual_review"
    assert selection.selected_candidates == ()
    assert "重复" in selection.message


def test_prefilter_requires_positive_integer_k():
    decision = resolve_customer_route(make_profile(), south_port_node_id="node-south-port-demo")
    candidate = TransferPortCandidate("node-transfer-port-a", Decimal("10"), "人工维护距离")

    with pytest.raises(CustomerProfileError, match="K 必须是正整数"):
        prefilter_transfer_ports(decision, [candidate], k=0)
