from src.data.loaders import NodeRecord
from src.domain.node_registry import build_node_registry
from src.routing.bulk_shipping_time_mapper import (
    NearestRegionalBulkShippingTimeResolver,
)
from src.routing.inland_waterway_provider import PortCapabilityRecord
from src.routing.port_region_resolver import RuleBasedPortRegionResolver


def test_nearest_time_proxy_requires_confirmed_bulk_shipping_capability():
    registry = build_node_registry(
        (
            NodeRecord("", "测试海南东方港", 109.21, 19.74),
            NodeRecord("", "马村港", 110.03, 19.96),
        ),
        auto_alias=False,
    )
    target = registry.require("测试海南东方港")
    resolver = NearestRegionalBulkShippingTimeResolver(
        registry=registry,
        region_resolver=HainanRegionResolver(),
        port_capabilities=(),
    )

    result = resolver.resolve(
        port_name="测试海南东方港",
        port_node_id=target.node_id,
    )

    assert result.status == "manual_review"
    assert "可接收北港散船" in result.message


def test_confirmed_bulk_shipping_port_uses_nearest_same_region_time_reference():
    registry = build_node_registry(
        (
            NodeRecord("", "测试海南东方港", 109.21, 19.74),
            NodeRecord("", "马村港", 110.03, 19.96),
        ),
        auto_alias=False,
    )
    target = registry.require("测试海南东方港")
    resolver = NearestRegionalBulkShippingTimeResolver(
        registry=registry,
        region_resolver=HainanRegionResolver(),
        port_capabilities=(
            PortCapabilityRecord(
                node_id=target.node_id,
                canonical_name="测试海南东方港",
                region_code="hainan",
                can_handle_barge=False,
                supported_package_types=("散粮",),
                supported_commodities=("*",),
                source="confirmed_port_capability",
                infrastructure_type="seaport",
                can_receive_bulk_shipping=True,
                supported_transport_modes=("散船",),
                confirmation_status="confirmed",
            ),
        ),
    )

    result = resolver.resolve(
        port_name="测试海南东方港",
        port_node_id=target.node_id,
    )

    assert result.status == "resolved"
    assert result.source_type == "regional_proxy"
    assert result.shipping_time_region == "海南"
    assert result.duration_hours == 168
    assert result.reference_port_name == "马村港"
    assert "仅代理航时" in result.message


class HainanRegionResolver(RuleBasedPortRegionResolver):
    def resolve(self, *names):
        from src.routing.port_region_resolver import PortRegionResolution

        return PortRegionResolution(
            status="resolved",
            region_code="hainan",
            source="test_hainan_mapping",
            mapping_basis="测试同属海南区域",
            message="测试解析到海南。",
        )
