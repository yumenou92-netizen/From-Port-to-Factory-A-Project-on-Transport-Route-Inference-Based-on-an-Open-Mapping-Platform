from datetime import date
from decimal import Decimal

from src.data.loaders import NodeRecord, make_node_id
from src.data.node_master_capabilities import (
    build_barge_capabilities_from_node_master,
)
from src.data.node_master_maintenance import NodeMasterMaintenanceEntry
from src.domain.freight_rate import create_freight_rate
from src.domain.node_registry import ExternalAliasRule, build_node_registry
from src.routing.inland_waterway_provider import RegionMappingRecord


def test_exact_barge_rate_infers_capability_but_not_customer_transfer_role():
    entries = (
        make_entry(
            "南港A",
            node_type="物流节点",
            attributes=("海港", "内河码头"),
            packages=("散粮", "集装箱"),
            city="广州市",
            longitude=113.5,
            latitude=23.0,
        ),
        make_entry(
            "客户B",
            node_type="客户、物流节点",
            attributes=("客户仓库", "内河码头"),
            packages=("散粮", "集装箱"),
            city="佛山市",
            longitude=113.1,
            latitude=22.9,
        ),
    )
    registry = registry_for(entries)
    rate = make_rate("南港A", "客户B", registry)

    result = build_barge_capabilities_from_node_master(
        node_master_entries=entries,
        freight_rates=(rate,),
        registry=registry,
        region_mappings=(pearl_delta_mapping(),),
    )

    by_name = {
        record.canonical_name: record for record in result.capabilities
    }
    assert by_name["南港A"].can_handle_barge is True
    assert by_name["南港A"].can_receive_bulk_shipping is True
    assert by_name["南港A"].is_transfer_port is False
    assert by_name["客户B"].can_handle_barge is True
    assert by_name["客户B"].is_transfer_port is False
    assert by_name["客户B"].infrastructure_type == "customer_barge_receiver"
    assert by_name["客户B"].supported_package_types == ("散粮", "集装箱")


def test_inland_logistics_destination_becomes_transfer_and_uses_nearest_region():
    entries = (
        make_entry(
            "广州锚点港",
            node_type="物流节点",
            attributes=("海港", "内河码头"),
            packages=("散粮",),
            city="广州市",
            longitude=113.5,
            latitude=23.0,
        ),
        make_entry(
            "无关键词内河港",
            node_type="物流节点",
            attributes=("内河码头",),
            packages=("散粮",),
            city="未知市",
            longitude=113.6,
            latitude=23.1,
        ),
    )
    registry = registry_for(entries)
    rate = make_rate("广州锚点港", "无关键词内河港", registry)

    result = build_barge_capabilities_from_node_master(
        node_master_entries=entries,
        freight_rates=(rate,),
        registry=registry,
        region_mappings=(pearl_delta_mapping(),),
    )

    destination = next(
        record
        for record in result.capabilities
        if record.canonical_name == "无关键词内河港"
    )
    assignment = next(
        record
        for record in result.region_assignments
        if record.canonical_name == "无关键词内河港"
    )
    assert destination.is_transfer_port is True
    assert destination.can_receive_bulk_shipping is False
    assert destination.region_code == "pearl_river_delta"
    assert assignment.method == "nearest_region_proxy"
    assert assignment.anchor_name == "广州锚点港"
    assert assignment.distance_km is not None


def test_confirmed_rate_only_endpoints_fill_bounded_capability_gaps():
    registry = build_node_registry(
        (
            NodeRecord(
                make_node_id("东莞粤储粮港务有限公司"),
                "东莞粤储粮港务有限公司",
                113.6,
                22.98,
            ),
            NodeRecord(
                make_node_id("南宁港牛湾作业区"),
                "南宁港牛湾作业区",
                108.55,
                22.79,
            ),
        ),
        external_alias_rules=(
            ExternalAliasRule(
                canonical_name="东莞粤储粮港务有限公司",
                aliases=("东莞粤储粮",),
                source="名称字典.xlsx",
            ),
        ),
    )
    rates = (
        make_rate(
            "东莞粤储粮",
            "南宁港牛湾作业区",
            registry,
            commodity_scope="小麦",
        ),
        make_rate(
            "东莞粤储粮",
            "南宁港牛湾作业区",
            registry,
            commodity_scope="玉米、大豆",
        ),
    )

    result = build_barge_capabilities_from_node_master(
        node_master_entries=(),
        freight_rates=rates,
        registry=registry,
        region_mappings=(
            RegionMappingRecord(
                region_code="pearl_river_delta",
                region_name="珠三角",
                city_keywords=("东莞",),
                port_keywords=("粤储粮",),
                source="business_confirmation",
            ),
            RegionMappingRecord(
                region_code="nanning",
                region_name="南宁",
                city_keywords=("南宁",),
                port_keywords=("牛湾",),
                source="business_confirmation",
            ),
        ),
    )

    by_name = {
        record.canonical_name: record for record in result.capabilities
    }
    origin = by_name["东莞粤储粮港务有限公司"]
    destination = by_name["南宁港牛湾作业区"]
    assert origin.region_code == "pearl_river_delta"
    assert origin.infrastructure_type == "sea_river_integrated_port"
    assert origin.can_receive_bulk_shipping is True
    assert origin.is_transfer_port is False
    assert destination.region_code == "nanning"
    assert destination.infrastructure_type == "inland_port"
    assert destination.can_receive_bulk_shipping is False
    assert destination.is_transfer_port is True
    assert origin.supported_commodities == ("大豆", "小麦", "玉米")
    assert destination.supported_commodities == ("大豆", "小麦", "玉米")
    assert all(
        "运费数据.xlsx" in record.source
        for record in (origin, destination)
    )


def make_entry(
    name,
    *,
    node_type,
    attributes,
    packages,
    city,
    longitude,
    latitude,
):
    return NodeMasterMaintenanceEntry(
        row_number=2,
        node_type=node_type,
        node_nature="港口码头" if "物流节点" in node_type else "饲料客户",
        port_attributes=attributes,
        package_types=packages,
        draft_capacity=None,
        business_unit=None,
        full_name=name,
        aliases=(),
        province="广东省",
        city=city,
        district=None,
        address=None,
        longitude=longitude,
        latitude=latitude,
        source=f"节点信息维护0731.xlsx#{name}",
    )


def registry_for(entries):
    return build_node_registry(
        NodeRecord(
            node_id=make_node_id(entry.full_name),
            name=entry.full_name,
            longitude=entry.longitude,
            latitude=entry.latitude,
        )
        for entry in entries
    )


def make_rate(
    origin,
    destination,
    registry,
    *,
    commodity_scope="玉米、小麦",
):
    return create_freight_rate(
        origin_name=origin,
        destination_name=destination,
        transport_mode="驳船",
        package_type="散粮",
        commodity_scope=commodity_scope,
        raw_price=Decimal("18"),
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="测试真实运价",
        maintained_at=date(2026, 7, 31),
        from_node_id=registry.require(origin).node_id,
        to_node_id=registry.require(destination).node_id,
        source_file="运费数据.xlsx",
        source_row_number=1,
    )


def pearl_delta_mapping():
    return RegionMappingRecord(
        region_code="pearl_river_delta",
        region_name="珠三角",
        city_keywords=("广州市", "佛山市"),
        port_keywords=("广州", "佛山"),
        source="business_confirmation",
    )
