from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from src.routing.bulk_shipping_provider import (
    BulkShippingWorkbook,
    classify_bulk_shipping_destination,
    make_bulk_shipping_cost_result,
    make_bulk_shipping_time_result,
    parse_vessel_capacity,
)
from src.domain.route_request import RouteRequest


def test_workbook_loads_latest_project_columns_and_selects_smallest_eligible_vessel(tmp_path):
    workbook_path = write_bulk_workbook(tmp_path / "散船运价表.xlsx")
    workbook = BulkShippingWorkbook.load(workbook_path)

    assert [(column.destination_label, column.vessel_type) for column in workbook.columns] == [
        ("珠三角", "2-3万吨"),
        ("珠三角", "5-6万吨"),
        ("钦州", "2.5-3万吨"),
    ]

    request = RouteRequest(500, "吨", "散粮", "玉米")
    match = workbook.match("东莞新沙港", request)

    assert match.is_resolved
    assert match.destination_label == "珠三角"
    assert match.shipping_time_region == "珠三角"
    assert match.rate_column is not None
    assert match.rate_column.vessel_type == "2-3万吨"
    assert match.rate_column.rate_yuan_per_ton == Decimal("50")
    assert match.total_cost_yuan == Decimal("25000")
    assert match.duration_hours == Decimal("144")


def test_bulk_shipping_cost_and_time_results_are_traceable(tmp_path):
    workbook = BulkShippingWorkbook.load(write_bulk_workbook(tmp_path / "散船运价表.xlsx"))
    request = RouteRequest(2450, "吨", "散粮", "小麦")
    match = workbook.match("钦州港", request)

    cost_result = make_bulk_shipping_cost_result(request, match)
    time_result = make_bulk_shipping_time_result("钦州港", match)

    assert cost_result.status == "valid"
    assert cost_result.total_cost_yuan == Decimal("161700")
    assert cost_result.price_unit == "元/吨"
    assert cost_result.rule_id == "bulk_shipping_real_workbook_rate"
    assert "散船运价表.xlsx" in cost_result.price_source
    assert time_result.status == "resolved"
    assert time_result.duration_hours == Decimal("168")
    assert time_result.time_scope == "complete_segment"
    assert "模型不拆分" in time_result.message


def test_order_over_largest_vessel_requires_manual_review(tmp_path):
    workbook = BulkShippingWorkbook.load(write_bulk_workbook(tmp_path / "散船运价表.xlsx"))
    request = RouteRequest(70000, "吨", "散粮", "玉米")

    match = workbook.match("东莞新沙港", request)

    assert not match.is_resolved
    assert "超过目的组 珠三角 全部可用船型最大承载" in match.message


def test_unmapped_port_requires_manual_review_without_guessing(tmp_path):
    workbook = BulkShippingWorkbook.load(write_bulk_workbook(tmp_path / "散船运价表.xlsx"))

    match = workbook.match("贵港白沙码头", RouteRequest(500, "吨", "散粮", "玉米"))

    assert not match.is_resolved
    assert "缺少已确认散船费率目的组" in match.message


def test_vessel_capacity_parses_single_values_and_ranges():
    single = parse_vessel_capacity("1万吨")
    ranged = parse_vessel_capacity("1.5-1.6万吨")

    assert single is not None
    assert single.min_tons == Decimal("10000")
    assert single.max_tons == Decimal("10000")
    assert ranged is not None
    assert ranged.min_tons == Decimal("15000")
    assert ranged.max_tons == Decimal("16000")


def test_destination_classifier_uses_confirmed_business_groups():
    assert classify_bulk_shipping_destination("广州新港") == ("珠三角", "珠三角")
    assert classify_bulk_shipping_destination("秀屿港") == ("秀屿", "福建")
    assert classify_bulk_shipping_destination("揭阳港") == ("揭阳", "珠三角")
    assert classify_bulk_shipping_destination("阳江港") == ("茂名/阳江", "粤西")
    assert classify_bulk_shipping_destination("钟山站") == (None, None)


def write_bulk_workbook(path: Path) -> Path:
    rows = [
        [cell("A1", "散船运价日报表")],
        [
            cell("A2", "日期"),
            cell("B2", "珠三角"),
            cell("C2", ""),
            cell("D2", "钦州"),
            cell("E2", "日照"),
        ],
        [
            cell("A3", ""),
            cell("B3", "2-3万吨"),
            cell("C3", "5-6万吨"),
            cell("D3", "2.5-3万吨"),
            cell("E3", "1万吨"),
        ],
        [
            cell("A4", "7/5 周日"),
            cell("B4", "55"),
            cell("C4", "53"),
            cell("D4", "70"),
            cell("E4", "37"),
        ],
        [
            cell("A5", "7/6 周一"),
            cell("B5", "50"),
            cell("C5", "48"),
            cell("D5", "66"),
            cell("E5", "36"),
        ],
    ]
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml(rows))
    return path


def cell(ref: str, value: str) -> str:
    if value == "":
        return f'<c r="{ref}"/>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'


def sheet_xml(rows: list[list[str]]) -> str:
    body = []
    for index, row in enumerate(rows, start=1):
        body.append(f'<row r="{index}">{"".join(row)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="散船运价表" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
