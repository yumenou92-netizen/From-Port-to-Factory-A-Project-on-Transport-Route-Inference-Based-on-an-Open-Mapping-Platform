from decimal import Decimal

from src.domain.cost_rules import calculate_rail_container_delivery_truck_unit_price
from src.domain.route_request import RouteRequest
from src.routing.rail_customer_delivery_provider import (
    CustomerDedicatedSidingRecord,
    DirectTruckDeliveryRecord,
    RailCustomerDeliveryProvider,
    RailTerminalScope,
    ThirdPartyDedicatedSidingRecord,
)


def scope(container_type="敞顶箱"):
    return RailTerminalScope(
        commodity_scope=("玉米", "小麦"),
        trade_type="内贸",
        container_type=container_type,
        source="test_fixture:rail-terminal",
        source_type="demo_placeholder",
    )


def request():
    return RouteRequest(2, "箱", "集装箱", "玉米", trade_type="内贸")


def test_direct_truck_uses_rail_terminal_formula_without_overriding_general_container_truck_rule():
    provider = RailCustomerDeliveryProvider(
        direct_truck_records=(
            DirectTruckDeliveryRecord(
                "南站A", "south-a", "客户A", "customer-a", scope(), Decimal("30"),
                "tencent_map_driving_route", Decimal("2"), "tencent_map_driving_route",
            ),
        ),
    )

    result = provider.build_direct_truck(
        south_station_name="南站A", customer_name="客户A", request=request(), container_type="敞顶箱"
    )

    assert result.status == "resolved"
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.transport_mode == "汽运"
    assert edge.edge_role == "delivery"
    assert edge.cost_yuan == Decimal("1360")
    assert edge.cost_rule_id == "rail_container_delivery_truck_distance"
    assert edge.distance_km == Decimal("30")
    assert edge.data_source.startswith("demo_placeholder:")
    assert calculate_rail_container_delivery_truck_unit_price(Decimal("10")) == Decimal("450")
    assert calculate_rail_container_delivery_truck_unit_price(Decimal("20")) == Decimal("500")


def test_customer_dedicated_siding_forms_one_rail_delivery_edge():
    provider = RailCustomerDeliveryProvider(
        customer_dedicated_siding_records=(
            CustomerDedicatedSidingRecord(
                "南站A", "south-a", "客户A", "customer-a", scope("顶开门箱"), Decimal("180"), Decimal("4"), "maintained:customer-siding",
            ),
        ),
    )

    result = provider.build_customer_dedicated_siding(
        south_station_name="南站A", customer_name="客户A", request=request(), container_type="顶开门箱"
    )

    assert result.status == "resolved"
    assert len(result.edges) == 1
    assert result.edges[0].transport_mode == "铁路"
    assert result.edges[0].edge_role == "delivery"
    assert result.edges[0].cost_yuan == Decimal("360")


def test_third_party_dedicated_siding_keeps_transfer_and_delivery_as_two_edges():
    provider = RailCustomerDeliveryProvider(
        third_party_dedicated_siding_records=(
            ThirdPartyDedicatedSidingRecord(
                "南站A", "south-a", "第三方专用线", "third-party-a", "客户A", "customer-a", scope(),
                Decimal("160"), Decimal("3"), "maintained:third-party-rail",
                "汽运", Decimal("80"), Decimal("1"), "maintained:third-party-delivery",
            ),
        ),
    )

    result = provider.build_third_party_dedicated_siding(
        south_station_name="南站A", customer_name="客户A", request=request(), container_type="敞顶箱"
    )

    assert result.status == "resolved"
    assert [edge.edge_role for edge in result.edges] == ["transfer", "delivery"]
    assert [edge.transport_mode for edge in result.edges] == ["铁路", "汽运"]
    assert [edge.cost_yuan for edge in result.edges] == [Decimal("320"), Decimal("160")]
    assert all(edge.transport_stage == "south_to_customer" for edge in result.edges)


def test_missing_or_non_box_terminal_record_does_not_build_an_edge():
    provider = RailCustomerDeliveryProvider()
    missing = provider.build_direct_truck(
        south_station_name="南站A", customer_name="客户A", request=request(), container_type="敞顶箱"
    )
    wrong_unit = RailCustomerDeliveryProvider().build_direct_truck(
        south_station_name="南站A",
        customer_name="客户A",
        request=RouteRequest(1, "柜", "集装箱", "玉米", trade_type="内贸"),
        container_type="敞顶箱",
    )

    assert missing.status == "manual_review"
    assert not missing.edges
    assert wrong_unit.status == "not_applicable"
