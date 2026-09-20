import json
from decimal import Decimal

from openpyxl import Workbook

from src.data.loaders import NodeRecord, make_node_id
from src.data.rail_container_data import (
    load_rail_container_local_data,
    load_rail_container_runtime_data,
)
from src.domain.node_registry import build_node_registry


def _registry():
    return build_node_registry(
        (
            NodeRecord(make_node_id("北站"), "北站", 122.0, 46.0),
            NodeRecord(make_node_id("南站"), "南站", 118.0, 25.0),
            NodeRecord(make_node_id("客户"), "客户", 118.1, 25.1),
            NodeRecord(make_node_id("第三方专用线"), "第三方专用线", 118.2, 25.2),
        ),
        auto_alias=False,
    )


def _write_table(workbook, name, headers, rows):
    sheet = workbook.create_sheet(name)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)


def _source(source_id, table_type, sheet_name, fields, defaults=None):
    return {
        "source_id": source_id,
        "table_type": table_type,
        "workbook": "铁路测试.xlsx",
        "sheet_name": sheet_name,
        "field_mapping": {field: header for field, header in fields.items()},
        "defaults": defaults or {},
    }


def _manifest(tmp_path, *, include_fee=True):
    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_table(
        workbook,
        "站点",
        ["站点", "角色", "省", "市", "经度", "纬度"],
        [["北站", "north", "东北", "哈尔滨市", "122", "46"], ["南站", "south", "福建省", "福州市", "118", "25"]],
    )
    _write_table(
        workbook,
        "费率",
        ["发站", "到站", "费用", "单位", "品种", "贸易", "箱型", "状态"],
        [["北站", "南站", "650", "元/组", "玉米、小麦", "内贸", "敞顶箱", "confirmed"]],
    )
    _write_table(workbook, "时效", ["始发区域", "到达区域", "小时", "状态"], [["东北", "福建省", "168", "confirmed"]])
    _write_table(
        workbook,
        "直达",
        ["南站", "客户", "品种", "贸易", "箱型", "距离", "距离来源", "小时", "时效来源", "状态"],
        [["南站", "客户", "玉米", "内贸", "敞顶箱", "10", "腾讯地图", "2", "腾讯地图", "confirmed"]],
    )
    if include_fee:
        _write_table(workbook, "站费", ["站点", "费用", "状态"], [["北站", "136.5", "confirmed"], ["南站", "136.5", "confirmed"]])
    workbook.save(tmp_path / "铁路测试.xlsx")
    station_fields = {
        "station_name": "站点", "station_role": "角色", "province": "省", "city": "市",
        "longitude": "经度", "latitude": "纬度",
    }
    sources = [
        _source("station", "station_master", "站点", station_fields),
        _source(
            "rate",
            "trunk_rate",
            "费率",
            {
                "north_station_name": "发站", "south_station_name": "到站", "base_freight": "费用",
                "base_freight_unit": "单位", "commodity_scope": "品种", "trade_type": "贸易",
                "container_type": "箱型", "confirmation_status": "状态",
            },
        ),
        _source(
            "time", "time_region", "时效",
            {"origin_region": "始发区域", "destination_region": "到达区域", "duration_hours": "小时", "confirmation_status": "状态"},
        ),
        _source(
            "truck", "direct_truck", "直达",
            {
                "south_station_name": "南站", "customer_name": "客户", "commodity_scope": "品种",
                "trade_type": "贸易", "container_type": "箱型", "distance_km": "距离",
                "distance_source": "距离来源", "duration_hours": "小时", "time_source": "时效来源",
                "confirmation_status": "状态",
            },
        ),
    ]
    if include_fee:
        sources.append(
            _source("fee", "station_fee", "站费", {"station_name": "站点", "fee_yuan_per_box": "费用", "confirmation_status": "状态"})
        )
    manifest = tmp_path / "铁路集装箱数据源.json"
    manifest.write_text(json.dumps({"sources": sources}, ensure_ascii=False), encoding="utf-8")
    return manifest


def test_local_manifest_loads_excel_tables_and_admits_complete_trunk_rate(tmp_path):
    result = load_rail_container_local_data(_manifest(tmp_path), data_dir=tmp_path, node_registry=_registry())

    assert result.admitted_count == 1
    assert result.trunk_records[0].base_freight_yuan_per_box == Decimal("325")
    assert result.trunk_records[0].duration_hours == Decimal("168")
    assert result.trunk_records[0].origin_station_fee_yuan_per_box == Decimal("136.5")
    assert len(result.terminal_provider.direct_truck_records) == 1
    assert result.build_node_registry(_registry()).lookup("南站") is not None


def test_local_manifest_keeps_missing_station_fee_as_explicit_admission_gap(tmp_path):
    result = load_rail_container_local_data(_manifest(tmp_path, include_fee=False), data_dir=tmp_path, node_registry=_registry())

    assert result.trunk_records == ()
    assert result.admissions[0].status == "held_station_fee"
    assert "元/箱上下站费" in result.admissions[0].message


def test_runtime_data_combines_station_master_with_customer_registry(tmp_path):
    runtime = load_rail_container_runtime_data(_manifest(tmp_path), data_dir=tmp_path, base_registry=_registry())

    assert runtime.node_registry.lookup("北站") is not None
    assert runtime.node_registry.lookup("客户") is not None
    assert runtime.local_data.admitted_count == 1
