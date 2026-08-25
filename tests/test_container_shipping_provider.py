from decimal import Decimal

from src.data.container_trunk_admission_audit import build_container_trunk_admission_audit
from src.data.loaders import NodeRecord, RealDataBundle
from src.data.node_master_maintenance import NodeMasterMaintenanceEntry
from src.domain.node_registry import build_node_registry
from src.domain.route_request import RouteRequest
from src.routing.container_shipping_provider import (
    ContainerShippingRateTimeRecord,
    TableContainerShippingProvider,
)


def test_container_vessel_provider_requires_box_and_never_reuses_bulk_data():
    provider = TableContainerShippingProvider(())
    request = RouteRequest(2, "箱", "集装箱", "玉米", trade_type="内贸")

    result = provider.match(
        origin_name="北港A",
        south_port_name="海港A",
        request=request,
    )

    assert result.status == "manual_review"
    assert "不构边" in result.message
    cabinet_request = RouteRequest(1, "柜", "集装箱", "玉米", trade_type="内贸")
    cabinet_result = provider.match(
        origin_name="北港A",
        south_port_name="海港A",
        request=cabinet_request,
    )
    assert cabinet_result.status == "not_applicable"
    assert "不得自动换算" in cabinet_result.message


def test_container_vessel_provider_builds_only_confirmed_exact_record():
    record = ContainerShippingRateTimeRecord(
        origin_name="北港A",
        south_port_name="海港A",
        transport_mode="集装箱船",
        package_type="集装箱",
        quantity_unit="箱",
        commodity_scope=("玉米",),
        trade_type="内贸",
        raw_price=Decimal("1200"),
        raw_price_unit="元/箱",
        price_type="unit_price",
        duration_hours=Decimal("96"),
        source="test.csv#row=2",
        confirmation_status="confirmed",
        origin_node_id="north",
        south_port_node_id="south",
        maintained_at="2026-08-06",
        source_row_number=2,
    )
    provider = TableContainerShippingProvider((record,))
    edge, result = provider.build_edge(
        origin_name="北港A",
        south_port_name="海港A",
        origin_node_id="north",
        south_port_node_id="south",
        request=RouteRequest(2, "箱", "集装箱", "玉米", trade_type="内贸"),
    )

    assert result.status == "resolved"
    assert edge is not None
    assert edge.transport_mode == "集装箱船"
    assert edge.transport_stage == "north_to_south"
    assert edge.cost_yuan == Decimal("2400")
    assert edge.time_hours == Decimal("96")


def test_container_trunk_audit_separates_sea_port_from_inland_and_customer_nodes():
    entries = (
        entry("海河港A", "物流节点", "港口码头", ("海港", "内河码头"), ("集装箱",)),
        entry("内河港B", "物流节点", "港口码头", ("内河码头",), ("集装箱",)),
        entry("客户自有码头", "客户", "饲料客户", ("客户仓库", "内河码头"), ("集装箱",)),
        entry("待标注港C", "物流节点", "港口码头", (), ("集装箱",)),
    )
    nodes = [NodeRecord(f"node-{index}", item.full_name, 113 + index, 22 + index) for index, item in enumerate(entries)]
    bundle = RealDataBundle(
        data_dir=__import__("pathlib").Path("."),
        freight_rates=[],
        nodes=nodes,
        additional_fees=[],
        node_registry=build_node_registry(nodes),
        node_master_entries=entries,
    )

    audit = build_container_trunk_admission_audit(bundle)
    rows = {row.port_name: row for row in audit.rows}

    assert rows["海河港A"].readiness_status == "eligible_pending_rate_time"
    assert rows["内河港B"].readiness_status == "excluded_inland_only"
    assert rows["客户自有码头"].readiness_status == "excluded_customer_or_non_port"
    assert rows["待标注港C"].readiness_status == "manual_review_missing_waterway_tag"
    assert audit.rate_time_source_status == "source_not_connected"


def entry(name, node_type, node_nature, port_attributes, package_types):
    return NodeMasterMaintenanceEntry(
        row_number=1,
        node_type=node_type,
        node_nature=node_nature,
        port_attributes=port_attributes,
        package_types=package_types,
        draft_capacity=None,
        business_unit=None,
        full_name=name,
        aliases=(),
        province=None,
        city=None,
        district=None,
        address=None,
        longitude=113,
        latitude=22,
        source="test.xlsx#row=2",
    )
