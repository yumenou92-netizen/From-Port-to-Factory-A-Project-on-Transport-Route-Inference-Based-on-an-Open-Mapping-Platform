from decimal import Decimal

from src.domain.route_request import RouteRequest
from src.routing.formal_inland_waterway_provider import (
    TableInlandWaterwayBargeProvider,
)
from src.routing.inland_waterway_freight_provider import (
    InlandWaterwayFreightRecord,
)
from src.routing.inland_waterway_provider import (
    InlandWaterwayTimeRecord,
    PortCapabilityRecord,
    RegionMappingRecord,
)


def test_confirmed_fujian_minjiang_rule_builds_real_barge_edge():
    provider = make_provider()

    result = provider.build_barge_edge(
        origin_node_id="node-nanping",
        origin_name="南平港",
        destination_node_id="node-military",
        destination_name="军航码头",
        request=RouteRequest(Decimal("2450"), "吨", "散粮", "玉米"),
    )
    reverse = provider.build_barge_edge(
        origin_node_id="node-military",
        origin_name="军航码头",
        destination_node_id="node-nanping",
        destination_name="南平港",
        request=RouteRequest(Decimal("2450"), "吨", "散粮", "小麦"),
    )

    assert result.status == "generated"
    assert result.edge is not None
    assert result.edge.transport_mode == "驳船"
    assert result.edge.transport_stage == "south_to_customer"
    assert result.edge.edge_role == "transfer"
    assert result.edge.cost_yuan == Decimal("122500")
    assert result.edge.time_hours == Decimal("15")
    assert result.edge.time_scope == "complete_segment"
    assert result.edge.cost_rule_id == "fujian_minjiang_barge_freight"
    assert result.edge.cost_components[0].source_type == "real_data"
    assert "demo_placeholder" not in result.message
    assert reverse.status == "generated"
    assert reverse.edge is not None
    assert reverse.edge.cost_yuan == Decimal("122500")
    assert reverse.edge.time_hours == Decimal("15")


def test_formal_barge_provider_lists_capability_backed_destinations():
    provider = make_provider()

    candidates = provider.list_destination_candidates(
        origin_node_id="node-military",
        origin_name="军航码头",
        request=RouteRequest(Decimal("2450"), "吨", "散粮", "玉米"),
    )

    assert [(item.node_id, item.canonical_name) for item in candidates] == [
        ("node-nanping", "南平港")
    ]


def test_formal_barge_provider_requires_transfer_port_role_for_transfer_destination():
    provider = make_provider(nanping_is_transfer_port=None)
    request = RouteRequest(Decimal("2450"), "吨", "散粮", "玉米")

    candidates = provider.list_destination_candidates(
        origin_node_id="node-military",
        origin_name="军航码头",
        request=request,
    )
    result = provider.build_barge_edge(
        origin_node_id="node-military",
        origin_name="军航码头",
        destination_node_id="node-nanping",
        destination_name="南平港",
        request=request,
    )

    assert candidates == ()
    assert result.status == "manual_review"
    assert result.edge is None
    assert "中转港功能角色" in result.message


def test_formal_barge_provider_does_not_infer_missing_endpoint_capability():
    provider = TableInlandWaterwayBargeProvider(
        port_capabilities=(),
        region_mappings=make_region_mappings(),
        freight_records=make_freight_records(),
        time_records=make_time_records(),
    )

    result = provider.build_barge_edge(
        origin_node_id="node-nanping",
        origin_name="南平港",
        destination_node_id="node-military",
        destination_name="军航码头",
        request=RouteRequest(Decimal("500"), "吨", "散粮", "玉米"),
    )

    assert result.status == "manual_review"
    assert result.edge is None
    assert "能力" in result.message


def make_provider(
    *,
    nanping_is_transfer_port: bool | None = True,
) -> TableInlandWaterwayBargeProvider:
    return TableInlandWaterwayBargeProvider(
        port_capabilities=(
            PortCapabilityRecord(
                node_id="node-nanping",
                canonical_name="南平港",
                region_code="fujian_minjiang",
                can_handle_barge=True,
                supported_package_types=("散粮", "集装箱"),
                supported_commodities=("玉米", "小麦"),
                source="confirmed_port_capability#nanping",
                infrastructure_type="inland_port",
                can_receive_bulk_shipping=False,
                is_transfer_port=nanping_is_transfer_port,
                supported_transport_modes=("驳船", "铁路"),
                confirmation_status="confirmed",
            ),
            PortCapabilityRecord(
                node_id="node-military",
                canonical_name="军航码头",
                region_code="fujian_minjiang",
                can_handle_barge=True,
                supported_package_types=("散粮",),
                supported_commodities=("玉米", "小麦"),
                source="confirmed_port_capability#military",
                infrastructure_type="sea_river_integrated_port",
                can_receive_bulk_shipping=True,
                is_transfer_port=True,
                supported_transport_modes=("散船", "驳船"),
                confirmation_status="confirmed",
            ),
        ),
        region_mappings=make_region_mappings(),
        freight_records=make_freight_records(),
        time_records=make_time_records(),
    )


def make_region_mappings() -> tuple[RegionMappingRecord, ...]:
    return (
        RegionMappingRecord(
            region_code="fujian_minjiang",
            region_name="福建闽江内河",
            city_keywords=("南平港", "军航码头"),
            port_keywords=("南平港", "军航码头"),
            source="business_confirmation_2026-07-29",
            bulk_rate_destination_group="马尾",
            bulk_time_region="福建",
        ),
    )


def make_freight_records() -> tuple[InlandWaterwayFreightRecord, ...]:
    return (
        InlandWaterwayFreightRecord(
            origin_region_code="fujian_minjiang",
            destination_region_code="fujian_minjiang",
            package_type="散粮",
            commodity_scope=("玉米", "小麦"),
            unit_price_yuan_per_ton=Decimal("50"),
            fee_unit="元/吨",
            trade_type="内贸",
            bidirectional=True,
            source_type="real_data",
            source="business_confirmation_2026-07-28",
            rule_id="fujian_minjiang_barge_freight",
            rule_version="1.0",
            maintained_at="2026-07-28",
        ),
    )


def make_time_records() -> tuple[InlandWaterwayTimeRecord, ...]:
    return (
        InlandWaterwayTimeRecord(
            origin_region_code="fujian_minjiang",
            destination_region_code="fujian_minjiang",
            duration_value=Decimal("15"),
            duration_unit="小时",
            time_scope="complete_segment",
            bidirectional=True,
            source_type="real_data",
            source="business_confirmation_2026-07-28",
            rule_id="fujian_minjiang_barge_complete_time",
            rule_version="1.0",
            maintained_at="2026-07-28",
        ),
    )
