from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.application.route_planning import (
    SouthPortCandidateDecision,
    TransferPort,
)
from src.data.loaders import RealDataBundle
from src.data.node_master_maintenance import NodeMasterMaintenanceEntry
from src.data.port_node_maintenance import PortNodeMaintenanceEntry
from src.domain.freight_rate import FreightRate
from src.domain.node_registry import NodeRegistry, build_node_registry
from src.domain.node_role import (
    infer_node_role_from_name,
    infer_port_waterway_role,
    north_south_bulk_exclusion_reason,
)
from src.domain.route_request import RouteRequest
from src.geo.distance_provider import GeoPoint


class SouthPortSelectionError(ValueError):
    """Raised when south-port selection cannot safely satisfy the request."""


@dataclass(frozen=True)
class SouthPortSelection:
    ports: tuple[TransferPort, ...]
    decisions: tuple[SouthPortCandidateDecision, ...]


@dataclass(frozen=True)
class _MaintainedNodeIdentity:
    is_port: bool
    is_customer: bool
    waterway_role: str
    supported_package_types: tuple[str, ...]
    source: str


def select_automatic_south_ports(
    bundle: RealDataBundle,
    request: RouteRequest,
    destination: GeoPoint,
    *,
    origin_node_id: str,
    excluded_node_ids: set[str],
    preferred_node_ids: set[str],
    limit: int,
    alternative_transport_origin_node_ids: set[str] | None = None,
) -> SouthPortSelection:
    if limit <= 0:
        raise SouthPortSelectionError("候选南港数量必须大于 0。")
    registry = bundle.node_registry or build_node_registry(bundle.nodes)
    alternative_transport_origin_node_ids = set(
        alternative_transport_origin_node_ids or ()
    )
    bulk_origin_evidence_node_ids = bulk_freight_origin_node_ids(
        bundle.freight_rates,
        request,
    )
    maintained_identities = _maintained_identity_by_node_id(
        registry=registry,
        node_master_entries=bundle.node_master_entries,
        port_node_entries=bundle.port_node_entries,
    )
    origins: dict[str, TransferPort] = {}
    for rate in bundle.freight_rates:
        if (
            rate.package_type != request.package_type
            or not rate.supports_commodity(request.commodity)
            or rate.from_node_id is None
            or rate.from_node_id == origin_node_id
            or rate.from_node_id in excluded_node_ids
        ):
            continue
        node = registry.nodes.get(rate.from_node_id)
        if node is None:
            continue
        point = GeoPoint(Decimal(str(node.longitude)), Decimal(str(node.latitude)))
        origins.setdefault(
            node.node_id,
            TransferPort(
                node_id=node.node_id,
                name=node.canonical_name,
                point=point,
                straight_line_km_to_factory=haversine_km(point, destination),
            ),
        )

    eligible: list[TransferPort] = []
    decisions: list[SouthPortCandidateDecision] = []
    for port in origins.values():
        node = registry.nodes[port.node_id]
        identity = maintained_identities.get(node.node_id)
        node_role, waterway_role, identity_evidence = (
            _resolved_identity(
                node.canonical_name,
                node.aliases,
                identity,
            )
        )
        has_bulk_evidence = node.node_id in bulk_origin_evidence_node_ids
        evidence = (
            f"node_role={node_role}",
            f"waterway_role={waterway_role}",
            *identity_evidence,
            (
                "bulk_freight_origin_evidence=applicable"
                if has_bulk_evidence
                else "bulk_freight_origin_evidence=missing"
            ),
        )
        exclusion_reason = north_south_bulk_exclusion_reason(
            node.canonical_name,
            *node.aliases,
        )
        if node_role != "port":
            decisions.append(
                _decision(
                    port,
                    reason=(
                        "正式节点标签及补充名称规则判断该始发节点"
                        "不是港口/码头。"
                    ),
                    evidence=evidence,
                )
            )
            continue
        if waterway_role == "inland_port":
            decisions.append(
                _decision(
                    port,
                    reason="已确认为纯内河港，不能作为北港散船干线终点。",
                    evidence=evidence,
                )
            )
            continue
        if (
            identity is not None
            and identity.supported_package_types
            and request.package_type
            not in identity.supported_package_types
        ):
            decisions.append(
                _decision(
                    port,
                    reason=(
                        f"正式节点标签未确认支持包装方式："
                        f"{request.package_type}。"
                    ),
                    evidence=evidence,
                )
            )
            continue
        if exclusion_reason is not None:
            decisions.append(
                _decision(
                    port,
                    reason=exclusion_reason,
                    evidence=evidence,
                )
            )
            continue
        if not _allows_bulk_candidate(
            waterway_role=waterway_role,
            has_bulk_freight_origin_evidence=has_bulk_evidence,
        ):
            decisions.append(
                _decision(
                    port,
                    reason="缺少海港/海河双用标识或适用散粮始发运价证据。",
                    evidence=evidence,
                )
            )
            continue
        eligible.append(port)

    ranked = sorted(
        eligible,
        key=lambda item: (
            item.node_id not in preferred_node_ids,
            item.straight_line_km_to_factory,
            item.name,
        ),
    )
    selected_list = list(ranked[:limit])
    alternative_quota = min(3, max(1, limit // 2))
    selected_alternative_ids = {
        port.node_id
        for port in selected_list
        if port.node_id in alternative_transport_origin_node_ids
    }
    missing_alternatives = [
        port
        for port in ranked
        if port.node_id in alternative_transport_origin_node_ids
        and port.node_id not in selected_alternative_ids
    ]
    for alternative in missing_alternatives[
        : max(0, alternative_quota - len(selected_alternative_ids))
    ]:
        replace_index = next(
            (
                index
                for index in range(len(selected_list) - 1, -1, -1)
                if selected_list[index].node_id
                not in alternative_transport_origin_node_ids
            ),
            None,
        )
        if replace_index is None:
            break
        selected_list[replace_index] = alternative
        selected_alternative_ids.add(alternative.node_id)
    selected = tuple(
        sorted(
            selected_list,
            key=lambda item: (
                item.node_id not in preferred_node_ids,
                item.node_id
                not in alternative_transport_origin_node_ids,
                item.straight_line_km_to_factory,
                item.name,
            ),
        )
    )
    selected_ids = {port.node_id for port in selected}
    for port in ranked:
        node = registry.nodes[port.node_id]
        _, resolved_waterway_role, identity_evidence = _resolved_identity(
            node.canonical_name,
            node.aliases,
            maintained_identities.get(node.node_id),
        )
        decisions.append(
            SouthPortCandidateDecision(
                node_id=port.node_id,
                name=port.name,
                status=(
                    "shortlisted"
                    if port.node_id in selected_ids
                    else "not_selected"
                ),
                stage="ranking",
                reason=(
                    "已通过南港身份筛选并进入本次构边。"
                    if port.node_id in selected_ids
                    else f"已通过身份筛选，但超出本次候选上限 {limit}。"
                ),
                evidence=(
                    f"waterway_role={resolved_waterway_role}",
                    *identity_evidence,
                    (
                        "bulk_freight_origin_evidence=applicable"
                        if node.node_id in bulk_origin_evidence_node_ids
                        else "bulk_freight_origin_evidence=not_required_confirmed_sea_access"
                    ),
                    (
                        "maintained_last_mile_rate=preferred"
                        if port.node_id in preferred_node_ids
                        else (
                            "exact_od_barge_origin=multimodal_quota"
                            if port.node_id
                            in alternative_transport_origin_node_ids
                            else "last_mile_rate=confirmed_rule_fallback"
                        )
                    ),
                ),
            )
        )
    return SouthPortSelection(
        ports=selected,
        decisions=tuple(
            sorted(
                decisions,
                key=lambda item: (
                    item.status != "shortlisted",
                    item.name,
                    item.node_id,
                ),
            )
        ),
    )


def select_requested_south_port(
    name: str,
    *,
    registry: NodeRegistry,
    freight_rates: Sequence[FreightRate],
    request: RouteRequest,
    destination: GeoPoint,
    origin_node_id: str,
    excluded_node_ids: set[str],
    node_master_entries: Sequence[NodeMasterMaintenanceEntry] = (),
    port_node_entries: Sequence[PortNodeMaintenanceEntry] = (),
) -> SouthPortSelection:
    node = registry.lookup(name)
    if node is None:
        raise SouthPortSelectionError(
            f"指定南港 {name} 尚未注册为标准节点；"
            "第一版指定南港入口不使用临时坐标替代正式港口身份。"
        )
    if node.node_id == origin_node_id:
        raise SouthPortSelectionError("指定南港不能与北港使用同一标准节点。")
    identity = _maintained_identity_by_node_id(
        registry=registry,
        node_master_entries=node_master_entries,
        port_node_entries=port_node_entries,
    ).get(node.node_id)
    inferred_role, waterway_role, identity_evidence = _resolved_identity(
        node.canonical_name,
        node.aliases,
        identity,
    )
    if inferred_role in {"railway_station", "customer_facility"}:
        role_text = "铁路站点" if inferred_role == "railway_station" else "客户工厂/仓库"
        raise SouthPortSelectionError(
            f"指定南港 {name} 按正式节点标签或补充名称规则属于{role_text}，"
            "不能作为南港；"
            "客户自有码头应维护为单独的港口/码头节点。"
        )
    if inferred_role != "port":
        raise SouthPortSelectionError(
            f"指定南港 {name} 未被正式节点标签或补充名称规则识别为港口/码头。"
        )
    if waterway_role == "inland_port":
        raise SouthPortSelectionError(
            f"指定南港 {name} 已确认为内河码头，不能作为北港散船干线终点；"
            "该节点只可在后续内河/末段运输阶段使用。"
        )
    exclusion_reason = north_south_bulk_exclusion_reason(
        node.canonical_name,
        *node.aliases,
    )
    if exclusion_reason is not None:
        raise SouthPortSelectionError(
            f"指定南港 {name} 当前不能作为北港散粮散船干线终点："
            f"{exclusion_reason}"
        )
    if (
        identity is not None
        and identity.supported_package_types
        and request.package_type not in identity.supported_package_types
    ):
        raise SouthPortSelectionError(
            f"指定南港 {name} 的正式节点标签未确认支持包装方式："
            f"{request.package_type}。"
        )
    bulk_evidence_ids = bulk_freight_origin_node_ids(freight_rates, request)
    has_bulk_evidence = node.node_id in bulk_evidence_ids
    if not _allows_bulk_candidate(
        waterway_role=waterway_role,
        has_bulk_freight_origin_evidence=has_bulk_evidence,
    ):
        raise SouthPortSelectionError(
            f"指定南港 {name} 尚无已确认海港/海河双用标识，且没有适用的"
            "散粮始发运价证据（本订单口径），不能作为北港散船干线终点；"
            "若该节点仅出现集装箱运价，只能列为潜在中转港待后续人工确认。"
        )
    if node.node_id in excluded_node_ids:
        raise SouthPortSelectionError(
            f"指定南港 {name} 存在同日运价冲突，当前不能绕过人工复核。"
        )
    point = GeoPoint(
        Decimal(str(node.longitude)),
        Decimal(str(node.latitude)),
    )
    port = TransferPort(
        node_id=node.node_id,
        name=node.canonical_name,
        point=point,
        straight_line_km_to_factory=haversine_km(point, destination),
    )
    return SouthPortSelection(
        ports=(port,),
        decisions=(
            SouthPortCandidateDecision(
                node_id=port.node_id,
                name=port.name,
                status="shortlisted",
                stage="ranking",
                reason="用户显式指定南港，已通过节点身份和散粮准入校验。",
                evidence=(
                    "user_selected_south_port",
                    f"waterway_role={waterway_role}",
                    *identity_evidence,
                    (
                        "bulk_freight_origin_evidence=applicable"
                        if has_bulk_evidence
                        else "bulk_freight_origin_evidence=not_required_confirmed_sea_access"
                    ),
                ),
            ),
        ),
    )


def bulk_freight_origin_node_ids(
    rates: Sequence[FreightRate],
    request: RouteRequest,
) -> set[str]:
    """Return nodes backed by any freight-origin evidence for this bulk order."""

    if request.package_type != "散粮" or request.quantity_unit != "吨":
        return set()
    return {
        rate.from_node_id
        for rate in rates
        if (
            rate.from_node_id is not None
            and rate.package_type == "散粮"
            and rate.supports_commodity(request.commodity)
        )
    }


def _maintained_identity_by_node_id(
    *,
    registry: NodeRegistry,
    node_master_entries: Sequence[NodeMasterMaintenanceEntry],
    port_node_entries: Sequence[PortNodeMaintenanceEntry],
) -> dict[str, _MaintainedNodeIdentity]:
    """Index maintained identity tags, with the newer node master authoritative."""

    result: dict[str, _MaintainedNodeIdentity] = {}
    for entry in port_node_entries:
        node_id = _single_registered_node_id(entry.all_names, registry)
        if node_id is None:
            continue
        result[node_id] = _MaintainedNodeIdentity(
            is_port=True,
            is_customer=False,
            waterway_role="unknown_port",
            supported_package_types=(),
            source=entry.source,
        )
    for entry in node_master_entries:
        node_id = _single_registered_node_id(entry.all_names, registry)
        if node_id is None:
            continue
        is_port = (
            entry.is_logistics_node
            and "港口码头" in entry.node_nature
        )
        result[node_id] = _MaintainedNodeIdentity(
            is_port=is_port,
            is_customer=entry.is_customer_node and not is_port,
            waterway_role=_maintained_waterway_role(entry, is_port=is_port),
            supported_package_types=entry.package_types,
            source=entry.source,
        )
    return result


def _single_registered_node_id(
    names: Sequence[str],
    registry: NodeRegistry,
) -> str | None:
    node_ids = {
        node.node_id
        for name in names
        if (node := registry.lookup(name)) is not None
    }
    return next(iter(node_ids)) if len(node_ids) == 1 else None


def _maintained_waterway_role(
    entry: NodeMasterMaintenanceEntry,
    *,
    is_port: bool,
) -> str:
    if not is_port:
        return "not_port"
    if entry.has_seaport_attribute and entry.has_inland_port_attribute:
        return "sea_inland_dual_use"
    if entry.has_seaport_attribute:
        return "sea_port"
    if entry.has_inland_port_attribute:
        return "inland_port"
    return "unknown_port"


def _resolved_identity(
    canonical_name: str,
    aliases: Sequence[str],
    maintained: _MaintainedNodeIdentity | None,
) -> tuple[str, str, tuple[str, ...]]:
    if maintained is None:
        return (
            infer_node_role_from_name(canonical_name),
            infer_port_waterway_role(canonical_name, *aliases),
            ("identity_source=name_rule_fallback",),
        )
    if maintained.is_port:
        role = "port"
    elif maintained.is_customer:
        role = "customer_facility"
    else:
        role = infer_node_role_from_name(canonical_name)
    waterway_role = maintained.waterway_role
    if waterway_role == "unknown_port":
        inferred = infer_port_waterway_role(canonical_name, *aliases)
        if inferred not in {"not_port", "unknown_port"}:
            waterway_role = inferred
    return (
        role,
        waterway_role,
        (
            f"identity_source={maintained.source}",
            "identity_method=maintained_tag_primary",
        ),
    )


def _allows_bulk_candidate(
    *,
    waterway_role: str,
    has_bulk_freight_origin_evidence: bool,
) -> bool:
    if waterway_role in {"sea_port", "sea_inland_dual_use"}:
        return True
    return (
        waterway_role == "unknown_port"
        and has_bulk_freight_origin_evidence
    )


def haversine_km(left: GeoPoint, right: GeoPoint) -> Decimal:
    radius_km = 6371.0088
    lat1 = math.radians(float(left.latitude))
    lat2 = math.radians(float(right.latitude))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(float(right.longitude - left.longitude))
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    distance = 2 * radius_km * math.asin(math.sqrt(value))
    return Decimal(str(round(distance, 3)))


def _decision(
    port: TransferPort,
    *,
    reason: str,
    evidence: tuple[str, ...],
) -> SouthPortCandidateDecision:
    return SouthPortCandidateDecision(
        node_id=port.node_id,
        name=port.name,
        status="excluded",
        stage="identity",
        reason=reason,
        evidence=evidence,
    )
