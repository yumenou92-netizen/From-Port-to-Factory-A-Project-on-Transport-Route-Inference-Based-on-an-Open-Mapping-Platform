from decimal import Decimal

from src.data.loaders import EdgeCandidate
from src.data.name_dictionary import NameDictionaryEntry
from src.data.node_coordinate_backfill import (
    backfill_review_to_row,
    collect_missing_node_locations,
    query_coordinate_candidates,
)
from src.geo.coordinate_provider import CoordinateResolution


def test_collect_missing_node_locations_deduplicates_endpoint_sides_and_uses_explicit_full_name():
    candidates = [
        make_candidate("rate_1", None, "node_b", "测试东港", "客户甲"),
        make_candidate("rate_2", None, None, "测试东港", "客户乙"),
    ]
    entries = [
        NameDictionaryEntry(2, "港口码头", "测试东港码头有限公司", "测试东港"),
        NameDictionaryEntry(3, "客户仓库", None, "客户乙"),
    ]

    locations = collect_missing_node_locations(candidates, entries)

    assert [location.raw_name for location in locations] == ["测试东港", "客户乙"]
    port = locations[0]
    assert port.query_name == "测试东港码头有限公司"
    assert port.missing_sides == ("origin",)
    assert port.candidate_count == 2
    assert port.dictionary_status == "explicit_full_short_pair_review_required"
    assert locations[1].dictionary_status == "dictionary_name_without_explicit_pair"


def test_coordinate_backfill_query_returns_candidates_without_registration():
    location = collect_missing_node_locations([make_candidate("rate_1", None, "node_b", "甲港", "客户")])[0]
    reviews = query_coordinate_candidates([location], FakeProvider())

    row = backfill_review_to_row(reviews[0])

    assert row["coordinate_resolution"]["status"] == "resolved"
    assert row["coordinate_resolution"]["longitude"] == 110.1
    assert "不自动注册节点或别名" in row["review_action"]


def test_ambiguous_dictionary_pair_keeps_raw_query_name_for_manual_review():
    entries = [
        NameDictionaryEntry(2, "港口码头", "甲港有限公司", "中心码头"),
        NameDictionaryEntry(3, "港口码头", "乙港有限公司", "中心码头"),
    ]

    location = collect_missing_node_locations(
        [make_candidate("rate_1", None, "node_b", "中心码头", "客户")],
        entries,
    )[0]

    assert location.query_name == "中心码头"
    assert location.dictionary_status == "ambiguous_dictionary_mapping_review_required"


class FakeProvider:
    def resolve(self, name: str) -> CoordinateResolution:
        return CoordinateResolution(
            status="resolved",
            query_name=name,
            node_id=None,
            canonical_name="甲港",
            longitude=110.1,
            latitude=22.1,
            source="fake_tencent",
            message="test",
            source_confidence="top1",
        )


def make_candidate(
    rate_id: str,
    from_node_id: str | None,
    to_node_id: str | None,
    origin: str,
    destination: str,
) -> EdgeCandidate:
    return EdgeCandidate(
        rate_id=rate_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        origin=origin,
        destination=destination,
        transport_mode="驳船",
        packaging="散粮",
        product_scope="玉米",
        raw_price=Decimal("20"),
        raw_price_unit="元/吨",
        total_cost=Decimal("10000"),
        price_source="测试",
        maintenance_date=None,
        effective_maintenance_date="1970-01-01",
        maintenance_date_defaulted=True,
        price_type="unit_price",
        calculation_rule_id="test",
        calculation_rule_version="1.0",
        calculation_detail="test",
        source_file=None,
        source_row_number=None,
    )
