from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence
from xml.etree import ElementTree

from src.data.loaders import RealDataBundle, data_dir_from_env, load_real_data_bundle
from src.domain.route_request import RouteRequest


BULK_RATE_FILE_NAME = "散船运价表.xlsx"
TARGET_DESTINATION_LABELS = {
    "马尾",
    "揭阳",
    "漳州",
    "珠三角",
    "茂名/阳江",
    "湛江",
    "铁山",
    "钦州",
    "防城港",
    "马村/海口",
}
TARGET_BUT_UNCONFIRMED_LABELS = {"秀屿"}
OUT_OF_SCOPE_DESTINATION_LABELS = {"日照", "潍坊", "长三角", "重庆驳船"}
DEFAULT_OUTPUT_DIR = Path("output")


@dataclass(frozen=True)
class RequestAuditRow:
    quantity: str
    quantity_unit: str
    package_type: str
    commodity: str
    billed_candidates: int
    graph_ready_candidates: int
    missing_node_candidates: int
    manual_review_items: int
    skipped_packaging: int
    skipped_product: int


@dataclass(frozen=True)
class BulkWorkbookColumn:
    column: str
    destination_label: str
    vessel_type: str
    latest_value: str | None
    scope: str
    note: str


@dataclass(frozen=True)
class FoundationAudit:
    data_dir: str
    freight_rate_count: int
    coordinate_count: int
    additional_fee_count: int
    unique_freight_location_count: int
    unresolved_freight_location_count: int
    unresolved_additional_fee_node_count: int
    transport_modes: dict[str, int]
    package_types: dict[str, int]
    fee_units: dict[str, int]
    request_rows: list[RequestAuditRow]
    bulk_workbook_path: str | None
    bulk_latest_date_label: str | None
    bulk_columns: list[BulkWorkbookColumn]
    unresolved_freight_locations: list[str]
    unresolved_additional_fee_nodes: list[str]


def build_data_foundation_audit(
    bundle: RealDataBundle,
    *,
    bulk_workbook_path: Path | None = None,
    request_profiles: Sequence[RouteRequest] | None = None,
) -> FoundationAudit:
    registry = bundle.node_registry
    freight_locations = sorted(
        {
            value
            for rate in bundle.freight_rates
            for value in (rate.origin_name, rate.destination_name)
            if value
        }
    )
    unresolved_freight_locations = (
        [name for name in freight_locations if registry is None or registry.lookup(name) is None]
        if freight_locations
        else []
    )
    additional_fee_nodes = sorted({fee.node_name for fee in bundle.additional_fees if fee.node_name})
    unresolved_additional_fee_nodes = (
        [name for name in additional_fee_nodes if registry is None or registry.lookup(name) is None]
        if additional_fee_nodes
        else []
    )

    request_rows = [
        audit_request_profile(bundle, request)
        for request in (request_profiles or default_request_profiles(bundle))
    ]

    bulk_columns: list[BulkWorkbookColumn] = []
    latest_date_label: str | None = None
    if bulk_workbook_path is not None:
        bulk_columns, latest_date_label = inspect_bulk_workbook(bulk_workbook_path)

    return FoundationAudit(
        data_dir=str(bundle.data_dir),
        freight_rate_count=len(bundle.freight_rates),
        coordinate_count=len(bundle.nodes),
        additional_fee_count=len(bundle.additional_fees),
        unique_freight_location_count=len(freight_locations),
        unresolved_freight_location_count=len(unresolved_freight_locations),
        unresolved_additional_fee_node_count=len(unresolved_additional_fee_nodes),
        transport_modes=dict(sorted(bundle.transport_modes.items())),
        package_types=dict(sorted(bundle.packaging_types.items())),
        fee_units=dict(sorted(bundle.fee_units.items())),
        request_rows=request_rows,
        bulk_workbook_path=str(bulk_workbook_path) if bulk_workbook_path else None,
        bulk_latest_date_label=latest_date_label,
        bulk_columns=bulk_columns,
        unresolved_freight_locations=unresolved_freight_locations,
        unresolved_additional_fee_nodes=unresolved_additional_fee_nodes,
    )


def audit_request_profile(bundle: RealDataBundle, request: RouteRequest) -> RequestAuditRow:
    from src.data.loaders import build_order_edge_candidates_for_request

    result = build_order_edge_candidates_for_request(bundle, request)
    return RequestAuditRow(
        quantity=str(request.quantity),
        quantity_unit=request.quantity_unit,
        package_type=request.package_type,
        commodity=request.commodity,
        billed_candidates=len(result.candidates),
        graph_ready_candidates=len(result.graph_ready_candidates),
        missing_node_candidates=result.missing_node_candidate_count,
        manual_review_items=result.manual_review_count,
        skipped_packaging=result.skipped_packaging,
        skipped_product=result.skipped_product,
    )


def default_request_profiles(bundle: RealDataBundle) -> tuple[RouteRequest, ...]:
    profiles = [RouteRequest(500, "吨", "散粮", "玉米")]
    seen = {("吨", "散粮", "玉米")}
    package_counter = Counter(rate.package_type for rate in bundle.freight_rates)
    commodity_counter: Counter[str] = Counter()
    unit_by_package: dict[str, Counter[str]] = defaultdict(Counter)
    for rate in bundle.freight_rates:
        unit = unit_from_price_unit(rate.raw_price_unit)
        if unit:
            unit_by_package[rate.package_type][unit] += 1
        for commodity in split_commodity_scope(rate.commodity_scope):
            commodity_counter[commodity] += 1

    for package_type, _ in package_counter.most_common(6):
        unit = unit_by_package[package_type].most_common(1)[0][0] if unit_by_package[package_type] else "吨"
        quantity = Decimal("500")
        for commodity, _ in commodity_counter.most_common(8):
            key = (unit, package_type, commodity)
            if key in seen:
                continue
            profiles.append(RouteRequest(quantity, unit, package_type, commodity))
            seen.add(key)
            break
    return tuple(profiles[:8])


def split_commodity_scope(value: str) -> tuple[str, ...]:
    parts = [part.strip() for part in re.split(r"[、,，/；;]+", value or "") if part.strip()]
    return tuple(parts or (value.strip(),)) if value else ()


def unit_from_price_unit(value: str) -> str | None:
    text = str(value or "").strip()
    if "/" not in text:
        return None
    return text.rsplit("/", 1)[-1].strip() or None


def find_bulk_workbook(data_dir: Path) -> Path | None:
    matches = sorted(data_dir.rglob(BULK_RATE_FILE_NAME))
    return matches[0] if matches else None


def inspect_bulk_workbook(path: Path) -> tuple[list[BulkWorkbookColumn], str | None]:
    rows = read_xlsx_first_sheet(path)
    if len(rows) < 3:
        return [], None
    header_row = rows[1]
    vessel_row = rows[2]
    latest_index = latest_nonblank_row_index(rows, start_index=3)
    latest_row = rows[latest_index] if latest_index is not None else []
    latest_date_label = cell_text(latest_row, 0) if latest_index is not None else None

    max_cols = max(len(header_row), len(vessel_row), len(latest_row))
    columns: list[BulkWorkbookColumn] = []
    previous_destination = ""
    for col_index in range(1, max_cols):
        destination = cell_text(header_row, col_index) or previous_destination
        if cell_text(header_row, col_index):
            previous_destination = destination
        vessel = cell_text(vessel_row, col_index)
        if not destination and not vessel:
            continue
        latest_value = cell_text(latest_row, col_index) if latest_index is not None else None
        scope, note = classify_bulk_destination(destination)
        columns.append(
            BulkWorkbookColumn(
                column=excel_column_name(col_index + 1),
                destination_label=destination,
                vessel_type=vessel,
                latest_value=latest_value or None,
                scope=scope,
                note=note,
            )
        )
    return columns, latest_date_label


def classify_bulk_destination(destination: str) -> tuple[str, str]:
    if destination in TARGET_DESTINATION_LABELS:
        return "project_scope_confirmed", "目标省区且已有船型资格口径"
    if destination in TARGET_BUT_UNCONFIRMED_LABELS:
        return "project_scope_needs_confirmation", "目标省区内目的地，但尚未进入已确认船型资格表"
    if destination in OUT_OF_SCOPE_DESTINATION_LABELS:
        return "out_of_scope", "非本阶段广东/广西/福建/海南目标范围或非散船干线"
    return "needs_review", "未识别目的地标签，需要人工判断是否属于项目范围"


def read_xlsx_first_sheet(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = read_shared_strings(archive)
        sheet_name = first_sheet_path(archive)
        root = ElementTree.fromstring(archive.read(sheet_name))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            reference = cell.attrib.get("r", "")
            col_index = column_index_from_reference(reference)
            values[col_index] = read_cell_value(cell, shared_strings)
        if values:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
    return rows


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values: list[str] = []
    for item in root.findall("x:si", namespace):
        text_parts = [node.text or "" for node in item.findall(".//x:t", namespace)]
        values.append("".join(text_parts))
    return values


def first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    main_ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    first_sheet = workbook.find(".//x:sheets/x:sheet", main_ns)
    if first_sheet is None:
        raise ValueError("工作簿没有工作表。")
    relationship_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    for rel in rels.findall("r:Relationship", rel_ns):
        if rel.attrib.get("Id") == relationship_id:
            target = rel.attrib["Target"]
            return "xl/" + target.lstrip("/")
    raise ValueError("无法定位第一个工作表。")


def read_cell_value(cell: ElementTree.Element, shared_strings: Sequence[str]) -> str:
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text = "".join(node.text or "" for node in cell.findall(".//x:t", namespace))
        return text.strip()
    value_node = cell.find("x:v", namespace)
    if value_node is None or value_node.text is None:
        return ""
    raw_value = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except (ValueError, IndexError):
            return raw_value
    return raw_value


def latest_nonblank_row_index(rows: Sequence[Sequence[str]], *, start_index: int) -> int | None:
    latest: int | None = None
    for index in range(start_index, len(rows)):
        if any(str(value).strip() for value in rows[index]):
            latest = index
    return latest


def cell_text(row: Sequence[str], index: int) -> str:
    return str(row[index]).strip() if index < len(row) else ""


def column_index_from_reference(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha()).upper()
    value = 0
    for char in letters:
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def excel_column_name(one_based_index: int) -> str:
    result = ""
    value = one_based_index
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def write_audit_outputs(audit: FoundationAudit, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "data_foundation_audit.json"
    markdown_path = output_dir / "data_foundation_audit.md"
    json_path.write_text(
        json.dumps(to_jsonable(asdict(audit)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(audit), encoding="utf-8")
    write_csv(
        output_dir / "data_foundation_request_profiles.csv",
        [asdict(row) for row in audit.request_rows],
    )
    write_csv(
        output_dir / "data_foundation_bulk_workbook_columns.csv",
        [asdict(column) for column in audit.bulk_columns],
    )
    write_csv(
        output_dir / "data_foundation_unresolved_locations.csv",
        [{"name": name, "scope": "freight_rate"} for name in audit.unresolved_freight_locations]
        + [{"name": name, "scope": "additional_fee"} for name in audit.unresolved_additional_fee_nodes],
    )
    return json_path, markdown_path


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def render_markdown(audit: FoundationAudit) -> str:
    lines = [
        "# 数据夯实审计",
        "",
        "本报告由只读脚本生成；不写回真实数据、不调用 Tencent、不自动确认节点或别名。",
        "",
        "## 1. 总览",
        "",
        f"- 运价记录：{audit.freight_rate_count}",
        f"- 坐标节点：{audit.coordinate_count}",
        f"- AdditionalFee 原始记录：{audit.additional_fee_count}",
        f"- 运价表不同地点名称：{audit.unique_freight_location_count}",
        f"- 运价地点未注册数量：{audit.unresolved_freight_location_count}",
        f"- AdditionalFee 节点未注册数量：{audit.unresolved_additional_fee_node_count}",
        "",
        "## 2. 订单口径覆盖",
        "",
        "| 订单 | 已计费候选 | 端点完整候选 | 缺节点候选 | 人工复核 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in audit.request_rows:
        order = f"{row.quantity}{row.quantity_unit}/{row.package_type}/{row.commodity}"
        lines.append(
            f"| {order} | {row.billed_candidates} | {row.graph_ready_candidates} | "
            f"{row.missing_node_candidates} | {row.manual_review_items} |"
        )
    lines.extend(
        [
            "",
            "## 3. 散船运价表列审计",
            "",
            f"- 工作簿：{audit.bulk_workbook_path or '未找到'}",
            f"- 最新数据行标签：{audit.bulk_latest_date_label or '未识别'}",
            "",
            "| 列 | 目的标签 | 船型 | 最新值 | 范围判断 | 说明 |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for column in audit.bulk_columns:
        lines.append(
            f"| {column.column} | {column.destination_label} | {column.vessel_type} | "
            f"{column.latest_value or ''} | {column.scope} | {column.note} |"
        )
    if audit.unresolved_freight_locations or audit.unresolved_additional_fee_nodes:
        lines.extend(["", "## 4. 需人工处理的节点", ""])
        for name in audit.unresolved_freight_locations:
            lines.append(f"- 运价端点未注册：{name}")
        for name in audit.unresolved_additional_fee_nodes:
            lines.append(f"- AdditionalFee 节点未注册：{name}")
    else:
        lines.extend(["", "## 4. 需人工处理的节点", "", "- 当前运价端点和 AdditionalFee 节点均已能匹配现有节点注册表。"])
    lines.extend(
        [
            "",
            "## 5. 使用建议",
            "",
            "- 若更换 Demo 订单，先看“订单口径覆盖”是否出现缺节点候选或人工复核激增。",
            "- W2 前先处理散船运价表中 `project_scope_needs_confirmation` 和 `needs_review` 的目的标签。",
            "- W3 前先补齐全部相关南港的节点画像、目的组映射、所在地标签和散粮/散船能力。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成阶段 18 前的数据夯实只读审计。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bulk-workbook", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    bundle = load_real_data_bundle(data_dir_from_env())
    bulk_workbook = args.bulk_workbook or find_bulk_workbook(bundle.data_dir)
    audit = build_data_foundation_audit(bundle, bulk_workbook_path=bulk_workbook)
    json_path, markdown_path = write_audit_outputs(audit, args.output_dir)
    print("数据夯实审计已生成")
    print(f"Markdown: {markdown_path}")
    print(f"JSON: {json_path}")
    print(f"运价地点未注册：{audit.unresolved_freight_location_count}")
    print(f"AdditionalFee 节点未注册：{audit.unresolved_additional_fee_node_count}")
    print(f"散船运价表列数：{len(audit.bulk_columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
