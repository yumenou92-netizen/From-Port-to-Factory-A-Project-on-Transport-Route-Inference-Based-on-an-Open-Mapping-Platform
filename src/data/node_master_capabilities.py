from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Sequence

from src.data.node_master_maintenance import NodeMasterMaintenanceEntry
from src.domain.freight_rate import FreightRate
from src.domain.node_registry import NodeRegistry, StandardNode
from src.routing.inland_waterway_provider import (
    PortCapabilityRecord,
    RegionMappingRecord,
)


RegionAssignmentMethod = Literal["exact_mapping", "nearest_region_proxy"]


class NodeMasterCapabilityError(ValueError):
    """Raised when source-backed barge capability inference is ambiguous."""


@dataclass(frozen=True)
class ConfirmedRateOnlyEndpoint:
    canonical_name: str
    aliases: tuple[str, ...]
    region_code: str
    infrastructure_type: str
    can_receive_bulk_shipping: bool
    is_transfer_port: bool
    supported_transport_modes: tuple[str, ...]
    source: str

    @property
    def all_names(self) -> tuple[str, ...]:
        return (self.canonical_name, *self.aliases)


CONFIRMED_RATE_ONLY_ENDPOINTS = (
    ConfirmedRateOnlyEndpoint(
        canonical_name="东莞粤储粮港务有限公司",
        aliases=("东莞粤储粮",),
        region_code="pearl_river_delta",
        infrastructure_type="sea_river_integrated_port",
        can_receive_bulk_shipping=True,
        is_transfer_port=False,
        supported_transport_modes=("散船", "驳船"),
        source=(
            "business_confirmation_2026-07-31:"
            "exact_barge_rate_proves_scoped_capability"
        ),
    ),
    ConfirmedRateOnlyEndpoint(
        canonical_name="南宁港牛湾作业区",
        aliases=(),
        region_code="nanning",
        infrastructure_type="inland_port",
        can_receive_bulk_shipping=False,
        is_transfer_port=True,
        supported_transport_modes=("驳船",),
        source=(
            "business_confirmation_2026-07-31:"
            "exact_barge_rate_proves_scoped_capability"
        ),
    ),
)


@dataclass(frozen=True)
class NodeRegionAssignment:
    node_id: str
    canonical_name: str
    region_code: str
    method: RegionAssignmentMethod
    source: str
    anchor_node_id: str | None = None
    anchor_name: str | None = None
    distance_km: float | None = None


@dataclass(frozen=True)
class NodeMasterCapabilityBuildResult:
    capabilities: tuple[PortCapabilityRecord, ...]
    region_assignments: tuple[NodeRegionAssignment, ...]
    unresolved_node_names: tuple[str, ...]
    ignored_non_barge_rate_count: int
    unresolved_rate_endpoint_count: int

    @property
    def exact_region_assignment_count(self) -> int:
        return sum(
            assignment.method == "exact_mapping"
            for assignment in self.region_assignments
        )

    @property
    def nearest_region_assignment_count(self) -> int:
        return sum(
            assignment.method == "nearest_region_proxy"
            for assignment in self.region_assignments
        )


@dataclass
class _EndpointEvidence:
    rates: list[FreightRate]
    appears_as_origin: bool = False
    appears_as_destination: bool = False


def build_barge_capabilities_from_node_master(
    *,
    node_master_entries: Sequence[NodeMasterMaintenanceEntry],
    freight_rates: Sequence[FreightRate],
    registry: NodeRegistry,
    region_mappings: Sequence[RegionMappingRecord],
) -> NodeMasterCapabilityBuildResult:
    """Build source-backed barge capabilities without writing formal CSVs.

    An exact barge rate is treated as evidence that both OD endpoints can handle
    the rate's packaging and commodities. Physical port roles still come from
    the maintained node master: a transfer port must be a logistics node with an
    inland-waterway attribute, while a sea-only port cannot become a transfer
    node merely because a rate exists.
    """

    evidence_by_node_id: dict[str, _EndpointEvidence] = {}
    unresolved_rate_endpoint_count = 0
    ignored_non_barge_rate_count = 0
    for rate in freight_rates:
        if not is_barge_rate(rate):
            ignored_non_barge_rate_count += 1
            continue
        if rate.from_node_id is None or rate.to_node_id is None:
            unresolved_rate_endpoint_count += 1
            continue
        origin = evidence_by_node_id.setdefault(
            rate.from_node_id, _EndpointEvidence([])
        )
        origin.rates.append(rate)
        origin.appears_as_origin = True
        destination = evidence_by_node_id.setdefault(
            rate.to_node_id, _EndpointEvidence([])
        )
        destination.rates.append(rate)
        destination.appears_as_destination = True

    entry_by_node_id = _index_master_entries(
        node_master_entries=node_master_entries,
        registry=registry,
    )
    rate_only_overrides: dict[str, ConfirmedRateOnlyEndpoint] = {}
    direct_assignments: dict[str, NodeRegionAssignment] = {}
    direct_anchors: list[
        tuple[str, NodeMasterMaintenanceEntry, NodeRegionAssignment]
    ] = []
    unresolved_node_names: list[str] = []

    for node_id in evidence_by_node_id:
        node = registry.nodes.get(node_id)
        entry = entry_by_node_id.get(node_id)
        if node is None or entry is None:
            if node is not None:
                unresolved_node_names.append(node.canonical_name)
            continue
        matches = [
            mapping
            for mapping in region_mappings
            if mapping.matches(entry.location_text)
        ]
        if len(matches) > 1:
            codes = "、".join(
                sorted(mapping.region_code for mapping in matches)
            )
            raise NodeMasterCapabilityError(
                f"节点 {node.canonical_name} 同时匹配多个内河时效区域：{codes}"
            )
        if not matches:
            continue
        mapping = matches[0]
        assignment = NodeRegionAssignment(
            node_id=node_id,
            canonical_name=node.canonical_name,
            region_code=mapping.region_code,
            method="exact_mapping",
            source=f"{entry.source};{mapping.source}",
        )
        direct_assignments[node_id] = assignment
        direct_anchors.append((node_id, entry, assignment))

    assignments = dict(direct_assignments)
    for node_id in evidence_by_node_id:
        if node_id in assignments:
            continue
        node = registry.nodes.get(node_id)
        entry = entry_by_node_id.get(node_id)
        if node is None or entry is None:
            continue
        if not direct_anchors:
            unresolved_node_names.append(node.canonical_name)
            continue
        anchor_node_id, anchor_entry, anchor_assignment = min(
            direct_anchors,
            key=lambda item: _haversine_km(
                entry.latitude,
                entry.longitude,
                item[1].latitude,
                item[1].longitude,
            ),
        )
        distance_km = _haversine_km(
            entry.latitude,
            entry.longitude,
            anchor_entry.latitude,
            anchor_entry.longitude,
        )
        assignments[node_id] = NodeRegionAssignment(
            node_id=node_id,
            canonical_name=node.canonical_name,
            region_code=anchor_assignment.region_code,
            method="nearest_region_proxy",
            source=(
                f"business_confirmation_2026-07-31:nearest_region;"
                f"node={entry.source};anchor={anchor_assignment.source}"
            ),
            anchor_node_id=anchor_node_id,
            anchor_name=anchor_assignment.canonical_name,
            distance_km=round(distance_km, 3),
        )

    available_region_codes = {
        mapping.region_code for mapping in region_mappings
    }
    for node_id, evidence in evidence_by_node_id.items():
        if node_id in entry_by_node_id:
            continue
        node = registry.nodes.get(node_id)
        if node is None:
            continue
        override = _match_rate_only_override(node)
        if override is None:
            continue
        if override.region_code not in available_region_codes:
            raise NodeMasterCapabilityError(
                f"节点 {node.canonical_name} 的已确认能力覆盖要求区域 "
                f"{override.region_code}，但区域映射表未维护该区域。"
            )
        rate_only_overrides[node_id] = override
        evidence_source = _rate_evidence_source(evidence)
        assignments[node_id] = NodeRegionAssignment(
            node_id=node_id,
            canonical_name=node.canonical_name,
            region_code=override.region_code,
            method="exact_mapping",
            source=f"{override.source};{evidence_source}",
        )
        unresolved_node_names = [
            name
            for name in unresolved_node_names
            if name != node.canonical_name
        ]

    capabilities: list[PortCapabilityRecord] = []
    for node_id, evidence in evidence_by_node_id.items():
        node = registry.nodes.get(node_id)
        entry = entry_by_node_id.get(node_id)
        assignment = assignments.get(node_id)
        override = rate_only_overrides.get(node_id)
        if node is None or assignment is None:
            continue
        if entry is None:
            if override is None:
                continue
            packages = {
                rate.package_type for rate in evidence.rates
            }
            commodities = {
                commodity
                for rate in evidence.rates
                for commodity in _split_commodity_scope(
                    rate.commodity_scope
                )
            }
            capabilities.append(
                PortCapabilityRecord(
                    node_id=node_id,
                    canonical_name=node.canonical_name,
                    region_code=assignment.region_code,
                    can_handle_barge=True,
                    supported_package_types=tuple(sorted(packages)),
                    supported_commodities=tuple(
                        sorted(commodities)
                    ),
                    source=(
                        f"{override.source};"
                        f"{_rate_evidence_source(evidence)}"
                    ),
                    aliases=tuple(
                        sorted(
                            {
                                *node.aliases,
                                *override.all_names,
                            }
                            - {node.canonical_name}
                        )
                    ),
                    infrastructure_type=override.infrastructure_type,
                    can_receive_bulk_shipping=(
                        override.can_receive_bulk_shipping
                    ),
                    is_transfer_port=override.is_transfer_port,
                    supported_transport_modes=(
                        override.supported_transport_modes
                    ),
                    shipping_time_region=assignment.region_code,
                    confirmation_status="confirmed",
                    maintained_at="2026-07-31",
                )
            )
            continue
        packages = {
            package
            for package in entry.package_types
            if package in {"散粮", "集装箱"}
        }
        commodities: set[str] = set()
        for rate in evidence.rates:
            packages.add(rate.package_type)
            commodities.update(_split_commodity_scope(rate.commodity_scope))

        normalized_names = {
            _normalize_name(value) for value in entry.all_names
        }
        is_nanping = "南平港" in normalized_names
        is_junhang = any("军航码头" in value for value in normalized_names)
        has_seaport = entry.has_seaport_attribute or is_junhang
        has_inland = (
            entry.has_inland_port_attribute or is_nanping or is_junhang
        )
        has_rail = entry.has_rail_attribute or is_nanping
        if is_nanping:
            packages.update({"散粮", "集装箱"})
            commodities.update({"玉米", "小麦"})
        if is_junhang:
            packages.add("散粮")
            commodities.update({"玉米", "小麦"})

        can_receive_bulk_shipping = (
            entry.is_logistics_node
            and not entry.is_customer_node
            and has_seaport
            and "散粮" in packages
        )
        is_transfer_port = (
            entry.is_logistics_node
            and not entry.is_customer_node
            and has_inland
            and evidence.appears_as_destination
        )
        transport_modes = {"驳船"}
        if can_receive_bulk_shipping:
            transport_modes.add("散船")
        if has_rail:
            transport_modes.add("铁路")
        capability_source = _capability_source(
            entry=entry,
            evidence=evidence,
            assignment=assignment,
            special_confirmation=(
                "business_confirmation_2026-07-31:nanping"
                if is_nanping
                else (
                    "business_confirmation_2026-07-31:junhang"
                    if is_junhang
                    else None
                )
            ),
        )
        capabilities.append(
            PortCapabilityRecord(
                node_id=node_id,
                canonical_name=node.canonical_name,
                region_code=assignment.region_code,
                can_handle_barge=True,
                supported_package_types=tuple(sorted(packages)),
                supported_commodities=tuple(sorted(commodities)),
                source=capability_source,
                aliases=tuple(
                    sorted(
                        {
                            *node.aliases,
                            *entry.all_names,
                        }
                        - {node.canonical_name}
                    )
                ),
                infrastructure_type=_infrastructure_type(
                    entry=entry,
                    has_seaport=has_seaport,
                    has_inland=has_inland,
                ),
                can_receive_bulk_shipping=can_receive_bulk_shipping,
                is_transfer_port=is_transfer_port,
                supported_transport_modes=tuple(sorted(transport_modes)),
                city=entry.city,
                shipping_time_region=assignment.region_code,
                confirmation_status="confirmed",
                maintained_at="2026-07-31",
            )
        )

    return NodeMasterCapabilityBuildResult(
        capabilities=tuple(
            sorted(capabilities, key=lambda record: record.canonical_name)
        ),
        region_assignments=tuple(
            sorted(assignments.values(), key=lambda item: item.canonical_name)
        ),
        unresolved_node_names=tuple(sorted(set(unresolved_node_names))),
        ignored_non_barge_rate_count=ignored_non_barge_rate_count,
        unresolved_rate_endpoint_count=unresolved_rate_endpoint_count,
    )


def is_barge_rate(rate: FreightRate) -> bool:
    return "驳船" in re.sub(r"\s+", "", rate.transport_mode)


def _index_master_entries(
    *,
    node_master_entries: Sequence[NodeMasterMaintenanceEntry],
    registry: NodeRegistry,
) -> dict[str, NodeMasterMaintenanceEntry]:
    result: dict[str, NodeMasterMaintenanceEntry] = {}
    for entry in node_master_entries:
        node_ids = {
            node.node_id
            for name in entry.all_names
            if (node := registry.lookup(name)) is not None
        }
        if not node_ids:
            continue
        if len(node_ids) > 1:
            names = "、".join(entry.all_names)
            raise NodeMasterCapabilityError(
                f"{entry.source} 的名称指向多个标准节点：{names}"
            )
        node_id = next(iter(node_ids))
        previous = result.get(node_id)
        if previous is not None and previous.full_name != entry.full_name:
            if not _same_physical_location(previous, entry):
                raise NodeMasterCapabilityError(
                    f"{previous.source} 与 {entry.source} 指向同一标准节点，"
                    "但坐标不一致。"
                )
            continue
        result[node_id] = entry
    return result


def _same_physical_location(
    left: NodeMasterMaintenanceEntry,
    right: NodeMasterMaintenanceEntry,
) -> bool:
    return (
        math.isclose(left.longitude, right.longitude, abs_tol=1e-6)
        and math.isclose(left.latitude, right.latitude, abs_tol=1e-6)
    )


def _split_commodity_scope(value: str) -> set[str]:
    return {
        item.strip()
        for item in re.split(r"[,，、/；;]+", value)
        if item.strip()
    }


def _match_rate_only_override(
    node: StandardNode,
) -> ConfirmedRateOnlyEndpoint | None:
    node_names = {
        _normalize_name(value)
        for value in (
            node.canonical_name,
            *node.aliases,
        )
    }
    matches = [
        override
        for override in CONFIRMED_RATE_ONLY_ENDPOINTS
        if node_names
        & {
            _normalize_name(value)
            for value in override.all_names
        }
    ]
    if len(matches) > 1:
        raise NodeMasterCapabilityError(
            f"节点 {node.canonical_name} 同时匹配多个已确认能力覆盖。"
        )
    return matches[0] if matches else None


def _rate_evidence_source(evidence: _EndpointEvidence) -> str:
    sources = sorted(
        {
            (
                f"{rate.source_file or 'unknown_rate_source'}"
                f"#{rate.source_row_number or 'unknown_row'}"
            )
            for rate in evidence.rates
        }
    )
    return "exact_od_evidence=" + ",".join(sources)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _infrastructure_type(
    *,
    entry: NodeMasterMaintenanceEntry,
    has_seaport: bool,
    has_inland: bool,
) -> str:
    if entry.is_customer_node:
        return "customer_barge_receiver"
    if entry.is_logistics_node and has_seaport and has_inland:
        return "sea_river_integrated_port"
    if entry.is_logistics_node and has_inland:
        return "inland_port"
    if entry.is_logistics_node and has_seaport:
        return "sea_port"
    return "unknown_logistics_node"


def _capability_source(
    *,
    entry: NodeMasterMaintenanceEntry,
    evidence: _EndpointEvidence,
    assignment: NodeRegionAssignment,
    special_confirmation: str | None,
) -> str:
    rate_sources = sorted(
        {
            (
                f"{rate.source_file or 'unknown_rate_source'}"
                f"#{rate.source_row_number or '?'}"
            )
            for rate in evidence.rates
        }
    )
    parts = [
        entry.source,
        f"barge_rate_evidence={','.join(rate_sources)}",
        f"region_assignment={assignment.method}:{assignment.region_code}",
    ]
    if assignment.anchor_name is not None:
        parts.append(
            f"nearest_anchor={assignment.anchor_name}:"
            f"{assignment.distance_km}km"
        )
    if special_confirmation is not None:
        parts.append(special_confirmation)
    return ";".join(parts)


def _haversine_km(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    radius_km = 6371.0088
    phi_1 = math.radians(latitude_1)
    phi_2 = math.radians(latitude_2)
    delta_phi = math.radians(latitude_2 - latitude_1)
    delta_lambda = math.radians(longitude_2 - longitude_1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_1)
        * math.cos(phi_2)
        * math.sin(delta_lambda / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
