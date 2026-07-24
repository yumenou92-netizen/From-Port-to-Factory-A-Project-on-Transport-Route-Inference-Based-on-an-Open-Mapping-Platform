from __future__ import annotations

import csv
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, Sequence

from src.domain.route_request import ALLOWED_TRADE_TYPES, RouteRequest
from src.routing.transport_contracts import CostComponent

if TYPE_CHECKING:
    from src.domain.node_registry import NodeRegistry


PORT_OPERATION_FEE_FILE_NAME = "南港码头作业费.csv"
PORT_OPERATION_FEE_TYPE = "码头作业费"
PORT_OPERATION_FEE_UNIT = "元/吨"
PORT_OPERATION_FEE_UNITS = frozenset({"元/吨", "元/箱"})
PORT_OPERATION_FEE_COMPONENT_TYPE = "south_port_operation_fee"
PORT_OPERATION_FEE_RULE_ID = "south_port_operation_fee_yuan_per_ton"
PORT_OPERATION_FEE_BOX_RULE_ID = "south_port_operation_fee_yuan_per_box"
PORT_OPERATION_FEE_RULE_VERSION = "0.1"
REGIONAL_PROXY_OPERATION_FEE_RULE_ID = "south_port_operation_fee_regional_proxy"
REGIONAL_PROXY_OPERATION_FEE_RULE_VERSION = "1.0"
DEMO_PORT_OPERATION_FEE_RULE_ID = "demo_placeholder_south_port_operation_fee"
DEMO_PORT_OPERATION_FEE_RULE_VERSION = "0.1"

PortOperationFeeStatus = Literal["resolved", "manual_review"]
PortOperationFeeSourceType = Literal["real_data", "regional_proxy", "demo_placeholder"]


class PortOperationFeeError(ValueError):
    """Raised when south-port operation fee interface data is unsafe."""


@dataclass(frozen=True)
class PortOperationFeeRate:
    port_name: str
    package_type: str
    fee_type: str
    unit_price_yuan_per_ton: Decimal
    source: str
    fee_unit: str = PORT_OPERATION_FEE_UNIT
    trade_type: str = "内贸"
    source_type: PortOperationFeeSourceType = "real_data"
    node_id: str | None = None
    commodity_scope: tuple[str, ...] = ("*",)
    aliases: tuple[str, ...] = ()
    maintained_at: str | None = None
    operation_fee_region_code: str | None = None
    is_region_reference: bool = False
    reference_port_node_id: str | None = None
    mapping_source: str | None = None
    mapping_basis: str | None = None
    mapping_rule_id: str | None = None
    mapping_rule_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "port_name", _required_text(self.port_name, "南港名称"))
        object.__setattr__(self, "package_type", _required_text(self.package_type, "包装方式"))
        object.__setattr__(self, "fee_type", _required_text(self.fee_type, "费用类型"))
        object.__setattr__(self, "fee_unit", _required_text(self.fee_unit, "费用单位"))
        object.__setattr__(self, "trade_type", _required_text(self.trade_type, "贸易类型"))
        object.__setattr__(self, "source", _required_text(self.source, "费用来源"))
        object.__setattr__(self, "node_id", _optional_text(self.node_id))
        object.__setattr__(self, "maintained_at", _optional_text(self.maintained_at))
        object.__setattr__(
            self,
            "operation_fee_region_code",
            _optional_text(self.operation_fee_region_code),
        )
        object.__setattr__(
            self,
            "reference_port_node_id",
            _optional_text(self.reference_port_node_id),
        )
        object.__setattr__(self, "mapping_source", _optional_text(self.mapping_source))
        object.__setattr__(self, "mapping_basis", _optional_text(self.mapping_basis))
        object.__setattr__(self, "mapping_rule_id", _optional_text(self.mapping_rule_id))
        object.__setattr__(
            self,
            "mapping_rule_version",
            _optional_text(self.mapping_rule_version),
        )
        object.__setattr__(
            self,
            "commodity_scope",
            _normalized_text_tuple(self.commodity_scope, "适用品种"),
        )
        object.__setattr__(
            self,
            "aliases",
            _normalized_text_tuple(self.aliases, "费用表别名", allow_empty=True),
        )
        if self.source_type not in {"real_data", "regional_proxy", "demo_placeholder"}:
            raise PortOperationFeeError(f"不支持的码头作业费来源类型：{self.source_type}")
        if not isinstance(self.is_region_reference, bool):
            raise PortOperationFeeError("地域代理参考码头标志必须是布尔值。")
        if self.is_region_reference and (
            self.node_id is None or self.operation_fee_region_code is None
        ):
            raise PortOperationFeeError(
                "地域代理参考费率必须包含参考码头 node_id 和 operation_fee_region_code。"
            )
        if self.is_region_reference and self.source_type != "real_data":
            raise PortOperationFeeError("地域代理参考费率必须来自 real_data。")
        if self.source_type == "regional_proxy":
            missing_trace = [
                name
                for name, value in (
                    ("operation_fee_region_code", self.operation_fee_region_code),
                    ("reference_port_node_id", self.reference_port_node_id),
                    ("mapping_source", self.mapping_source),
                    ("mapping_basis", self.mapping_basis),
                    ("mapping_rule_id", self.mapping_rule_id),
                    ("mapping_rule_version", self.mapping_rule_version),
                )
                if value is None
            ]
            if missing_trace:
                raise PortOperationFeeError(
                    "地域代理费率缺少追溯字段：" + "、".join(missing_trace)
                )
        if self.fee_unit not in PORT_OPERATION_FEE_UNITS:
            supported = "、".join(sorted(PORT_OPERATION_FEE_UNITS))
            raise PortOperationFeeError(f"不支持的码头作业费单位：{self.fee_unit}；当前支持 {supported}。")
        if self.trade_type not in ALLOWED_TRADE_TYPES:
            supported = "、".join(sorted(ALLOWED_TRADE_TYPES))
            raise PortOperationFeeError(f"不支持的贸易类型：{self.trade_type}；当前支持 {supported}。")
        object.__setattr__(
            self,
            "unit_price_yuan_per_ton",
            _positive_decimal(self.unit_price_yuan_per_ton, "码头作业费单价"),
        )

    def matches_port(self, *, node_id: str | None, port_name: str) -> bool:
        if self.port_name == "*" or "*" in self.aliases:
            return True
        normalized_node_id = _optional_text(node_id)
        if self.node_id is not None:
            return normalized_node_id == self.node_id
        normalized_name = _required_text(port_name, "南港名称")
        return normalized_name in (self.port_name, *self.aliases)

    def supports_request(self, request: RouteRequest) -> bool:
        return (
            self.package_type == request.package_type
            and self.trade_type == request.trade_type
            and self.fee_unit == f"元/{request.quantity_unit}"
            and (request.commodity in self.commodity_scope or "*" in self.commodity_scope)
        )

    @property
    def source_ref(self) -> str:
        prefix = f"{self.source_type}:"
        return self.source if self.source.startswith(prefix) else f"{prefix}{self.source}"


@dataclass(frozen=True)
class PortOperationFeeRegionAssignment:
    """Confirmed node-to-operation-fee-region mapping used by regional fallback."""

    port_node_id: str
    operation_fee_region_code: str
    source: str
    mapping_basis: str
    mapping_rule_id: str
    mapping_rule_version: str
    confirmation_status: Literal["confirmed", "manual_review"] = "manual_review"
    maintained_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "port_node_id",
            _required_text(self.port_node_id, "地域代理目标港口 node_id"),
        )
        object.__setattr__(
            self,
            "operation_fee_region_code",
            _required_text(self.operation_fee_region_code, "作业费区域编码"),
        )
        object.__setattr__(self, "source", _required_text(self.source, "区域映射来源"))
        object.__setattr__(
            self,
            "mapping_basis",
            _required_text(self.mapping_basis, "地域代理映射依据"),
        )
        object.__setattr__(
            self,
            "mapping_rule_id",
            _required_text(self.mapping_rule_id, "地域代理映射规则编号"),
        )
        object.__setattr__(
            self,
            "mapping_rule_version",
            _required_text(self.mapping_rule_version, "地域代理映射规则版本"),
        )
        object.__setattr__(self, "maintained_at", _optional_text(self.maintained_at))
        if self.confirmation_status not in {"confirmed", "manual_review"}:
            raise PortOperationFeeError(
                f"不支持的地域代理映射确认状态：{self.confirmation_status}"
            )

    @property
    def is_confirmed(self) -> bool:
        return self.confirmation_status == "confirmed"


@dataclass(frozen=True)
class PortOperationFeeQuote:
    status: PortOperationFeeStatus
    message: str
    total_cost_yuan: Decimal | None = None
    component: CostComponent | None = None
    rate: PortOperationFeeRate | None = None

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "manual_review"}:
            raise PortOperationFeeError(f"不支持的码头作业费结果状态：{self.status}")
        object.__setattr__(self, "message", _required_text(self.message, "码头作业费结果说明"))
        if self.status == "resolved":
            if self.total_cost_yuan is None or self.component is None or self.rate is None:
                raise PortOperationFeeError("resolved 码头作业费结果必须包含金额、费用组成和费率。")
        else:
            if self.total_cost_yuan is not None or self.component is not None:
                raise PortOperationFeeError("manual_review 码头作业费结果不得携带可计入金额。")

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class SouthPortOperationFeeProvider(Protocol):
    def quote(
        self,
        *,
        port_name: str,
        request: RouteRequest,
        port_node_id: str | None = None,
        fee_type: str = PORT_OPERATION_FEE_TYPE,
    ) -> PortOperationFeeQuote:
        """Return one operation-fee quote, or manual_review without a usable amount."""


class TablePortOperationFeeProvider:
    def __init__(
        self,
        rates: Sequence[PortOperationFeeRate] = (),
        *,
        region_assignments: Sequence[PortOperationFeeRegionAssignment] = (),
    ) -> None:
        self.rates = tuple(rates)
        self.region_assignments = tuple(region_assignments)

    @classmethod
    def from_csv(
        cls,
        path: Path,
        *,
        registry: NodeRegistry | None = None,
        region_assignments: Sequence[PortOperationFeeRegionAssignment] = (),
    ) -> "TablePortOperationFeeProvider":
        return cls(
            load_port_operation_fee_rates(path, registry=registry),
            region_assignments=region_assignments,
        )

    def quote(
        self,
        *,
        port_name: str,
        request: RouteRequest,
        port_node_id: str | None = None,
        fee_type: str = PORT_OPERATION_FEE_TYPE,
    ) -> PortOperationFeeQuote:
        requested_fee_type = _required_text(fee_type, "费用类型")
        exact_port_matches = [
            rate
            for rate in self.rates
            if rate.fee_type == requested_fee_type
            and rate.source_type != "regional_proxy"
            and rate.matches_port(node_id=port_node_id, port_name=port_name)
        ]
        exact_matches = [rate for rate in exact_port_matches if rate.supports_request(request)]
        if len(exact_matches) > 1:
            sources = "；".join(rate.source_ref for rate in exact_matches)
            return PortOperationFeeQuote(
                status="manual_review",
                message=f"南港 {port_name} 存在多条可匹配 {requested_fee_type} 精确费率，请人工去重：{sources}",
            )
        if len(exact_matches) == 1:
            return make_port_operation_fee_quote(exact_matches[0], request)

        normalized_port_node_id = _optional_text(port_node_id)
        if normalized_port_node_id is None:
            return PortOperationFeeQuote(
                status="manual_review",
                message=(
                    f"南港 {port_name} 没有适用的精确 {requested_fee_type} 费率，且缺少标准 node_id；"
                    "地域代理不得按名称或坐标猜测，当前不计入该费用，也不解释为 0。"
                ),
            )

        assignments = [
            item
            for item in self.region_assignments
            if item.port_node_id == normalized_port_node_id and item.is_confirmed
        ]
        if len(assignments) != 1:
            reason = "未维护已确认映射" if not assignments else "存在多条已确认映射"
            return PortOperationFeeQuote(
                status="manual_review",
                message=(
                    f"南港 {port_name} 没有适用的精确 {requested_fee_type} 费率，且{reason}；"
                    "地域代理不启用，当前不计入该费用，也不解释为 0。"
                ),
            )

        assignment = assignments[0]
        reference_matches = [
            rate
            for rate in self.rates
            if rate.fee_type == requested_fee_type
            and rate.source_type == "real_data"
            and rate.is_region_reference
            and rate.operation_fee_region_code == assignment.operation_fee_region_code
            and rate.supports_request(request)
        ]
        if len(reference_matches) != 1:
            reason = "没有唯一适用参考费率" if not reference_matches else "存在多条适用参考费率"
            return PortOperationFeeQuote(
                status="manual_review",
                message=(
                    f"南港 {port_name} 已映射作业费区域 {assignment.operation_fee_region_code}，"
                    f"但{reason}；当前不计入该费用，也不解释为 0。"
                ),
            )

        reference_rate = reference_matches[0]
        proxy_rate = replace(
            reference_rate,
            port_name=port_name,
            node_id=normalized_port_node_id,
            aliases=(),
            source_type="regional_proxy",
            is_region_reference=False,
            reference_port_node_id=reference_rate.node_id,
            mapping_source=assignment.source,
            mapping_basis=assignment.mapping_basis,
            mapping_rule_id=assignment.mapping_rule_id,
            mapping_rule_version=assignment.mapping_rule_version,
        )
        return make_port_operation_fee_quote(proxy_rate, request)


class DemoPortOperationFeeProvider(TablePortOperationFeeProvider):
    """Explicit placeholder provider for presentation-only operation-fee trials."""

    def __init__(
        self,
        *,
        unit_price_yuan_per_ton: Decimal = Decimal("6"),
        package_type: str = "散粮",
        fee_unit: str = PORT_OPERATION_FEE_UNIT,
        trade_type: str = "内贸",
        commodity_scope: Sequence[str] = ("*",),
    ) -> None:
        super().__init__(
            (
                PortOperationFeeRate(
                    port_name="*",
                    package_type=package_type,
                    fee_type=PORT_OPERATION_FEE_TYPE,
                    unit_price_yuan_per_ton=unit_price_yuan_per_ton,
                    source="demo_placeholder:south_port_operation_fee",
                    fee_unit=fee_unit,
                    trade_type=trade_type,
                    source_type="demo_placeholder",
                    aliases=("*",),
                    commodity_scope=tuple(commodity_scope),
                ),
            )
        )


def make_port_operation_fee_quote(
    rate: PortOperationFeeRate,
    request: RouteRequest,
) -> PortOperationFeeQuote:
    expected_fee_unit = f"元/{request.quantity_unit}"
    if rate.fee_unit != expected_fee_unit:
        return PortOperationFeeQuote(
            status="manual_review",
            message=(
                f"码头作业费费率单位为 {rate.fee_unit}，订单单位为 {request.quantity_unit}；"
                "不做吨/箱/柜单位互换。"
            ),
        )
    total_cost = rate.unit_price_yuan_per_ton * request.quantity
    proxy_trace = ""
    if rate.source_type == "regional_proxy":
        proxy_trace = (
            f"；地域代理区域={rate.operation_fee_region_code}"
            f"；参考码头node_id={rate.reference_port_node_id}"
            f"；映射来源={rate.mapping_source}"
            f"；映射依据={rate.mapping_basis}"
            f"；映射规则={rate.mapping_rule_id}/{rate.mapping_rule_version}"
            "；该费率不是目标码头精确真实费率"
        )
    if rate.source_type == "demo_placeholder":
        rule_id = DEMO_PORT_OPERATION_FEE_RULE_ID
        rule_version = DEMO_PORT_OPERATION_FEE_RULE_VERSION
    elif rate.source_type == "regional_proxy":
        rule_id = REGIONAL_PROXY_OPERATION_FEE_RULE_ID
        rule_version = (
            rate.mapping_rule_version or REGIONAL_PROXY_OPERATION_FEE_RULE_VERSION
        )
    elif rate.fee_unit == "元/箱":
        rule_id = PORT_OPERATION_FEE_BOX_RULE_ID
        rule_version = PORT_OPERATION_FEE_RULE_VERSION
    else:
        rule_id = PORT_OPERATION_FEE_RULE_ID
        rule_version = PORT_OPERATION_FEE_RULE_VERSION
    component = CostComponent(
        component_type=PORT_OPERATION_FEE_COMPONENT_TYPE,
        amount_yuan=total_cost,
        source_type=rate.source_type,
        source=rate.source_ref,
        rule_id=rule_id,
        rule_version=rule_version,
        calculation_detail=(
            f"{rate.fee_type}：{rate.unit_price_yuan_per_ton}{rate.fee_unit}"
            f"×{request.quantity}{request.quantity_unit}={total_cost}元；"
            f"贸易类型={rate.trade_type}；来源={rate.source_ref}{proxy_trace}"
        ),
    )
    return PortOperationFeeQuote(
        status="resolved",
        total_cost_yuan=total_cost,
        component=component,
        rate=rate,
        message=(
            f"已按 {rate.fee_unit} 汇总码头作业费生成独立费用组成。"
            if rate.source_type != "regional_proxy"
            else (
                "目标码头无适用精确费率；已按人工维护的作业费区域引用唯一参考码头费率。"
                "该结果标记为 regional_proxy，不代表目标码头真实精确费率。"
            )
        ),
    )


def find_optional_port_operation_fee_file(data_dir: Path) -> Path | None:
    matches = sorted(data_dir.rglob(PORT_OPERATION_FEE_FILE_NAME))
    if not matches:
        return None
    if len(matches) > 1:
        joined = "; ".join(str(path) for path in matches)
        raise PortOperationFeeError(f"DATA_DIR 下存在多个 {PORT_OPERATION_FEE_FILE_NAME}，请先明确数据来源：{joined}")
    return matches[0]


def load_port_operation_fee_rates(
    path: Path,
    *,
    registry: NodeRegistry | None = None,
) -> list[PortOperationFeeRate]:
    rows = read_csv_rows(path)
    rates: list[PortOperationFeeRate] = []
    for row_no, row in enumerate(rows, start=2):
        port_name = read_field(row, row_no, "port_name", required=True)
        explicit_node_id = read_field(row, row_no, "node_id", required=False)
        registry_node = registry.lookup(port_name) if registry is not None else None
        fee_unit = read_field(row, row_no, "fee_unit", required=True)
        if fee_unit not in PORT_OPERATION_FEE_UNITS:
            supported = "、".join(sorted(PORT_OPERATION_FEE_UNITS))
            raise PortOperationFeeError(
                f"{path.name} 第 {row_no} 行费用单位为 {fee_unit}，当前仅支持 {supported}。"
            )
        source_type = read_field(row, row_no, "source_type", required=False) or "real_data"
        if source_type == "regional_proxy":
            raise PortOperationFeeError(
                f"{path.name} 第 {row_no} 行不得直接维护 regional_proxy；"
                "地域代理必须由真实参考码头费率和已确认区域映射在运行时生成。"
            )
        rates.append(
            PortOperationFeeRate(
                port_name=port_name,
                package_type=read_field(row, row_no, "package_type", required=True),
                fee_type=read_field(row, row_no, "fee_type", required=True),
                unit_price_yuan_per_ton=_positive_decimal(
                    read_field(row, row_no, "unit_price", required=True),
                    "码头作业费单价",
                ),
                source=read_field(row, row_no, "source", required=True),
                fee_unit=fee_unit,
                trade_type=read_field(row, row_no, "trade_type", required=False) or "内贸",
                source_type=source_type,
                node_id=explicit_node_id or (registry_node.node_id if registry_node else None),
                commodity_scope=split_text_list(
                    read_field(row, row_no, "commodity_scope", required=False) or "*"
                ),
                aliases=split_text_list(read_field(row, row_no, "aliases", required=False), allow_empty=True),
                maintained_at=read_field(row, row_no, "maintained_at", required=False),
                operation_fee_region_code=read_field(
                    row,
                    row_no,
                    "operation_fee_region_code",
                    required=False,
                ),
                is_region_reference=parse_optional_bool(
                    read_field(row, row_no, "is_region_reference", required=False),
                    path,
                    row_no,
                    "is_region_reference",
                    default=False,
                ),
                reference_port_node_id=read_field(
                    row,
                    row_no,
                    "reference_port_node_id",
                    required=False,
                ),
                mapping_basis=read_field(row, row_no, "mapping_basis", required=False),
                mapping_rule_id=read_field(row, row_no, "mapping_rule_id", required=False),
                mapping_rule_version=read_field(
                    row,
                    row_no,
                    "mapping_rule_version",
                    required=False,
                ),
            )
        )
    return rates


FIELD_ALIASES = {
    "node_id": ("node_id", "节点ID", "标准节点ID"),
    "port_name": ("port_name", "港口名称", "南港名称", "节点名称"),
    "package_type": ("package_type", "包装方式"),
    "fee_type": ("fee_type", "费用类型"),
    "unit_price": ("unit_price", "单价", "费率"),
    "fee_unit": ("fee_unit", "费用单位", "单位"),
    "trade_type": ("trade_type", "tradeType", "贸易类型", "内外贸"),
    "source": ("source", "数据来源", "来源"),
    "source_type": ("source_type", "来源类型"),
    "commodity_scope": ("commodity_scope", "适用品种", "品种范围"),
    "aliases": ("aliases", "别名", "别名列表"),
    "maintained_at": ("maintained_at", "维护日期"),
    "operation_fee_region_code": (
        "operation_fee_region_code",
        "作业费区域编码",
        "码头作业费区域编码",
    ),
    "is_region_reference": ("is_region_reference", "是否地域代理参考码头"),
    "reference_port_node_id": ("reference_port_node_id", "参考码头节点ID"),
    "mapping_basis": ("mapping_basis", "映射依据"),
    "mapping_rule_id": ("mapping_rule_id", "映射规则编号"),
    "mapping_rule_version": ("mapping_rule_version", "映射规则版本"),
}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    last_decode_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise PortOperationFeeError(f"{path.name} 缺少表头。")
                return [
                    {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
                    for row in reader
                ]
        except UnicodeDecodeError as exc:
            last_decode_error = exc
            continue
        except OSError as exc:
            raise PortOperationFeeError(f"无法读取 {path}: {exc}") from exc
    raise PortOperationFeeError(
        f"无法解码 {path}; supported encodings: utf-8-sig, gb18030."
    ) from last_decode_error


def read_field(row: dict[str, str], row_no: int, logical_name: str, *, required: bool) -> str:
    for field_name in FIELD_ALIASES[logical_name]:
        if field_name in row and row[field_name].strip():
            return row[field_name].strip()
    if required:
        aliases = " / ".join(FIELD_ALIASES[logical_name])
        raise PortOperationFeeError(f"第 {row_no} 行缺少必填字段：{aliases}")
    return ""


def split_text_list(value: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in re.split(r"[;,，；、|/]+", value or "") if part.strip())
    if not parts and not allow_empty:
        raise PortOperationFeeError("列表字段不能为空。")
    return tuple(dict.fromkeys(parts))


TRUE_VALUES = {"1", "true", "yes", "y", "是"}
FALSE_VALUES = {"0", "false", "no", "n", "否"}


def parse_optional_bool(
    value: str,
    path: Path,
    row_no: int,
    field_name: str,
    *,
    default: bool,
) -> bool:
    text = str(value).strip().lower()
    if not text:
        return default
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise PortOperationFeeError(
        f"{path.name} 第 {row_no} 行字段 {field_name} 必须是明确布尔值。"
    )


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise PortOperationFeeError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_text_tuple(
    values: Sequence[object],
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    try:
        normalized = tuple(_required_text(value, field_name) for value in values)
    except TypeError:
        raise PortOperationFeeError(f"{field_name}必须是可迭代文本。") from None
    if not normalized and not allow_empty:
        raise PortOperationFeeError(f"{field_name}不能为空。")
    return tuple(dict.fromkeys(normalized))


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise PortOperationFeeError(f"{field_name}必须是大于 0 的有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise PortOperationFeeError(f"{field_name}必须是大于 0 的有限数值。") from None
    if not number.is_finite() or number <= 0:
        raise PortOperationFeeError(f"{field_name}必须是大于 0 的有限数值。")
    return number
