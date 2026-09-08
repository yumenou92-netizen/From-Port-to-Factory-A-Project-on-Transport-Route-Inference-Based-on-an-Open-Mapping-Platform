"""铁路运费计算器台账（Excel 文件持久化）。

数据落在 <PROJECT_ROOT>/output/铁路运费台账.xlsx，单文件、表头固定。
提供加载 / 追加 / 更新 / 删除 / 导出（xlsx / csv）能力。
读写统一经过模块级线程锁，避免 ThreadingHTTPServer 并发写坏文件。
"""

from __future__ import annotations

import csv
import io
import shutil
import sys
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PACKAGE_DIR = PROJECT_ROOT / ".python_packages"
if LOCAL_PACKAGE_DIR.exists() and str(LOCAL_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_PACKAGE_DIR))

from openpyxl import Workbook, load_workbook

OUTPUT_DIR = PROJECT_ROOT / "output"
LEDGER_FILE_NAME = "铁路运费台账.xlsx"
LEDGER_PATH = OUTPUT_DIR / LEDGER_FILE_NAME

# (内部键, Excel 表头)。顺序即表头顺序。
LEDGER_COLUMNS: list[tuple[str, str]] = [
    ("seq", "台账序号"),
    ("savedAt", "保存时间"),
    ("northStation", "北方站点"),
    ("southStation", "南方站点"),
    ("customerFactory", "客户工厂"),
    ("loadTons", "整车装载吨数"),
    ("discountRatio", "下浮率"),
    ("totalFreightYuan", "运费"),
    ("electrifiedKm", "电气化里程"),
    ("stampTaxYuan", "印花税"),
    ("jingjiuDiversionYuan", "京九分流"),
    ("railConstructionFundAdjustedBaseYuan", "铁建基金折算基数"),
    ("originHandlingAdjustedYuan", "发站装卸费"),
    ("destinationHandlingAdjustedYuan", "到站装卸费"),
    ("pickupDeliveryAdjustedYuan", "取送车费"),
    ("otherAdjustedYuan", "其他费"),
    ("fullPriceTotalYuan", "原表全价合计"),
    ("userFullPriceTotalYuan", "用户全价合计"),
    ("localFreightAdjustedTotalYuan", "地方运费下浮后合计"),
    ("adjustedTotalYuan", "下浮后报价"),
    ("inputLoadUnitPriceYuanPerTon", "折合单吨价"),
    ("workbookUnitPriceYuanPerTon", "原表60吨单价"),
]

# 旧版（v1）列结构：地方运费固定两列。检测到旧表头时自动迁移到新结构。
_LEGACY_COLUMNS: list[tuple[str, str]] = [
    ("seq", "台账序号"),
    ("savedAt", "保存时间"),
    ("northStation", "北方站点"),
    ("southStation", "南方站点"),
    ("customerFactory", "客户工厂"),
    ("loadTons", "整车装载吨数"),
    ("discountRatio", "下浮率"),
    ("totalFreightYuan", "运费"),
    ("electrifiedKm", "电气化里程"),
    ("stampTaxYuan", "印花税"),
    ("jingjiuDiversionYuan", "京九分流"),
    ("railConstructionFundAdjustedBaseYuan", "铁建基金折算基数"),
    ("localFreight1AdjustedBaseYuan", "地方运费1折算基数"),
    ("localFreight2AdjustedBaseYuan", "地方运费2折算基数"),
    ("originHandlingAdjustedYuan", "发站装卸费"),
    ("destinationHandlingAdjustedYuan", "到站装卸费"),
    ("pickupDeliveryAdjustedYuan", "取送车费"),
    ("otherAdjustedYuan", "其他费"),
    ("fullPriceTotalYuan", "原表全价合计"),
    ("userFullPriceTotalYuan", "用户全价合计"),
    ("adjustedTotalYuan", "下浮后报价"),
    ("inputLoadUnitPriceYuanPerTon", "折合单吨价"),
    ("workbookUnitPriceYuanPerTon", "原表60吨单价"),
]
_LEGACY_HEADER_NAMES = [name for _, name in _LEGACY_COLUMNS]
_LEGACY_HEADER_KEYS = [key for key, _ in _LEGACY_COLUMNS]

# RLock：append/update/delete 内部会再次调用 load_records，必须可重入
_LOCK = threading.RLock()
_HEADER_NAMES = [name for _, name in LEDGER_COLUMNS]
_HEADER_KEYS = [key for key, _ in LEDGER_COLUMNS]


def _ensure_workbook() -> None:
    """文件不存在时创建带表头的空台账。"""
    if LEDGER_PATH.exists():
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "台账"
    sheet.append(_HEADER_NAMES)
    workbook.save(LEDGER_PATH)


def _to_decimal_or_zero(value: Any) -> Decimal:
    """把单元格值（str/int/Decimal/None）安全转 Decimal，失败按 0。"""
    if value is None or str(value).strip() == "":
        return Decimal("0")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return Decimal("0")
    return result if result.is_finite() else Decimal("0")


def _ensure_schema() -> None:
    """检测旧版 v1 表头（地方运费固定两列）并迁移为新结构，迁移前备份原文件。

    仅在表头与 v1 完全一致时执行，新结构或异常结构一律不碰，避免误伤。
    """
    if not LEDGER_PATH.exists():
        return
    workbook = load_workbook(LEDGER_PATH, read_only=True)
    try:
        sheet = workbook["台账"]
        header = next(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if header != tuple(_LEGACY_HEADER_NAMES):
        return
    backup_path = LEDGER_PATH.with_name(
        f"{LEDGER_FILE_NAME}.bak_schema_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    shutil.copy2(LEDGER_PATH, backup_path)
    workbook = load_workbook(LEDGER_PATH, read_only=True, data_only=True)
    try:
        sheet = workbook["台账"]
        rows = [row for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    records: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not row or not any(v not in (None, "") for v in row[1:]):
            continue
        legacy: dict[str, Any] = {}
        for index, key in enumerate(_LEGACY_HEADER_KEYS):
            legacy[key] = row[index] if index < len(row) else None
        record = {key: legacy.get(key) for key in _HEADER_KEYS if key in legacy}
        base1 = _to_decimal_or_zero(legacy.get("localFreight1AdjustedBaseYuan"))
        base2 = _to_decimal_or_zero(legacy.get("localFreight2AdjustedBaseYuan"))
        discount = _to_decimal_or_zero(legacy.get("discountRatio"))
        record["localFreightAdjustedTotalYuan"] = str(
            (base1 + base2) * (Decimal("1") - discount)
        )
        records.append(record)
    _write_records(records)


def _row_to_record(values: tuple[Any, ...]) -> dict[str, Any] | None:
    """把一行单元格转成记录 dict；表头行或空行返回 None。"""
    if not values or not any(v not in (None, "") for v in values[1:]):
        return None
    record: dict[str, Any] = {}
    for index, key in enumerate(_HEADER_KEYS):
        value = values[index] if index < len(values) else None
        record[key] = value
    return record


def load_records() -> list[dict[str, Any]]:
    """读取全部台账记录（按行序）。"""
    with _LOCK:
        _ensure_schema()
        if not LEDGER_PATH.exists():
            return []
        workbook = load_workbook(LEDGER_PATH, read_only=True, data_only=True)
        try:
            sheet = workbook["台账"]
            records: list[dict[str, Any]] = []
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                if index == 0:
                    continue
                record = _row_to_record(row)
                if record is not None:
                    records.append(record)
            return records
        finally:
            workbook.close()


def _next_seq(records: list[dict[str, Any]]) -> int:
    seqs = [int(r.get("seq") or 0) for r in records]
    return (max(seqs) + 1) if seqs else 1


def _write_records(records: list[dict[str, Any]]) -> None:
    """全量写回（记录量级小，简单可靠）。"""
    _ensure_workbook()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "台账"
    sheet.append(_HEADER_NAMES)
    for record in records:
        sheet.append([record.get(key) for key in _HEADER_KEYS])
    workbook.save(LEDGER_PATH)


def _strip_system_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """剔除调用方不应覆盖的系统字段。"""
    return {key: value for key, value in fields.items() if key not in ("seq", "savedAt")}


def append_record(fields: dict[str, Any]) -> dict[str, Any]:
    """追加一条记录；seq 自增不重用。"""
    with _LOCK:
        records = load_records()
        record: dict[str, Any] = {
            "seq": _next_seq(records),
            "savedAt": datetime.now().isoformat(timespec="seconds"),
            **_strip_system_fields(fields),
        }
        records.append(record)
        _write_records(records)
        return record


def update_record(seq: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    """按 seq 覆盖更新；找不到返回 None。"""
    with _LOCK:
        records = load_records()
        for record in records:
            if int(record.get("seq") or -1) == seq:
                record.update(_strip_system_fields(fields))
                _write_records(records)
                return record
        return None


def delete_record(seq: int) -> bool:
    """按 seq 删除；找不到返回 False。"""
    with _LOCK:
        records = load_records()
        remaining = [r for r in records if int(r.get("seq") or -1) != seq]
        if len(remaining) == len(records):
            return False
        _write_records(remaining)
        return True


def export_xlsx() -> bytes:
    """导出一份 xlsx 快照（与原台账同结构）。"""
    with _LOCK:
        _ensure_schema()
        _ensure_workbook()
        workbook = load_workbook(LEDGER_PATH)
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()
        return buffer.getvalue()


def export_csv() -> bytes:
    """导出 csv（UTF-8 带 BOM，Excel 直接打开不乱码）。"""
    with _LOCK:
        records = load_records()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_HEADER_NAMES)
        for record in records:
            writer.writerow([record.get(key) for key in _HEADER_KEYS])
        return ("\ufeff" + buffer.getvalue()).encode("utf-8")
