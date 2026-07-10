from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable


EDGE_FIELDS = {"始发", "到达", "运输方式", "费用", "费用单位"}
EDGE_CONTEXT_FIELDS = {"包装方式", "包装类型", "适用品种", "价格来源", "维护日期"}
COORDINATE_FIELDS = {"名称", "经度", "纬度"}
DATE_FIELDS = {"维护日期"}
VALUE_PREVIEW_LIMIT = 40


class DataAuditError(Exception):
    """Raised when JSON data audit cannot proceed."""


@dataclass
class FieldStats:
    present: int = 0
    missing: int = 0
    type_counts: Counter[str] = field(default_factory=Counter)
    values: Counter[str] = field(default_factory=Counter)


@dataclass
class FeeIssueStats:
    field_name: str
    numeric_count: int = 0
    string_count: int = 0
    non_numeric_count: int = 0
    negative_count: int = 0
    zero_count: int = 0
    outlier_count: int = 0
    min_value: float | None = None
    max_value: float | None = None
    outlier_examples: list[float] = field(default_factory=list)


@dataclass
class JsonFileAudit:
    path: Path
    structure_type: str
    records: list[dict[str, Any]]
    malformed_lines: int = 0
    field_stats: dict[str, FieldStats] = field(default_factory=dict)
    duplicate_exact_count: int = 0
    duplicate_business_key_count: int = 0
    empty_origin_count: int = 0
    empty_destination_count: int = 0
    alias_groups: dict[str, list[str]] = field(default_factory=dict)
    fee_issues: dict[str, FeeIssueStats] = field(default_factory=dict)
    date_empty_count: int = 0
    date_invalid_count: int = 0
    date_formats: Counter[str] = field(default_factory=Counter)
    direct_edge_fields: set[str] = field(default_factory=set)
    missing_edge_fields: set[str] = field(default_factory=set)
    supplemental_role: str = ""

    @property
    def record_count(self) -> int:
        return len(self.records)


def data_dir_from_env() -> Path:
    value = os.environ.get("DATA_DIR")
    if not value:
        raise DataAuditError("缺少环境变量 DATA_DIR。请先设置 DATA_DIR 指向 JSON 数据目录。")

    path = Path(value)
    if not path.exists():
        raise DataAuditError(f"DATA_DIR 不存在: {path}")
    if not path.is_dir():
        raise DataAuditError(f"DATA_DIR 不是目录: {path}")
    return path


def load_json_records(path: Path) -> tuple[str, list[dict[str, Any]], int]:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return "empty_file", [], 0

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return "json_array", _dict_records(parsed), 0
        if isinstance(parsed, dict):
            return "json_object", [parsed], 0
        return f"json_{type(parsed).__name__}", [], 0
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        malformed = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed_line = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(parsed_line, dict):
                records.append(parsed_line)
            else:
                malformed += 1
        return "json_lines", records, malformed


def _dict_records(items: Iterable[Any]) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)]


def audit_data_dir(data_dir: Path) -> list[JsonFileAudit]:
    json_files = sorted(data_dir.rglob("*.json"))
    if not json_files:
        raise DataAuditError(f"DATA_DIR 下未找到 JSON 文件: {data_dir}")
    return [audit_json_file(path) for path in json_files]


def audit_json_file(path: Path) -> JsonFileAudit:
    structure_type, records, malformed = load_json_records(path)
    audit = JsonFileAudit(path=path, structure_type=structure_type, records=records, malformed_lines=malformed)
    audit.field_stats = collect_field_stats(records)
    audit.duplicate_exact_count = count_exact_duplicates(records)
    audit.duplicate_business_key_count = count_business_key_duplicates(records)
    audit.empty_origin_count = count_empty(records, "始发")
    audit.empty_destination_count = count_empty(records, "到达")
    audit.alias_groups = find_alias_groups(records)
    audit.fee_issues = collect_fee_issues(records)
    audit.date_empty_count, audit.date_invalid_count, audit.date_formats = collect_date_stats(records)
    classify_edge_fields(audit)
    return audit


def collect_field_stats(records: list[dict[str, Any]]) -> dict[str, FieldStats]:
    fields = sorted({key for record in records for key in record})
    stats = {field_name: FieldStats() for field_name in fields}
    total = len(records)

    for field_name in fields:
        field_stat = stats[field_name]
        for record in records:
            value = record.get(field_name)
            if is_missing(value):
                field_stat.missing += 1
                field_stat.type_counts["missing"] += 1
                continue
            field_stat.present += 1
            field_stat.type_counts[value_type(value)] += 1
            if isinstance(value, (str, int, float, bool)):
                field_stat.values[str(value)] += 1
        if field_stat.present + field_stat.missing < total:
            field_stat.missing += total - field_stat.present - field_stat.missing

    return stats


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "null"
    return type(value).__name__


def count_exact_duplicates(records: list[dict[str, Any]]) -> int:
    signatures = Counter(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)
    return sum(count - 1 for count in signatures.values() if count > 1)


def count_business_key_duplicates(records: list[dict[str, Any]]) -> int:
    fields = {field_name for record in records for field_name in record}
    if EDGE_FIELDS.issubset(fields):
        key_fields = ["始发", "到达", "运输方式", "包装方式", "适用品种", "费用", "费用单位", "价格来源"]
    elif COORDINATE_FIELDS.issubset(fields):
        key_fields = ["名称", "经度", "纬度"]
    elif {"节点简称", "包装类型", "费用类型", "单价", "费用单位"}.issubset(fields):
        key_fields = ["节点简称", "包装类型", "费用类型", "单价", "费用单位"]
    else:
        return 0
    signatures = Counter(tuple(str(record.get(field_name, "")).strip() for field_name in key_fields) for record in records)
    return sum(count - 1 for count in signatures.values() if count > 1)


def count_empty(records: list[dict[str, Any]], field_name: str) -> int:
    if not any(field_name in record for record in records):
        return 0
    return sum(1 for record in records if is_missing(record.get(field_name)))


def find_alias_groups(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    names: set[str] = set()
    for record in records:
        for field_name in ["始发", "到达", "名称", "节点简称"]:
            value = record.get(field_name)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())

    groups: dict[str, list[str]] = defaultdict(list)
    for name in names:
        normalized = normalize_name_for_alias(name)
        if normalized:
            groups[normalized].append(name)
    return {
        normalized: sorted(values)
        for normalized, values in groups.items()
        if len(set(values)) > 1
    }


def normalize_name_for_alias(name: str) -> str:
    text = re.sub(r"\s+", "", name)
    text = re.sub(r"[()（）]", "", text)
    suffixes = [
        "股份有限公司",
        "有限责任公司",
        "有限公司",
        "集团",
        "工厂",
        "码头",
        "港",
        "站",
    ]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix) + 2:
                text = text[: -len(suffix)]
                changed = True
    return text


def collect_fee_issues(records: list[dict[str, Any]]) -> dict[str, FeeIssueStats]:
    fee_fields = sorted({field_name for record in records for field_name in record if field_name in {"费用", "单价"}})
    return {field_name: audit_fee_field(records, field_name) for field_name in fee_fields}


def audit_fee_field(records: list[dict[str, Any]], field_name: str) -> FeeIssueStats:
    stats = FeeIssueStats(field_name=field_name)
    numeric_values: list[float] = []
    for record in records:
        value = record.get(field_name)
        if is_missing(value):
            continue
        number = parse_number(value)
        if isinstance(value, str):
            stats.string_count += 1
        if number is None:
            stats.non_numeric_count += 1
            continue
        stats.numeric_count += 1
        numeric_values.append(number)
        if number < 0:
            stats.negative_count += 1
        if number == 0:
            stats.zero_count += 1

    if numeric_values:
        stats.min_value = min(numeric_values)
        stats.max_value = max(numeric_values)
        outliers = detect_outliers(numeric_values)
        stats.outlier_count = len(outliers)
        stats.outlier_examples = outliers[:10]
    return stats


def parse_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def detect_outliers(values: list[float]) -> list[float]:
    if len(values) < 8:
        return []
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    lower = sorted_values[:midpoint]
    upper = sorted_values[midpoint + (len(sorted_values) % 2) :]
    q1 = median(lower)
    q3 = median(upper)
    iqr = q3 - q1
    if iqr == 0:
        return []
    low = q1 - 3 * iqr
    high = q3 + 3 * iqr
    return [value for value in sorted_values if value < low or value > high]


def collect_date_stats(records: list[dict[str, Any]]) -> tuple[int, int, Counter[str]]:
    empty = 0
    invalid = 0
    formats: Counter[str] = Counter()
    for record in records:
        for field_name in DATE_FIELDS:
            if field_name not in record:
                continue
            value = record.get(field_name)
            if is_missing(value):
                empty += 1
                continue
            text = str(value).strip()
            if is_valid_date(text):
                formats["YYYY-MM-DD"] += 1
            else:
                formats["invalid"] += 1
                invalid += 1
    return empty, invalid, formats


def is_valid_date(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def classify_edge_fields(audit: JsonFileAudit) -> None:
    fields = set(audit.field_stats)
    audit.direct_edge_fields = fields & (EDGE_FIELDS | EDGE_CONTEXT_FIELDS)
    audit.missing_edge_fields = EDGE_FIELDS - fields

    if EDGE_FIELDS.issubset(fields):
        audit.supplemental_role = "可直接形成候选运输边；仍需按订单数量和费用单位换算为该运输段总费用。"
    elif COORDINATE_FIELDS.issubset(fields):
        audit.supplemental_role = "地点坐标补充表；可用于生成节点和候选港距离筛选，不能单独形成运输边。"
    elif {"节点简称", "费用类型", "单价", "费用单位"}.issubset(fields):
        audit.supplemental_role = "节点附加费用表；可补充码头/站点作业费，不能单独形成运输边。"
    else:
        audit.supplemental_role = "结构未知；需要人工定义用途。"


def write_summary_csv(audits: list[JsonFileAudit], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "file",
        "structure_type",
        "record_count",
        "field",
        "present_count",
        "missing_count",
        "missing_rate",
        "types",
        "top_values",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        for audit in audits:
            for field_name, stats in sorted(audit.field_stats.items()):
                writer.writerow(
                    {
                        "file": audit.path.name,
                        "structure_type": audit.structure_type,
                        "record_count": audit.record_count,
                        "field": field_name,
                        "present_count": stats.present,
                        "missing_count": stats.missing,
                        "missing_rate": round(stats.missing / audit.record_count, 4) if audit.record_count else 0,
                        "types": format_counter(stats.type_counts),
                        "top_values": format_counter(stats.values, VALUE_PREVIEW_LIMIT),
                    }
                )


def write_markdown_report(audits: list[JsonFileAudit], data_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# 数据使用审计报告")
    lines.append("")
    lines.append(f"- 数据目录: `{data_dir}`")
    lines.append(f"- JSON 文件数: {len(audits)}")
    lines.append("- 本报告只审计 JSON 数据，不将记录写入路径图。")
    lines.append("")

    lines.append("## 1. 文件清单")
    lines.append("")
    lines.append("| 文件 | 结构类型 | 记录数 | 解析问题 |")
    lines.append("|---|---:|---:|---:|")
    for audit in audits:
        lines.append(f"| {audit.path.name} | {audit.structure_type} | {audit.record_count} | malformed_lines={audit.malformed_lines} |")
    lines.append("")

    lines.append("## 2. 字段结构、类型和缺失率")
    for audit in audits:
        lines.append("")
        lines.append(f"### {audit.path.name}")
        lines.append("")
        lines.append("| 字段 | 出现数 | 缺失数 | 缺失率 | 类型分布 | 主要取值 |")
        lines.append("|---|---:|---:|---:|---|---|")
        for field_name, stats in sorted(audit.field_stats.items()):
            missing_rate = round(stats.missing / audit.record_count, 4) if audit.record_count else 0
            lines.append(
                f"| {field_name} | {stats.present} | {stats.missing} | {missing_rate:.2%} | "
                f"{format_counter(stats.type_counts)} | {format_counter(stats.values, 12)} |"
            )
    lines.append("")

    lines.append("## 3. 关键业务字段取值")
    append_value_section(lines, audits, "运输方式")
    append_value_section(lines, audits, "费用单位")
    append_value_section(lines, audits, "包装方式")
    append_value_section(lines, audits, "包装类型")
    append_value_section(lines, audits, "适用品种")

    lines.append("## 4. 始发、到达名称质量")
    lines.append("")
    lines.append("| 文件 | 始发空值 | 到达空值 | 明显别名组数 | 别名示例 |")
    lines.append("|---|---:|---:|---:|---|")
    for audit in audits:
        alias_examples = "; ".join(
            f"{key}: {', '.join(values[:4])}"
            for key, values in list(audit.alias_groups.items())[:5]
        )
        lines.append(
            f"| {audit.path.name} | {audit.empty_origin_count} | {audit.empty_destination_count} | "
            f"{len(audit.alias_groups)} | {alias_examples or '-'} |"
        )
    lines.append("")

    lines.append("## 5. 重复记录检查")
    lines.append("")
    lines.append("| 文件 | 完全重复记录数 | 业务键重复记录数 |")
    lines.append("|---|---:|---:|")
    for audit in audits:
        lines.append(f"| {audit.path.name} | {audit.duplicate_exact_count} | {audit.duplicate_business_key_count} |")
    lines.append("")

    lines.append("## 6. 费用质量检查")
    lines.append("")
    lines.append("| 文件 | 费用字段 | 数值数 | 字符串数 | 非数值数 | 负数 | 零值 | 异常值数 | 最小值 | 最大值 | 异常示例 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for audit in audits:
        if not audit.fee_issues:
            lines.append(f"| {audit.path.name} | - | 0 | 0 | 0 | 0 | 0 | 0 | - | - | - |")
            continue
        for issue in audit.fee_issues.values():
            lines.append(
                f"| {audit.path.name} | {issue.field_name} | {issue.numeric_count} | {issue.string_count} | "
                f"{issue.non_numeric_count} | {issue.negative_count} | {issue.zero_count} | {issue.outlier_count} | "
                f"{format_number(issue.min_value)} | {format_number(issue.max_value)} | {', '.join(map(format_number, issue.outlier_examples)) or '-'} |"
            )
    lines.append("")

    lines.append("## 7. 维护日期检查")
    lines.append("")
    lines.append("| 文件 | 空日期数 | 非 YYYY-MM-DD 数 | 日期格式分布 |")
    lines.append("|---|---:|---:|---|")
    for audit in audits:
        lines.append(
            f"| {audit.path.name} | {audit.date_empty_count} | {audit.date_invalid_count} | "
            f"{format_counter(audit.date_formats) or '-'} |"
        )
    lines.append("")

    lines.append("## 8. 可直接形成运输边的字段判断")
    lines.append("")
    lines.append("| 文件 | 可用字段 | 缺少的核心边字段 | 数据用途判断 |")
    lines.append("|---|---|---|---|")
    for audit in audits:
        lines.append(
            f"| {audit.path.name} | {', '.join(sorted(audit.direct_edge_fields)) or '-'} | "
            f"{', '.join(sorted(audit.missing_edge_fields)) or '-'} | {audit.supplemental_role} |"
        )
    lines.append("")

    lines.append("## 9. 对后续模型的约束")
    lines.append("")
    lines.append("- `运价表.json` 可以形成候选 `TransportEdge/FreightRate`，但 `费用单位` 包含 `元/吨`、`元/箱` 等，进入路径搜索前必须结合订单数量、箱量或吨数换算为该段总费用。")
    lines.append("- `地点经纬度.json` 适合作为 `Node` 坐标来源，用于名称匹配、节点建模和候选中转港距离筛选。")
    lines.append("- `其他费用表.json` 是节点附加费用来源，例如作业费、提柜费、装卸费，不能单独作为一条运输边。")
    lines.append("- 当前 JSON 数据没有运输时效字段；散船运时和汽运/驳船/铁路耗时仍需人工输入或其他数据源补充。")
    lines.append("- 当前 JSON 数据没有客户是否有自有码头字段；第二阶段水路链分支需要额外的 `CustomerProfile` 数据补充。")
    lines.append("- 当前 JSON 数据没有统一 node_id；后续必须先做地点名称到 node_id 的标准化映射，特别是南方港口必须保持同一个物理节点只对应一个 node_id。")
    lines.append("")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_value_section(lines: list[str], audits: list[JsonFileAudit], field_name: str) -> None:
    combined: Counter[str] = Counter()
    for audit in audits:
        stats = audit.field_stats.get(field_name)
        if stats:
            combined.update(stats.values)
    lines.append("")
    lines.append(f"### {field_name}")
    lines.append("")
    if not combined:
        lines.append("- 未发现该字段。")
        return
    for value, count in combined.most_common():
        lines.append(f"- `{value}`: {count}")
    lines.append("")


def format_counter(counter: Counter[str], limit: int = 20) -> str:
    if not counter:
        return ""
    return "; ".join(f"{key}:{value}" for key, value in counter.most_common(limit))


def format_number(value: float | None) -> str:
    if value is None:
        return "-"
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = data_dir_from_env()
    audits = audit_data_dir(data_dir)
    write_markdown_report(audits, data_dir, project_root / "docs" / "data_usage_report.md")
    write_summary_csv(audits, project_root / "output" / "data_quality_summary.csv")
    print(f"已审计 JSON 文件数: {len(audits)}")
    print(f"已生成: {project_root / 'docs' / 'data_usage_report.md'}")
    print(f"已生成: {project_root / 'output' / 'data_quality_summary.csv'}")


if __name__ == "__main__":
    main()
