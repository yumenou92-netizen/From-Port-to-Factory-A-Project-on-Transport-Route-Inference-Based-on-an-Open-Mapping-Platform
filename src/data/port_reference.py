from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.routing.inland_waterway_provider import PortCapabilityRecord, RegionMappingRecord
from src.routing.port_operation_fee_provider import PortOperationFeeRegionAssignment

if TYPE_CHECKING:
    from src.domain.node_registry import NodeRegistry


PORT_CAPABILITY_FILE_NAME = "港口能力表.csv"
PORT_REGION_MAPPING_FILE_NAME = "区域映射表.csv"


class PortReferenceLoadError(ValueError):
    """Raised when optional port-reference tables exist but cannot be loaded safely."""


@dataclass(frozen=True)
class PortReferenceTables:
    data_dir: Path
    port_capability_file: Path | None
    region_mapping_file: Path | None
    port_capabilities: tuple[PortCapabilityRecord, ...]
    region_mappings: tuple[RegionMappingRecord, ...]
    operation_fee_region_assignments: tuple[PortOperationFeeRegionAssignment, ...]
    warnings: tuple[str, ...] = ()

    @property
    def missing_file_names(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.port_capability_file is None:
            missing.append(PORT_CAPABILITY_FILE_NAME)
        if self.region_mapping_file is None:
            missing.append(PORT_REGION_MAPPING_FILE_NAME)
        return tuple(missing)


def load_port_reference_tables(
    data_dir: str | Path,
    *,
    registry: NodeRegistry | None = None,
) -> PortReferenceTables:
    """Load optional W3 port capability and region-mapping tables.

    Missing W3 tables are not fatal: the audit should report that the interface
    is ready but no formal source has been connected. If a table exists, malformed
    rows fail loudly instead of producing guessed capabilities or mappings.
    """

    root = Path(data_dir)
    capability_file = find_optional_unique_file(root, PORT_CAPABILITY_FILE_NAME)
    region_mapping_file = find_optional_unique_file(root, PORT_REGION_MAPPING_FILE_NAME)
    warnings: list[str] = []

    if capability_file is None:
        warnings.append(f"{PORT_CAPABILITY_FILE_NAME} 未接入；缺失能力不生成对应运输边。")
        capabilities: tuple[PortCapabilityRecord, ...] = ()
    else:
        capabilities = tuple(load_port_capability_records(capability_file, registry=registry))
        if not capabilities:
            warnings.append(
                f"{PORT_CAPABILITY_FILE_NAME} 已存在但没有有效数据行；"
                "缺失能力仍不生成对应运输边。"
            )

    if region_mapping_file is None:
        warnings.append(f"{PORT_REGION_MAPPING_FILE_NAME} 未接入；未映射港口进入人工复核。")
        mappings: tuple[RegionMappingRecord, ...] = ()
        operation_fee_assignments: tuple[PortOperationFeeRegionAssignment, ...] = ()
    else:
        mappings = tuple(load_region_mapping_records(region_mapping_file))
        operation_fee_assignments = tuple(
            load_operation_fee_region_assignments(region_mapping_file)
        )
        if not mappings:
            warnings.append(
                f"{PORT_REGION_MAPPING_FILE_NAME} 已存在但没有有效数据行；"
                "未映射港口仍进入人工复核。"
            )

    return PortReferenceTables(
        data_dir=root,
        port_capability_file=capability_file,
        region_mapping_file=region_mapping_file,
        port_capabilities=capabilities,
        region_mappings=mappings,
        operation_fee_region_assignments=operation_fee_assignments,
        warnings=tuple(warnings),
    )


def find_optional_unique_file(data_dir: Path, file_name: str) -> Path | None:
    matches = sorted(data_dir.rglob(file_name))
    if not matches:
        return None
    if len(matches) > 1:
        joined = "; ".join(str(path) for path in matches)
        raise PortReferenceLoadError(f"DATA_DIR 下存在多个 {file_name}，请先明确数据来源：{joined}")
    return matches[0]


def load_port_capability_records(
    path: Path,
    *,
    registry: NodeRegistry | None = None,
) -> list[PortCapabilityRecord]:
    rows = read_csv_rows(path)
    records: list[PortCapabilityRecord] = []
    for row_no, row in enumerate(rows, start=2):
        canonical_name = read_field(row, row_no, "canonical_name", required=True)
        explicit_node_id = read_field(row, row_no, "node_id", required=False)
        registry_node = registry.lookup(canonical_name) if registry is not None else None
        node_id = explicit_node_id or (registry_node.node_id if registry_node else None)
        records.append(
            PortCapabilityRecord(
                node_id=node_id,
                canonical_name=canonical_name,
                region_code=read_field(row, row_no, "region_code", required=False),
                can_handle_barge=parse_optional_bool(
                    read_field(row, row_no, "can_handle_barge", required=False),
                    path,
                    row_no,
                    "can_handle_barge",
                ),
                supported_package_types=split_optional_text_list(
                    read_field(row, row_no, "supported_package_types", required=False)
                ),
                supported_commodities=split_optional_text_list(
                    read_field(row, row_no, "supported_commodities", required=False)
                ),
                source=read_field(row, row_no, "source", required=True),
                aliases=split_text_list(read_field(row, row_no, "aliases", required=False), allow_empty=True),
                infrastructure_type=read_field(row, row_no, "infrastructure_type", required=True),
                can_receive_bulk_shipping=parse_optional_bool(
                    read_field(row, row_no, "can_receive_bulk_shipping", required=False),
                    path,
                    row_no,
                    "can_receive_bulk_shipping",
                ),
                is_transfer_port=parse_optional_bool(
                    read_field(row, row_no, "is_transfer_port", required=False),
                    path,
                    row_no,
                    "is_transfer_port",
                ),
                supported_transport_modes=split_optional_text_list(
                    read_field(row, row_no, "supported_transport_modes", required=False)
                ),
                city=read_field(row, row_no, "city", required=False),
                shipping_time_region=read_field(
                    row,
                    row_no,
                    "shipping_time_region",
                    required=False,
                ),
                confirmation_status=read_field(
                    row,
                    row_no,
                    "confirmation_status",
                    required=False,
                )
                or "manual_review",
                maintained_at=read_field(row, row_no, "maintained_at", required=False),
            )
        )
    return records


def load_region_mapping_records(path: Path) -> list[RegionMappingRecord]:
    rows = read_csv_rows(path)
    records: list[RegionMappingRecord] = []
    for row_no, row in enumerate(rows, start=2):
        records.append(
            RegionMappingRecord(
                region_code=read_field(row, row_no, "region_code", required=True),
                region_name=read_field(row, row_no, "region_name", required=True),
                city_keywords=split_text_list(read_field(row, row_no, "city_keywords", required=True)),
                port_keywords=split_text_list(read_field(row, row_no, "port_keywords", required=True)),
                source=read_field(row, row_no, "source", required=True),
                bulk_rate_destination_group=read_field(
                    row,
                    row_no,
                    "bulk_rate_destination_group",
                    required=False,
                ),
                bulk_time_region=read_field(row, row_no, "bulk_time_region", required=False),
            )
        )
    return records


def load_operation_fee_region_assignments(
    path: Path,
) -> list[PortOperationFeeRegionAssignment]:
    """Load explicit node-id assignments; never infer operation-fee regions from keywords."""

    rows = read_csv_rows(path)
    assignments: list[PortOperationFeeRegionAssignment] = []
    for row_no, row in enumerate(rows, start=2):
        region_code = read_field(
            row,
            row_no,
            "operation_fee_region_code",
            required=False,
        )
        if not region_code:
            continue
        node_ids = split_text_list(
            read_field(row, row_no, "operation_fee_port_node_ids", required=True)
        )
        for node_id in node_ids:
            assignments.append(
                PortOperationFeeRegionAssignment(
                    port_node_id=node_id,
                    operation_fee_region_code=region_code,
                    source=read_field(row, row_no, "source", required=True),
                    mapping_basis=read_field(
                        row,
                        row_no,
                        "operation_fee_mapping_basis",
                        required=True,
                    ),
                    mapping_rule_id=read_field(
                        row,
                        row_no,
                        "operation_fee_mapping_rule_id",
                        required=True,
                    ),
                    mapping_rule_version=read_field(
                        row,
                        row_no,
                        "operation_fee_mapping_rule_version",
                        required=True,
                    ),
                    confirmation_status=read_field(
                        row,
                        row_no,
                        "operation_fee_confirmation_status",
                        required=False,
                    )
                    or "manual_review",
                    maintained_at=read_field(
                        row,
                        row_no,
                        "maintained_at",
                        required=False,
                    ),
                )
            )
    return assignments


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    last_decode_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise PortReferenceLoadError(f"{path.name} 缺少表头。")
                return [
                    {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
                    for row in reader
                ]
        except UnicodeDecodeError as exc:
            last_decode_error = exc
            continue
        except OSError as exc:
            raise PortReferenceLoadError(f"无法读取 {path}: {exc}") from exc
    raise PortReferenceLoadError(
        f"无法解码 {path}; supported encodings: utf-8-sig, gb18030."
    ) from last_decode_error


FIELD_ALIASES = {
    "node_id": ("node_id", "节点ID", "标准节点ID"),
    "canonical_name": ("canonical_name", "port_name", "港口名称", "节点名称", "标准名称"),
    "region_code": ("region_code", "区域编码", "内河区域编码"),
    "can_handle_barge": ("can_handle_barge", "可生成内河驳船边", "可走内河驳船"),
    "supported_package_types": ("supported_package_types", "支持包装方式", "包装方式"),
    "supported_commodities": ("supported_commodities", "支持品种", "适用品种", "货物品种"),
    "source": ("source", "数据来源", "来源"),
    "aliases": ("aliases", "别名", "别名列表"),
    "infrastructure_type": ("infrastructure_type", "基础设施类型", "节点类型"),
    "can_receive_bulk_shipping": ("can_receive_bulk_shipping", "可接收北港散船", "可接收散船干线"),
    "is_transfer_port": ("is_transfer_port", "是否中转港", "中转港"),
    "supported_transport_modes": ("supported_transport_modes", "支持运输方式", "运输方式"),
    "city": ("city", "城市", "市域"),
    "shipping_time_region": ("shipping_time_region", "航运时效区", "纯航行时效分区"),
    "confirmation_status": ("confirmation_status", "确认状态"),
    "maintained_at": ("maintained_at", "维护日期"),
    "region_name": ("region_name", "区域名称"),
    "city_keywords": ("city_keywords", "城市关键词", "所在地关键词"),
    "port_keywords": ("port_keywords", "港口关键词", "码头关键词"),
    "bulk_rate_destination_group": ("bulk_rate_destination_group", "散船目的组", "费率目的组"),
    "bulk_time_region": ("bulk_time_region", "纯航行时效分区", "时效分区"),
    "operation_fee_region_code": (
        "operation_fee_region_code",
        "作业费区域编码",
        "码头作业费区域编码",
    ),
    "operation_fee_port_node_ids": (
        "operation_fee_port_node_ids",
        "作业费区域港口节点ID",
        "港口节点ID列表",
    ),
    "operation_fee_mapping_basis": (
        "operation_fee_mapping_basis",
        "作业费映射依据",
    ),
    "operation_fee_mapping_rule_id": (
        "operation_fee_mapping_rule_id",
        "作业费映射规则编号",
    ),
    "operation_fee_mapping_rule_version": (
        "operation_fee_mapping_rule_version",
        "作业费映射规则版本",
    ),
    "operation_fee_confirmation_status": (
        "operation_fee_confirmation_status",
        "作业费映射确认状态",
    ),
}


def read_field(row: dict[str, str], row_no: int, logical_name: str, *, required: bool) -> str:
    for field_name in FIELD_ALIASES[logical_name]:
        if field_name in row and row[field_name].strip():
            return row[field_name].strip()
    if required:
        aliases = " / ".join(FIELD_ALIASES[logical_name])
        raise PortReferenceLoadError(f"第 {row_no} 行缺少必填字段：{aliases}")
    return ""


TRUE_VALUES = {"1", "true", "yes", "y", "是", "可", "支持"}
FALSE_VALUES = {"0", "false", "no", "n", "否", "不可", "不支持"}


def parse_bool(value: str, path: Path, row_no: int, field_name: str) -> bool:
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise PortReferenceLoadError(f"{path.name} 第 {row_no} 行字段 {field_name} 必须是明确布尔值。")


def parse_optional_bool(
    value: str,
    path: Path,
    row_no: int,
    field_name: str,
) -> bool | None:
    if not str(value).strip():
        return None
    return parse_bool(value, path, row_no, field_name)


def split_text_list(value: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in re.split(r"[;,，；、|/]+", value or "") if part.strip())
    if not parts and not allow_empty:
        raise PortReferenceLoadError("列表字段不能为空。")
    return tuple(dict.fromkeys(parts))


def split_optional_text_list(value: str) -> tuple[str, ...] | None:
    if not str(value).strip():
        return None
    return split_text_list(value)
