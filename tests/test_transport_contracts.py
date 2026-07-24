from decimal import Decimal

import pytest

from src.routing.transport_contracts import (
    CostComponent,
    CostComposition,
    ManualReviewOutcome,
    TransportContractError,
)


def make_component(component_type: str, amount: str) -> CostComponent:
    return CostComponent(
        component_type=component_type,
        amount_yuan=amount,
        source_type="confirmed_rule",
        source="sanitized_test_source",
        rule_id=f"rule_{component_type}",
        rule_version="1.0",
        calculation_detail=f"{component_type}合成测试计算",
    )


def test_cost_composition_sums_traceable_components_and_validates_total():
    composition = CostComposition(
        (
            make_component("bulk_shipping_freight", "30000"),
            make_component("south_port_operation", "5000"),
        )
    )

    assert composition.total_cost_yuan == Decimal("35000")
    composition.validate_total("35000")


def test_cost_composition_rejects_mismatched_total_and_zero_component():
    composition = CostComposition((make_component("bulk_shipping_freight", "30000"),))

    with pytest.raises(TransportContractError, match="不一致"):
        composition.validate_total("30001")
    with pytest.raises(TransportContractError, match="大于 0"):
        make_component("south_port_operation", "0")


@pytest.mark.parametrize("bad_amount", ["NaN", "Infinity", True])
def test_cost_component_rejects_non_finite_or_boolean_amount(bad_amount):
    with pytest.raises(TransportContractError, match="大于 0"):
        make_component("bulk_shipping_freight", bad_amount)


def test_cost_composition_requires_component_and_valid_source_type():
    with pytest.raises(TransportContractError, match="至少包含一项"):
        CostComposition(())

    with pytest.raises(TransportContractError, match="不支持的费用来源类型"):
        CostComponent(
            component_type="bulk_shipping_freight",
            amount_yuan="30000",
            source_type="unknown_source",
            source="test",
            rule_id="test",
            rule_version="1.0",
            calculation_detail="test",
        )


def test_demo_placeholder_is_explicit_source_type():
    component = CostComponent(
        component_type="south_port_operation",
        amount_yuan="5000",
        source_type="demo_placeholder",
        source="synthetic_demo",
        rule_id="demo_placeholder_port_operation",
        rule_version="1.0",
        calculation_detail="仅用于演示接口连通性。",
    )

    assert component.is_demo_placeholder


def test_regional_proxy_is_a_traceable_non_placeholder_source_type():
    component = CostComponent(
        component_type="south_port_operation_fee",
        amount_yuan="4000",
        source_type="regional_proxy",
        source=(
            "regional_proxy:reference_port_node_id=node-xiuyu;"
            "region_code=fujian_zhangzhou"
        ),
        rule_id="south_port_operation_fee_region_proxy",
        rule_version="1.0",
        calculation_detail=(
            "按已维护作业费区域映射引用参考码头费率；"
            "该金额不是目标码头精确真实费率。"
        ),
    )

    assert component.source_type == "regional_proxy"
    assert not component.is_demo_placeholder


def test_manual_review_outcome_requires_stable_trace_fields():
    outcome = ManualReviewOutcome(
        status="manual_review",
        reason_code="RATE_UNIT_UNCONFIRMED",
        source_ref="bulk_shipping_rate.xlsx#sheet=demo&cell=D4",
        details="价格单位尚未确认。",
        owner_unit="W2",
    )

    assert outcome.status == "manual_review"
    assert outcome.reason_code == "RATE_UNIT_UNCONFIRMED"

    with pytest.raises(TransportContractError, match="来源引用"):
        ManualReviewOutcome(
            status="manual_review",
            reason_code="RATE_UNIT_UNCONFIRMED",
            source_ref="",
            details="价格单位尚未确认。",
            owner_unit="W2",
        )
