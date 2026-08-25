from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

try:
    from .cost_rules import CostCalculationResult
    from .freight_rate import FreightRate
    from .shipping_time_provider import ShippingTimeResult
    from .transport_contracts import (
        CostComponent,
        CostComposition,
        ManualReviewOutcome,
        TimeScope,
        TransportEdgeRole,
        TransportStage,
        validate_transport_semantics,
    )
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.domain.cost_rules import CostCalculationResult
    from src.domain.freight_rate import FreightRate
    from src.routing.shipping_time_provider import ShippingTimeResult
    from src.routing.transport_contracts import (
        CostComponent,
        CostComposition,
        ManualReviewOutcome,
        TimeScope,
        TransportEdgeRole,
        TransportStage,
        validate_transport_semantics,
    )


TransportEdgeStatus = Literal["available", "not_applicable", "manual_review"]


class TransportEdgeError(ValueError):
    """Raised when a transport edge cannot be represented safely."""


@dataclass(frozen=True)
class TransportEdge:
    edge_id: str
    status: TransportEdgeStatus
    from_node_id: str | None
    to_node_id: str | None
    transport_mode: str
    package_type: str
    commodity: str
    cost_yuan: Decimal | None
    time_hours: Decimal | None
    raw_price: Decimal | None
    raw_price_unit: str | None
    price_source: str | None
    maintained_at: date | None
    distance_km: Decimal | None
    distance_source: str | None
    time_source: str | None
    cost_rule_id: str | None
    cost_rule_version: str | None
    calculation_detail: str | None
    data_source: str
    unavailable_reason: str | None = None
    transport_stage: TransportStage | None = None
    edge_role: TransportEdgeRole | None = None
    time_scope: TimeScope | None = None
    cost_components: tuple[CostComponent, ...] = ()
    manual_review_outcomes: tuple[ManualReviewOutcome, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"available", "not_applicable", "manual_review"}:
            raise TransportEdgeError(f"不支持的运输边状态：{self.status}")

        object.__setattr__(self, "edge_id", _required_text(self.edge_id, "运输边编号"))
        object.__setattr__(self, "from_node_id", _optional_text(self.from_node_id))
        object.__setattr__(self, "to_node_id", _optional_text(self.to_node_id))
        object.__setattr__(self, "transport_mode", _required_text(self.transport_mode, "运输方式"))
        object.__setattr__(self, "package_type", _required_text(self.package_type, "包装方式"))
        object.__setattr__(self, "commodity", _required_text(self.commodity, "货物品种"))
        object.__setattr__(self, "raw_price_unit", _optional_text(self.raw_price_unit))
        object.__setattr__(self, "price_source", _optional_text(self.price_source))
        object.__setattr__(self, "distance_source", _optional_text(self.distance_source))
        object.__setattr__(self, "time_source", _optional_text(self.time_source))
        object.__setattr__(self, "cost_rule_id", _optional_text(self.cost_rule_id))
        object.__setattr__(self, "cost_rule_version", _optional_text(self.cost_rule_version))
        object.__setattr__(self, "calculation_detail", _optional_text(self.calculation_detail))
        object.__setattr__(self, "data_source", _required_text(self.data_source, "运输边数据来源"))
        object.__setattr__(self, "unavailable_reason", _optional_text(self.unavailable_reason))
        object.__setattr__(self, "transport_stage", _optional_text(self.transport_stage))
        object.__setattr__(self, "edge_role", _optional_text(self.edge_role))
        object.__setattr__(self, "time_scope", _optional_text(self.time_scope))
        object.__setattr__(self, "cost_components", tuple(self.cost_components))
        object.__setattr__(self, "manual_review_outcomes", tuple(self.manual_review_outcomes))
        try:
            validate_transport_semantics(
                self.transport_stage,
                self.edge_role,
                self.time_scope,
            )
        except ValueError as exc:
            raise TransportEdgeError(str(exc)) from None

        cost = _optional_positive_decimal(self.cost_yuan, "运输段总费用")
        time = _optional_positive_decimal(self.time_hours, "运输时间")
        raw_price = _optional_finite_decimal(self.raw_price, "原始价格")
        distance = _optional_positive_decimal(self.distance_km, "距离")
        object.__setattr__(self, "cost_yuan", cost)
        object.__setattr__(self, "time_hours", time)
        object.__setattr__(self, "raw_price", raw_price)
        object.__setattr__(self, "distance_km", distance)

        if (distance is None) != (self.distance_source is None):
            raise TransportEdgeError("距离数值和距离来源必须同时存在或同时为空。")
        if self.maintained_at is not None and not isinstance(self.maintained_at, date):
            raise TransportEdgeError("运价维护日期必须是 date 或 None。")

        if self.status == "available":
            required_values = {
                "起点节点": self.from_node_id,
                "终点节点": self.to_node_id,
                "运输段总费用": cost,
                "运输时间": time,
                "原始价格": raw_price,
                "原始费用单位": self.raw_price_unit,
                "价格来源": self.price_source,
                "时间来源": self.time_source,
                "计费规则编号": self.cost_rule_id,
                "计费规则版本": self.cost_rule_version,
                "计费过程": self.calculation_detail,
            }
            missing = [name for name, value in required_values.items() if value is None]
            if missing:
                raise TransportEdgeError(f"可用运输边缺少字段：{'、'.join(missing)}。")
            if raw_price is not None and raw_price <= 0:
                raise TransportEdgeError("可用运输边的原始价格必须大于 0。")
            if self.unavailable_reason is not None:
                raise TransportEdgeError("可用运输边不得包含不可用原因。")
            if self.manual_review_outcomes:
                raise TransportEdgeError("可用运输边不得包含人工复核结果。")
            if self.cost_components:
                try:
                    CostComposition(self.cost_components).validate_total(cost)
                except ValueError as exc:
                    raise TransportEdgeError(str(exc)) from None
        elif self.unavailable_reason is None:
            raise TransportEdgeError("不可用运输边必须说明原因。")

    @property
    def edge_key(self) -> str:
        return self.edge_id

    @property
    def cost(self) -> Decimal | None:
        return self.cost_yuan

    @property
    def is_available(self) -> bool:
        return self.status == "available"

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"

    def to_graph_attributes(self) -> dict[str, Any]:
        if not self.is_available:
            raise TransportEdgeError(
                f"不可用运输边 {self.edge_id} 不能加入正式图：{self.unavailable_reason}"
            )
        return {
            "edge_id": self.edge_id,
            "status": self.status,
            "transport_mode": self.transport_mode,
            "package_type": self.package_type,
            "commodity": self.commodity,
            "cost": self.cost_yuan,
            "cost_yuan": self.cost_yuan,
            "time_hours": self.time_hours,
            "raw_price": self.raw_price,
            "raw_price_unit": self.raw_price_unit,
            "price_source": self.price_source,
            "maintained_at": self.maintained_at,
            "distance_km": self.distance_km,
            "distance_source": self.distance_source,
            "time_source": self.time_source,
            "cost_rule_id": self.cost_rule_id,
            "cost_rule_version": self.cost_rule_version,
            "calculation_detail": self.calculation_detail,
            "data_source": self.data_source,
            "transport_stage": self.transport_stage,
            "edge_role": self.edge_role,
            "time_scope": self.time_scope,
            "cost_components": self.cost_components,
        }


def build_transport_edge(
    rate: FreightRate,
    cost_result: CostCalculationResult,
    time_result: ShippingTimeResult,
    *,
    commodity: str,
    distance_km: object | None = None,
    distance_source: str | None = None,
    data_source: str | None = None,
    transport_stage: TransportStage | None = None,
    edge_role: TransportEdgeRole | None = None,
    cost_components: tuple[CostComponent, ...] = (),
    manual_review_outcomes: tuple[ManualReviewOutcome, ...] = (),
) -> TransportEdge:
    """Combine one rate, cost result, and time result into a traceable edge."""
    normalized_commodity = _required_text(commodity, "货物品种")
    normalized_distance = _optional_positive_decimal(distance_km, "距离")
    normalized_distance_source = _optional_text(distance_source)
    source = _optional_text(data_source) or _rate_data_source(rate)

    review_reasons: list[str] = []
    not_applicable_reasons: list[str] = []

    for outcome in manual_review_outcomes:
        review_reasons.append(f"[{outcome.reason_code}] {outcome.details}（{outcome.source_ref}）")

    if rate.from_node_id is None:
        review_reasons.append("缺少起点节点 ID。")
    if rate.to_node_id is None:
        review_reasons.append("缺少终点节点 ID。")

    if cost_result.status == "valid":
        cost_yuan = cost_result.total_cost_yuan
    elif cost_result.status == "not_applicable":
        cost_yuan = None
        not_applicable_reasons.append(cost_result.message)
    else:
        cost_yuan = None
        review_reasons.append(cost_result.message)

    if time_result.status == "resolved":
        time_hours = time_result.duration_hours
    else:
        time_hours = None
        review_reasons.append(time_result.message)

    if not rate.supports_commodity(normalized_commodity):
        not_applicable_reasons.append(f"货物品种 {normalized_commodity} 不在运价适用范围内。")
    if cost_result.transport_mode != rate.transport_mode:
        review_reasons.append("计费结果运输方式与运价记录不一致。")
    if cost_result.rate_packaging != rate.package_type:
        review_reasons.append("计费结果包装方式与运价记录不一致。")
    if time_result.transport_mode and time_result.transport_mode != rate.transport_mode:
        review_reasons.append("运输时间方式与运价记录不一致。")
    if cost_result.price_unit != rate.raw_price_unit:
        review_reasons.append("计费结果价格单位与运价记录不一致。")
    if cost_result.price_source != rate.price_source:
        review_reasons.append("计费结果价格来源与运价记录不一致。")
    if normalized_distance is not None and normalized_distance_source is None:
        review_reasons.append("已提供距离数值但缺少距离来源。")
    if normalized_distance is None and normalized_distance_source is not None:
        review_reasons.append("已提供距离来源但缺少距离数值。")

    edge_distance = (
        normalized_distance
        if normalized_distance is not None and normalized_distance_source is not None
        else None
    )
    edge_distance_source = (
        normalized_distance_source
        if normalized_distance is not None and normalized_distance_source is not None
        else None
    )

    if review_reasons:
        status: TransportEdgeStatus = "manual_review"
        unavailable_reason = _join_unique((*review_reasons, *not_applicable_reasons))
    elif not_applicable_reasons:
        status = "not_applicable"
        unavailable_reason = _join_unique(not_applicable_reasons)
    else:
        status = "available"
        unavailable_reason = None

    edge_id = make_transport_edge_id(
        from_node_id=rate.from_node_id,
        to_node_id=rate.to_node_id,
        transport_mode=rate.transport_mode,
        package_type=rate.package_type,
        commodity=normalized_commodity,
        cost_yuan=cost_yuan,
        time_hours=time_hours,
        price_source=cost_result.price_source,
        time_source=time_result.source,
        cost_rule_id=cost_result.rule_id,
        cost_rule_version=cost_result.rule_version,
        distance_km=normalized_distance,
        distance_source=normalized_distance_source,
        data_source=source,
        transport_stage=transport_stage,
        edge_role=edge_role,
        time_scope=time_result.time_scope,
        cost_components=tuple(
            (
                item.component_type,
                item.amount_yuan,
                item.source_type,
                item.source,
                item.rule_id,
                item.rule_version,
                item.calculation_detail,
            )
            for item in cost_components
        ),
        manual_review_outcomes=tuple(
            (
                item.reason_code,
                item.source_ref,
                item.details,
                item.owner_unit,
            )
            for item in manual_review_outcomes
        ),
    )
    return TransportEdge(
        edge_id=edge_id,
        status=status,
        from_node_id=rate.from_node_id,
        to_node_id=rate.to_node_id,
        transport_mode=rate.transport_mode,
        package_type=rate.package_type,
        commodity=normalized_commodity,
        cost_yuan=cost_yuan,
        time_hours=time_hours,
        raw_price=rate.raw_price,
        raw_price_unit=rate.raw_price_unit,
        price_source=cost_result.price_source,
        maintained_at=rate.maintained_at,
        distance_km=edge_distance,
        distance_source=edge_distance_source,
        time_source=time_result.source,
        cost_rule_id=cost_result.rule_id,
        cost_rule_version=cost_result.rule_version,
        calculation_detail=cost_result.calculation_detail,
        data_source=source,
        unavailable_reason=unavailable_reason,
        transport_stage=transport_stage,
        edge_role=edge_role,
        time_scope=time_result.time_scope,
        cost_components=cost_components,
        manual_review_outcomes=manual_review_outcomes,
    )


def make_transport_edge_id(**values: object) -> str:
    normalized_parts: list[str] = []
    for key, value in sorted(values.items()):
        if isinstance(value, Decimal):
            text = format(value.normalize(), "f")
        elif isinstance(value, date):
            text = value.isoformat()
        else:
            text = str(value).strip() if value is not None else ""
        normalized_parts.append(f"{key}={text}")
    digest = hashlib.sha256("|".join(normalized_parts).encode("utf-8")).hexdigest()[:16]
    return f"edge_{digest}"


def _rate_data_source(rate: FreightRate) -> str:
    if rate.source_file and rate.source_row_number is not None:
        return f"{rate.source_file}#row={rate.source_row_number}"
    if rate.source_file:
        return rate.source_file
    return rate.price_source


def _join_unique(messages: list[str] | tuple[str, ...]) -> str:
    unique: list[str] = []
    for message in messages:
        text = str(message).strip()
        if text and text not in unique:
            unique.append(text)
    return "；".join(unique)


def _optional_positive_decimal(value: object | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        number = _finite_decimal(value, field_name)
    except TransportEdgeError:
        raise TransportEdgeError(f"{field_name}必须是大于 0 的有限数值。") from None
    if number <= 0:
        raise TransportEdgeError(f"{field_name}必须是大于 0 的有限数值。")
    return number


def _optional_finite_decimal(value: object | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _finite_decimal(value, field_name)


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise TransportEdgeError(f"{field_name}必须是有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise TransportEdgeError(f"{field_name}必须是有限数值。") from None
    if not number.is_finite():
        raise TransportEdgeError(f"{field_name}必须是有限数值。")
    return number


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise TransportEdgeError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
