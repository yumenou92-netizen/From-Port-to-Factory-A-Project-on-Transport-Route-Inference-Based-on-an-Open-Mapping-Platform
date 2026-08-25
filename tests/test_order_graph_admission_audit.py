import csv
import json
from decimal import Decimal

from src.data.loaders import NodeRecord, RealDataBundle
from src.data.order_graph_admission_audit import (
    OrderScenario,
    build_order_graph_admission_audit,
    discover_bulk_quantity_profiles,
    discover_order_scenarios,
    write_audit_outputs,
)
from src.domain.freight_rate import create_freight_rate
from src.domain.node_registry import build_node_registry
from src.routing.bulk_shipping_provider import BulkRateColumn, BulkShippingWorkbook
from src.routing.port_operation_fee_provider import (
    PortOperationFeeRate,
    TablePortOperationFeeProvider,
)


def test_scenario_discovery_covers_order_dimensions_and_vessel_boundaries():
    bundle = make_bundle()
    workbook = make_workbook()

    scenarios = discover_order_scenarios(bundle, workbook)

    assert {scenario.commodity for scenario in scenarios} == {"玉米", "小麦", "大豆"}
    assert {
        (scenario.package_type, scenario.quantity_unit)
        for scenario in scenarios
    } == {("散粮", "吨"), ("集装箱", "箱"), ("集装箱", "柜")}
    assert {scenario.trade_type for scenario in scenarios} == {"内贸", "外贸"}
    assert len(scenarios) == 48
    assert discover_bulk_quantity_profiles(workbook) == (
        Decimal("500"),
        Decimal("2450"),
        Decimal("30000"),
        Decimal("30001"),
    )


def test_audit_separates_ready_port_mapping_gap_and_implementation_scope(tmp_path):
    bundle = make_bundle()
    workbook = make_workbook()
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="广州南沙港",
                node_id=bundle.node_registry.lookup("广州南沙港").node_id,
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("8"),
                source="test_fee.csv#row=2",
                commodity_scope=("*",),
                trade_type="内贸",
            ),
        ),
        registry=bundle.node_registry,
    )
    scenarios = (
        OrderScenario("S001", "500", "吨", "散粮", "玉米", "内贸"),
        OrderScenario("S002", "1", "箱", "集装箱", "玉米", "内贸"),
        OrderScenario("S003", "500", "吨", "散粮", "大麦", "内贸"),
        OrderScenario("S004", "30000", "吨", "散粮", "小麦", "内贸"),
        OrderScenario("S005", "30001", "吨", "散粮", "小麦", "内贸"),
        OrderScenario("S006", "1", "柜", "集装箱", "玉米", "外贸"),
    )

    audit = build_order_graph_admission_audit(
        bundle,
        workbook=workbook,
        operation_fee_provider=provider,
        scenarios=scenarios,
    )

    rows = {
        (row.scenario_id, row.port_name): row
        for row in audit.port_rows
        if row.selection_scope == "automatic_port_candidate"
    }
    assert rows[("S001", "广州南沙港")].offline_admission_status == (
        "ready_pending_tencent"
    )
    assert rows[("S001", "广州南沙港")].manual_selection_status == (
        "ready_pending_tencent"
    )
    assert rows[("S003", "广州南沙港")].offline_admission_status == (
        "not_candidate_for_order"
    )
    assert rows[("S003", "广州南沙港")].manual_selection_status == (
        "ready_pending_tencent"
    )
    all_rows = {
        (row.scenario_id, row.port_name): row
        for row in audit.port_rows
    }
    assert all_rows[("S001", "清远清新码头")].offline_admission_status == (
        "excluded_inland_port"
    )
    assert all_rows[("S001", "清远清新码头")].port_waterway_role == (
        "inland_port"
    )
    assert rows[("S004", "广州南沙港")].selected_vessel_max_tons == "30000"
    assert rows[("S004", "广州南沙港")].bulk_shipping_status == "resolved"
    assert rows[("S005", "广州南沙港")].offline_admission_status == (
        "blocked_before_tencent"
    )
    assert rows[("S005", "广州南沙港")].blocking_codes == (
        "bulk_vessel_capacity_exceeded"
    )
    capacity_issue = next(
        issue
        for issue in audit.issue_rows
        if issue.scenario_id == "S005"
        and issue.port_name == "广州南沙港"
        and issue.issue_code == "bulk_vessel_capacity_exceeded"
    )
    assert capacity_issue.review_priority == "P1"
    assert any(
        row.port_name == "广州南沙港"
        and row.issue_code == "bulk_vessel_capacity_exceeded"
        for row in audit.manual_review_rows
    )
    container_issue = next(
        issue
        for issue in audit.issue_rows
        if issue.scenario_id == "S002"
        and issue.port_name == "广州南沙港"
        and issue.issue_code == "bulk_shipping_order_not_implemented"
    )
    assert not container_issue.manual_confirmation_required
    assert all(
        row.issue_code != "bulk_shipping_order_not_implemented"
        for row in audit.manual_review_rows
    )
    cabinet_issue = next(
        issue
        for issue in audit.issue_rows
        if issue.scenario_id == "S006"
        and issue.port_name == "广州南沙港"
        and issue.issue_code == "operation_fee_quantity_unit_not_supported"
    )
    assert not cabinet_issue.manual_confirmation_required
    assert all(
        row.issue_code != "operation_fee_quantity_unit_not_supported"
        for row in audit.manual_review_rows
    )
    registered_manual_port = next(
        row
        for row in audit.port_rows
        if row.scenario_id == "S001" and row.port_name == "广州花都港"
    )
    assert registered_manual_port.matching_last_mile_rate_count == 0
    assert registered_manual_port.selection_scope == (
        "potential_transfer_port_pending_confirmation"
    )
    assert registered_manual_port.offline_admission_status == (
        "excluded_no_bulk_origin_evidence"
    )
    unclassified_registered_port = next(
        row
        for row in audit.port_rows
        if row.scenario_id == "S001" and row.port_name == "测试待确认码头"
    )
    assert unclassified_registered_port.selection_scope == (
        "registered_port_manual_only"
    )
    freight_evidence_port = next(
        row
        for row in audit.port_rows
        if row.scenario_id == "S001" and row.port_name == "广州新港"
    )
    assert freight_evidence_port.port_waterway_role == "unknown_port"
    assert freight_evidence_port.selection_scope == "automatic_port_candidate"
    assert freight_evidence_port.matching_last_mile_rate_count == 0
    assert freight_evidence_port.last_mile_source_status == (
        "confirmed_rule_fallback"
    )
    assert freight_evidence_port.offline_admission_status == (
        "blocked_before_tencent"
    )
    assert not any(
        issue.scenario_id == "S001"
        and issue.port_name == "广州新港"
        and issue.issue_code == "sea_port_marker_missing"
        for issue in audit.issue_rows
    )
    assert all(
        row.port_name != "清远清新码头"
        or row.offline_admission_status == "excluded_inland_port"
        for row in audit.port_rows
        if row.scenario_id == "S001"
    )

    paths = write_audit_outputs(audit, tmp_path / "output")
    assert paths["manual_review"].exists()
    assert paths["ports"].exists()
    assert "不调用 Tencent" in paths["markdown"].read_text(encoding="utf-8")
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["scenario_count"] == len(scenarios)
    with paths["scenarios"].open(encoding="utf-8-sig", newline="") as handle:
        headers = next(csv.reader(handle))
    assert headers[:3] == ["scenario_id", "quantity", "quantity_unit"]


def test_audit_excludes_confirmed_customer_facility_from_candidate_fallback():
    bundle = make_fallback_bundle()
    workbook = make_workbook()
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="广州南沙港",
                node_id=bundle.node_registry.lookup("广州南沙港").node_id,
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("8"),
                source="test_fee.csv#row=2",
                commodity_scope=("*",),
                trade_type="内贸",
            ),
        ),
        registry=bundle.node_registry,
    )
    scenario = OrderScenario("S001", "500", "吨", "散粮", "大豆", "内贸")

    audit = build_order_graph_admission_audit(
        bundle,
        workbook=workbook,
        operation_fee_provider=provider,
        scenarios=(scenario,),
    )

    rows = {row.port_name: row for row in audit.port_rows}
    assert rows["广州南沙港"].selection_scope == "automatic_port_candidate"
    assert rows["省储直属库"].selection_scope == "excluded_customer_facility"
    assert rows["省储直属库"].inferred_node_role == "customer_facility"
    assert rows["省储直属库"].matching_last_mile_rate_count == 1
    assert rows["省储直属库"].offline_admission_status == (
        "excluded_confirmed_node_role"
    )
    assert not any(
        row.port_name == "省储直属库"
        and row.issue_code == "customer_origin_not_south_port"
        for row in audit.manual_review_rows
    )


def make_bundle() -> RealDataBundle:
    nodes = [
        NodeRecord("node-guangzhou", "广州南沙港", 113.6, 22.7),
        NodeRecord("node-huadu", "广州花都港", 113.2, 23.4),
        NodeRecord("node-new-port", "广州新港", 113.5, 23.1),
        NodeRecord("node-qingyuan", "清远清新码头", 112.9, 23.7),
        NodeRecord("node-unclassified-port", "测试待确认码头", 113.1, 23.2),
        NodeRecord("node-customer", "测试客户", 113.0, 23.0),
    ]
    registry = build_node_registry(nodes)
    rates = []
    for node_id, name in (
        (registry.lookup("广州南沙港").node_id, "广州南沙港"),
        (registry.lookup("广州新港").node_id, "广州新港"),
        (registry.lookup("清远清新码头").node_id, "清远清新码头"),
    ):
        for package_type, price_unit in (
            ("散粮", "元/吨"),
            ("集装箱", "元/箱"),
        ):
            rates.append(
                create_freight_rate(
                    origin_name=name,
                    destination_name="测试客户",
                    transport_mode=(
                        "驳船"
                        if name == "广州新港" and package_type == "散粮"
                        else "汽运"
                    ),
                    package_type=package_type,
                    commodity_scope="玉米、小麦、大豆",
                    raw_price=Decimal("10"),
                    raw_price_unit=price_unit,
                    price_type="unit_price",
                    price_source="test",
                    from_node_id=node_id,
                    to_node_id="node-customer",
                )
            )
    rates.append(
        create_freight_rate(
            origin_name="广州花都港",
            destination_name="测试客户",
            transport_mode="汽运",
            package_type="集装箱",
            commodity_scope="玉米、小麦",
            raw_price=Decimal("300"),
            raw_price_unit="元/箱",
            price_type="unit_price",
            price_source="test",
            from_node_id=registry.lookup("广州花都港").node_id,
            to_node_id="node-customer",
        )
    )
    return RealDataBundle(
        data_dir=tmp_data_dir(),
        freight_rates=rates,
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
    )


def make_fallback_bundle() -> RealDataBundle:
    nodes = [
        NodeRecord("node-guangzhou", "广州南沙港", 113.6, 22.7),
        NodeRecord("node-depot", "省储直属库", 113.4, 23.1),
        NodeRecord("node-customer", "测试客户", 113.0, 23.0),
    ]
    registry = build_node_registry(nodes)
    rates = [
        create_freight_rate(
            origin_name=name,
            destination_name="测试客户",
            transport_mode="汽运",
            package_type="散粮",
            commodity_scope="大豆",
            raw_price=Decimal("10"),
            raw_price_unit="元/吨",
            price_type="unit_price",
            price_source="test",
            from_node_id=node_id,
            to_node_id="node-customer",
        )
        for node_id, name in (
            (registry.lookup("广州南沙港").node_id, "广州南沙港"),
            (registry.lookup("省储直属库").node_id, "省储直属库"),
        )
    ]
    return RealDataBundle(
        data_dir=tmp_data_dir(),
        freight_rates=rates,
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
    )


def make_workbook() -> BulkShippingWorkbook:
    return BulkShippingWorkbook(
        (
            BulkRateColumn(
                destination_label="珠三角",
                vessel_type="2-3万吨",
                rate_yuan_per_ton=Decimal("50"),
                cell_ref="B4",
                latest_date_label="2026-07-28",
                workbook_path="test.xlsx",
                scope="project_scope_confirmed",
            ),
        )
    )


def tmp_data_dir():
    from pathlib import Path

    return Path(".")
