"""Formal contract for future north-to-south container-vessel data.

This module deliberately has no fallback to bulk-shipping rates, bulk shipping
times, barge rules, or rail rules.  A container-vessel trunk becomes a graph
edge only after a confirmed record supplies both a price and a complete-segment
duration for the exact order scope.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Sequence

from src.domain.freight_rate import FreightRate, PriceType, create_freight_rate
from src.domain.latest_rate_selector import select_latest_freight_rates
from src.domain.route_request import RouteRequest
from src.routing.shipping_time_provider import ShippingTimeResult
from src.routing.transport_contracts import CostComponent
from src.routing.transport_edge import TransportEdge, build_transport_edge


CONTAINER_SHIPPING_FILE_NAME = "集装箱船运价时效.csv"
CONTAINER_SHIPPING_RULE_ID = "container_vessel_confirmed_rate_time"
CONTAINER_SHIPPING_RULE_VERSION = "1.0"

ContainerShippingStatus = Literal["resolved", "not_applicable", "manual_review"]


class ContainerShippingError(ValueError):
    """Raised when a container-vessel source cannot be consumed safely."""


@dataclass(frozen=True)
class ContainerShippingRateTimeRecord:
    """One confirmed north-to-south container-vessel rate/time record.

    ``price_type`` deliberately supports both per-box and quoted-total records;
    the pricing unit is checked exactly and no ``箱``/``柜`` conversion exists.
    """

    origin_name: str
    south_port_name: str
    transport_mode: str
    package_type: str
    quantity_unit: str
    commodity_scope: tuple[str, ...]
    trade_type: str
    raw_price: Decimal
    raw_price_unit: str
    price_type: PriceType
    duration_hours: Decimal
    source: str
    confirmation_status: Literal["confirmed", "manual_review"]
    origin_node_id: str | None = None
    south_port_node_id: str | None = None
    maintained_at: str | None = None
    source_row_number: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin_name", _required_text(self.origin_name, "北港名称"))
        object.__setattr__(self, "south_port_name", _required_text(self.south_port_name, "南港名称"))
        object.__setattr__(self, "transport_mode", _required_text(self.transport_mode, "运输方式"))
        object.__setattr__(self, "package_type", _required_text(self.package_type, "包装方式"))
        object.__setattr__(self, "quantity_unit", _required_text(self.quantity_unit, "订单数量单位"))
        object.__setattr__(self, "commodity_scope", _text_list(self.commodity_scope, "适用品种"))
        object.__setattr__(self, "trade_type", _required_text(self.trade_type, "贸易类型"))
        object.__setattr__(self, "raw_price", _positive_decimal(self.raw_price, "集装箱船报价"))
        object.__setattr__(self, "raw_price_unit", _required_text(self.raw_price_unit, "报价单位"))
        object.__setattr__(self, "duration_hours", _positive_decimal(self.duration_hours, "航运总时效"))
        object.__setattr__(self, "source", _required_text(self.source, "数据来源"))
        object.__setattr__(self, "origin_node_id", _optional_text(self.origin_node_id))
        object.__setattr__(self, "south_port_node_id", _optional_text(self.south_port_node_id))
        object.__setattr__(self, "maintained_at", _optional_text(self.maintained_at))

        if self.transport_mode != "集装箱船":
            raise ContainerShippingError("北港至南港集装箱干线运输方式必须为“集装箱船”。")
        if self.package_type != "集装箱":
            raise ContainerShippingError("集装箱船干线记录的包装方式必须为“集装箱”。")
        if self.quantity_unit != "箱":
            raise ContainerShippingError("集装箱船首轮只支持订单数量单位“箱”，不得把“柜”换算为“箱”。")
        if self.trade_type not in {"内贸", "外贸"}:
            raise ContainerShippingError("贸易类型必须为“内贸”或“外贸”。")
        if self.price_type not in {"unit_price", "total_price"}:
            raise ContainerShippingError("价格类型必须为 unit_price 或 total_price。")
        if self.price_type == "unit_price" and _normalize_unit(self.raw_price_unit) != "元/箱":
            raise ContainerShippingError("集装箱船单价记录的报价单位必须为“元/箱”。")
        if self.price_type == "total_price" and _normalize_unit(self.raw_price_unit) != "元":
            raise ContainerShippingError("集装箱船总价记录的报价单位必须为“元”。")
        if self.confirmation_status not in {"confirmed", "manual_review"}:
            raise ContainerShippingError("确认状态必须为 confirmed 或 manual_review。")
        if self.source_row_number is not None and self.source_row_number <= 0:
            raise ContainerShippingError("来源行号必须为正整数或空。")

    def supports_request(self, request: RouteRequest) -> bool:
        return (
            request.package_type == self.package_type
            and request.quantity_unit == self.quantity_unit
            and request.trade_type == self.trade_type
            and (request.commodity in self.commodity_scope or "*" in self.commodity_scope)
        )

    def to_freight_rate(self) -> FreightRate:
        return create_freight_rate(
            origin_name=self.origin_name,
            destination_name=self.south_port_name,
            transport_mode=self.transport_mode,
            package_type=self.package_type,
            commodity_scope="、".join(self.commodity_scope),
            raw_price=self.raw_price,
            raw_price_unit=self.raw_price_unit,
            price_type=self.price_type,
            price_source=f"real_business_data:{self.source}",
            maintained_at=self.maintained_at,
            from_node_id=self.origin_node_id,
            to_node_id=self.south_port_node_id,
            source_file=CONTAINER_SHIPPING_FILE_NAME,
            source_row_number=self.source_row_number,
        )


@dataclass(frozen=True)
class ContainerShippingMatch:
    status: ContainerShippingStatus
    message: str
    record: ContainerShippingRateTimeRecord | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class TableContainerShippingProvider:
    """Match confirmed container-vessel records without any implicit fallback."""

    def __init__(self, records: Sequence[ContainerShippingRateTimeRecord]) -> None:
        self.records = tuple(records)

    @classmethod
    def from_csv(cls, path: Path) -> "TableContainerShippingProvider":
        return cls(load_container_shipping_records(path))

    def match(
        self,
        *,
        origin_name: str,
        south_port_name: str,
        request: RouteRequest,
        origin_node_id: str | None = None,
        south_port_node_id: str | None = None,
    ) -> ContainerShippingMatch:
        if request.package_type != "集装箱" or request.quantity_unit != "箱":
            return ContainerShippingMatch(
                status="not_applicable",
                message="集装箱船首轮仅支持“集装箱/箱”订单；“柜”不得自动换算或构边。",
            )

        candidates = [
            record
            for record in self.records
            if record.confirmation_status == "confirmed"
            and record.supports_request(request)
            and _same_endpoint(record.origin_node_id, record.origin_name, origin_node_id, origin_name)
            and _same_endpoint(
                record.south_port_node_id,
                record.south_port_name,
                south_port_node_id,
                south_port_name,
            )
        ]
        if not candidates:
            return ContainerShippingMatch(
                status="manual_review",
                message=(
                    f"未找到 {origin_name} 至 {south_port_name} 适用于当前订单的已确认集装箱船"
                    "运价与航运总时效；北港—南港集装箱船干线不构边。"
                ),
            )

        rates = [record.to_freight_rate() for record in candidates]
        selection = select_latest_freight_rates(rates)
        if selection.review_issues or len(selection.selected_rates) != 1:
            return ContainerShippingMatch(
                status="manual_review",
                message=(
                    f"{origin_name} 至 {south_port_name} 的集装箱船报价存在同日冲突或无法唯一选择"
                    "最新记录，请人工复核后再构边。"
                ),
            )
        selected_rate = selection.selected_rates[0]
        selected_records = [
            record
            for record in candidates
            if record.to_freight_rate().rate_id == selected_rate.rate_id
        ]
        if len(selected_records) != 1:
            return ContainerShippingMatch(
                status="manual_review",
                message=(
                    f"{origin_name} 至 {south_port_name} 的集装箱船报价在同一费率身份下"
                    "对应多条时效记录，请人工确认后再构边。"
                ),
            )
        selected = selected_records[0]
        return ContainerShippingMatch(
            status="resolved",
            message="已匹配已确认集装箱船运价与航运总时效。",
            record=selected,
        )

    def build_edge(
        self,
        *,
        origin_name: str,
        south_port_name: str,
        request: RouteRequest,
        origin_node_id: str | None = None,
        south_port_node_id: str | None = None,
    ) -> tuple[TransportEdge | None, ContainerShippingMatch]:
        match = self.match(
            origin_name=origin_name,
            south_port_name=south_port_name,
            request=request,
            origin_node_id=origin_node_id,
            south_port_node_id=south_port_node_id,
        )
        if not match.is_resolved or match.record is None:
            return None, match
        record = match.record
        rate = record.to_freight_rate()
        cost = rate.evaluate_for_request(request)
        time = ShippingTimeResult(
            status="resolved",
            duration_hours=record.duration_hours,
            source=f"real_business_data:{record.source}",
            message="已使用维护的集装箱船航运总时效；模型不拆分时间组成。",
            stage=f"{origin_name}至{south_port_name}",
            transport_mode="集装箱船",
            input_value=str(record.duration_hours),
            input_unit="小时",
            time_scope="complete_segment",
        )
        if cost.status != "valid" or cost.total_cost_yuan is None:
            return None, ContainerShippingMatch(
                status="manual_review",
                message=f"集装箱船报价未通过精确计费校验：{cost.message}",
            )
        edge = build_transport_edge(
            rate,
            cost,
            time,
            commodity=request.commodity,
            data_source=f"real_business_data:{record.source}",
            transport_stage="north_to_south",
            edge_role="trunk",
            cost_components=(
                CostComponent(
                    component_type="container_vessel_freight",
                    amount_yuan=cost.total_cost_yuan,
                    source_type="real_data",
                    source=record.source,
                    rule_id=CONTAINER_SHIPPING_RULE_ID,
                    rule_version=CONTAINER_SHIPPING_RULE_VERSION,
                    calculation_detail=cost.calculation_detail,
                ),
            ),
        )
        if not edge.is_available:
            return None, ContainerShippingMatch(
                status="manual_review",
                message=f"集装箱船边未通过 TransportEdge 校验：{edge.unavailable_reason}",
            )
        return edge, match


def find_optional_container_shipping_file(data_dir: Path) -> Path | None:
    matches = sorted(Path(data_dir).rglob(CONTAINER_SHIPPING_FILE_NAME))
    if len(matches) > 1:
        raise ContainerShippingError(
            f"DATA_DIR 下存在多个 {CONTAINER_SHIPPING_FILE_NAME}，请先明确数据来源："
            + "；".join(str(path) for path in matches)
        )
    return matches[0] if matches else None


def load_container_shipping_records(path: Path) -> tuple[ContainerShippingRateTimeRecord, ...]:
    rows = _read_csv(path)
    records: list[ContainerShippingRateTimeRecord] = []
    for row_number, row in enumerate(rows, start=2):
        records.append(
            ContainerShippingRateTimeRecord(
                origin_name=_field(row, "origin_name", row_number, required=True),
                south_port_name=_field(row, "south_port_name", row_number, required=True),
                transport_mode=_field(row, "transport_mode", row_number, required=True),
                package_type=_field(row, "package_type", row_number, required=True),
                quantity_unit=_field(row, "quantity_unit", row_number, required=True),
                commodity_scope=_split_list(_field(row, "commodity_scope", row_number, required=True)),
                trade_type=_field(row, "trade_type", row_number, required=True),
                raw_price=_field(row, "raw_price", row_number, required=True),
                raw_price_unit=_field(row, "raw_price_unit", row_number, required=True),
                price_type=_field(row, "price_type", row_number, required=True),
                duration_hours=_field(row, "duration_hours", row_number, required=True),
                source=_field(row, "source", row_number, required=True),
                confirmation_status=_field(row, "confirmation_status", row_number, required=True),
                origin_node_id=_field(row, "origin_node_id", row_number, required=False),
                south_port_node_id=_field(row, "south_port_node_id", row_number, required=False),
                maintained_at=_field(row, "maintained_at", row_number, required=False),
                source_row_number=row_number,
            )
        )
    return tuple(records)


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "origin_node_id": ("origin_node_id", "北港节点ID", "始发节点ID"),
    "origin_name": ("origin_name", "北港名称", "始发港"),
    "south_port_node_id": ("south_port_node_id", "南港节点ID", "到达节点ID"),
    "south_port_name": ("south_port_name", "南港名称", "到达港"),
    "transport_mode": ("transport_mode", "运输方式"),
    "package_type": ("package_type", "包装方式"),
    "quantity_unit": ("quantity_unit", "订单数量单位", "计费数量单位"),
    "commodity_scope": ("commodity_scope", "适用品种", "货物品种"),
    "trade_type": ("trade_type", "贸易类型"),
    "raw_price": ("raw_price", "报价", "单价或总价"),
    "raw_price_unit": ("raw_price_unit", "报价单位", "费用单位"),
    "price_type": ("price_type", "价格类型"),
    "duration_hours": ("duration_hours", "航运总时效小时", "时效小时"),
    "source": ("source", "数据来源", "来源"),
    "confirmation_status": ("confirmation_status", "确认状态"),
    "maintained_at": ("maintained_at", "维护日期"),
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    decode_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise ContainerShippingError(f"{path.name} 缺少表头。")
                return [
                    {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
                    for row in reader
                ]
        except UnicodeDecodeError as exc:
            decode_error = exc
    raise ContainerShippingError(f"无法解码 {path}。") from decode_error


def _field(row: dict[str, str], name: str, row_number: int, *, required: bool) -> str:
    for alias in FIELD_ALIASES[name]:
        value = row.get(alias, "").strip()
        if value:
            return value
    if required:
        raise ContainerShippingError(
            f"{CONTAINER_SHIPPING_FILE_NAME} 第 {row_number} 行缺少必填字段："
            + " / ".join(FIELD_ALIASES[name])
        )
    return ""


def _same_endpoint(record_id: str | None, record_name: str, requested_id: str | None, requested_name: str) -> bool:
    if record_id and requested_id:
        return record_id == requested_id
    return _normalize_name(record_name) == _normalize_name(requested_name)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value).strip())


def _normalize_unit(value: str) -> str:
    return str(value).strip().replace(" ", "").replace("／", "/")


def _split_list(value: str) -> tuple[str, ...]:
    return _text_list(tuple(part for part in re.split(r"[,，、;/；|]+", value) if part.strip()), "适用品种")


def _text_list(values: Sequence[object], field_name: str) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(_required_text(value, field_name) for value in values))
    if not result:
        raise ContainerShippingError(f"{field_name}不能为空。")
    return result


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ContainerShippingError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _positive_decimal(value: object, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise ContainerShippingError(f"{field_name}必须是数值。") from None
    if not number.is_finite() or number <= 0:
        raise ContainerShippingError(f"{field_name}必须是大于 0 的有限数值。")
    return number
