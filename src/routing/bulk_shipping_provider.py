from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree

from src.domain.cost_rules import CostCalculationResult
from src.domain.freight_rate import FreightRate, create_freight_rate
from src.domain.route_request import RouteRequest
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_contracts import CostComponent


BULK_SHIPPING_RULE_ID = "bulk_shipping_real_workbook_rate"
BULK_SHIPPING_RULE_VERSION = "1.0"
BULK_SHIPPING_TIME_RULE_ID = "bulk_shipping_region_complete_segment_time"
BULK_SHIPPING_TIME_RULE_VERSION = "1.0"

PROJECT_DESTINATION_LABELS = {
    "马尾",
    "秀屿",
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

OUT_OF_SCOPE_DESTINATION_LABELS = {"日照", "潍坊", "长三角", "重庆驳船"}

REGION_DAYS = {
    "福建": Decimal("4"),
    "珠三角": Decimal("6"),
    "粤西": Decimal("7"),
    "海南": Decimal("7"),
    "广西": Decimal("7"),
}


class BulkShippingError(ValueError):
    """Raised when real bulk-shipping data cannot be interpreted safely."""


@dataclass(frozen=True)
class BulkRateColumn:
    destination_label: str
    vessel_type: str
    rate_yuan_per_ton: Decimal
    cell_ref: str
    latest_date_label: str
    workbook_path: str
    scope: str

    @property
    def source_ref(self) -> str:
        return (
            f"{self.workbook_path}#latest={self.latest_date_label}"
            f"#destination={self.destination_label}#vessel={self.vessel_type}#cell={self.cell_ref}"
        )


@dataclass(frozen=True)
class VesselCapacity:
    vessel_type: str
    min_tons: Decimal
    max_tons: Decimal

    @property
    def representative_tons(self) -> Decimal:
        return self.max_tons


@dataclass(frozen=True)
class BulkShippingMatch:
    status: str
    message: str
    rate_column: BulkRateColumn | None = None
    destination_label: str | None = None
    shipping_time_region: str | None = None
    capacity: VesselCapacity | None = None
    total_cost_yuan: Decimal | None = None
    duration_hours: Decimal | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class BulkShippingWorkbook:
    def __init__(self, columns: Sequence[BulkRateColumn]) -> None:
        self.columns = tuple(columns)

    @classmethod
    def load(cls, path: Path) -> "BulkShippingWorkbook":
        if not path.exists():
            raise BulkShippingError(f"散船运价表不存在：{path}")
        rows = _read_xlsx_first_sheet(path)
        if len(rows) < 4:
            raise BulkShippingError("散船运价表至少需要标题行、目的行、船型行和一行报价。")
        destination_row = rows[1]
        vessel_row = rows[2]
        latest_index = _latest_nonblank_row_index(rows, start_index=3)
        if latest_index is None:
            raise BulkShippingError("散船运价表缺少有效报价行。")
        latest_row = rows[latest_index]
        latest_label = _cell_text(latest_row, 0)
        if not latest_label:
            raise BulkShippingError("散船运价表最新报价行缺少日期标签。")

        columns: list[BulkRateColumn] = []
        previous_destination = ""
        max_cols = max(len(destination_row), len(vessel_row), len(latest_row))
        for col_index in range(1, max_cols):
            explicit_destination = _cell_text(destination_row, col_index)
            if explicit_destination:
                previous_destination = explicit_destination
            destination = explicit_destination or previous_destination
            vessel = _cell_text(vessel_row, col_index)
            value = _cell_text(latest_row, col_index)
            if not destination and not vessel:
                continue
            scope = classify_destination_scope(destination)
            if scope != "project_scope_confirmed":
                continue
            if not value:
                continue
            try:
                rate = _positive_decimal(value, "散船报价")
            except BulkShippingError as exc:
                raise BulkShippingError(
                    f"散船运价表 {latest_label} {destination}/{vessel} 报价无效：{exc}"
                ) from None
            columns.append(
                BulkRateColumn(
                    destination_label=destination,
                    vessel_type=vessel,
                    rate_yuan_per_ton=rate,
                    cell_ref=f"{_excel_column_name(col_index + 1)}{latest_index + 1}",
                    latest_date_label=latest_label,
                    workbook_path=str(path),
                    scope=scope,
                )
            )
        return cls(columns)

    def match(self, port_name: str, request: RouteRequest) -> BulkShippingMatch:
        if request.quantity_unit != "吨" or request.package_type != "散粮":
            return BulkShippingMatch(
                status="manual_review",
                message="散船真实运价当前只支持散粮订单，且订单单位必须为吨。",
            )
        destination_label, time_region = classify_bulk_shipping_destination(port_name)
        if destination_label is None or time_region is None:
            return BulkShippingMatch(
                status="manual_review",
                message=f"南港 {port_name} 缺少已确认散船费率目的组或航运总时效分区。",
            )
        candidate_columns = [
            column
            for column in self.columns
            if column.destination_label == destination_label
        ]
        if not candidate_columns:
            return BulkShippingMatch(
                status="manual_review",
                message=f"散船运价表最新行缺少目的组 {destination_label} 的可用报价。",
                destination_label=destination_label,
                shipping_time_region=time_region,
            )

        capacities: list[tuple[BulkRateColumn, VesselCapacity]] = []
        for column in candidate_columns:
            capacity = parse_vessel_capacity(column.vessel_type)
            if capacity is not None:
                capacities.append((column, capacity))
        if not capacities:
            return BulkShippingMatch(
                status="manual_review",
                message=f"目的组 {destination_label} 没有可解析船型。",
                destination_label=destination_label,
                shipping_time_region=time_region,
            )

        quantity = Decimal(str(request.quantity))
        eligible = [
            (column, capacity)
            for column, capacity in capacities
            if capacity.max_tons >= quantity
        ]
        if not eligible:
            max_capacity = max(capacity.max_tons for _, capacity in capacities)
            return BulkShippingMatch(
                status="manual_review",
                message=(
                    f"订单 {quantity} 吨超过目的组 {destination_label} "
                    f"全部可用船型最大承载 {max_capacity} 吨。"
                ),
                destination_label=destination_label,
                shipping_time_region=time_region,
            )

        selected_column, selected_capacity = sorted(
            eligible,
            key=lambda item: (
                item[1].representative_tons,
                item[0].rate_yuan_per_ton,
                item[0].vessel_type,
            ),
        )[0]
        days = REGION_DAYS[time_region]
        duration_hours = days * Decimal("24")
        total_cost = selected_column.rate_yuan_per_ton * quantity
        return BulkShippingMatch(
            status="resolved",
            message=(
                f"已匹配目的组 {destination_label}、船型 {selected_column.vessel_type}；"
                f"航运总时效分区 {time_region}={days}天。"
            ),
            rate_column=selected_column,
            destination_label=destination_label,
            shipping_time_region=time_region,
            capacity=selected_capacity,
            total_cost_yuan=total_cost,
            duration_hours=duration_hours,
        )


def classify_destination_scope(destination: str) -> str:
    if destination in PROJECT_DESTINATION_LABELS:
        return "project_scope_confirmed"
    if destination in OUT_OF_SCOPE_DESTINATION_LABELS:
        return "out_of_scope"
    return "needs_review"


def classify_bulk_shipping_destination(port_name: str) -> tuple[str | None, str | None]:
    name = str(port_name).strip()
    rules = (
        ("马尾", "马尾", "福建"),
        ("秀屿", "秀屿", "福建"),
        ("漳州", "漳州", "福建"),
        ("揭阳", "揭阳", "珠三角"),
        ("茂名", "茂名/阳江", "粤西"),
        ("阳江", "茂名/阳江", "粤西"),
        ("湛江", "湛江", "粤西"),
        ("铁山", "铁山", "广西"),
        ("钦州", "钦州", "广西"),
        ("防城港", "防城港", "广西"),
        ("马村", "马村/海口", "海南"),
        ("海口", "马村/海口", "海南"),
        ("深圳", "珠三角", "珠三角"),
        ("蛇口", "珠三角", "珠三角"),
        ("广州", "珠三角", "珠三角"),
        ("黄埔", "珠三角", "珠三角"),
        ("东莞", "珠三角", "珠三角"),
        ("新沙", "珠三角", "珠三角"),
    )
    for keyword, destination_label, region in rules:
        if keyword in name:
            return destination_label, region
    return None, None


def parse_vessel_capacity(vessel_type: str) -> VesselCapacity | None:
    text = str(vessel_type).strip()
    if not text:
        return None
    normalized = text.replace("—", "-").replace("－", "-").replace("–", "-")
    match = re.search(r"(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?", normalized)
    if match is None:
        return None
    start = Decimal(match.group(1)) * Decimal("10000")
    end = Decimal(match.group(2)) * Decimal("10000") if match.group(2) else start
    if end < start:
        start, end = end, start
    return VesselCapacity(vessel_type=text, min_tons=start, max_tons=end)


def make_bulk_shipping_rate(
    origin_name: str,
    origin_node_id: str,
    port_name: str,
    port_node_id: str,
    request: RouteRequest,
    match: BulkShippingMatch,
) -> FreightRate:
    if not match.is_resolved or match.rate_column is None:
        raise BulkShippingError("未解析的散船运价不能生成 FreightRate。")
    return create_freight_rate(
        origin_name=origin_name,
        destination_name=port_name,
        transport_mode="散船",
        package_type=request.package_type,
        commodity_scope=request.commodity,
        raw_price=match.rate_column.rate_yuan_per_ton,
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source=f"real_business_data:{match.rate_column.source_ref}",
        from_node_id=origin_node_id,
        to_node_id=port_node_id,
        source_file="散船运价表.xlsx",
    )


def make_bulk_shipping_cost_result(request: RouteRequest, match: BulkShippingMatch) -> CostCalculationResult:
    if not match.is_resolved or match.rate_column is None or match.total_cost_yuan is None:
        return CostCalculationResult(
            status="manual_review",
            total_cost_yuan=None,
            rule_id=BULK_SHIPPING_RULE_ID,
            rule_version=BULK_SHIPPING_RULE_VERSION,
            calculation_detail=match.message,
            price_source="real_business_data:散船运价表.xlsx",
            transport_mode="散船",
            rate_packaging=request.package_type,
            price_unit="元/吨",
            message=match.message,
        )
    return CostCalculationResult(
        status="valid",
        total_cost_yuan=match.total_cost_yuan,
        rule_id=BULK_SHIPPING_RULE_ID,
        rule_version=BULK_SHIPPING_RULE_VERSION,
        calculation_detail=(
            f"{match.rate_column.destination_label}/{match.rate_column.vessel_type}："
            f"{match.rate_column.rate_yuan_per_ton}元/吨×"
            f"{request.quantity}{request.quantity_unit}={match.total_cost_yuan}元；"
            f"来源={match.rate_column.source_ref}"
        ),
        price_source=f"real_business_data:{match.rate_column.source_ref}",
        transport_mode="散船",
        rate_packaging=request.package_type,
        price_unit="元/吨",
        message="已按真实散船运价表计算北港至南港散船干线费用。",
    )


def make_bulk_shipping_time_result(port_name: str, match: BulkShippingMatch) -> ShippingTimeResult:
    if not match.is_resolved or match.duration_hours is None or match.shipping_time_region is None:
        return ShippingTimeResult(
            status="manual_review",
            duration_hours=None,
            source="confirmed_region_shipping_total_time",
            message=match.message,
            stage=f"北港至{port_name}",
            transport_mode="散船",
            time_scope="complete_segment",
        )
    days = REGION_DAYS[match.shipping_time_region]
    return ShippingTimeResult(
        status="resolved",
        duration_hours=match.duration_hours,
        source="confirmed_region_shipping_total_time",
        message=(
            f"已按领导确认口径采用{match.shipping_time_region}航运总时效："
            f"{days}天×24={match.duration_hours}小时；模型不拆分等待、装卸和航行组成。"
        ),
        stage=f"北港至{port_name}",
        transport_mode="散船",
        input_value=str(days),
        input_unit="天",
        time_scope="complete_segment",
    )


def make_bulk_shipping_cost_component(match: BulkShippingMatch) -> CostComponent:
    if not match.is_resolved or match.rate_column is None or match.total_cost_yuan is None:
        raise BulkShippingError("未解析的散船运价不能生成费用组成。")
    return CostComponent(
        component_type="bulk_shipping_freight",
        amount_yuan=match.total_cost_yuan,
        source_type="real_data",
        source=match.rate_column.source_ref,
        rule_id=BULK_SHIPPING_RULE_ID,
        rule_version=BULK_SHIPPING_RULE_VERSION,
        calculation_detail=(
            f"{match.rate_column.rate_yuan_per_ton}元/吨×当前订单吨数"
            f"={match.total_cost_yuan}元；船型={match.rate_column.vessel_type}"
        ),
    )


def _read_xlsx_first_sheet(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_name = _first_sheet_path(archive)
        root = ElementTree.fromstring(archive.read(sheet_name))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            reference = cell.attrib.get("r", "")
            col_index = _column_index_from_reference(reference)
            values[col_index] = _read_cell_value(cell, shared_strings)
        if values:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
    return rows


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
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


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    main_ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    first_sheet = workbook.find(".//x:sheets/x:sheet", main_ns)
    if first_sheet is None:
        raise BulkShippingError("散船运价工作簿没有工作表。")
    relationship_id = first_sheet.attrib[
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    ]
    for rel in rels.findall("r:Relationship", rel_ns):
        if rel.attrib.get("Id") == relationship_id:
            return "xl/" + rel.attrib["Target"].lstrip("/")
    raise BulkShippingError("无法定位散船运价工作簿第一个工作表。")


def _read_cell_value(cell: ElementTree.Element, shared_strings: Sequence[str]) -> str:
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", namespace)).strip()
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


def _latest_nonblank_row_index(rows: Sequence[Sequence[str]], *, start_index: int) -> int | None:
    latest: int | None = None
    for index in range(start_index, len(rows)):
        if any(str(value).strip() for value in rows[index]):
            latest = index
    return latest


def _cell_text(row: Sequence[str], index: int) -> str:
    return str(row[index]).strip() if index < len(row) else ""


def _column_index_from_reference(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha()).upper()
    value = 0
    for char in letters:
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _excel_column_name(one_based_index: int) -> str:
    result = ""
    value = one_based_index
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _positive_decimal(value: object, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise BulkShippingError(f"{field_name}必须是大于 0 的有限数值。") from None
    if not number.is_finite() or number <= 0:
        raise BulkShippingError(f"{field_name}必须是大于 0 的有限数值。")
    return number
