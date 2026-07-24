import json
from decimal import Decimal

from src.data.loaders import NodeRecord, make_node_id
from src.data.name_dictionary import NameDictionaryEntry
from src.data.port_label_rules import (
    collect_port_label_tencent_locations,
    load_port_label_rule_bundle,
    match_port_label_name,
    port_label_tencent_review_to_row,
    query_port_label_tencent_candidates,
)
from src.domain.node_registry import build_node_registry
from src.geo.coordinate_provider import CoordinateResolution


def test_port_label_rules_expand_inbound_fee_to_operation_fee_rates(tmp_path):
    path = tmp_path / "部分码头标签.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.6改",
                "description": "港口散粮服务费计费规则",
                "lastUpdated": "2026-07-24",
                "rules": [
                    {
                        "portName": ["钦州港", "金港"],
                        "tradeType": "内贸",
                        "variety": ["玉米", "小麦"],
                        "serviceFees": {"入库": 39},
                    },
                    {
                        "portName": "钦州港",
                        "tradeType": "外贸",
                        "variety": ["木薯"],
                        "serviceFees": {"入库": 119.2},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    registry = build_node_registry(
        [
            NodeRecord(make_node_id("钦州港"), "钦州港", 108.6, 21.7),
        ]
    )

    bundle = load_port_label_rule_bundle(path, registry=registry)

    assert bundle.version == "1.6改"
    assert len(bundle.rates) == 3
    qinzhou_domestic = bundle.rates[0]
    assert qinzhou_domestic.port_name == "钦州港"
    assert qinzhou_domestic.package_type == "散粮"
    assert qinzhou_domestic.fee_type == "码头作业费"
    assert qinzhou_domestic.fee_unit == "元/吨"
    assert qinzhou_domestic.trade_type == "内贸"
    assert qinzhou_domestic.unit_price_yuan_per_ton == Decimal("39")
    assert qinzhou_domestic.commodity_scope == ("玉米", "小麦")
    assert qinzhou_domestic.node_id == make_node_id("钦州港")
    assert bundle.audit_rows[1]["port_name"] == "金港"
    assert bundle.audit_rows[1]["registry_match_status"] == "unmatched"


def test_port_label_rules_invalid_inbound_fee_becomes_review_row(tmp_path):
    path = tmp_path / "部分码头标签.json"
    path.write_text(
        json.dumps(
            {
                "version": "bad",
                "rules": [
                    {
                        "portName": "钦州港",
                        "tradeType": "内贸",
                        "variety": ["玉米"],
                        "serviceFees": {"入库": 0},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bundle = load_port_label_rule_bundle(path)

    assert bundle.rates == ()
    assert bundle.audit_rows[0]["conversion_status"] == "manual_review"
    assert "必须是大于 0" in bundle.audit_rows[0]["issue"]


def test_port_label_name_uses_unique_dictionary_suffix_match_without_registering_alias():
    registry = build_node_registry(
        [
            NodeRecord(
                make_node_id("南宁那桐鸿海码头"),
                "南宁那桐鸿海码头",
                108.0,
                23.0,
            ),
        ]
    )
    entries = [
        NameDictionaryEntry(
            29,
            "港口码头",
            None,
            "南宁那桐鸿海码头",
        )
    ]

    match = match_port_label_name(
        "南宁那桐鸿海",
        registry=registry,
        dictionary_entries=entries,
    )

    assert match.match_status == "dictionary_suffix_unique"
    assert match.node is not None
    assert match.node.canonical_name == "南宁那桐鸿海码头"
    assert match.dictionary_rows == (29,)
    assert registry.lookup("南宁那桐鸿海") is None
    assert match.tencent_query_names == ()


def test_port_label_name_keeps_ambiguous_dictionary_suffixes_for_tencent_review():
    registry = build_node_registry(
        [
            NodeRecord(make_node_id("广州新港"), "广州新港", 113.0, 23.0),
            NodeRecord(make_node_id("新会新港"), "新会新港", 112.0, 22.0),
        ]
    )
    entries = [
        NameDictionaryEntry(14, "港口码头", None, "广州新港"),
        NameDictionaryEntry(50, "港口码头", None, "新会新港"),
    ]

    match = match_port_label_name(
        "新港",
        registry=registry,
        dictionary_entries=entries,
    )

    assert match.node is None
    assert match.match_status == "unmatched"
    assert match.dictionary_status == "candidate_only"
    assert match.dictionary_rows == (14, 50)
    assert match.tencent_query_names == ("新港", "广州新港", "新会新港")


def test_port_label_name_excludes_railway_dictionary_rows_from_port_fee_queries():
    registry = build_node_registry(
        [
            NodeRecord(make_node_id("广州南沙港"), "广州南沙港", 113.0, 22.0),
        ]
    )
    entries = [
        NameDictionaryEntry(18, "港口码头", None, "广州南沙港"),
        NameDictionaryEntry(88, "铁路站台", None, "南沙港站"),
    ]

    match = match_port_label_name(
        "南沙",
        registry=registry,
        dictionary_entries=entries,
    )

    assert match.dictionary_rows == (18,)
    assert match.tencent_query_names == ("南沙", "广州南沙港")


def test_port_label_tencent_review_deduplicates_labels_and_query_names():
    rows = [
        {
            "port_name": "宝盛",
            "node_id": "",
            "dictionary_status": "candidate_only",
            "dictionary_rows": "11",
            "dictionary_candidates": "湛江宝盛码头",
            "tencent_query_names": "宝盛；湛江宝盛码头",
        },
        {
            "port_name": "宝盛",
            "node_id": "",
            "dictionary_status": "candidate_only",
            "dictionary_rows": "11",
            "dictionary_candidates": "湛江宝盛码头",
            "tencent_query_names": "宝盛；湛江宝盛码头",
        },
        {
            "port_name": "钦州港",
            "node_id": "node_qinzhou",
            "dictionary_status": "not_needed",
            "dictionary_rows": "",
            "dictionary_candidates": "",
            "tencent_query_names": "",
        },
    ]
    locations = collect_port_label_tencent_locations(rows)
    provider = RecordingProvider()

    reviews = query_port_label_tencent_candidates(locations, provider)
    row = port_label_tencent_review_to_row(reviews[0])

    assert len(locations) == 1
    assert locations[0].query_names == ("宝盛", "湛江宝盛码头")
    assert provider.queries == ["宝盛", "湛江宝盛码头"]
    assert row["coordinate_resolutions"][0]["canonical_name"] == "候选地点"
    assert "不写正式表" in row["review_action"]


class RecordingProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def resolve(self, name: str) -> CoordinateResolution:
        self.queries.append(name)
        return CoordinateResolution(
            status="resolved",
            query_name=name,
            node_id=None,
            canonical_name="候选地点",
            longitude=113.1,
            latitude=23.1,
            source="fake_tencent",
            message="test",
            source_confidence="top1",
        )
