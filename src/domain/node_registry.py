from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

try:
    from .data_loaders import NodeRecord, make_node_id
    from .freight_rate import FreightRate
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.data.loaders import NodeRecord, make_node_id
    from src.domain.freight_rate import FreightRate


DEFAULT_COORDINATE_TOLERANCE = 0.02


class NodeRegistryError(Exception):
    """Raised when node names cannot be standardized safely."""


@dataclass(frozen=True)
class AliasRule:
    canonical_name: str
    aliases: tuple[str, ...]

    @property
    def all_names(self) -> tuple[str, ...]:
        return (self.canonical_name, *self.aliases)


@dataclass(frozen=True)
class StandardNode:
    node_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    longitude: float
    latitude: float
    source_record_count: int


@dataclass(frozen=True)
class CoordinateConflict:
    canonical_name: str
    names: tuple[str, ...]
    max_longitude_delta: float
    max_latitude_delta: float


@dataclass(frozen=True)
class NodeMatchReport:
    total_rate_records: int
    matched_rate_records: int
    unmatched_rate_records: int
    unique_location_names: int
    matched_location_names: int
    unmatched_location_names: int
    unmatched_names: tuple[str, ...]


@dataclass(frozen=True)
class NodeRegistry:
    nodes: dict[str, StandardNode]
    name_to_node_id: dict[str, str]
    alias_groups: tuple[tuple[str, ...], ...]
    alias_review_groups: tuple[tuple[str, ...], ...]
    coordinate_conflicts: tuple[CoordinateConflict, ...]

    def lookup(self, name: str) -> StandardNode | None:
        node_id = self.name_to_node_id.get(normalize_lookup_name(name))
        if node_id is None:
            return None
        return self.nodes[node_id]

    def require(self, name: str) -> StandardNode:
        node = self.lookup(name)
        if node is None:
            raise NodeRegistryError(f"找不到标准节点: {name}")
        return node


def build_node_registry(
    node_records: Iterable[NodeRecord],
    alias_rules: Iterable[AliasRule] | None = None,
    auto_alias: bool = True,
    coordinate_tolerance: float = DEFAULT_COORDINATE_TOLERANCE,
) -> NodeRegistry:
    records = list(node_records)
    records_by_name = collect_records_by_name(records)
    names = sorted(records_by_name)
    parent = {name: name for name in names}
    alias_rules = tuple(alias_rules or ())

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    alias_review_groups: tuple[tuple[str, ...], ...] = ()
    if auto_alias:
        mergeable_alias_groups, alias_review_groups = classify_auto_alias_names(records_by_name, coordinate_tolerance)
        for alias_names in mergeable_alias_groups:
            first_name = alias_names[0]
            for name in alias_names[1:]:
                union(first_name, name)

    preferred_canonical: dict[str, str] = {}
    for rule in alias_rules:
        existing_names = [name for name in rule.all_names if name in records_by_name]
        if not existing_names:
            continue
        first_name = existing_names[0]
        for name in existing_names[1:]:
            union(first_name, name)
        preferred_canonical[find(first_name)] = rule.canonical_name.strip()

    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(find(name), []).append(name)

    standard_nodes: dict[str, StandardNode] = {}
    name_to_node_id: dict[str, str] = {}
    alias_groups: list[tuple[str, ...]] = []
    coordinate_conflicts: list[CoordinateConflict] = []

    for root, group_names in sorted(groups.items()):
        canonical_name = preferred_canonical.get(root) or choose_canonical_name(group_names)
        aliases = tuple(sorted(set(group_names + ([canonical_name] if canonical_name else []))))
        node_id = make_node_id(canonical_name)
        longitude, latitude = choose_coordinates(canonical_name, group_names, records_by_name)
        source_record_count = sum(len(records_by_name[name]) for name in group_names)

        standard_nodes[node_id] = StandardNode(
            node_id=node_id,
            canonical_name=canonical_name,
            aliases=aliases,
            longitude=longitude,
            latitude=latitude,
            source_record_count=source_record_count,
        )

        for alias in aliases:
            name_to_node_id[normalize_lookup_name(alias)] = node_id

        if len(aliases) > 1:
            alias_groups.append(aliases)

        conflict = detect_coordinate_conflict(canonical_name, group_names, records_by_name, coordinate_tolerance)
        if conflict is not None:
            coordinate_conflicts.append(conflict)

    return NodeRegistry(
        nodes=standard_nodes,
        name_to_node_id=name_to_node_id,
        alias_groups=tuple(alias_groups),
        alias_review_groups=alias_review_groups,
        coordinate_conflicts=tuple(coordinate_conflicts),
    )


def collect_records_by_name(records: list[NodeRecord]) -> dict[str, list[NodeRecord]]:
    records_by_name: dict[str, list[NodeRecord]] = {}
    for record in records:
        name = record.name.strip()
        if not name:
            raise NodeRegistryError("节点名称不能为空。")
        records_by_name.setdefault(name, []).append(record)
    return records_by_name


def classify_auto_alias_names(
    records_by_name: dict[str, list[NodeRecord]],
    coordinate_tolerance: float,
) -> tuple[list[list[str]], tuple[tuple[str, ...], ...]]:
    alias_candidates: dict[str, list[str]] = {}
    for name in records_by_name:
        key = conservative_alias_key(name)
        alias_candidates.setdefault(key, []).append(name)

    alias_groups: list[list[str]] = []
    review_groups: list[tuple[str, ...]] = []
    for names in alias_candidates.values():
        unique_names = sorted(set(names))
        if len(unique_names) < 2:
            continue
        if coordinates_within_tolerance(unique_names, records_by_name, coordinate_tolerance):
            alias_groups.append(unique_names)
        else:
            review_groups.append(tuple(unique_names))
    return alias_groups, tuple(review_groups)


def conservative_alias_key(name: str) -> str:
    text = normalize_lookup_name(name)
    if text.endswith("站") and len(text) > 3:
        return text[:-1]
    return text


def normalize_lookup_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name).strip())


def coordinates_within_tolerance(
    names: list[str],
    records_by_name: dict[str, list[NodeRecord]],
    coordinate_tolerance: float,
) -> bool:
    longitudes: list[float] = []
    latitudes: list[float] = []
    for name in names:
        for record in records_by_name[name]:
            longitudes.append(record.longitude)
            latitudes.append(record.latitude)
    if not longitudes or not latitudes:
        return False
    return (
        max(longitudes) - min(longitudes) <= coordinate_tolerance
        and max(latitudes) - min(latitudes) <= coordinate_tolerance
    )


def choose_canonical_name(names: list[str]) -> str:
    return sorted(names, key=lambda value: (len(value), value))[0]


def choose_coordinates(
    canonical_name: str,
    group_names: list[str],
    records_by_name: dict[str, list[NodeRecord]],
) -> tuple[float, float]:
    if canonical_name in records_by_name:
        record = records_by_name[canonical_name][0]
        return record.longitude, record.latitude

    first_source_name = sorted(group_names)[0]
    record = records_by_name[first_source_name][0]
    return record.longitude, record.latitude


def detect_coordinate_conflict(
    canonical_name: str,
    group_names: list[str],
    records_by_name: dict[str, list[NodeRecord]],
    coordinate_tolerance: float,
) -> CoordinateConflict | None:
    longitudes: list[float] = []
    latitudes: list[float] = []
    for name in group_names:
        for record in records_by_name[name]:
            longitudes.append(record.longitude)
            latitudes.append(record.latitude)

    longitude_delta = max(longitudes) - min(longitudes)
    latitude_delta = max(latitudes) - min(latitudes)
    if longitude_delta <= coordinate_tolerance and latitude_delta <= coordinate_tolerance:
        return None

    return CoordinateConflict(
        canonical_name=canonical_name,
        names=tuple(sorted(group_names)),
        max_longitude_delta=longitude_delta,
        max_latitude_delta=latitude_delta,
    )


def analyze_freight_rate_node_coverage(
    registry: NodeRegistry,
    freight_rates: Iterable[FreightRate],
) -> NodeMatchReport:
    rates = list(freight_rates)
    unique_names: set[str] = set()
    unmatched_names: set[str] = set()
    matched_rate_records = 0

    for rate in rates:
        unique_names.update({rate.origin_name, rate.destination_name})
        origin_node = registry.lookup(rate.origin_name)
        destination_node = registry.lookup(rate.destination_name)
        if origin_node and destination_node:
            matched_rate_records += 1
            continue
        if origin_node is None:
            unmatched_names.add(rate.origin_name)
        if destination_node is None:
            unmatched_names.add(rate.destination_name)

    matched_location_names = sum(1 for name in unique_names if registry.lookup(name) is not None)
    unmatched_location_names = len(unique_names) - matched_location_names
    unmatched_rate_records = len(rates) - matched_rate_records

    return NodeMatchReport(
        total_rate_records=len(rates),
        matched_rate_records=matched_rate_records,
        unmatched_rate_records=unmatched_rate_records,
        unique_location_names=len(unique_names),
        matched_location_names=matched_location_names,
        unmatched_location_names=unmatched_location_names,
        unmatched_names=tuple(sorted(unmatched_names)),
    )
