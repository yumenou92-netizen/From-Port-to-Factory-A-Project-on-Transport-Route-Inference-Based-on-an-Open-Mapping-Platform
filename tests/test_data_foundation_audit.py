import json
import zipfile

from src.data.data_foundation_audit import (
    build_data_foundation_audit,
    inspect_bulk_workbook,
    write_audit_outputs,
)
from src.data.loaders import load_real_data_bundle
from src.domain.route_request import RouteRequest


def test_data_foundation_audit_counts_all_freight_locations_and_request_profiles(tmp_path):
    data_dir = write_real_data_fixture(tmp_path)
    workbook_path = write_minimal_bulk_workbook(tmp_path / "散船运价表.xlsx")
    bundle = load_real_data_bundle(data_dir)

    audit = build_data_foundation_audit(
        bundle,
        bulk_workbook_path=workbook_path,
        request_profiles=(RouteRequest(500, "吨", "散粮", "玉米"),),
    )

    assert audit.freight_rate_count == 2
    assert audit.unique_freight_location_count == 3
    assert audit.unresolved_freight_location_count == 1
    assert audit.unresolved_freight_locations == ["未注册客户"]
    assert audit.unresolved_additional_fee_node_count == 1
    assert audit.request_rows[0].billed_candidates == 1
    assert audit.request_rows[0].graph_ready_candidates == 1
    assert audit.request_rows[0].missing_node_candidates == 0
    assert audit.bulk_latest_date_label == "2026-07-06"
    assert [column.scope for column in audit.bulk_columns] == [
        "project_scope_confirmed",
        "project_scope_confirmed",
        "project_scope_needs_confirmation",
        "out_of_scope",
        "out_of_scope",
    ]


def test_write_audit_outputs_creates_markdown_json_and_csv(tmp_path):
    data_dir = write_real_data_fixture(tmp_path / "data")
    workbook_path = write_minimal_bulk_workbook(tmp_path / "散船运价表.xlsx")
    audit = build_data_foundation_audit(
        load_real_data_bundle(data_dir),
        bulk_workbook_path=workbook_path,
        request_profiles=(RouteRequest(500, "吨", "散粮", "玉米"),),
    )

    json_path, markdown_path = write_audit_outputs(audit, tmp_path / "output")

    assert json_path.exists()
    assert markdown_path.exists()
    assert "数据夯实审计" in markdown_path.read_text(encoding="utf-8")
    assert (tmp_path / "output" / "data_foundation_request_profiles.csv").exists()
    assert (tmp_path / "output" / "data_foundation_bulk_workbook_columns.csv").exists()


def test_inspect_bulk_workbook_reads_merged_like_headers_from_previous_destination(tmp_path):
    workbook_path = write_minimal_bulk_workbook(tmp_path / "散船运价表.xlsx")

    columns, latest = inspect_bulk_workbook(workbook_path)

    assert latest == "2026-07-06"
    assert [(column.column, column.destination_label, column.vessel_type) for column in columns[:2]] == [
        ("B", "珠三角", "2-3万吨"),
        ("C", "珠三角", "5-6万吨"),
    ]


def write_real_data_fixture(path):
    path.mkdir(parents=True, exist_ok=True)
    write_json_lines(
        path / "运价表.json",
        [
            {
                "始发": "南港A",
                "到达": "客户A",
                "运输方式": "汽运",
                "包装方式": "散粮",
                "适用品种": "玉米",
                "费用": 20,
                "费用单位": "元/吨",
                "价格来源": "测试来源",
                "维护日期": "2026-04-15",
            },
            {
                "始发": "南港A",
                "到达": "未注册客户",
                "运输方式": "汽运",
                "包装方式": "集装箱",
                "适用品种": "玉米",
                "费用": 500,
                "费用单位": "元/箱",
                "价格来源": "测试来源",
                "维护日期": "2026-04-15",
            },
        ],
    )
    write_json_lines(
        path / "地点经纬度.json",
        [
            {"名称": "南港A", "经度": 110.1, "纬度": 22.1},
            {"名称": "客户A", "经度": 111.1, "纬度": 23.1},
        ],
    )
    write_json_lines(
        path / "其他费用表.json",
        [
            {
                "节点简称": "南港A",
                "包装类型": "散粮",
                "费用类型": "作业费",
                "单价": 8,
                "费用单位": "元/吨",
            },
            {
                "节点简称": "未注册码头",
                "包装类型": "散粮",
                "费用类型": "作业费",
                "单价": 9,
                "费用单位": "元/吨",
            },
        ],
    )
    return path


def write_json_lines(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )


def write_minimal_bulk_workbook(path):
    shared_strings = [
        "散船运价日报表（2026年）",
        "南港区域",
        "珠三角",
        "秀屿",
        "日照",
        "重庆驳船",
        "2-3万吨",
        "5-6万吨",
        "1.3-1.5万吨",
        "1万吨",
        "0.3-0.4万吨",
        "2026-07-06",
    ]
    shared_string_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c></row>
    <row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c><c r="D2" t="s"><v>3</v></c><c r="E2" t="s"><v>4</v></c><c r="F2" t="s"><v>5</v></c></row>
    <row r="3"><c r="B3" t="s"><v>6</v></c><c r="C3" t="s"><v>7</v></c><c r="D3" t="s"><v>8</v></c><c r="E3" t="s"><v>9</v></c><c r="F3" t="s"><v>10</v></c></row>
    <row r="4"><c r="A4" t="s"><v>11</v></c><c r="B4"><v>50</v></c><c r="C4"><v>48</v></c><c r="D4"><v>45</v></c><c r="E4"><v>37</v></c><c r="F4"><v>65</v></c></row>
  </sheetData>
</worksheet>"""
    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="散船运价表" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_string_xml)
    return path
