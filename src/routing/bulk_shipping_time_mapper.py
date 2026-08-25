from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.domain.node_registry import NodeRegistry
from src.routing.bulk_shipping_provider import (
    REGION_DAYS,
    classify_bulk_shipping_destination,
)
from src.routing.inland_waterway_provider import PortCapabilityRecord
from src.routing.port_region_resolver import PortRegionResolver


@dataclass(frozen=True)
class BulkShippingTimeMapping:
    status: str
    message: str
    shipping_time_region: str | None = None
    duration_hours: Decimal | None = None
    source_type: str | None = None
    reference_port_node_id: str | None = None
    reference_port_name: str | None = None
    distance_km: Decimal | None = None

    @property
    def is_resolved(self) -> bool:
        return (
            self.status == "resolved"
            and self.shipping_time_region is not None
            and self.duration_hours is not None
        )


class NearestRegionalBulkShippingTimeResolver:
    """Fill a missing bulk-shipping time only for confirmed sea-capable ports.

    A nearest-port time proxy supplies time, not physical connectivity and not
    a bulk freight destination group. This prevents an inland port from being
    turned into a north-to-south sea-shipping endpoint merely because it is
    geographically close to a seaport.
    """

    def __init__(
        self,
        *,
        registry: NodeRegistry,
        region_resolver: PortRegionResolver,
        port_capabilities: Sequence[PortCapabilityRecord],
    ) -> None:
        self.registry = registry
        self.region_resolver = region_resolver
        self.port_capabilities = tuple(port_capabilities)

    def resolve(
        self,
        *,
        port_name: str,
        port_node_id: str,
    ) -> BulkShippingTimeMapping:
        _, direct_region = classify_bulk_shipping_destination(port_name)
        if direct_region is not None:
            return BulkShippingTimeMapping(
                status="resolved",
                shipping_time_region=direct_region,
                duration_hours=REGION_DAYS[direct_region] * Decimal("24"),
                source_type="confirmed_rule",
                message=f"港口 {port_name} 已命中精确航运总时效分区 {direct_region}。",
            )

        target_node = self.registry.nodes.get(port_node_id)
        if target_node is None:
            return BulkShippingTimeMapping(
                status="manual_review",
                message=f"港口 {port_name} 缺少标准节点坐标，不能执行最近航时代理。",
            )
        capabilities = [
            record
            for record in self.port_capabilities
            if record.matches(node_id=port_node_id, name=port_name)
            and record.confirmation_status == "confirmed"
            and record.can_receive_bulk_shipping is True
        ]
        if len(capabilities) != 1:
            return BulkShippingTimeMapping(
                status="manual_review",
                message=(
                    f"港口 {port_name} 尚未由港口能力表唯一确认可接收北港散船；"
                    "不得用最近航时代理推断海运连通性。"
                ),
            )
        target_region = self.region_resolver.resolve(
            target_node.canonical_name,
            port_name,
            *target_node.aliases,
        )
        if not target_region.is_resolved:
            return BulkShippingTimeMapping(
                status="manual_review",
                message=(
                    f"港口 {port_name} 无法安全确定所在区域："
                    f"{target_region.message}"
                ),
            )

        references: list[tuple[Decimal, str, str, str]] = []
        for node in self.registry.nodes.values():
            _, reference_time_region = classify_bulk_shipping_destination(
                node.canonical_name
            )
            if reference_time_region is None:
                continue
            reference_region = self.region_resolver.resolve(
                node.canonical_name,
                *node.aliases,
            )
            if (
                not reference_region.is_resolved
                or reference_region.region_code != target_region.region_code
            ):
                continue
            references.append(
                (
                    _haversine_km(
                        target_node.longitude,
                        target_node.latitude,
                        node.longitude,
                        node.latitude,
                    ),
                    node.node_id,
                    node.canonical_name,
                    reference_time_region,
                )
            )
        if not references:
            return BulkShippingTimeMapping(
                status="manual_review",
                message=(
                    f"区域 {target_region.region_code} 内没有具备坐标的已确认航时参考港。"
                ),
            )
        distance_km, reference_node_id, reference_name, time_region = sorted(
            references,
            key=lambda item: (item[0], item[1], item[2]),
        )[0]
        return BulkShippingTimeMapping(
            status="resolved",
            shipping_time_region=time_region,
            duration_hours=REGION_DAYS[time_region] * Decimal("24"),
            source_type="regional_proxy",
            reference_port_node_id=reference_node_id,
            reference_port_name=reference_name,
            distance_km=distance_km,
            message=(
                f"港口 {port_name} 已由能力表确认可接收北港散船；"
                f"采用同区域最近参考港 {reference_name} 的航运总时效分区 "
                f"{time_region}，距离={distance_km}公里。"
                "该结果仅代理航时，不代理运价目的组或港口连通性。"
            ),
        )


def _haversine_km(
    origin_longitude: float,
    origin_latitude: float,
    destination_longitude: float,
    destination_latitude: float,
) -> Decimal:
    radius_km = 6371.0088
    origin_latitude_rad = math.radians(origin_latitude)
    destination_latitude_rad = math.radians(destination_latitude)
    latitude_delta = math.radians(destination_latitude - origin_latitude)
    longitude_delta = math.radians(destination_longitude - origin_longitude)
    a = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(origin_latitude_rad)
        * math.cos(destination_latitude_rad)
        * math.sin(longitude_delta / 2) ** 2
    )
    distance = radius_km * 2 * math.asin(min(1.0, math.sqrt(a)))
    return Decimal(str(distance)).quantize(Decimal("0.01"))
