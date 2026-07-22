from datetime import date
from decimal import Decimal

import pytest

from src.domain.cost_rules import CostCalculationResult
from src.domain.freight_rate import create_freight_rate
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_edge import TransportEdgeError, build_transport_edge
from src.routing.transport_contracts import CostComponent, ManualReviewOutcome


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


def make_cost_result(**overrides) -> CostCalculationResult:
    values = {
        "status": "valid",
        "total_cost_yuan": Decimal("10000"),
        "rule_id": "known_truck_maintained_rate",
        "rule_version": "1.0",
        "calculation_detail": "20元/吨 × 500吨 = 10000元",
        "price_source": "演示熟悉路线台账",
        "transport_mode": "汽运",
        "rate_packaging": "散粮",
        "price_unit": "元/吨",
        "message": "已按维护运价计算当前订单运输段总费用。",
    }
    values.update(overrides)
    return CostCalculationResult(**values)


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


def test_builds_available_traceable_transport_edge():
    edge = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
        distance_km="35.2",
        distance_source="人工确认道路距离",
    )

    assert edge.status == "available"
    assert edge.is_available
    assert edge.from_node_id == "node-transfer-port-demo"
    assert edge.to_node_id == "node-factory-demo"
    assert edge.cost_yuan == Decimal("10000")
    assert edge.cost == Decimal("10000")
    assert edge.time_hours == Decimal("2.5")
    assert edge.raw_price == Decimal("20")
    assert edge.raw_price_unit == "元/吨"
    assert edge.maintained_at == date(2026, 7, 1)
    assert edge.distance_km == Decimal("35.2")
    assert edge.cost_rule_id == "known_truck_maintained_rate"
    assert edge.cost_rule_version == "1.0"
    assert edge.data_source == "sanitized_rates.json#row=8"
    assert edge.unavailable_reason is None


def test_available_edge_exports_graph_attributes_with_independent_weights():
    edge = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
    )

    attributes = edge.to_graph_attributes()

    assert attributes["edge_id"] == edge.edge_id
    assert attributes["cost"] == Decimal("10000")
    assert attributes["time_hours"] == Decimal("2.5")
    assert "weight" not in attributes
    assert attributes["price_source"] == "演示熟悉路线台账"
    assert attributes["time_source"] == "manual_shipping_time"


def test_edge_preserves_stage_time_scope_and_validated_cost_components():
    component = CostComponent(
        component_type="road_freight",
        amount_yuan="10000",
        source_type="confirmed_rule",
        source="sanitized_rates.json#row=8",
        rule_id="known_truck_maintained_rate",
        rule_version="1.0",
        calculation_detail="20元/吨 × 500吨 = 10000元",
    )
    edge = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(time_scope="road_driving"),
        commodity="玉米",
        transport_stage="road_last_mile",
        cost_components=(component,),
    )

    attributes = edge.to_graph_attributes()

    assert edge.transport_stage == "road_last_mile"
    assert edge.time_scope == "road_driving"
    assert attributes["cost_components"] == (component,)


def test_edge_rejects_cost_component_total_mismatch():
    component = CostComponent(
        component_type="road_freight",
        amount_yuan="9999",
        source_type="confirmed_rule",
        source="sanitized_rates.json#row=8",
        rule_id="known_truck_maintained_rate",
        rule_version="1.0",
        calculation_detail="错误合成测试金额",
    )

    with pytest.raises(TransportEdgeError, match="不一致"):
        build_transport_edge(
            make_rate(),
            make_cost_result(),
            make_time_result(),
            commodity="玉米",
            cost_components=(component,),
        )


def test_manual_review_outcome_makes_edge_unavailable_with_trace():
    outcome = ManualReviewOutcome(
        status="manual_review",
        reason_code="RATE_UNIT_UNCONFIRMED",
        source_ref="sanitized_rates.json#row=8",
        details="价格单位尚未确认。",
        owner_unit="W2",
    )

    edge = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
        manual_review_outcomes=(outcome,),
    )

    assert edge.status == "manual_review"
    assert edge.manual_review_outcomes == (outcome,)
    assert "RATE_UNIT_UNCONFIRMED" in edge.unavailable_reason
    assert "价格单位尚未确认" in edge.unavailable_reason


@pytest.mark.parametrize(
    ("stage", "scope", "message"),
    [
        ("unknown_stage", "complete_segment", "不支持的运输阶段"),
        ("bulk_shipping_trunk", "road_driving", "不允许使用时间范围"),
    ],
)
def test_edge_rejects_invalid_stage_time_scope_contract(stage, scope, message):
    with pytest.raises(TransportEdgeError, match=message):
        build_transport_edge(
            make_rate(),
            make_cost_result(),
            make_time_result(time_scope=scope),
            commodity="玉米",
            transport_stage=stage,
        )


def test_missing_node_ids_make_edge_unavailable_without_fabricated_nodes():
    edge = build_transport_edge(
        make_rate(from_node_id=None),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
    )

    assert edge.status == "manual_review"
    assert not edge.is_available
    assert edge.from_node_id is None
    assert "起点节点" in edge.unavailable_reason
    with pytest.raises(TransportEdgeError, match="不可用运输边"):
        edge.to_graph_attributes()


def test_missing_cost_never_defaults_to_zero():
    cost_result = make_cost_result(
        status="manual_review",
        total_cost_yuan=None,
        calculation_detail="未计算：运价冲突。",
        message="同日运价冲突，请人工确认。",
    )

    edge = build_transport_edge(
        make_rate(),
        cost_result,
        make_time_result(),
        commodity="玉米",
    )

    assert edge.status == "manual_review"
    assert edge.cost_yuan is None
    assert edge.cost is None
    assert "同日运价冲突" in edge.unavailable_reason


def test_missing_time_never_defaults_to_zero():
    time_result = make_time_result(
        status="manual_review",
        duration_hours=None,
        message="缺少人工运输时间。",
    )

    edge = build_transport_edge(
        make_rate(),
        make_cost_result(),
        time_result,
        commodity="玉米",
    )

    assert edge.status == "manual_review"
    assert edge.time_hours is None
    assert "缺少人工运输时间" in edge.unavailable_reason


def test_not_applicable_cost_produces_not_applicable_edge():
    cost_result = make_cost_result(
        status="not_applicable",
        total_cost_yuan=None,
        calculation_detail="未计算：订单品种不适用。",
        message="订单品种不在运价适用范围内。",
    )

    edge = build_transport_edge(
        make_rate(),
        cost_result,
        make_time_result(),
        commodity="大豆",
    )

    assert edge.status == "not_applicable"
    assert not edge.is_available
    assert edge.cost_yuan is None
    assert "不在运价适用范围" in edge.unavailable_reason


def test_transport_mode_or_packaging_mismatch_requires_review():
    edge = build_transport_edge(
        make_rate(),
        make_cost_result(transport_mode="水运", rate_packaging="集装箱"),
        make_time_result(transport_mode="铁路"),
        commodity="玉米",
    )

    assert edge.status == "manual_review"
    assert "运输方式与运价记录不一致" in edge.unavailable_reason
    assert "包装方式与运价记录不一致" in edge.unavailable_reason
    assert "运输时间方式与运价记录不一致" in edge.unavailable_reason


def test_distance_and_source_must_be_present_together():
    edge_without_source = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
        distance_km="35.2",
        distance_source=None,
    )
    source_without_edge = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
        distance_km=None,
        distance_source="人工确认道路距离",
    )

    assert edge_without_source.status == "manual_review"
    assert "距离来源" in edge_without_source.unavailable_reason
    assert source_without_edge.status == "manual_review"
    assert "距离数值" in source_without_edge.unavailable_reason


@pytest.mark.parametrize("distance", [0, "-1", "not-a-number"])
def test_invalid_distance_is_rejected(distance):
    with pytest.raises(TransportEdgeError, match="距离必须是大于 0"):
        build_transport_edge(
            make_rate(),
            make_cost_result(),
            make_time_result(),
            commodity="玉米",
            distance_km=distance,
            distance_source="人工确认道路距离",
        )


def test_edge_id_is_stable_and_distinguishes_parallel_sources():
    first = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
    )
    same = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
    )
    alternative = build_transport_edge(
        make_rate(price_source="演示备用报价", source_row_number=9),
        make_cost_result(price_source="演示备用报价"),
        make_time_result(),
        commodity="玉米",
    )

    assert first.edge_id == same.edge_id
    assert first.edge_id != alternative.edge_id


def test_edge_id_distinguishes_stage_time_scope_and_cost_component_trace():
    base = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
    )
    staged = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
        transport_stage="road_last_mile",
    )
    scoped = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(time_scope="road_driving"),
        commodity="玉米",
    )
    component = CostComponent(
        component_type="road_freight",
        amount_yuan="10000",
        source_type="confirmed_rule",
        source="sanitized_component_source",
        rule_id="known_truck_maintained_rate",
        rule_version="1.0",
        calculation_detail="合成费用组成追溯",
    )
    composed = build_transport_edge(
        make_rate(),
        make_cost_result(),
        make_time_result(),
        commodity="玉米",
        cost_components=(component,),
    )

    assert len({base.edge_id, staged.edge_id, scoped.edge_id, composed.edge_id}) == 4
