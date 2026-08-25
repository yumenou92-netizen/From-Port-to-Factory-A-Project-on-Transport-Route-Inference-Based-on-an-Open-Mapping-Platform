from datetime import date
from decimal import Decimal

from src.domain.freight_rate import create_freight_rate
from src.domain.route_request import RouteRequest
from src.routing.formal_inland_waterway_provider import (
    ExactOdInlandWaterwayBargeProvider,
)
from src.routing.inland_waterway_provider import (
    InlandWaterwayTimeRecord,
    PortCapabilityRecord,
)


def test_exact_od_provider_builds_real_rate_times_quantity_edge():
    provider = make_provider((make_rate(Decimal("17.9"), row=10),))
    request = RouteRequest(
        Decimal("2450"),
        "吨",
        "散粮",
        "玉米",
        trade_type="内贸",
    )

    candidates = provider.list_destination_candidates(
        origin_node_id="node-origin",
        origin_name="广州新港",
        request=request,
    )
    result = provider.build_barge_edge(
        origin_node_id="node-origin",
        origin_name="广州新港",
        destination_node_id="node-transfer",
        destination_name="贵港白沙码头",
        request=request,
    )

    assert [item.node_id for item in candidates] == ["node-transfer"]
    assert result.status == "generated"
    assert result.edge is not None
    assert result.edge.cost_yuan == Decimal("43855.0")
    assert result.edge.time_hours == Decimal("120")
    assert result.edge.raw_price == Decimal("17.9")
    assert result.edge.raw_price_unit == "元/吨"
    assert result.edge.transport_stage == "south_to_customer"
    assert result.edge.edge_role == "transfer"
    assert result.edge.cost_components[0].source_type == "real_data"
    assert "运价表.json#10" in result.edge.cost_components[0].source


def test_exact_od_conflict_is_listed_for_review_and_never_auto_selected():
    provider = make_provider(
        (
            make_rate(Decimal("17.9"), row=10),
            make_rate(Decimal("18.5"), row=11),
        )
    )
    request = RouteRequest(
        Decimal("500"),
        "吨",
        "散粮",
        "玉米",
        trade_type="内贸",
    )

    candidates = provider.list_destination_candidates(
        origin_node_id="node-origin",
        origin_name="广州新港",
        request=request,
    )
    result = provider.build_barge_edge(
        origin_node_id="node-origin",
        origin_name="广州新港",
        destination_node_id="node-transfer",
        destination_name="贵港白沙码头",
        request=request,
    )

    assert [item.node_id for item in candidates] == ["node-transfer"]
    assert result.status == "manual_review"
    assert result.edge is None
    assert "冲突报价" in result.message
    assert "不以区域费率覆盖" in result.message


def test_exact_od_provider_allows_customer_delivery_without_transfer_role():
    customer_capability = capability(
        "node-customer",
        "客户工厂",
        "pearl_river_delta",
        infrastructure_type="customer_barge_receiver",
        is_transfer_port=False,
    )
    rate = create_freight_rate(
        origin_name="广州新港",
        destination_name="客户工厂",
        transport_mode="驳船",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price=Decimal("8"),
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="真实业务运价",
        maintained_at=date(2026, 7, 31),
        from_node_id="node-origin",
        to_node_id="node-customer",
        source_file="运价表.json",
        source_row_number=20,
    )
    provider = ExactOdInlandWaterwayBargeProvider(
        port_capabilities=(
            capability(
                "node-origin",
                "广州新港",
                "pearl_river_delta",
                infrastructure_type="sea_river_integrated_port",
                is_transfer_port=False,
            ),
            customer_capability,
        ),
        exact_od_rates=(rate,),
        time_records=(
            time_record(
                "pearl_river_delta",
                "pearl_river_delta",
                Decimal("1.5"),
            ),
        ),
    )

    result = provider.build_barge_edge(
        origin_node_id="node-origin",
        origin_name="广州新港",
        destination_node_id="node-customer",
        destination_name="客户工厂",
        request=RouteRequest(
            Decimal("500"),
            "吨",
            "散粮",
            "玉米",
            trade_type="内贸",
        ),
        edge_role="delivery",
    )

    assert result.status == "generated"
    assert result.edge is not None
    assert result.edge.edge_role == "delivery"
    assert result.edge.cost_yuan == Decimal("4000")


def test_applicable_origin_ids_require_a_buildable_exact_od_edge():
    request = RouteRequest(
        Decimal("500"),
        "吨",
        "散粮",
        "玉米",
        trade_type="内贸",
    )
    missing_time_provider = ExactOdInlandWaterwayBargeProvider(
        port_capabilities=(
            capability(
                "node-origin",
                "广州新港",
                "pearl_river_delta",
                infrastructure_type="sea_river_integrated_port",
                is_transfer_port=False,
            ),
            capability(
                "node-transfer",
                "贵港白沙码头",
                "guigang",
                infrastructure_type="inland_port",
                is_transfer_port=True,
            ),
        ),
        exact_od_rates=(make_rate(Decimal("17.9"), row=10),),
        time_records=(),
    )

    assert missing_time_provider.applicable_origin_node_ids(request) == frozenset()
    assert make_provider(
        (make_rate(Decimal("17.9"), row=10),)
    ).applicable_origin_node_ids(request) == frozenset({"node-origin"})


def make_provider(rates):
    return ExactOdInlandWaterwayBargeProvider(
        port_capabilities=(
            capability(
                "node-origin",
                "广州新港",
                "pearl_river_delta",
                infrastructure_type="sea_river_integrated_port",
                is_transfer_port=False,
            ),
            capability(
                "node-transfer",
                "贵港白沙码头",
                "guigang",
                infrastructure_type="inland_port",
                is_transfer_port=True,
            ),
        ),
        exact_od_rates=rates,
        time_records=(
            time_record(
                "pearl_river_delta",
                "guigang",
                Decimal("5"),
            ),
        ),
    )


def make_rate(price, *, row):
    return create_freight_rate(
        origin_name="广州新港",
        destination_name="贵港白沙码头",
        transport_mode="驳船",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price=price,
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="2026驳船集采",
        maintained_at=date(2026, 4, 15),
        from_node_id="node-origin",
        to_node_id="node-transfer",
        source_file="运价表.json",
        source_row_number=row,
    )


def capability(
    node_id,
    name,
    region_code,
    *,
    infrastructure_type,
    is_transfer_port,
):
    return PortCapabilityRecord(
        node_id=node_id,
        canonical_name=name,
        region_code=region_code,
        can_handle_barge=True,
        supported_package_types=("散粮",),
        supported_commodities=("玉米", "小麦"),
        source=f"节点能力#{name}",
        infrastructure_type=infrastructure_type,
        can_receive_bulk_shipping=(
            infrastructure_type == "sea_river_integrated_port"
        ),
        is_transfer_port=is_transfer_port,
        supported_transport_modes=("驳船",),
        confirmation_status="confirmed",
    )


def time_record(origin_region, destination_region, days):
    return InlandWaterwayTimeRecord(
        origin_region_code=origin_region,
        destination_region_code=destination_region,
        duration_value=days,
        duration_unit="天",
        time_scope="complete_segment",
        bidirectional=True,
        source_type="real_data",
        source="business_confirmation",
        rule_id="barge_complete_time",
        rule_version="1.0",
    )
