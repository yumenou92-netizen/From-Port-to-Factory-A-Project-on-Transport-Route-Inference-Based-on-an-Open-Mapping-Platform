import json

import pytest

from src.data_audit import (
    DataAuditError,
    audit_json_file,
    load_json_records,
    resolve_audit_output_paths,
    validate_sensitive_output_path,
    write_markdown_report,
)
from src.data_audit import main as run_data_audit


def test_load_json_lines_records(tmp_path):
    path = tmp_path / "rates.json"
    rows = [
        {"始发": "测试北港", "到达": "测试客户A", "运输方式": "汽运", "费用": 10, "费用单位": "元/吨"},
        {"始发": "测试北港", "到达": "测试客户B", "运输方式": "驳船", "费用": 20, "费用单位": "元/箱"},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    structure_type, records, malformed = load_json_records(path)

    assert structure_type == "json_lines"
    assert malformed == 0
    assert records == rows


def test_load_json_lines_counts_malformed_and_non_object_lines(tmp_path):
    path = tmp_path / "rates.json"
    path.write_text(
        '\n'.join(
            [
                json.dumps({"费用": 10, "费用单位": "元/吨"}, ensure_ascii=False),
                "{bad json",
                json.dumps(["not", "an", "object"], ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )

    structure_type, records, malformed = load_json_records(path)
    audit = audit_json_file(path)

    assert structure_type == "json_lines"
    assert len(records) == 1
    assert malformed == 2
    assert audit.malformed_lines == 2


def test_audit_json_file_detects_required_edge_fields_and_fee_issues(tmp_path):
    path = tmp_path / "rates.json"
    rows = [
        {
            "始发": "测试北港",
            "到达": "测试客户A",
            "运输方式": "汽运",
            "包装方式": "散粮",
            "适用品种": "玉米、小麦",
            "费用": 10,
            "费用单位": "元/吨",
            "维护日期": "2026-04-15",
        },
        {
            "始发": "测试北港",
            "到达": "测试客户A",
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
    assert len(audit.fee_issues) == 1
    assert audit.fee_issues[0].field_name == "费用"
    assert audit.fee_issues[0].fee_unit == "元/吨"
    assert audit.fee_issues[0].non_numeric_count == 1
    assert audit.date_invalid_count == 1


def test_fee_outliers_are_grouped_by_fee_unit(tmp_path):
    path = tmp_path / "rates.json"
    rows = []
    for value in [10, 11, 12, 13, 14, 15, 16, 100]:
        rows.append({"费用": value, "费用单位": "元/吨"})
    for value in [500, 510, 520, 530, 540, 550, 560, 570]:
        rows.append({"费用": value, "费用单位": "元/箱"})
    rows.append({"费用": 17, "费用单位": " 元 ／ 吨 "})
    rows.append({"单价": 12})
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    audit = audit_json_file(path)
    issues = {(issue.field_name, issue.fee_unit): issue for issue in audit.fee_issues}

    assert set(issues) == {
        ("费用", "元/吨"),
        ("费用", "元/箱"),
        ("单价", "<缺少费用单位>"),
    }
    assert issues[("费用", "元/吨")].min_value == 10
    assert issues[("费用", "元/吨")].max_value == 100
    assert issues[("费用", "元/吨")].outlier_count == 1
    assert issues[("费用", "元/箱")].min_value == 500
    assert issues[("费用", "元/箱")].max_value == 570
    assert issues[("费用", "元/箱")].outlier_count == 0
    assert issues[("单价", "<缺少费用单位>")].numeric_count == 1


def test_markdown_report_separates_sanitized_and_detailed_content(tmp_path):
    data_dir = tmp_path / "private_data"
    data_dir.mkdir()
    rate_path = data_dir / "rates.json"
    rows = [
        {
            "始发": "机密测试北港",
            "到达": "机密测试客户",
            "运输方式": "机密运输模式",
            "包装方式": "散粮",
            "适用品种": "测试品种",
            "费用": 1234.5,
            "费用单位": "元/吨",
            "经度": 110.123456,
            "纬度": 22.654321,
        },
        {
            "始发": "机密测试北港码头",
            "到达": "机密测试客户二号",
            "运输方式": "机密运输模式",
            "包装方式": "散粮",
            "适用品种": "测试品种",
            "费用": 1200,
            "费用单位": "元/吨",
        },
    ]
    rate_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    audits = [audit_json_file(rate_path)]
    sanitized_path = tmp_path / "sanitized.md"
    detailed_path = tmp_path / "detailed.md"

    write_markdown_report(audits, data_dir, sanitized_path)
    write_markdown_report(audits, data_dir, detailed_path, include_sensitive_details=True)

    sanitized = sanitized_path.read_text(encoding="utf-8")
    detailed = detailed_path.read_text(encoding="utf-8")
    assert str(data_dir) not in sanitized
    assert "机密测试北港" not in sanitized
    assert "机密测试客户" not in sanitized
    assert "1234.5" not in sanitized
    assert "110.123456" not in sanitized
    assert "机密运输模式" not in sanitized
    assert "机密测试北港码头" not in sanitized
    assert "别名示例 | 机密" not in sanitized
    assert "<DATA_DIR：本地路径已脱敏>" in sanitized
    assert "已脱敏" in sanitized
    assert str(data_dir) in detailed
    assert "机密测试北港" in detailed
    assert "机密测试北港码头" in detailed
    assert "机密运输模式" in detailed
    assert "1234.5" in detailed


def test_default_sensitive_outputs_stay_under_output(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_AUDIT_REPORT_PATH", raising=False)
    monkeypatch.delenv("DATA_AUDIT_DETAILED_REPORT_PATH", raising=False)
    monkeypatch.delenv("DATA_QUALITY_SUMMARY_PATH", raising=False)
    monkeypatch.delenv("DATA_AUDIT_ALLOW_EXTERNAL_SENSITIVE_OUTPUT", raising=False)

    report_path, detailed_path, summary_path = resolve_audit_output_paths(tmp_path)

    assert report_path == tmp_path / "docs" / "data_usage_report.md"
    assert detailed_path == tmp_path / "output" / "data_usage_report_detailed.md"
    assert summary_path == tmp_path / "output" / "data_quality_summary.csv"


def test_sensitive_output_rejects_project_docs_path(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_AUDIT_ALLOW_EXTERNAL_SENSITIVE_OUTPUT", raising=False)

    with pytest.raises(DataAuditError, match="只允许写入项目 output/ 目录"):
        validate_sensitive_output_path(
            tmp_path,
            tmp_path / "docs" / "private_details.md",
            "本地详细报告",
        )


def test_data_audit_main_supports_custom_output_paths(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    report_path = tmp_path / "private_report.md"
    detailed_report_path = tmp_path / "private_detailed_report.md"
    summary_path = tmp_path / "private_summary.csv"
    path = data_dir / "rates.json"
    row = {
        "始发": "测试北港",
        "到达": "测试客户A",
        "运输方式": "汽运",
        "包装方式": "散粮",
        "适用品种": "玉米",
        "费用": 10,
        "费用单位": "元/吨",
        "价格来源": "测试",
    }
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATA_AUDIT_REPORT_PATH", str(report_path))
    monkeypatch.setenv("DATA_AUDIT_DETAILED_REPORT_PATH", str(detailed_report_path))
    monkeypatch.setenv("DATA_QUALITY_SUMMARY_PATH", str(summary_path))
    monkeypatch.setenv("DATA_AUDIT_ALLOW_EXTERNAL_SENSITIVE_OUTPUT", "1")

    run_data_audit()

    assert report_path.exists()
    assert detailed_report_path.exists()
    assert summary_path.exists()
    assert "数据使用审计报告" in report_path.read_text(encoding="utf-8")
    assert str(data_dir) not in report_path.read_text(encoding="utf-8")
    assert str(data_dir) in detailed_report_path.read_text(encoding="utf-8")
    assert "rates.json" in summary_path.read_text(encoding="utf-8-sig")
