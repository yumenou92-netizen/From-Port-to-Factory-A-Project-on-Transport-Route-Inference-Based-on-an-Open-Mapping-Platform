from decimal import Decimal
from pathlib import Path

import pytest

from src.application.south_port_selection import (
    SouthPortSelectionError,
    select_automatic_south_ports,
    select_requested_south_port,
)
from src.data.loaders import NodeRecord, RealDataBundle
from src.data.node_master_maintenance import NodeMasterMaintenanceEntry
from src.data.port_node_maintenance import PortNodeMaintenanceEntry
from src.domain.freight_rate import create_freight_rate
from src.domain.node_registry import build_node_registry
from src.domain.route_request import RouteRequest
from src.geo.distance_provider import GeoPoint


def test_automatic_selection_uses_bulk_barge_origin_evidence_and_explains_exclusions():
    bundle = make_bundle()

    selection = select_automatic_south_ports(
        bundle,
        make_request(),
        GeoPoint(Decimal("113.0"), Decimal("23.0")),
        origin_node_id="node-north",
        excluded_node_ids=set(),
        preferred_node_ids=set(),
        limit=2,
    )

    assert {port.name for port in selection.ports} == {"广州新港", "钦州港"}
    decisions = {decision.name: decision for decision in selection.decisions}
    assert decisions["广州新港"].status == "shortlisted"
    assert "bulk_freight_origin_evidence=applicable" in decisions[
        "广州新港"
    ].evidence
    assert decisions["清远清新码头"].status == "excluded"
    assert "纯内河港" in decisions["清远清新码头"].reason
    assert decisions["测试饲料有限公司"].status == "excluded"
    assert "不是港口/码头" in decisions["测试饲料有限公司"].reason


def test_requested_selection_rejects_container_only_origin_but_accepts_bulk_origin():
    bundle = make_bundle()
    destination = GeoPoint(Decimal("113.0"), Decimal("23.0"))

    accepted = select_requested_south_port(
        "广州新港",
        registry=bundle.node_registry,
        freight_rates=bundle.freight_rates,
        request=make_request(),
        destination=destination,
        origin_node_id="node-north",
        excluded_node_ids=set(),
    )

    assert accepted.ports[0].name == "广州新港"
    with pytest.raises(
        SouthPortSelectionError,
        match="没有适用的散粮始发运价证据",
    ):
        select_requested_south_port(
            "广州花都港",
            registry=bundle.node_registry,
            freight_rates=bundle.freight_rates,
            request=make_request(),
            destination=destination,
            origin_node_id="node-north",
            excluded_node_ids=set(),
        )


def test_maintained_port_tags_precede_name_heuristics_for_automatic_selection():
    nodes = [
        NodeRecord("node-xinsha", "东莞新沙", 113.5565, 22.9992),
        NodeRecord("node-customer", "客户工厂", 113.0, 23.0),
    ]
    registry = build_node_registry(nodes)
    bundle = RealDataBundle(
        data_dir=Path("test-data"),
        freight_rates=[
            make_rate(registry, "东莞新沙", "散粮", "汽运")
        ],
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
        node_master_entries=(
            NodeMasterMaintenanceEntry(
                row_number=777,
                node_type="物流节点",
                node_nature="港口码头",
                port_attributes=("海港", "内河码头"),
                package_types=("散粮", "集装箱"),
                draft_capacity="60000",
                business_unit=None,
                full_name="东莞新沙",
                aliases=("新沙",),
                province="广东省",
                city="东莞市",
                district="麻涌镇",
                address="西部干道新沙港区",
                longitude=113.5565,
                latitude=22.9992,
                source="节点信息维护0731.xlsx#节点信息维护!777",
            ),
        ),
    )

    selection = select_automatic_south_ports(
        bundle,
        make_request(),
        GeoPoint(Decimal("113.0"), Decimal("23.0")),
        origin_node_id="node-north",
        excluded_node_ids=set(),
        preferred_node_ids=set(),
        limit=1,
    )

    assert [port.name for port in selection.ports] == ["东莞新沙"]
    decision = next(
        item for item in selection.decisions if item.name == "东莞新沙"
    )
    assert decision.status == "shortlisted"
    assert (
        "identity_source=节点信息维护0731.xlsx#节点信息维护!777"
        in decision.evidence
    )


def test_waterway_attribute_does_not_promote_maintained_warehouse_to_port():
    nodes = [
        NodeRecord(
            "node-warehouse",
            "东莞市深粮物流有限公司",
            113.56,
            22.98,
        ),
        NodeRecord("node-customer", "客户工厂", 113.0, 23.0),
    ]
    registry = build_node_registry(nodes)
    bundle = RealDataBundle(
        data_dir=Path("test-data"),
        freight_rates=[
            make_rate(
                registry,
                "东莞市深粮物流有限公司",
                "散粮",
                "汽运",
            )
        ],
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
        node_master_entries=(
            NodeMasterMaintenanceEntry(
                row_number=776,
                node_type="物流节点",
                node_nature="租赁库",
                port_attributes=("海港", "内河码头"),
                package_types=("散粮", "集装箱"),
                draft_capacity="17000",
                business_unit=None,
                full_name="东莞市深粮物流有限公司",
                aliases=("东莞深粮",),
                province="广东省",
                city="东莞市",
                district="麻涌镇",
                address="漳彭村新港南路8号",
                longitude=113.56,
                latitude=22.98,
                source="节点信息维护0731.xlsx#节点信息维护!776",
            ),
        ),
    )

    selection = select_automatic_south_ports(
        bundle,
        make_request(),
        GeoPoint(Decimal("113.0"), Decimal("23.0")),
        origin_node_id="node-north",
        excluded_node_ids=set(),
        preferred_node_ids=set(),
        limit=1,
    )

    assert selection.ports == ()
    decision = next(iter(selection.decisions))
    assert decision.status == "excluded"
    assert "不是港口/码头" in decision.reason
    assert (
        "identity_method=maintained_tag_primary"
        in decision.evidence
    )


def test_legacy_0729_port_nature_is_used_when_newer_master_is_absent():
    nodes = [
        NodeRecord("node-xinsha", "东莞新沙", 113.5565, 22.9992),
        NodeRecord("node-customer", "客户工厂", 113.0, 23.0),
    ]
    registry = build_node_registry(nodes)
    bundle = RealDataBundle(
        data_dir=Path("test-data"),
        freight_rates=[
            make_rate(registry, "东莞新沙", "散粮", "汽运")
        ],
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
        port_node_entries=(
            PortNodeMaintenanceEntry(
                row_number=5,
                full_name="东莞新沙",
                aliases=("新沙",),
                longitude=113.5565,
                latitude=22.9992,
                province="广东省",
                city="东莞市",
                district="麻涌镇",
                address="西部干道新沙港区",
                source="码头信息维护0729版.xlsx#5",
            ),
        ),
    )

    selection = select_automatic_south_ports(
        bundle,
        make_request(),
        GeoPoint(Decimal("113.0"), Decimal("23.0")),
        origin_node_id="node-north",
        excluded_node_ids=set(),
        preferred_node_ids=set(),
        limit=1,
    )

    assert [port.name for port in selection.ports] == ["东莞新沙"]
    decision = next(iter(selection.decisions))
    assert (
        "identity_source=码头信息维护0729版.xlsx#5"
        in decision.evidence
    )


def test_automatic_selection_reserves_multimodal_quota_without_losing_nearest_port():
    nodes = [
        NodeRecord("node-qinzhou", "钦州港", 108.6, 21.7),
        NodeRecord("node-zhanjiang", "湛江港", 110.4, 21.2),
        NodeRecord("node-guangzhou", "广州新港", 113.5, 23.05),
        NodeRecord("node-customer", "客户工厂", 108.7, 21.8),
    ]
    registry = build_node_registry(nodes)
    rates = [
        make_rate(registry, name, "散粮", "汽运")
        for name in ("钦州港", "湛江港", "广州新港")
    ]
    bundle = RealDataBundle(
        data_dir=Path("test-data"),
        freight_rates=rates,
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
    )

    selection = select_automatic_south_ports(
        bundle,
        make_request(),
        GeoPoint(Decimal("108.7"), Decimal("21.8")),
        origin_node_id="node-north",
        excluded_node_ids=set(),
        preferred_node_ids=set(),
        alternative_transport_origin_node_ids={
            registry.require("广州新港").node_id
        },
        limit=2,
    )

    assert [port.name for port in selection.ports] == [
        "广州新港",
        "钦州港",
    ]
    decisions = {decision.name: decision for decision in selection.decisions}
    assert (
        "exact_od_barge_origin=multimodal_quota"
        in decisions["广州新港"].evidence
    )
    assert decisions["湛江港"].status == "not_selected"


def test_multimodal_quota_still_applies_when_initial_shortlist_is_all_preferred():
    nodes = [
        NodeRecord("node-qinzhou", "钦州港", 108.6, 21.7),
        NodeRecord("node-zhanjiang", "湛江港", 110.4, 21.2),
        NodeRecord("node-guangzhou", "广州新港", 113.5, 23.05),
        NodeRecord("node-customer", "客户工厂", 108.7, 21.8),
    ]
    registry = build_node_registry(nodes)
    rates = [
        make_rate(registry, name, "散粮", "汽运")
        for name in ("钦州港", "湛江港", "广州新港")
    ]
    bundle = RealDataBundle(
        data_dir=Path("test-data"),
        freight_rates=rates,
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
    )

    selection = select_automatic_south_ports(
        bundle,
        make_request(),
        GeoPoint(Decimal("108.7"), Decimal("21.8")),
        origin_node_id="node-north",
        excluded_node_ids=set(),
        preferred_node_ids={
            registry.require("钦州港").node_id,
            registry.require("湛江港").node_id,
        },
        alternative_transport_origin_node_ids={
            registry.require("广州新港").node_id
        },
        limit=2,
    )

    assert {port.name for port in selection.ports} == {
        "钦州港",
        "广州新港",
    }


def make_bundle() -> RealDataBundle:
    nodes = [
        NodeRecord("node-guangzhou", "广州新港", 113.5, 23.05),
        NodeRecord("node-qinzhou", "钦州港", 108.6, 21.7),
        NodeRecord("node-qingyuan", "清远清新码头", 112.9, 23.7),
        NodeRecord("node-company", "测试饲料有限公司", 113.2, 23.1),
        NodeRecord("node-huadu", "广州花都港", 113.2, 23.4),
        NodeRecord("node-customer", "客户工厂", 113.0, 23.0),
    ]
    registry = build_node_registry(nodes)
    rates = [
        make_rate(registry, name, package_type, transport_mode)
        for name, package_type, transport_mode in (
            ("广州新港", "散粮", "驳船"),
            ("钦州港", "散粮", "汽运"),
            ("清远清新码头", "散粮", "汽运"),
            ("测试饲料有限公司", "散粮", "汽运"),
            ("广州花都港", "集装箱", "汽运"),
        )
    ]
    return RealDataBundle(
        data_dir=Path("test-data"),
        freight_rates=rates,
        nodes=nodes,
        additional_fees=[],
        node_registry=registry,
    )


def make_rate(
    registry,
    origin_name: str,
    package_type: str,
    transport_mode: str,
):
    origin = registry.lookup(origin_name)
    destination = registry.lookup("客户工厂")
    return create_freight_rate(
        origin_name=origin_name,
        destination_name="客户工厂",
        transport_mode=transport_mode,
        package_type=package_type,
        commodity_scope="玉米、小麦",
        raw_price=Decimal("20"),
        raw_price_unit="元/吨" if package_type == "散粮" else "元/箱",
        price_type="unit_price",
        price_source="test",
        from_node_id=origin.node_id,
        to_node_id=destination.node_id,
    )


def make_request() -> RouteRequest:
    return RouteRequest(
        quantity=Decimal("2450"),
        quantity_unit="吨",
        package_type="散粮",
        commodity="玉米",
    )
