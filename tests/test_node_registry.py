from decimal import Decimal

from src.data_loaders import NodeRecord, make_node_id
from src.freight_rate import FreightRate, create_freight_rate
from src.node_registry import (
    AliasRule,
    analyze_freight_rate_node_coverage,
    build_node_registry,
)


def test_build_node_registry_creates_stable_standard_nodes():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="北港A", longitude=110.1, latitude=22.1),
            NodeRecord(node_id="raw_2", name="南港B", longitude=111.1, latitude=23.1),
        ]
    )

    north_port = registry.require("北港A")

    assert len(registry.nodes) == 2
    assert north_port.node_id == make_node_id("北港A")
    assert north_port.canonical_name == "北港A"
    assert registry.lookup(" 北港A ") == north_port


def test_build_node_registry_merges_obvious_station_aliases_when_coordinates_match():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="怀化西", longitude=109.91, latitude=27.55),
            NodeRecord(node_id="raw_2", name="怀化西站", longitude=109.915, latitude=27.555),
        ]
    )

    plain = registry.require("怀化西")
    station = registry.require("怀化西站")

    assert plain.node_id == station.node_id
    assert plain.aliases == ("怀化西", "怀化西站")
    assert len(registry.alias_groups) == 1
    assert not registry.alias_review_groups
    assert not registry.coordinate_conflicts


def test_build_node_registry_keeps_station_aliases_separate_and_marks_review_when_coordinates_conflict():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="怀化西", longitude=109.91, latitude=27.55),
            NodeRecord(node_id="raw_2", name="怀化西站", longitude=115.0, latitude=30.0),
        ]
    )

    assert registry.require("怀化西").node_id != registry.require("怀化西站").node_id
    assert not registry.alias_groups
    assert registry.alias_review_groups == (("怀化西", "怀化西站"),)
    assert not registry.coordinate_conflicts


def test_build_node_registry_supports_forced_physical_node_merge():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="南方港口一期", longitude=111.0, latitude=22.0),
            NodeRecord(node_id="raw_2", name="南方港口二期", longitude=111.5, latitude=22.5),
        ],
        alias_rules=[
            AliasRule(
                canonical_name="南方港口",
                aliases=("南方港口一期", "南方港口二期"),
            )
        ],
    )

    first = registry.require("南方港口一期")
    second = registry.require("南方港口二期")
    canonical = registry.require("南方港口")

    assert first.node_id == second.node_id == canonical.node_id
    assert canonical.node_id == make_node_id("南方港口")
    assert canonical.canonical_name == "南方港口"
    assert canonical.aliases == ("南方港口", "南方港口一期", "南方港口二期")
    assert len(registry.coordinate_conflicts) == 1


def test_analyze_freight_rate_node_coverage_reports_unmatched_locations():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="北港A", longitude=110.1, latitude=22.1),
            NodeRecord(node_id="raw_2", name="南港B", longitude=111.1, latitude=23.1),
        ]
    )
    rates = [
        make_rate("北港A", "南港B"),
        make_rate("北港A", "未知客户"),
    ]

    report = analyze_freight_rate_node_coverage(registry, rates)

    assert report.total_rate_records == 2
    assert report.matched_rate_records == 1
    assert report.unmatched_rate_records == 1
    assert report.unique_location_names == 3
    assert report.matched_location_names == 2
    assert report.unmatched_location_names == 1
    assert report.unmatched_names == ("未知客户",)


def make_rate(origin: str, destination: str) -> FreightRate:
    return create_freight_rate(
        origin_name=origin,
        destination_name=destination,
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price=Decimal("10"),
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="测试来源",
    )
