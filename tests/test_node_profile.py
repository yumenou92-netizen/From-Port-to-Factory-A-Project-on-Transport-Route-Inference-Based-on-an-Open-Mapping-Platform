from datetime import date

import pytest

from src.domain.node_profile import NodeProfile, NodeProfileError


def test_bulk_shipping_port_requires_seaport_and_explicit_capability():
    profile = NodeProfile(
        node_id="node-south-port-demo",
        infrastructure_type="seaport",
        capabilities=("散船", "散粮", "散船"),
        source="sanitized_node_profile.csv#row=2",
        province="广东省",
        city="广州市",
        port_area="广州",
        shipping_time_region="珠三角",
        maintained_at=date(2026, 7, 22),
    )

    assert profile.is_bulk_shipping_port
    assert profile.capabilities == ("散粮", "散船")
    assert profile.standard_location_label == "广州"


def test_inland_port_is_not_silently_treated_as_bulk_shipping_seaport():
    profile = NodeProfile(
        node_id="node-inland-port-demo",
        infrastructure_type="inland_port",
        capabilities=("散船",),
        source="sanitized_node_profile.csv#row=3",
        city="南宁市",
    )

    assert not profile.is_bulk_shipping_port
    assert profile.standard_location_label == "南宁市"


def test_node_profile_rejects_unknown_infrastructure_type_and_missing_source():
    with pytest.raises(NodeProfileError, match="不支持的基础设施类型"):
        NodeProfile(
            node_id="node-demo",
            infrastructure_type="dock",
            capabilities=(),
            source="test",
        )

    with pytest.raises(NodeProfileError, match="节点画像来源"):
        NodeProfile(
            node_id="node-demo",
            infrastructure_type="seaport",
            capabilities=("散粮",),
            source="",
        )


def test_node_profile_rejects_unconfirmed_shipping_time_region():
    with pytest.raises(NodeProfileError, match="不支持的纯航行时效分区"):
        NodeProfile(
            node_id="node-demo",
            infrastructure_type="seaport",
            capabilities=("散粮",),
            source="test",
            shipping_time_region="华南",
        )


def test_route_relevant_capabilities_require_explicit_confirmation():
    unknown_profile = NodeProfile(
        node_id="node-port-unknown",
        infrastructure_type="seaport",
        capabilities=(),
        source="port_capability.csv#row=2",
    )

    assert unknown_profile.supported_package_types is None
    assert unknown_profile.supported_commodities is None
    assert unknown_profile.supported_transport_modes is None
    assert not unknown_profile.capability_data_confirmed

    confirmed_profile = NodeProfile(
        node_id="node-port-confirmed",
        infrastructure_type="seaport",
        capabilities=("散粮",),
        source="manual_confirmed:2026-07-24",
        region_code="fujian_zhangzhou",
        city="漳州市",
        shipping_time_region="福建",
        supported_package_types=("散粮",),
        supported_commodities=("玉米", "小麦"),
        supported_transport_modes=("散船", "驳船", "汽运"),
        confirmation_status="confirmed",
    )

    assert confirmed_profile.capability_data_confirmed
    assert confirmed_profile.region_code == "fujian_zhangzhou"


def test_empty_supported_values_are_explicitly_confirmed_empty_not_unknown():
    profile = NodeProfile(
        node_id="node-factory",
        infrastructure_type="factory",
        capabilities=(),
        source="manual_confirmed:2026-07-24",
        supported_package_types=(),
        supported_commodities=(),
        supported_transport_modes=(),
        confirmation_status="confirmed",
    )

    assert profile.capability_data_confirmed
    assert profile.supported_transport_modes == ()
