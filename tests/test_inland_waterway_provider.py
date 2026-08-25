from decimal import Decimal

from src.domain.route_request import RouteRequest
from src.routing.inland_waterway_provider import (
    DEFAULT_PORT_CAPABILITY_RECORDS,
    DemoInlandWaterwayBargeProvider,
    InlandWaterwayRateTimeRecord,
    PortCapabilityRecord,
    RegionMappingRecord,
)


def test_demo_provider_does_not_assign_barge_capability_to_generic_fuzhou_customer():
    result = DemoInlandWaterwayBargeProvider().build_barge_edge(
        origin_node_id="node-mawei",
        origin_name="马尾港",
        destination_node_id="node-fuzhou-customer",
        destination_name="福州客户码头",
        request=make_request(),
    )

    assert result.status == "not_applicable"
    assert result.edge is None
    assert "未同时匹配到支持区域" in result.message


def test_confirmed_fujian_capabilities_are_exact_and_package_specific():
    capabilities = {
        record.canonical_name: record
        for record in DEFAULT_PORT_CAPABILITY_RECORDS
        if record.region_code == "fujian_minjiang"
    }

    military = capabilities["军航码头"]
    assert military.capability_data_confirmed
    assert military.supported_package_types == ("散粮",)
    assert military.supported_commodities == ("玉米", "小麦")
    assert military.can_receive_bulk_shipping

    nanping = capabilities["南平港"]
    assert nanping.capability_data_confirmed
    assert nanping.supported_package_types == ("散粮", "集装箱")
    assert nanping.supported_commodities == ("玉米", "小麦")
    assert not nanping.can_receive_bulk_shipping
    assert nanping.supported_transport_modes == ("驳船", "铁路")
    assert "福州马尾港" not in capabilities
    assert not any("福州" == alias for record in capabilities.values() for alias in record.aliases)


def test_demo_minjiang_scope_only_allows_nanping_and_military_terminal_pair():
    provider = DemoInlandWaterwayBargeProvider()

    allowed = provider.build_barge_edge(
        origin_node_id="node-nanping",
        origin_name="南平港",
        destination_node_id="node-military",
        destination_name="军航码头",
        request=make_request(),
    )
    excluded = provider.build_barge_edge(
        origin_node_id="node-mawei",
        origin_name="福州马尾港",
        destination_node_id="node-military",
        destination_name="军航码头",
        request=make_request(),
    )

    assert allowed.status == "generated"
    assert allowed.edge is not None
    assert excluded.status == "not_applicable"
    assert excluded.edge is None


def test_demo_provider_generates_pearl_delta_placeholder_barge_edge():
    result = DemoInlandWaterwayBargeProvider().build_barge_edge(
        origin_node_id="node-guangzhou",
        origin_name="广州新港",
        destination_node_id="node-dongguan-customer",
        destination_name="东莞客户码头",
        request=make_request(),
    )

    assert result.status == "generated"
    assert result.region_code == "pearl_river_delta"
    assert result.edge is not None
    assert result.edge.cost_yuan == Decimal("24500")
    assert result.edge.time_hours == Decimal("6")
    assert result.edge.cost_components[0].source_type == "demo_placeholder"


def test_demo_provider_does_not_generate_for_other_regions():
    result = DemoInlandWaterwayBargeProvider().build_barge_edge(
        origin_node_id="node-qinzhou",
        origin_name="钦州港",
        destination_node_id="node-guangxi-customer",
        destination_name="广西客户码头",
        request=make_request(),
    )

    assert result.status == "not_applicable"
    assert result.edge is None
    assert "福建闽江和珠三角" in result.message


def test_demo_provider_does_not_generate_across_two_supported_regions():
    result = DemoInlandWaterwayBargeProvider().build_barge_edge(
        origin_node_id="node-nanping",
        origin_name="南平港",
        destination_node_id="node-guangzhou",
        destination_name="广州客户码头",
        request=make_request(),
    )

    assert result.status == "not_applicable"
    assert result.edge is None
    assert "不属于同一内河航运区域" in result.message


def test_demo_provider_requires_supported_package_and_quantity_unit():
    result = DemoInlandWaterwayBargeProvider().build_barge_edge(
        origin_node_id="node-guangzhou",
        origin_name="广州新港",
        destination_node_id="node-dongguan-customer",
        destination_name="东莞客户码头",
        request=RouteRequest(
            quantity=500,
            quantity_unit="箱",
            package_type="集装箱",
            commodity="玉米",
        ),
    )

    assert result.status == "not_applicable"
    assert result.edge is None
    assert "包装/品种" in result.message or "航费/航时表" in result.message


def test_bulk_barge_edge_rejects_container_only_terminal_capability():
    provider = DemoInlandWaterwayBargeProvider(
        port_capabilities=(
            PortCapabilityRecord(
                node_id="node-guangzhou",
                canonical_name="广州示例港",
                region_code="pearl_river_delta",
                can_handle_barge=True,
                supported_package_types=("散粮",),
                supported_commodities=("*",),
                source="demo_placeholder:origin_capability",
            ),
            PortCapabilityRecord(
                node_id="node-foshan-container",
                canonical_name="佛山示例集装箱码头",
                region_code="pearl_river_delta",
                can_handle_barge=True,
                supported_package_types=("集装箱",),
                supported_commodities=("*",),
                source="demo_placeholder:destination_capability",
                is_transfer_port=True,
            ),
        )
    )

    result = provider.build_barge_edge(
        origin_node_id="node-guangzhou",
        origin_name="广州示例港",
        destination_node_id="node-foshan-container",
        destination_name="佛山示例集装箱码头",
        request=make_request(),
    )

    assert result.status == "not_applicable"
    assert result.edge is None
    assert "包装/品种" in result.message


def test_demo_provider_does_not_emit_real_data_barge_edges():
    provider = DemoInlandWaterwayBargeProvider(
        rate_time_records=(
            InlandWaterwayRateTimeRecord(
                region_code="pearl_river_delta",
                package_type="散粮",
                commodity_scope=("*",),
                unit_rate_yuan_per_ton=Decimal("9"),
                duration_hours=Decimal("5"),
                source_type="real_data",
                source="future_real_inland_waterway.csv#row=1",
                rule_id="future_real_rule",
                rule_version="1.0",
            ),
        )
    )

    result = provider.build_barge_edge(
        origin_node_id="node-guangzhou",
        origin_name="广州新港",
        destination_node_id="node-dongguan-customer",
        destination_name="东莞客户码头",
        request=make_request(),
    )

    assert result.status == "not_applicable"
    assert result.edge is None
    assert "航费/航时表" in result.message


def test_region_mapping_and_capability_records_define_future_table_contract():
    region = RegionMappingRecord(
        region_code="pearl_river_delta",
        region_name="珠三角内河",
        city_keywords=("广州", "深圳", "东莞"),
        port_keywords=("黄埔", "蛇口"),
        bulk_rate_destination_group="珠三角",
        bulk_time_region="珠三角",
        source="demo_placeholder:region_mapping",
    )
    capability = PortCapabilityRecord(
        node_id="node-guangzhou",
        canonical_name="广州新港",
        region_code="pearl_river_delta",
        can_handle_barge=True,
        supported_package_types=("散粮",),
        supported_commodities=("*",),
        source="demo_placeholder:port_capability",
        infrastructure_type="seaport",
        can_receive_bulk_shipping=True,
        is_transfer_port=True,
        confirmation_status="confirmed",
    )
    rate_time = InlandWaterwayRateTimeRecord(
        region_code="pearl_river_delta",
        package_type="散粮",
        commodity_scope=("玉米",),
        unit_rate_yuan_per_ton=Decimal("9"),
        duration_hours=Decimal("5"),
        source_type="demo_placeholder",
        source="demo_placeholder:inland_barge_rate_time",
        rule_id="demo_placeholder_test",
        rule_version="0.1",
    )

    assert region.matches("广州客户码头")
    assert capability.matches(node_id="node-guangzhou", name="任意名称")
    assert capability.infrastructure_type == "seaport"
    assert capability.can_receive_bulk_shipping
    assert capability.transfer_port_role_confirmed
    assert capability.supports_order(make_request(commodity="小麦"))
    assert rate_time.supports_order(make_request(commodity="玉米"))
    assert not rate_time.supports_order(make_request(commodity="小麦"))


def make_request(*, commodity: str = "小麦") -> RouteRequest:
    return RouteRequest(
        quantity=Decimal("2450"),
        quantity_unit="吨",
        package_type="散粮",
        commodity=commodity,
    )
