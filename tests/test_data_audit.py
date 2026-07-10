import json

from src.data_audit import audit_json_file, load_json_records


def test_load_json_lines_records(tmp_path):
    path = tmp_path / "rates.json"
    rows = [
        {"始发": "漳州港", "到达": "客户A", "运输方式": "汽运", "费用": 10, "费用单位": "元/吨"},
        {"始发": "漳州港", "到达": "客户B", "运输方式": "驳船", "费用": 20, "费用单位": "元/箱"},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    structure_type, records, malformed = load_json_records(path)

    assert structure_type == "json_lines"
    assert malformed == 0
    assert records == rows


def test_audit_json_file_detects_required_edge_fields_and_fee_issues(tmp_path):
    path = tmp_path / "rates.json"
    rows = [
        {
            "始发": "漳州港",
            "到达": "客户A",
            "运输方式": "汽运",
            "包装方式": "散粮",
            "适用品种": "玉米、小麦",
            "费用": 10,
            "费用单位": "元/吨",
            "维护日期": "2026-04-15",
        },
        {
            "始发": "漳州港",
            "到达": "客户A",
            "运输方式": "汽运",
            "包装方式": "散粮",
            "适用品种": "玉米、小麦",
            "费用": "bad",
            "费用单位": "元/吨",
            "维护日期": "2026/04/15",
        },
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    audit = audit_json_file(path)

    assert audit.record_count == 2
    assert not audit.missing_edge_fields
    assert audit.fee_issues["费用"].non_numeric_count == 1
    assert audit.date_invalid_count == 1
