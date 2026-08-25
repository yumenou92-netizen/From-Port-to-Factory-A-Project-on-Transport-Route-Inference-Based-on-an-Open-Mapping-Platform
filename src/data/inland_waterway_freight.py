from __future__ import annotations

import csv
import re
from pathlib import Path

from src.routing.inland_waterway_freight_provider import (
    InlandWaterwayFreightError,
    InlandWaterwayFreightRecord,
)


INLAND_WATERWAY_FREIGHT_FILE_NAME = "内河驳船运输费率.csv"


class InlandWaterwayFreightLoadError(ValueError):
    """Raised when the formal inland-waterway freight table is unsafe."""


def find_optional_inland_waterway_freight_file(data_dir: Path) -> Path | None:
    matches = sorted(data_dir.rglob(INLAND_WATERWAY_FREIGHT_FILE_NAME))
    if not matches:
        return None
    if len(matches) > 1:
        joined = "；".join(str(path) for path in matches)
        raise InlandWaterwayFreightLoadError(
            f"DATA_DIR 下存在多个 {INLAND_WATERWAY_FREIGHT_FILE_NAME}：{joined}"
        )
    return matches[0]


def load_inland_waterway_freight_records(
    path: Path,
) -> tuple[InlandWaterwayFreightRecord, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise InlandWaterwayFreightLoadError(f"{path.name} 缺少表头。")
            rows = list(reader)
    except OSError as exc:
        raise InlandWaterwayFreightLoadError(f"无法读取 {path}: {exc}") from exc

    records: list[InlandWaterwayFreightRecord] = []
    for row_no, row in enumerate(rows, start=2):
        try:
            records.append(
                InlandWaterwayFreightRecord(
                    origin_region_code=_required(row, "origin_region_code", row_no),
                    destination_region_code=_required(
                        row,
                        "destination_region_code",
                        row_no,
                    ),
                    package_type=_required(row, "package_type", row_no),
                    commodity_scope=_split_scope(
                        _required(row, "commodity_scope", row_no)
                    ),
                    unit_price_yuan_per_ton=_required(row, "unit_price", row_no),
                    fee_unit=_required(row, "fee_unit", row_no),
                    trade_type=_required(row, "trade_type", row_no),
                    bidirectional=_parse_bool(
                        _required(row, "bidirectional", row_no),
                        row_no,
                    ),
                    source_type=_optional(row, "source_type") or "real_data",
                    source=_optional(row, "source") or f"{path.name}#row={row_no}",
                    rule_id=_required(row, "rule_id", row_no),
                    rule_version=_required(row, "rule_version", row_no),
                    maintained_at=_optional(row, "maintained_at"),
                )
            )
        except (InlandWaterwayFreightError, InlandWaterwayFreightLoadError) as exc:
            raise InlandWaterwayFreightLoadError(
                f"{path.name} 第 {row_no} 行无法加载：{exc}"
            ) from exc
    return tuple(records)


def _required(row: dict[str, str], field: str, row_no: int) -> str:
    value = _optional(row, field)
    if value is None:
        raise InlandWaterwayFreightLoadError(f"第 {row_no} 行缺少 {field}。")
    return value


def _optional(row: dict[str, str], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_scope(value: str) -> tuple[str, ...]:
    values = tuple(
        dict.fromkeys(
            part.strip()
            for part in re.split(r"[;,，；、|]+", value)
            if part.strip()
        )
    )
    if not values:
        raise InlandWaterwayFreightLoadError("commodity_scope 不能为空。")
    return values


def _parse_bool(value: str, row_no: int) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "是"}:
        return True
    if normalized in {"false", "0", "no", "n", "否"}:
        return False
    raise InlandWaterwayFreightLoadError(
        f"第 {row_no} 行 bidirectional 必须是 true/false 或 是/否。"
    )
