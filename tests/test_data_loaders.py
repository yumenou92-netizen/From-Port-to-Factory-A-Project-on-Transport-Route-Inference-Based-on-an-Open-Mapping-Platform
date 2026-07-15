import json
from decimal import Decimal

import pytest

from src.data_loaders import (
    DataLoadError,
    build_review_rows,
    build_order_edge_candidates,
    build_order_edge_candidates_for_request,
    edge_review_item_to_row,
    load_real_data_bundle,
    make_node_id,
)
from src.route_request import RouteRequest


def test_load_real_data_bundle_reads_required_business_json_files(tmp_path):
    data_dir = write_real_data_fixture(tmp_path)

    bundle = load_real_data_bundle(data_dir)

    assert len(bundle.freight_rates) == 2
    assert len(bundle.nodes) == 2
    assert len(bundle.additional_fees) == 1
    assert bundle.freight_rates[0].origin == "北港A"
    assert bundle.nodes[0].node_id == make_node_id("北港A")


def test_build_order_edge_candidates_converts_only_matching_units(tmp_path):
    data_dir = write_real_data_fixture(tmp_path)
    bundle = load_real_data_bundle(data_dir)

    result = build_order_edge_candidates(
        bundle,
        quantity=500,
        quantity_unit="吨",
        packaging="散粮",
        product="玉米",
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].total_cost == Decimal("10000")
    assert result.manual_review_count == 1
    assert result.skipped_packaging == 0
    assert result.skipped_product == 0
    assert len(result.manual_review_items) == 1
    assert "不能直接计算总费用" in result.manual_review_items[0].review_reason


def test_build_order_edge_candidates_uses_route_request_and_preserves_transport_mode(tmp_path):
    data_dir = write_real_data_fixture(tmp_path)
    bundle = load_real_data_bundle(data_dir)
    request = RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="散粮",
        commodity="玉米",
    )

    result = build_order_edge_candidates_for_request(bundle, request)

    assert len(result.candidates) == 1
    assert result.candidates[0].transport_mode == "驳船"
    assert result.candidates[0].total_cost == Decimal("10000")
    assert len(result.manual_review_items) == 1


def test_invalid_request_billing_stops_candidate_generation(tmp_path):
    bundle = load_real_data_bundle(write_real_data_fixture(tmp_path))
    request = RouteRequest(
        quantity=500,
        quantity_unit="箱",
        package_type="散粮",
        commodity="玉米",
    )

    result = build_order_edge_candidates_for_request(bundle, request)

    assert result.candidates == []
    assert result.request_validation.status == "manual_review"
    assert result.manual_review_count == 1
    review_rows = build_review_rows(result, request)
    assert len(review_rows) == result.manual_review_count
    assert review_rows[0]["validation_scope"] == "request"
    assert review_rows[0]["review_reason"]


def test_edge_build_result_distinguishes_billed_and_graph_ready_candidates(tmp_path):
    data_dir = write_real_data_fixture(tmp_path)
    write_json_lines(
        data_dir / "地点经纬度.json",
        [{"名称": "北港A", "经度": 110.1, "纬度": 22.1}],
    )
    bundle = load_real_data_bundle(data_dir)

    result = build_order_edge_candidates(
        bundle,
        quantity=500,
        quantity_unit="吨",
        packaging="散粮",
        product="玉米",
    )

    assert len(result.candidates) == 1
    assert result.graph_ready_candidates == []
    assert result.missing_node_candidate_count == 1


def test_edge_review_item_export_preserves_manual_follow_up_fields(tmp_path):
    bundle = load_real_data_bundle(write_real_data_fixture(tmp_path))
    result = build_order_edge_candidates(
        bundle,
        quantity=500,
        quantity_unit="吨",
        packaging="散粮",
        product="玉米",
    )

    row = edge_review_item_to_row(result.manual_review_items[0])

    assert row["validation_status"] == "manual_review"
    assert row["validation_scope"] == "freight_rate"
    assert row["review_reason"]
    assert row["fee_unit"] == "元/箱"
    assert row["transport_mode"] == "驳船"
    assert row["price_source"] == "测试来源"


def test_load_real_data_bundle_reports_missing_required_file(tmp_path):
    write_json_lines(tmp_path / "运价表.json", [])

    with pytest.raises(DataLoadError, match="缺少必要文件"):
        load_real_data_bundle(tmp_path)


def test_load_real_data_bundle_reports_invalid_coordinate_value(tmp_path):
    data_dir = write_real_data_fixture(tmp_path)
    write_json_lines(
        data_dir / "地点经纬度.json",
        [{"名称": "北港A", "经度": "bad", "纬度": 22.1}],
    )

    with pytest.raises(DataLoadError, match="经度.*不是有效数值"):
        load_real_data_bundle(data_dir)


def write_real_data_fixture(tmp_path):
    write_json_lines(
        tmp_path / "运价表.json",
        [
            {
                "始发": "北港A",
                "到达": "南港B",
                "运输方式": "驳船",
                "包装方式": "散粮",
                "适用品种": "玉米、小麦",
                "费用": 20,
                "费用单位": "元/吨",
                "价格来源": "测试来源",
                "维护日期": "2026-04-15",
            },
            {
                "始发": "北港A",
                "到达": "南港B",
                "运输方式": "驳船",
                "包装方式": "散粮",
                "适用品种": "玉米、小麦",
                "费用": 500,
                "费用单位": "元/箱",
                "价格来源": "测试来源",
            },
        ],
    )
    write_json_lines(
        tmp_path / "地点经纬度.json",
        [
            {"名称": "北港A", "经度": 110.1, "纬度": 22.1},
            {"名称": "南港B", "经度": 111.1, "纬度": 23.1},
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
