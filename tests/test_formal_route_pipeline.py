from decimal import Decimal

from src.cost_rules import CostCalculationResult
from src.customer_profile import (
    CustomerProfile,
    TransferPortCandidate,
    prefilter_transfer_ports,
    resolve_customer_route,
)
from src.freight_rate import create_freight_rate
from src.node_registry import NodeRegistry, StandardNode
from src.route_result import build_route_recommendations
from src.route_search import search_cost_and_time_paths
from src.shipping_time_provider import ShippingTimeResult
from src.transport_edge import build_transport_edge
from src.transport_graph import build_transport_multidigraph


def test_formal_customer_to_route_result_pipeline_preserves_traceable_branch():
    profile = CustomerProfile(
        customer_id="customer-demo-001",
        customer_name="演示客户",
        factory_node_id="node-factory",
        has_private_terminal=False,
        profile_source="脱敏客户档案",
        private_terminal_flag_source="人工确认表",
        allowed_package_types=("散粮",),
        allowed_commodities=("玉米",),
    )
    decision = resolve_customer_route(profile, south_port_node_id="node-south")
    selection = prefilter_transfer_ports(
        decision,
        [TransferPortCandidate("node-transfer", "18", "人工确认距离")],
        k=1,
    )

    water_edge = make_pipeline_edge(
        rate_id="rate-water",
        start="node-south",
        end="node-transfer",
        mode="水运",
        total_cost="2000",
        duration="10",
        source_row=1,
    )
    road_edge = make_pipeline_edge(
        rate_id="rate-road",
        start="node-transfer",
        end="node-factory",
        mode="汽运",
        total_cost="800",
        duration="2",
        source_row=2,
    )
    graph_result = build_transport_multidigraph(
        [water_edge, road_edge],
        node_registry=make_registry(),
    )
    searches = search_cost_and_time_paths(
        graph_result.graph,
        decision.south_port_node_id,
        decision.factory_node_id,
    )
    results = build_route_recommendations(graph_result.graph, searches)

    assert decision.branch == "transfer_terminal"
    assert selection.status == "resolved"
    assert selection.selected_candidates[0].port_node_id == "node-transfer"
    assert graph_result.issues == ()
    assert results.lowest_cost.status == "resolved"
    assert results.lowest_cost.path_node_ids == (
        "node-south",
        "node-transfer",
        "node-factory",
    )
    assert results.lowest_cost.total_cost_yuan == Decimal("2800")
    assert results.lowest_cost.total_time_hours == Decimal("12")
    assert len(results.lowest_cost.segments) == 2


def test_unknown_customer_branch_stops_before_candidate_execution():
    profile = CustomerProfile(
        customer_id="customer-review",
        customer_name="待确认客户",
        factory_node_id="node-factory",
        has_private_terminal=None,
        profile_source="脱敏客户档案",
    )
    decision = resolve_customer_route(profile, south_port_node_id="node-south")
    selection = prefilter_transfer_ports(
        decision,
        [TransferPortCandidate("node-transfer", "18", "人工确认距离")],
        k=1,
    )

    assert decision.status == "manual_review"
    assert selection.status == "manual_review"
    assert selection.selected_candidates == ()


def make_pipeline_edge(
    *,
    rate_id: str,
    start: str,
    end: str,
    mode: str,
    total_cost: str,
    duration: str,
    source_row: int,
):
    price_source = f"脱敏运价台账 {rate_id}"
    rate = create_freight_rate(
        origin_name=start,
        destination_name=end,
        transport_mode=mode,
        package_type="散粮",
        commodity_scope="玉米",
        raw_price="20",
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source=price_source,
        from_node_id=start,
        to_node_id=end,
        source_file="sanitized_rates.json",
        source_row_number=source_row,
    )
    cost = CostCalculationResult(
        status="valid",
        total_cost_yuan=Decimal(total_cost),
        rule_id="demo_confirmed_rate",
        rule_version="1.0",
        calculation_detail=f"脱敏费用合计 {total_cost} 元",
        price_source=price_source,
        transport_mode=mode,
        rate_packaging="散粮",
        price_unit="元/吨",
        message="已按脱敏确认运价计算。",
    )
    shipping_time = ShippingTimeResult(
        status="resolved",
        duration_hours=Decimal(duration),
        source="manual_shipping_time",
        message="已采用人工确认运输时间。",
        stage=f"{start} 至 {end}",
        transport_mode=mode,
        input_value=duration,
        input_unit="小时",
    )
    return build_transport_edge(
        rate,
        cost,
        shipping_time,
        commodity="玉米",
        data_source=f"sanitized_rates.json#row={source_row}",
    )


def make_registry() -> NodeRegistry:
    nodes = {
        node_id: StandardNode(node_id, name, (name,), longitude, latitude, 1)
        for node_id, name, longitude, latitude in (
            ("node-south", "演示南港", 113.1, 23.1),
            ("node-transfer", "演示中转港", 113.2, 23.2),
            ("node-factory", "演示客户工厂", 113.3, 23.3),
        )
    }
    return NodeRegistry(
        nodes=nodes,
        name_to_node_id={node.canonical_name: node_id for node_id, node in nodes.items()},
        alias_groups=(),
        alias_review_groups=(),
        coordinate_conflicts=(),
    )
