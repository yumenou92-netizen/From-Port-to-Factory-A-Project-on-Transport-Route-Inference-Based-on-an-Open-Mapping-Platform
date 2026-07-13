from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    from .unit_conversion import UnitConversionError, calculate_total_cost
except ImportError:  # Support direct script-style imports used by demo scripts.
    from unit_conversion import UnitConversionError, calculate_total_cost


REAL_RATE_FILE = "运价表.json"
REAL_COORDINATE_FILE = "地点经纬度.json"
REAL_ADDITIONAL_FEE_FILE = "其他费用表.json"


class DataLoadError(Exception):
    """Raised when business data cannot be loaded into standard objects."""


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    name: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class FreightRate:
    origin: str
    destination: str
    transport_mode: str
    packaging: str
    product_scope: str
    fee: Decimal
    fee_unit: str
    price_source: str
    maintenance_date: str | None = None


@dataclass(frozen=True)
class AdditionalFee:
    node_name: str
    packaging: str
    fee_type: str
    unit_price: Decimal
    fee_unit: str


@dataclass(frozen=True)
class EdgeCandidate:
    from_node_id: str | None
    to_node_id: str | None
    origin: str
    destination: str
    transport_mode: str
    packaging: str
    product_scope: str
    unit_fee: Decimal
    fee_unit: str
    total_cost: Decimal
    price_source: str
    maintenance_date: str | None


@dataclass(frozen=True)
class EdgeBuildResult:
    candidates: list[EdgeCandidate]
    skipped_unit_mismatch: int = 0
    skipped_packaging: int = 0
    skipped_product: int = 0


@dataclass(frozen=True)
class RealDataBundle:
    data_dir: Path
    freight_rates: list[FreightRate]
    nodes: list[NodeRecord]
    additional_fees: list[AdditionalFee]

    @property
    def node_by_name(self) -> dict[str, NodeRecord]:
        return {node.name: node for node in self.nodes}

    @property
    def transport_modes(self) -> Counter[str]:
        return Counter(rate.transport_mode for rate in self.freight_rates)

    @property
    def fee_units(self) -> Counter[str]:
        units = Counter(rate.fee_unit for rate in self.freight_rates)
        units.update(fee.fee_unit for fee in self.additional_fees)
        return units

    @property
    def packaging_types(self) -> Counter[str]:
        values = Counter(rate.packaging for rate in self.freight_rates)
        values.update(fee.packaging for fee in self.additional_fees)
        return values


def data_dir_from_env() -> Path:
    value = os.environ.get("DATA_DIR")
    if not value:
        raise DataLoadError("缺少环境变量 DATA_DIR。请设置为本地真实业务数据目录，例如 .\\data_REAL。")

    data_dir = Path(value)
    if not data_dir.exists():
        raise DataLoadError(f"DATA_DIR 不存在: {data_dir}")
    if not data_dir.is_dir():
        raise DataLoadError(f"DATA_DIR 不是目录: {data_dir}")
    return data_dir


def load_real_data_bundle(data_dir: str | Path) -> RealDataBundle:
    root = Path(data_dir)
    rate_rows = read_json_lines(find_required_file(root, REAL_RATE_FILE))
    coordinate_rows = read_json_lines(find_required_file(root, REAL_COORDINATE_FILE))
    additional_fee_rows = read_json_lines(find_required_file(root, REAL_ADDITIONAL_FEE_FILE))

    return RealDataBundle(
        data_dir=root,
        freight_rates=[parse_freight_rate(row, index) for index, row in enumerate(rate_rows, start=1)],
        nodes=[parse_node_record(row, index) for index, row in enumerate(coordinate_rows, start=1)],
        additional_fees=[parse_additional_fee(row, index) for index, row in enumerate(additional_fee_rows, start=1)],
    )


def find_required_file(data_dir: Path, file_name: str) -> Path:
    matches = sorted(data_dir.rglob(file_name))
    if not matches:
        raise DataLoadError(f"DATA_DIR 下缺少必要文件: {file_name}")
    if len(matches) > 1:
        joined = "; ".join(str(path) for path in matches)
        raise DataLoadError(f"DATA_DIR 下存在多个 {file_name}，请先明确数据来源: {joined}")
    return matches[0]


def read_json_lines(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DataLoadError(f"{path.name} 第 {line_no} 行不是合法 JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise DataLoadError(f"{path.name} 第 {line_no} 行不是 JSON 对象。")
        records.append(record)
    return records


def parse_freight_rate(row: dict[str, Any], row_no: int) -> FreightRate:
    required = ["始发", "到达", "运输方式", "包装方式", "适用品种", "费用", "费用单位", "价格来源"]
    require_fields(row, required, REAL_RATE_FILE, row_no)
    return FreightRate(
        origin=str(row["始发"]).strip(),
        destination=str(row["到达"]).strip(),
        transport_mode=str(row["运输方式"]).strip(),
        packaging=str(row["包装方式"]).strip(),
        product_scope=str(row["适用品种"]).strip(),
        fee=parse_decimal(row["费用"], REAL_RATE_FILE, row_no, "费用"),
        fee_unit=str(row["费用单位"]).strip(),
        price_source=str(row["价格来源"]).strip(),
        maintenance_date=optional_text(row.get("维护日期")),
    )


def parse_node_record(row: dict[str, Any], row_no: int) -> NodeRecord:
    required = ["名称", "经度", "纬度"]
    require_fields(row, required, REAL_COORDINATE_FILE, row_no)
    name = str(row["名称"]).strip()
    return NodeRecord(
        node_id=make_node_id(name),
        name=name,
        longitude=parse_float(row["经度"], REAL_COORDINATE_FILE, row_no, "经度"),
        latitude=parse_float(row["纬度"], REAL_COORDINATE_FILE, row_no, "纬度"),
    )


def parse_additional_fee(row: dict[str, Any], row_no: int) -> AdditionalFee:
    required = ["节点简称", "包装类型", "费用类型", "单价", "费用单位"]
    require_fields(row, required, REAL_ADDITIONAL_FEE_FILE, row_no)
    return AdditionalFee(
        node_name=str(row["节点简称"]).strip(),
        packaging=str(row["包装类型"]).strip(),
        fee_type=str(row["费用类型"]).strip(),
        unit_price=parse_decimal(row["单价"], REAL_ADDITIONAL_FEE_FILE, row_no, "单价"),
        fee_unit=str(row["费用单位"]).strip(),
    )


def require_fields(row: dict[str, Any], fields: list[str], file_name: str, row_no: int) -> None:
    missing = [field for field in fields if is_blank(row.get(field))]
    if missing:
        raise DataLoadError(f"{file_name} 第 {row_no} 行缺少必填字段: {', '.join(missing)}")


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def optional_text(value: Any) -> str | None:
    if is_blank(value):
        return None
    return str(value).strip()


def parse_decimal(value: Any, file_name: str, row_no: int, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有效数值: {value}") from exc
    if not number.is_finite():
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有限数值: {value}")
    return number


def parse_float(value: Any, file_name: str, row_no: int, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有效数值: {value}") from exc
    if not math.isfinite(number):
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有限数值: {value}")
    return number


def make_node_id(name: str) -> str:
    normalized = normalize_node_name(name)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"node_{digest}"


def normalize_node_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name).strip())


def build_order_edge_candidates(
    bundle: RealDataBundle,
    quantity: int | float | str | Decimal,
    quantity_unit: str,
    packaging: str | None = None,
    product: str | None = None,
) -> EdgeBuildResult:
    nodes = bundle.node_by_name
    candidates: list[EdgeCandidate] = []
    skipped_unit_mismatch = 0
    skipped_packaging = 0
    skipped_product = 0

    for rate in bundle.freight_rates:
        if packaging and rate.packaging != packaging:
            skipped_packaging += 1
            continue
        if product and not product_matches(product, rate.product_scope):
            skipped_product += 1
            continue

        try:
            total_cost = calculate_total_cost(rate.fee, rate.fee_unit, quantity, quantity_unit)
        except UnitConversionError:
            skipped_unit_mismatch += 1
            continue

        origin_node = nodes.get(rate.origin)
        destination_node = nodes.get(rate.destination)
        candidates.append(
            EdgeCandidate(
                from_node_id=origin_node.node_id if origin_node else None,
                to_node_id=destination_node.node_id if destination_node else None,
                origin=rate.origin,
                destination=rate.destination,
                transport_mode=rate.transport_mode,
                packaging=rate.packaging,
                product_scope=rate.product_scope,
                unit_fee=rate.fee,
                fee_unit=rate.fee_unit,
                total_cost=total_cost,
                price_source=rate.price_source,
                maintenance_date=rate.maintenance_date,
            )
        )

    return EdgeBuildResult(
        candidates=candidates,
        skipped_unit_mismatch=skipped_unit_mismatch,
        skipped_packaging=skipped_packaging,
        skipped_product=skipped_product,
    )


def product_matches(product: str, product_scope: str) -> bool:
    product_value = product.strip()
    allowed = {item.strip() for item in re.split(r"[,，、/]+", product_scope) if item.strip()}
    return product_value in allowed


def edge_candidate_to_row(candidate: EdgeCandidate) -> dict[str, Any]:
    return {
        "from_node_id": candidate.from_node_id,
        "to_node_id": candidate.to_node_id,
        "origin": candidate.origin,
        "destination": candidate.destination,
        "transport_mode": candidate.transport_mode,
        "packaging": candidate.packaging,
        "product_scope": candidate.product_scope,
        "unit_fee": str(candidate.unit_fee),
        "fee_unit": candidate.fee_unit,
        "total_cost": str(candidate.total_cost),
        "price_source": candidate.price_source,
        "maintenance_date": candidate.maintenance_date or "",
    }
