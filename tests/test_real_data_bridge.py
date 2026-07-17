import json
from decimal import Decimal

from src.data.loaders import (
    EdgeCandidate,
    build_order_edge_candidates,
    load_real_data_bundle,
    make_node_id,
)
from src.domain.node_registry import build_node_registry
from src.routing.real_data_bridge import (
    ManualTimeInput,
    build_real_candidate_route_recommendations,
    build_transport_edge_from_candidate,
)


def test_candidate_with_manual_time_becomes_available_transport_edge(tmp_path):
    bundle = load_real_data_bundle(write_real_data_fixture(tmp_path))
    result = build_order_edge_candidates(
        bundle,
        quantity=500,
        quantity_unit="吨",
        packaging="散粮",
        product="玉米",
    )

    edge = build_transport_edge_from_candidate(
        result.candidates[0],
        commodity="玉米",
        manual_time_input=ManualTimeInput("3.5"),
    )

    assert edge.status == "available"
    assert edge.from_node_id == make_node_id("南港B")
    assert edge.to_node_id == make_node_id("客户工厂C")
    assert edge.cost_yuan == Decimal("10000")
    assert edge.time_hours == Decimal("3.5")
    assert edge.raw_price == Decimal("20")
    assert edge.raw_price_unit == "元/吨"
    assert edge.time_source == "manual_shipping_time"
    assert edge.data_source == "运价表.json#row=1"


def test_candidate_without_manual_time_stays_manual_review(tmp_path):
    bundle = load_real_data_bundle(write_real_data_fixture(tmp_path))
    result = build_order_edge_candidates(
        bundle,
        quantity=500,
        quantity_unit="吨",
        packaging="散粮",
        product="玉米",
    )

    edge = build_transport_edge_from_candidate(result.candidates[0], commodity="玉米")

    assert edge.status == "manual_review"
    assert edge.time_hours is None
    assert "缺少人工运输时间" in edge.unavailable_reason


def test_candidate_missing_node_stays_manual_review_even_with_time():
    candidate = make_candidate(to_node_id=None)

    edge = build_transport_edge_from_candidate(
        candidate,
        commodity="玉米",
        manual_time_input=ManualTimeInput("2"),
    )

    assert edge.status == "manual_review"
    assert edge.to_node_id is None
    assert "缺少终点节点 ID" in edge.unavailable_reason


def test_candidates_enter_formal_graph_and_route_search_with_confirmed_time(tmp_path):
    bundle = load_real_data_bundle(write_real_data_fixture(tmp_path))
    result = build_order_edge_candidates(
        bundle,
        quantity=500,
        quantity_unit="吨",
        packaging="散粮",
        product="玉米",
    )
    registry = build_node_registry(bundle.nodes)
    route = build_real_candidate_route_recommendations(
        result.candidates,
        commodity="玉米",
        node_registry=registry,
        start_node_id=make_node_id("南港B"),
        end_node_id=make_node_id("客户工厂C"),
        default_manual_time=ManualTimeInput("2"),
    )

    assert route.available_edge_count == 1
    assert route.graph_result.added_edge_count == 1
    assert route.graph_result.issues == ()
    assert route.recommendations is not None
    assert route.recommendations.lowest_cost.status == "resolved"
    assert route.recommendations.lowest_cost.total_cost_yuan == Decimal("10000")
    assert route.recommendations.lowest_cost.total_time_hours == Decimal("2")
    assert route.recommendations.fastest_time.status == "resolved"


def make_candidate(**overrides) -> EdgeCandidate:
    values = {
        "rate_id": "rate-demo",
        "from_node_id": "node-south",
        "to_node_id": "node-factory",
        "origin": "南港B",
        "destination": "客户工厂C",
        "transport_mode": "汽运",
        "packaging": "散粮",
        "product_scope": "玉米",
        "raw_price": Decimal("20"),
        "raw_price_unit": "元/吨",
        "total_cost": Decimal("10000"),
        "price_source": "测试来源",
        "maintenance_date": "2026-04-15",
        "effective_maintenance_date": "2026-04-15",
        "maintenance_date_defaulted": False,
        "price_type": "unit_price",
        "calculation_rule_id": "freight_rate_unit_price",
        "calculation_rule_version": "1.0",
        "calculation_detail": "500吨 × 20元/吨 = 10000元",
        "source_file": "运价表.json",
        "source_row_number": 1,
    }
    values.update(overrides)
    return EdgeCandidate(**values)


def write_real_data_fixture(tmp_path):
    write_json_lines(
        tmp_path / "运价表.json",
        [
            {
                "始发": "南港B",
                "到达": "客户工厂C",
                "运输方式": "汽运",
                "包装方式": "散粮",
                "适用品种": "玉米、小麦",
                "费用": 20,
                "费用单位": "元/吨",
                "价格来源": "测试来源",
                "维护日期": "2026-04-15",
            }
        ],
    )
    write_json_lines(
        tmp_path / "地点经纬度.json",
        [
            {"名称": "南港B", "经度": 111.1, "纬度": 23.1},
            {"名称": "客户工厂C", "经度": 112.1, "纬度": 24.1},
        ],
    )
    write_json_lines(
        tmp_path / "其他费用表.json",
        [
            {
                "节点简称": "南港B",
                "包装类型": "散粮",
                "费用类型": "作业费",
                "单价": 8,
                "费用单位": "元/吨",
            }
        ],
    )
    return tmp_path


def write_json_lines(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )
