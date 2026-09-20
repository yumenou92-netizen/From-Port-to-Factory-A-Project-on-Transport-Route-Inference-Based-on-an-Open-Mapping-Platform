"""Read the confirmed first-batch railway-container test workbook.

The workbook remains a local business source.  This adapter does not copy it,
mutate it, or promote compound ``站转专用线`` endpoints to ordinary south
stations.  It extracts only exact north-station to south-station records whose
``敞顶箱-8.28查询`` amount has been confirmed as railway freight in yuan per
two-container group.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from src.data.excel_table import ExcelTableSource, LocalExcelTableError, read_excel_table
from src.data.loaders import NodeRecord, make_node_id
from src.domain.node_registry import NodeRegistry
from src.routing.rail_container_provider import RailContainerRateTimeRecord


TEST_ROUTE_SHEET = "测试路线"
NORTH_STATION_SHEET = "北方站点"
SOUTH_STATION_SHEET = "南方站点"
CONFIRMED_NORTH_STATION_FILE = "铁路北站确认站点.xlsx"
CONFIRMED_SOUTH_STATION_FILE = "铁路南站确认站点.xlsx"
GROUP_BOX_COUNT = Decimal("2")
OPEN_TOP_TARPAULIN_YUAN_PER_BOX = Decimal("250")
STANDARD_STATION_HANDLING_YUAN_PER_BOX = Decimal("136.5")
SHAOGUAN_STATION_HANDLING_YUAN_PER_BOX = Decimal("195")

RailTestRateAdmissionStatus = Literal[
    "admitted_normal_station_od",
    "held_special_terminal",
    "held_unregistered_north_station",
    "held_missing_station_metadata",
]


class RailTestWorkbookError(ValueError):
    """Raised when the received workbook cannot be safely consumed."""


@dataclass(frozen=True)
class RailTestRateAdmission:
    """One confirmed-price source row and its controlled admission outcome."""

    source_row_number: int
    north_station_name: str
    south_terminal_name: str
    railway_freight_yuan_per_group: Decimal
    railway_freight_yuan_per_box: Decimal
    served_customer_names: tuple[str, ...]
    status: RailTestRateAdmissionStatus
    message: str


@dataclass(frozen=True)
class RailTestWorkbookLoadResult:
    """Typed records plus every confirmed-price source-row outcome."""

    source: str
    records: tuple[RailContainerRateTimeRecord, ...]
    admissions: tuple[RailTestRateAdmission, ...]

    @property
    def admitted_count(self) -> int:
        return sum(
            item.status == "admitted_normal_station_od" for item in self.admissions
        )


def load_confirmed_rail_test_workbook(
    path: str | Path,
    *,
    node_registry: NodeRegistry,
) -> RailTestWorkbookLoadResult:
    """Load the confirmed 8.28 open-top rail freight source read-only.

    The input amount is *only* railway freight.  The adapter attaches the
    confirmed station-handling and open-top tarpaulin parameters as separate
    components, while storage and detention charges remain out of scope.
    """

    workbook_path = Path(path)
    try:
        route_rows = read_excel_table(
            _first_batch_route_source(workbook_path),
            base_dir=workbook_path.parent,
            required_fields=("north_station_name", "south_station_name", "railway_freight_yuan_per_group"),
        )
        north_rows = read_excel_table(
            _first_batch_station_source(workbook_path, NORTH_STATION_SHEET),
            base_dir=workbook_path.parent,
            required_fields=("station_name", "province", "city"),
        )
        south_rows = read_excel_table(
            _first_batch_station_source(workbook_path, SOUTH_STATION_SHEET),
            base_dir=workbook_path.parent,
            required_fields=("station_name", "province", "city"),
        )
        station_locations = _station_locations_from_mapped_rows((*north_rows, *south_rows))
        return _build_result(
            source=workbook_path.name,
            route_rows=_first_batch_route_values(route_rows),
            station_locations=station_locations,
            node_registry=node_registry,
        )
    except LocalExcelTableError as exc:
        raise RailTestWorkbookError(str(exc)) from exc


def _first_batch_route_source(path: Path) -> ExcelTableSource:
    return ExcelTableSource(
        source_id="first_batch_test_trunk_rate",
        table_type="trunk_rate",
        workbook=path.name,
        sheet_name=TEST_ROUTE_SHEET,
        field_mapping={
            "north_station_name": ("发站",),
            "south_station_name": ("到站",),
            "railway_freight_yuan_per_group": ("敞顶箱-8.28查询",),
            "customer_1": ("到客户1费用",),
            "customer_2": ("到客户2费用",),
        },
    )


def _first_batch_station_source(path: Path, sheet_name: str) -> ExcelTableSource:
    return ExcelTableSource(
        source_id=f"first_batch_{sheet_name}",
        table_type="station_master",
        workbook=path.name,
        sheet_name=sheet_name,
        field_mapping={
            "station_name": ("节点名称",),
            "province": ("所在省/自治区/直辖市",),
            "city": ("所在市",),
        },
    )


def _first_batch_route_values(rows: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
    headers = ("发站", "到站", "敞顶箱-8.28查询", "到客户1费用", "到客户2费用")
    values = tuple(
        (
            row.value("north_station_name"),
            row.value("south_station_name"),
            row.value("railway_freight_yuan_per_group"),
            row.value("customer_1"),
            row.value("customer_2"),
        )
        for row in rows
    )
    return (headers, *values)


def _station_locations_from_mapped_rows(rows: tuple[object, ...]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    ambiguous_keys: set[str] = set()
    for row in rows:
        name = _text(row.value("station_name"))
        province = _text(row.value("province"))
        city = _text(row.value("city"))
        if not name or not province or not city:
            continue
        key = _station_key(name)
        if key in ambiguous_keys:
            continue
        location = (province, city)
        current = result.get(key)
        if current is not None and current != location:
            result.pop(key, None)
            ambiguous_keys.add(key)
            continue
        result[key] = location
    return result


def load_confirmed_rail_station_nodes(data_dir: str | Path) -> tuple[NodeRecord, ...]:
    """Read only the current project-confirmed north/south station masters."""

    root = Path(data_dir)
    paths = tuple(root / name for name in (CONFIRMED_NORTH_STATION_FILE, CONFIRMED_SOUTH_STATION_FILE))
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise RailTestWorkbookError(f"缺少确认铁路站点主数据：{'、'.join(missing)}")
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency boundary
        raise RailTestWorkbookError("读取铁路站点主数据需要本地 openpyxl 依赖。") from exc

    records: dict[str, NodeRecord] = {}
    for path in paths:
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise RailTestWorkbookError(f"{path.name} 无法作为 Excel 工作簿读取：{exc}") from exc
        try:
            sheet = workbook.active
            rows = sheet.iter_rows(values_only=True)
            try:
                headers = tuple(_text(value) for value in next(rows))
            except StopIteration as exc:
                raise RailTestWorkbookError(f"{path.name} 为空。") from exc
            indexes = _required_indexes(headers, ("节点名称", "经度", "纬度"))
            for row in rows:
                name = _cell(row, indexes["节点名称"])
                longitude = _cell(row, indexes["经度"])
                latitude = _cell(row, indexes["纬度"])
                if not name or longitude is None or latitude is None:
                    continue
                try:
                    record = NodeRecord(
                        make_node_id(name),
                        name,
                        float(longitude),
                        float(latitude),
                    )
                except (TypeError, ValueError):
                    raise RailTestWorkbookError(f"{path.name} 的站点 {name} 坐标无法读取。") from None
                existing = records.get(record.name)
                if existing is not None and existing != record:
                    raise RailTestWorkbookError(f"确认铁路站点主数据中 {record.name} 存在冲突坐标。")
                records[record.name] = record
        finally:
            workbook.close()
    if not records:
        raise RailTestWorkbookError("确认铁路站点主数据没有可用站点。")
    return tuple(records.values())


def build_confirmed_rail_test_rates(
    *,
    source: str,
    route_rows: tuple[tuple[object, ...], ...],
    station_locations: dict[str, tuple[str, str]],
    node_registry: NodeRegistry,
) -> RailTestWorkbookLoadResult:
    """Build test-rate records from already-extracted rows for unit tests/audits."""

    return _build_result(
        source=source,
        route_rows=iter(route_rows),
        station_locations=station_locations,
        node_registry=node_registry,
    )


def _build_result(
    *,
    source: str,
    route_rows: object,
    station_locations: dict[str, tuple[str, str]],
    node_registry: NodeRegistry,
) -> RailTestWorkbookLoadResult:
    iterator = iter(route_rows)
    try:
        raw_headers = next(iterator)
    except StopIteration as exc:
        raise RailTestWorkbookError("测试路线工作表为空。") from exc
    headers = tuple(_text(value) for value in raw_headers)
    indexes = _required_indexes(headers, ("发站", "到站", "敞顶箱-8.28查询", "到客户1费用", "到客户2费用"))

    records: list[RailContainerRateTimeRecord] = []
    admissions: list[RailTestRateAdmission] = []
    seen_od: set[tuple[str, str]] = set()
    for row_number, row in enumerate(iterator, start=2):
        values = tuple(row)
        north_name = _cell(values, indexes["发站"])
        south_name = _cell(values, indexes["到站"])
        raw_amount = _cell(values, indexes["敞顶箱-8.28查询"])
        if not north_name or not south_name or raw_amount is None:
            continue
        amount = _positive_decimal(raw_amount, f"测试路线第 {row_number} 行敞顶箱-8.28查询")
        customers = tuple(
            value
            for value in (
                _cell(values, indexes["到客户1费用"]),
                _cell(values, indexes["到客户2费用"]),
            )
            if isinstance(value, str) and value
        )
        per_box = amount / GROUP_BOX_COUNT
        admission = _admit_row(
            row_number=row_number,
            north_name=north_name,
            south_name=south_name,
            amount=amount,
            per_box=per_box,
            customers=customers,
            station_locations=station_locations,
            node_registry=node_registry,
        )
        admissions.append(admission)
        if admission.status != "admitted_normal_station_od":
            continue

        north = _resolve_station(node_registry, north_name)
        south = _resolve_station(node_registry, south_name)
        assert north is not None and south is not None  # guarded by admission
        key = (north.node_id, south.node_id)
        if key in seen_od:
            raise RailTestWorkbookError(
                f"{source}/测试路线第 {row_number} 行与前序记录重复指向同一北南站 OD，需人工确认。"
            )
        seen_od.add(key)
        _, north_city = station_locations[_station_key(north_name)]
        south_province, south_city = station_locations[_station_key(south_name)]
        records.append(
            RailContainerRateTimeRecord(
                north_station_name=north.canonical_name,
                south_station_name=south.canonical_name,
                north_station_node_id=north.node_id,
                south_station_node_id=south.node_id,
                commodity_scope=("玉米", "小麦"),
                trade_type="内贸",
                container_type="敞顶箱",
                base_freight_yuan_per_box=per_box,
                discount_ratio=Decimal("0"),
                origin_station_fee_yuan_per_box=_station_handling_fee(north_city),
                destination_station_fee_yuan_per_box=_station_handling_fee(south_city),
                duration_hours=_duration_hours_for_location(south_province, south_city),
                source=(
                    f"{source}/{TEST_ROUTE_SHEET}/第{row_number}行/"
                    "敞顶箱-8.28查询（元/组，2箱/组）"
                ),
                source_type="real_data",
            )
        )
    if not admissions:
        raise RailTestWorkbookError(f"{source}/{TEST_ROUTE_SHEET} 没有可读取的敞顶箱-8.28查询金额。")
    return RailTestWorkbookLoadResult(source, tuple(records), tuple(admissions))


def _admit_row(
    *,
    row_number: int,
    north_name: str,
    south_name: str,
    amount: Decimal,
    per_box: Decimal,
    customers: tuple[str, ...],
    station_locations: dict[str, tuple[str, str]],
    node_registry: NodeRegistry,
) -> RailTestRateAdmission:
    common = dict(
        source_row_number=row_number,
        north_station_name=north_name,
        south_terminal_name=south_name,
        railway_freight_yuan_per_group=amount,
        railway_freight_yuan_per_box=per_box,
        served_customer_names=customers,
    )
    if "转" in south_name:
        return RailTestRateAdmission(
            **common,
            status="held_special_terminal",
            message="南端为“站转专用线”复合终点；须拆入专用线末端方案，不能作为普通南站干线边。",
        )
    north = _resolve_station(node_registry, north_name)
    if north is None:
        return RailTestRateAdmission(
            **common,
            status="held_unregistered_north_station",
            message="北站未在当前标准节点注册表唯一命中；不构边。",
        )
    south = _resolve_station(node_registry, south_name)
    if south is None:
        return RailTestRateAdmission(
            **common,
            status="held_missing_station_metadata",
            message="南站未在当前标准节点注册表唯一命中；不构边。",
        )
    north_location = station_locations.get(_station_key(north_name))
    south_location = station_locations.get(_station_key(south_name))
    if north_location is None or south_location is None:
        return RailTestRateAdmission(
            **common,
            status="held_missing_station_metadata",
            message="站点所在地市缺失，无法按确认规则确定装卸费或铁路总时效；不构边。",
        )
    try:
        _duration_hours_for_location(*south_location)
    except RailTestWorkbookError as exc:
        return RailTestRateAdmission(
            **common,
            status="held_missing_station_metadata",
            message=str(exc),
        )
    return RailTestRateAdmission(
        **common,
        status="admitted_normal_station_od",
        message="已匹配标准北南站、确认铁路干线费率、装卸费规则和完整铁路时效。",
    )


def _load_station_locations(workbook: object) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    ambiguous_keys: set[str] = set()
    for sheet_name in (NORTH_STATION_SHEET, SOUTH_STATION_SHEET):
        sheet = workbook[sheet_name]
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = tuple(_text(value) for value in next(rows))
        except StopIteration as exc:
            raise RailTestWorkbookError(f"{sheet_name} 工作表为空。") from exc
        indexes = _required_indexes(headers, ("节点名称", "所在省/自治区/直辖市", "所在市"))
        for row in rows:
            name = _cell(row, indexes["节点名称"])
            province = _cell(row, indexes["所在省/自治区/直辖市"])
            city = _cell(row, indexes["所在市"])
            if not name or not province or not city:
                continue
            key = _station_key(name)
            if key in ambiguous_keys:
                continue
            current = result.get(key)
            location = (province, city)
            if current is not None and current != location:
                # A master workbook may contain an unrelated north/south
                # homonym.  Preserve the ambiguity as missing metadata for
                # affected route rows rather than rejecting all other exact
                # OD records in this first-batch source.
                result.pop(key, None)
                ambiguous_keys.add(key)
                continue
            result[key] = location
    return result


def _required_indexes(headers: tuple[str, ...], required: tuple[str, ...]) -> dict[str, int]:
    indexes = {header: index for index, header in enumerate(headers) if header}
    missing = [name for name in required if name not in indexes]
    if missing:
        raise RailTestWorkbookError(f"工作表缺少必需字段：{'、'.join(missing)}")
    return {name: indexes[name] for name in required}


def _resolve_station(registry: NodeRegistry, name: str):
    candidates = (name, _station_key(name), f"{_station_key(name)}站")
    matches = {
        node.node_id: node
        for candidate in candidates
        if (node := registry.lookup(candidate)) is not None
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _station_key(value: object) -> str:
    text = _text(value)
    return text[:-1] if text.endswith("站") else text


def _station_handling_fee(city: str) -> Decimal:
    return (
        SHAOGUAN_STATION_HANDLING_YUAN_PER_BOX
        if city == "韶关市"
        else STANDARD_STATION_HANDLING_YUAN_PER_BOX
    )


def _duration_hours_for_location(province: str, city: str) -> Decimal:
    if province == "福建省":
        return Decimal("168")
    if province == "广东省":
        return Decimal("192")
    if province == "广西壮族自治区":
        return Decimal("192")
    raise RailTestWorkbookError(
        f"南站所在地为 {province}/{city}，未映射到已确认的福建/广东/广西铁路时效区；不构边。"
    )


def _positive_decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise RailTestWorkbookError(f"{label} 必须为正数。")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RailTestWorkbookError(f"{label} 必须为正数。") from None
    if not result.is_finite() or result <= 0:
        raise RailTestWorkbookError(f"{label} 必须为正数。")
    return result


def _cell(row: tuple[object, ...], index: int) -> object | None:
    if index >= len(row):
        return None
    value = row[index]
    if isinstance(value, str):
        return value.strip() or None
    return value


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""
