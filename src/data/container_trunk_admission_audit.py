"""Read-only readiness audit for the first container-vessel trunk milestone."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

from src.data.loaders import RealDataBundle
from src.data.node_master_maintenance import NodeMasterMaintenanceEntry
from src.routing.container_shipping_provider import (
    CONTAINER_SHIPPING_FILE_NAME,
    ContainerShippingRateTimeRecord,
    find_optional_container_shipping_file,
)


ContainerPortReadinessStatus = Literal[
    "eligible_pending_rate_time",
    "eligible_rate_time_available",
    "excluded_customer_or_non_port",
    "excluded_inland_only",
    "excluded_no_container_capability",
    "manual_review_missing_waterway_tag",
]


@dataclass(frozen=True)
class ContainerPortReadinessRow:
    node_id: str | None
    port_name: str
    waterway_role: str
    supports_container: bool
    readiness_status: ContainerPortReadinessStatus
    rate_time_record_count: int
    source: str
    message: str


@dataclass(frozen=True)
class ContainerTrunkAdmissionAudit:
    rate_time_source_status: str
    rate_time_source: str | None
    rate_time_record_count: int
    box_only_scope: bool
    rows: tuple[ContainerPortReadinessRow, ...]

    @property
    def eligible_port_count(self) -> int:
        return sum(
            row.readiness_status
            in {"eligible_pending_rate_time", "eligible_rate_time_available"}
            for row in self.rows
        )


def build_container_trunk_admission_audit(
    bundle: RealDataBundle,
    *,
    rate_time_records: Sequence[ContainerShippingRateTimeRecord] = (),
    rate_time_source: Path | None = None,
) -> ContainerTrunkAdmissionAudit:
    records = tuple(rate_time_records)
    confirmed_records = tuple(
        record for record in records if record.confirmation_status == "confirmed"
    )
    record_node_ids = {
        record.south_port_node_id
        for record in confirmed_records
        if record.south_port_node_id
    }
    record_names = {record.south_port_name for record in confirmed_records}
    rows: list[ContainerPortReadinessRow] = []

    for entry in bundle.node_master_entries:
        row = _readiness_row(
            entry,
            bundle=bundle,
            has_rate_time=(
                _node_id_for_entry(entry, bundle) in record_node_ids
                or entry.full_name in record_names
            ),
            record_count=sum(
                _node_id_for_entry(entry, bundle) == record.south_port_node_id
                or entry.full_name == record.south_port_name
                for record in confirmed_records
            ),
        )
        if row is not None:
            rows.append(row)

    if rate_time_source is None:
        source_status = "source_not_connected"
        source = None
    else:
        source_status = "loaded" if records else "loaded_empty"
        source = str(rate_time_source)
    return ContainerTrunkAdmissionAudit(
        rate_time_source_status=source_status,
        rate_time_source=source,
        rate_time_record_count=len(records),
        box_only_scope=True,
        rows=tuple(sorted(rows, key=lambda row: (row.readiness_status, row.port_name))),
    )


def load_container_trunk_admission_audit(bundle: RealDataBundle) -> ContainerTrunkAdmissionAudit:
    from src.routing.container_shipping_provider import TableContainerShippingProvider

    source = find_optional_container_shipping_file(bundle.data_dir)
    records = TableContainerShippingProvider.from_csv(source).records if source else ()
    return build_container_trunk_admission_audit(
        bundle,
        rate_time_records=records,
        rate_time_source=source,
    )


def write_container_trunk_audit_outputs(
    audit: ContainerTrunkAdmissionAudit,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "container_trunk_admission_audit.csv"
    json_path = output_dir / "container_trunk_admission_audit.json"
    markdown_path = output_dir / "container_trunk_admission_audit.md"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ContainerPortReadinessRow.__dataclass_fields__.keys())
        writer.writeheader()
        writer.writerows(asdict(row) for row in audit.rows)
    json_path.write_text(
        json.dumps(asdict(audit), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_container_trunk_admission_markdown(audit), encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "markdown": markdown_path}


def render_container_trunk_admission_markdown(audit: ContainerTrunkAdmissionAudit) -> str:
    lines = [
        "# 集装箱船北港—南港准入审计",
        "",
        "本报告只读，不调用 Tencent，不写入真实数据，也不生成图边。",
        "",
        f"- 首轮订单范围：仅 `集装箱/箱`；`柜` 不换算、不构边。",
        f"- 集装箱船运价时效源：{audit.rate_time_source or f'未接入（期望文件：{CONTAINER_SHIPPING_FILE_NAME}）'}。",
        f"- 已读取记录：{audit.rate_time_record_count} 条；具备南港身份与集装箱能力的候选：{audit.eligible_port_count} 个。",
        "- 准入条件：维护表为物流节点和港口码头，同时具备海港属性或海河一体属性，并支持集装箱；还必须存在适用的已确认集装箱船运价与航运总时效，才可在后续构建北港—南港图边。",
        "",
        "| 南港节点 | 水域角色 | 集装箱能力 | 运价时效记录 | 当前状态 | 说明 |",
        "|---|---|---:|---:|---|---|",
    ]
    lines.extend(
        f"| {row.port_name} | {row.waterway_role} | {'是' if row.supports_container else '否'} | "
        f"{row.rate_time_record_count} | {row.readiness_status} | {row.message} |"
        for row in audit.rows
    )
    return "\n".join(lines) + "\n"


def _readiness_row(
    entry: NodeMasterMaintenanceEntry,
    *,
    bundle: RealDataBundle,
    has_rate_time: bool,
    record_count: int,
) -> ContainerPortReadinessRow | None:
    if not entry.is_port_facility:
        return None
    node_id = _node_id_for_entry(entry, bundle)
    is_port = entry.is_logistics_node and "港口码头" in entry.node_nature
    supports_container = "集装箱" in entry.package_types
    if not is_port:
        return ContainerPortReadinessRow(
            node_id=node_id,
            port_name=entry.full_name,
            waterway_role="not_south_port",
            supports_container=supports_container,
            readiness_status="excluded_customer_or_non_port",
            rate_time_record_count=record_count,
            source=entry.source,
            message="维护标签不是可作为南港的物流节点/港口码头；客户或非港口节点不得提升为南港。",
        )
    if not supports_container:
        return ContainerPortReadinessRow(
            node_id=node_id,
            port_name=entry.full_name,
            waterway_role=_waterway_role(entry),
            supports_container=False,
            readiness_status="excluded_no_container_capability",
            rate_time_record_count=record_count,
            source=entry.source,
            message="维护表未标注集装箱能力，不作为集装箱船南港候选。",
        )
    waterway_role = _waterway_role(entry)
    if waterway_role == "inland_port":
        return ContainerPortReadinessRow(
            node_id=node_id,
            port_name=entry.full_name,
            waterway_role=waterway_role,
            supports_container=True,
            readiness_status="excluded_inland_only",
            rate_time_record_count=record_count,
            source=entry.source,
            message="纯内河港可在后续作为中转港，但不得作为北港—南港集装箱船干线终点。",
        )
    if waterway_role == "unknown_port":
        return ContainerPortReadinessRow(
            node_id=node_id,
            port_name=entry.full_name,
            waterway_role=waterway_role,
            supports_container=True,
            readiness_status="manual_review_missing_waterway_tag",
            rate_time_record_count=record_count,
            source=entry.source,
            message="维护表缺少海港/内河码头属性，不能仅凭港口名称或集装箱能力判断南港准入。",
        )
    return ContainerPortReadinessRow(
        node_id=node_id,
        port_name=entry.full_name,
        waterway_role=waterway_role,
        supports_container=True,
        readiness_status=("eligible_rate_time_available" if has_rate_time else "eligible_pending_rate_time"),
        rate_time_record_count=record_count,
        source=entry.source,
        message=(
            "已具备节点身份和集装箱能力；已发现对应集装箱船记录，仍需按北港、品种、贸易类型和箱数精确匹配。"
            if has_rate_time
            else "已具备节点身份和集装箱能力，但尚无已确认集装箱船运价与航运总时效，当前不构边。"
        ),
    )


def _node_id_for_entry(entry: NodeMasterMaintenanceEntry, bundle: RealDataBundle) -> str | None:
    if bundle.node_registry is None:
        return None
    nodes = {
        node.node_id
        for name in entry.all_names
        if (node := bundle.node_registry.lookup(name)) is not None
    }
    return next(iter(nodes)) if len(nodes) == 1 else None


def _waterway_role(entry: NodeMasterMaintenanceEntry) -> str:
    if entry.has_seaport_attribute and entry.has_inland_port_attribute:
        return "sea_river_integrated_port"
    if entry.has_seaport_attribute:
        return "sea_port"
    if entry.has_inland_port_attribute:
        return "inland_port"
    return "unknown_port"
