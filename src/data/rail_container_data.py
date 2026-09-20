"""Local-table adapter for formal railway-container planning data.

This module is the railway counterpart of the bulk-shipping data boundary:
registered Excel sources -> typed records -> explicit admission -> Providers.
It deliberately keeps rates, station fees, time regions and terminal plans in
separate tables so a new business workbook can be attached without changing
graph or route-search code.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Sequence

from src.data.excel_table import (
    ExcelTableRow,
    LocalExcelTableError,
    load_excel_source_manifest,
    read_excel_table,
)
from src.data.loaders import NodeRecord, make_node_id
from src.domain.node_registry import NodeRegistry, build_node_registry
from src.routing.rail_container_provider import RailContainerRateTimeRecord, TableRailContainerProvider
from src.routing.rail_customer_delivery_provider import (
    CustomerDedicatedSidingRecord,
    DirectTruckDeliveryRecord,
    RailCustomerDeliveryProvider,
    RailTerminalScope,
    ThirdPartyDedicatedSidingRecord,
)


RailAdmissionStatus = Literal[
    "admitted",
    "held_unregistered_station",
    "held_station_master",
    "held_station_fee",
    "held_time_region",
    "held_unit_or_scope",
    "held_duplicate",
]

TABLE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "station_master": ("station_name", "station_role", "province", "city", "longitude", "latitude"),
    "trunk_rate": (
        "north_station_name", "south_station_name", "base_freight", "base_freight_unit",
        "commodity_scope", "trade_type", "container_type", "confirmation_status",
    ),
    "station_fee": ("station_name", "fee_yuan_per_box", "confirmation_status"),
    "time_region": ("origin_region", "destination_region", "duration_hours", "confirmation_status"),
    "direct_truck": (
        "south_station_name", "customer_name", "commodity_scope", "trade_type", "container_type",
        "distance_km", "distance_source", "duration_hours", "time_source", "confirmation_status",
    ),
    "customer_dedicated_siding": (
        "south_station_name", "customer_name", "commodity_scope", "trade_type", "container_type",
        "unit_fee_yuan_per_box", "duration_hours", "time_source", "confirmation_status",
    ),
    "third_party_dedicated_siding": (
        "south_station_name", "third_party_name", "customer_name", "commodity_scope", "trade_type",
        "container_type", "rail_unit_fee_yuan_per_box", "rail_duration_hours", "rail_time_source",
        "delivery_transport_mode", "delivery_unit_fee_yuan_per_box", "delivery_duration_hours",
        "delivery_time_source", "confirmation_status",
    ),
}


class RailContainerLocalDataError(ValueError):
    """Raised when a local railway source is incomplete or inconsistent."""


@dataclass(frozen=True)
class RailStationMasterRecord:
    station_name: str
    station_role: Literal["north", "south"]
    province: str
    city: str
    longitude: float
    latitude: float
    source: str


@dataclass(frozen=True)
class RailStationFeeRecord:
    station_name: str
    fee_yuan_per_box: Decimal
    source: str


@dataclass(frozen=True)
class RailTimeRegionRecord:
    origin_region: str
    destination_region: str
    duration_hours: Decimal
    source: str


@dataclass(frozen=True)
class RailContainerAdmission:
    source: str
    row_number: int
    north_station_name: str
    south_station_name: str
    status: RailAdmissionStatus
    message: str


@dataclass(frozen=True)
class RailContainerLocalDataResult:
    """Typed table result; callers pass only the Providers to the application layer."""

    station_masters: tuple[RailStationMasterRecord, ...]
    station_fees: tuple[RailStationFeeRecord, ...]
    time_regions: tuple[RailTimeRegionRecord, ...]
    trunk_records: tuple[RailContainerRateTimeRecord, ...]
    terminal_provider: RailCustomerDeliveryProvider
    admissions: tuple[RailContainerAdmission, ...]

    @property
    def trunk_provider(self) -> TableRailContainerProvider:
        return TableRailContainerProvider(self.trunk_records)

    @property
    def admitted_count(self) -> int:
        return sum(item.status == "admitted" for item in self.admissions)

    def build_node_registry(self, base_registry: NodeRegistry | None = None) -> NodeRegistry:
        """Combine explicitly maintained rail stations with optional customer/port nodes.

        Node identities are regenerated from canonical names only; this is safe
        because ``make_node_id`` is the project-wide deterministic convention.
        Existing aliases are retained as coordinate-identical input names.
        """

        records: list[NodeRecord] = []
        if base_registry is not None:
            for node in base_registry.nodes.values():
                records.extend(
                    NodeRecord(make_node_id(alias), alias, node.longitude, node.latitude)
                    for alias in node.aliases
                )
        records.extend(
            NodeRecord(make_node_id(record.station_name), record.station_name, record.longitude, record.latitude)
            for record in self.station_masters
        )
        return build_node_registry(records, auto_alias=True)


@dataclass(frozen=True)
class RailContainerRuntimeData:
    """UI-neutral dependencies assembled from local tables and a base registry."""

    node_registry: NodeRegistry
    local_data: RailContainerLocalDataResult

    def planning_data(self):
        from src.application.rail_container_planning import RailContainerPlanningData

        return RailContainerPlanningData(
            node_registry=self.node_registry,
            trunk_provider=self.local_data.trunk_provider,
            terminal_provider=self.local_data.terminal_provider,
        )


def load_rail_container_local_data(
    manifest_path: str | Path,
    *,
    data_dir: str | Path,
    node_registry: NodeRegistry,
) -> RailContainerLocalDataResult:
    """Read registered Excel tables and admit only complete railway trunk rows."""

    try:
        sources = load_excel_source_manifest(manifest_path)
        rows_by_type: dict[str, list[ExcelTableRow]] = {}
        for source in sources:
            if source.table_type not in TABLE_REQUIRED_FIELDS:
                raise RailContainerLocalDataError(f"不支持的铁路数据表类型：{source.table_type}")
            rows_by_type.setdefault(source.table_type, []).extend(
                read_excel_table(
                    source,
                    base_dir=data_dir,
                    required_fields=TABLE_REQUIRED_FIELDS[source.table_type],
                )
            )
    except LocalExcelTableError as exc:
        raise RailContainerLocalDataError(str(exc)) from exc

    stations = tuple(_station_record(row) for row in rows_by_type.get("station_master", ()))
    fees = tuple(_station_fee_record(row) for row in rows_by_type.get("station_fee", ()))
    regions = tuple(_time_region_record(row) for row in rows_by_type.get("time_region", ()))
    _validate_station_masters(stations)
    _validate_unique_station_fees(fees)
    _validate_unique_time_regions(regions)
    trunk_records, admissions = _build_trunk_records(
        rows_by_type.get("trunk_rate", ()), stations, fees, regions, node_registry
    )
    terminal_provider = RailCustomerDeliveryProvider(
        direct_truck_records=tuple(
            _direct_truck_record(row, node_registry) for row in _confirmed(rows_by_type.get("direct_truck", ()))
        ),
        customer_dedicated_siding_records=tuple(
            _customer_siding_record(row, node_registry)
            for row in _confirmed(rows_by_type.get("customer_dedicated_siding", ()))
        ),
        third_party_dedicated_siding_records=tuple(
            _third_party_siding_record(row, node_registry)
            for row in _confirmed(rows_by_type.get("third_party_dedicated_siding", ()))
        ),
    )
    return RailContainerLocalDataResult(stations, fees, regions, trunk_records, terminal_provider, admissions)


def load_rail_container_runtime_data(
    manifest_path: str | Path,
    *,
    data_dir: str | Path,
    base_registry: NodeRegistry | None = None,
) -> RailContainerRuntimeData:
    """Build one formal dependency bundle without hard-coding workstation paths.

    Station master data are read first solely to add their coordinates to the
    existing customer-node registry; the full loader then performs the normal
    fee/time/OD admission against that combined registry.
    """

    stations = load_rail_station_masters(manifest_path, data_dir=data_dir)
    provisional = RailContainerLocalDataResult(stations, (), (), (), RailCustomerDeliveryProvider(), ())
    registry = provisional.build_node_registry(base_registry)
    local_data = load_rail_container_local_data(manifest_path, data_dir=data_dir, node_registry=registry)
    return RailContainerRuntimeData(registry, local_data)


def load_rail_station_masters(
    manifest_path: str | Path,
    *,
    data_dir: str | Path,
) -> tuple[RailStationMasterRecord, ...]:
    try:
        sources = load_excel_source_manifest(manifest_path)
        rows: list[ExcelTableRow] = []
        for source in sources:
            if source.table_type == "station_master":
                rows.extend(read_excel_table(source, base_dir=data_dir, required_fields=TABLE_REQUIRED_FIELDS["station_master"]))
    except LocalExcelTableError as exc:
        raise RailContainerLocalDataError(str(exc)) from exc
    if not rows:
        raise RailContainerLocalDataError("本地铁路数据源清单未登记 station_master 表，不能建立铁路站点节点。")
    records = tuple(_station_record(row) for row in rows)
    _validate_station_masters(records)
    return records


def _build_trunk_records(
    rows: Sequence[ExcelTableRow],
    stations: Sequence[RailStationMasterRecord],
    fees: Sequence[RailStationFeeRecord],
    regions: Sequence[RailTimeRegionRecord],
    registry: NodeRegistry,
) -> tuple[tuple[RailContainerRateTimeRecord, ...], tuple[RailContainerAdmission, ...]]:
    stations_by_name = {item.station_name: item for item in stations}
    fees_by_name = {item.station_name: item for item in fees}
    regions_by_key = {(item.origin_region, item.destination_region): item for item in regions}
    records: list[RailContainerRateTimeRecord] = []
    admissions: list[RailContainerAdmission] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in rows:
        north = _text(row.value("north_station_name"))
        south = _text(row.value("south_station_name"))
        common = dict(source=row.source_reference, row_number=row.row_number, north_station_name=north, south_station_name=south)
        if _text(row.value("confirmation_status")) != "confirmed":
            admissions.append(RailContainerAdmission(**common, status="held_unit_or_scope", message="铁路干线记录未标记 confirmed；不构边。"))
            continue
        north_master = stations_by_name.get(north)
        south_master = stations_by_name.get(south)
        if north_master is None or south_master is None or north_master.station_role != "north" or south_master.station_role != "south":
            admissions.append(RailContainerAdmission(**common, status="held_station_master", message="北站或南站未在独立站点主数据中以正确角色唯一维护；不构边。"))
            continue
        north_node = registry.lookup(north)
        south_node = registry.lookup(south)
        if north_node is None or south_node is None:
            admissions.append(RailContainerAdmission(**common, status="held_unregistered_station", message="北站或南站未在标准节点注册表唯一命中；不构边。"))
            continue
        north_fee = fees_by_name.get(north)
        south_fee = fees_by_name.get(south)
        if north_fee is None or south_fee is None:
            admissions.append(RailContainerAdmission(**common, status="held_station_fee", message="北站或南站缺少已确认元/箱上下站费；不构边。"))
            continue
        origin_region = _text(row.value("origin_region")) or "东北"
        destination_region = _text(row.value("destination_region")) or south_master.province
        time = regions_by_key.get((origin_region, destination_region))
        if time is None:
            admissions.append(RailContainerAdmission(**common, status="held_time_region", message=f"缺少 {origin_region} 至 {destination_region} 的已确认完整铁路时效；不构边。"))
            continue
        try:
            commodity_scope = _split_scope(_text(row.value("commodity_scope")))
            trade_type = _text(row.value("trade_type"))
            container_type = _text(row.value("container_type"))
            base_freight = _fee_per_box(row)
            discount = _ratio(row.value("discount_ratio"), default=Decimal("0"))
            record = RailContainerRateTimeRecord(
                north_station_name=north_node.canonical_name,
                south_station_name=south_node.canonical_name,
                north_station_node_id=north_node.node_id,
                south_station_node_id=south_node.node_id,
                commodity_scope=commodity_scope,
                trade_type=trade_type,
                container_type=container_type,
                base_freight_yuan_per_box=base_freight,
                discount_ratio=discount,
                origin_station_fee_yuan_per_box=north_fee.fee_yuan_per_box,
                destination_station_fee_yuan_per_box=south_fee.fee_yuan_per_box,
                duration_hours=time.duration_hours,
                source=row.source_reference,
                source_type="real_data",
            )
        except RailContainerLocalDataError as exc:
            admissions.append(RailContainerAdmission(**common, status="held_unit_or_scope", message=str(exc)))
            continue
        key = (north_node.node_id, south_node.node_id, *record.commodity_scope, record.trade_type, record.container_type)
        if key in seen:
            admissions.append(RailContainerAdmission(**common, status="held_duplicate", message="同一订单范围存在重复铁路 OD 记录；需确认最新有效记录后再构边。"))
            continue
        seen.add(key)
        records.append(record)
        admissions.append(RailContainerAdmission(**common, status="admitted", message="已匹配标准站点、精确铁路干线费率、两端站费和完整铁路时效。"))
    return tuple(records), tuple(admissions)


def _station_record(row: ExcelTableRow) -> RailStationMasterRecord:
    role = _text(row.value("station_role"))
    if role not in {"north", "south"}:
        raise RailContainerLocalDataError(f"{row.source_reference} 的 station_role 必须为 north 或 south。")
    return RailStationMasterRecord(
        _required(row, "station_name"),
        role,
        _required(row, "province"),
        _required(row, "city"),
        float(_positive(row.value("longitude"), "站点经度")),
        float(_positive(row.value("latitude"), "站点纬度")),
        row.source_reference,
    )


def _station_fee_record(row: ExcelTableRow) -> RailStationFeeRecord:
    if _text(row.value("confirmation_status")) != "confirmed":
        raise RailContainerLocalDataError(f"{row.source_reference} 的站点费未标记 confirmed。")
    return RailStationFeeRecord(_required(row, "station_name"), _positive(row.value("fee_yuan_per_box"), "站点费"), row.source_reference)


def _time_region_record(row: ExcelTableRow) -> RailTimeRegionRecord:
    if _text(row.value("confirmation_status")) != "confirmed":
        raise RailContainerLocalDataError(f"{row.source_reference} 的铁路时效未标记 confirmed。")
    return RailTimeRegionRecord(_required(row, "origin_region"), _required(row, "destination_region"), _positive(row.value("duration_hours"), "铁路总时效"), row.source_reference)


def _direct_truck_record(row: ExcelTableRow, registry: NodeRegistry) -> DirectTruckDeliveryRecord:
    scope = _scope(row)
    south, customer = _required_nodes(row, registry, "south_station_name", "customer_name")
    return DirectTruckDeliveryRecord(south.canonical_name, south.node_id, customer.canonical_name, customer.node_id, scope, _positive(row.value("distance_km"), "直达拖车距离"), _required(row, "distance_source"), _positive(row.value("duration_hours"), "直达拖车时效"), _required(row, "time_source"))


def _customer_siding_record(row: ExcelTableRow, registry: NodeRegistry) -> CustomerDedicatedSidingRecord:
    scope = _scope(row)
    south, customer = _required_nodes(row, registry, "south_station_name", "customer_name")
    return CustomerDedicatedSidingRecord(south.canonical_name, south.node_id, customer.canonical_name, customer.node_id, scope, _positive(row.value("unit_fee_yuan_per_box"), "客户专用线费用"), _positive(row.value("duration_hours"), "客户专用线时效"), _required(row, "time_source"))


def _third_party_siding_record(row: ExcelTableRow, registry: NodeRegistry) -> ThirdPartyDedicatedSidingRecord:
    scope = _scope(row)
    south, third, customer = _required_nodes(row, registry, "south_station_name", "third_party_name", "customer_name")
    return ThirdPartyDedicatedSidingRecord(south.canonical_name, south.node_id, third.canonical_name, third.node_id, customer.canonical_name, customer.node_id, scope, _positive(row.value("rail_unit_fee_yuan_per_box"), "第三方专用线铁路费用"), _positive(row.value("rail_duration_hours"), "第三方专用线铁路时效"), _required(row, "rail_time_source"), _required(row, "delivery_transport_mode"), _positive(row.value("delivery_unit_fee_yuan_per_box"), "第三方专用线交付费用"), _positive(row.value("delivery_duration_hours"), "第三方专用线交付时效"), _required(row, "delivery_time_source"))


def _scope(row: ExcelTableRow) -> RailTerminalScope:
    return RailTerminalScope(_split_scope(_required(row, "commodity_scope")), _required(row, "trade_type"), _required(row, "container_type"), row.source_reference, "real_data")


def _required_nodes(row: ExcelTableRow, registry: NodeRegistry, *fields: str):
    nodes = tuple(registry.lookup(_required(row, field)) for field in fields)
    if any(node is None for node in nodes):
        raise RailContainerLocalDataError(f"{row.source_reference} 的末端节点未在标准注册表唯一命中；不构边。")
    return nodes


def _confirmed(rows: Sequence[ExcelTableRow]) -> tuple[ExcelTableRow, ...]:
    return tuple(row for row in rows if _text(row.value("confirmation_status")) == "confirmed")


def _validate_station_masters(records: Sequence[RailStationMasterRecord]) -> None:
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (record.station_name, record.station_role)
        if key in seen:
            raise RailContainerLocalDataError(f"站点主数据中 {record.station_name}/{record.station_role} 重复。")
        seen.add(key)


def _validate_unique_station_fees(records: Sequence[RailStationFeeRecord]) -> None:
    names = [record.station_name for record in records]
    if len(names) != len(set(names)):
        raise RailContainerLocalDataError("站点费表存在重复站点；不得任取一条。")


def _validate_unique_time_regions(records: Sequence[RailTimeRegionRecord]) -> None:
    keys = [(record.origin_region, record.destination_region) for record in records]
    if len(keys) != len(set(keys)):
        raise RailContainerLocalDataError("铁路时效表存在重复区域映射；不得任取一条。")


def _fee_per_box(row: ExcelTableRow) -> Decimal:
    fee = _positive(row.value("base_freight"), "铁路干线费率")
    unit = _required(row, "base_freight_unit").replace(" ", "").replace("／", "/")
    if unit == "元/箱":
        return fee
    if unit == "元/组":
        boxes = _positive(row.value("group_box_count") or Decimal("2"), "每组箱数")
        if boxes != Decimal("2"):
            raise RailContainerLocalDataError("当前铁路集装箱元/组记录仅确认 2 箱/组；其他组数需人工确认。")
        return fee / boxes
    raise RailContainerLocalDataError(f"铁路干线费率单位 {unit} 不支持；只接受元/箱或已确认的元/组（2箱/组）。")


def _ratio(value: object, *, default: Decimal) -> Decimal:
    if value is None or str(value).strip() == "":
        return default
    result = _decimal(value, "下浮率")
    if result < 0 or result >= 1:
        raise RailContainerLocalDataError("下浮率必须大于等于 0 且小于 1。")
    return result


def _split_scope(value: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.replace("、", ",").replace("，", ",").split(",") if part.strip())
    if not values:
        raise RailContainerLocalDataError("适用品种不能为空。")
    return values


def _required(row: ExcelTableRow, field: str) -> str:
    value = _text(row.value(field))
    if not value:
        raise RailContainerLocalDataError(f"{row.source_reference} 缺少字段 {field}。")
    return value


def _positive(value: object, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise RailContainerLocalDataError(f"{label}必须为正数。")
    return result


def _decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RailContainerLocalDataError(f"{label}必须是有限数值。") from None
    if not result.is_finite():
        raise RailContainerLocalDataError(f"{label}必须是有限数值。")
    return result


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""
