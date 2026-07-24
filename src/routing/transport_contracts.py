from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal


TransportStage = Literal[
    "bulk_shipping_trunk",
    "barge_last_mile",
    "road_last_mile",
    "rail_trunk",
]
TimeScope = Literal["pure_sailing", "complete_segment", "road_driving"]
CostSourceType = Literal[
    "real_data",
    "confirmed_rule",
    "regional_proxy",
    "demo_placeholder",
]

ALLOWED_TRANSPORT_STAGES = {
    "bulk_shipping_trunk",
    "barge_last_mile",
    "road_last_mile",
    "rail_trunk",
}
ALLOWED_TIME_SCOPES = {"pure_sailing", "complete_segment", "road_driving"}
ALLOWED_TIME_SCOPES_BY_STAGE = {
    "bulk_shipping_trunk": {"pure_sailing"},
    "barge_last_mile": {"pure_sailing", "complete_segment"},
    "road_last_mile": {"road_driving", "complete_segment"},
    "rail_trunk": {"complete_segment"},
}


class TransportContractError(ValueError):
    """Raised when a shared transport contract is internally inconsistent."""


@dataclass(frozen=True)
class ManualReviewOutcome:
    status: Literal["manual_review"]
    reason_code: str
    source_ref: str
    details: str
    owner_unit: str

    def __post_init__(self) -> None:
        if self.status != "manual_review":
            raise TransportContractError("人工复核结果的状态必须是 manual_review。")
        object.__setattr__(self, "reason_code", _required_text(self.reason_code, "人工复核原因码"))
        object.__setattr__(self, "source_ref", _required_text(self.source_ref, "人工复核来源引用"))
        object.__setattr__(self, "details", _required_text(self.details, "人工复核说明"))
        object.__setattr__(self, "owner_unit", _required_text(self.owner_unit, "人工复核责任工作包"))


@dataclass(frozen=True)
class CostComponent:
    component_type: str
    amount_yuan: Decimal
    source_type: CostSourceType
    source: str
    rule_id: str
    rule_version: str
    calculation_detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_type", _required_text(self.component_type, "费用组成类型"))
        object.__setattr__(self, "source", _required_text(self.source, "费用组成来源"))
        object.__setattr__(self, "rule_id", _required_text(self.rule_id, "费用规则编号"))
        object.__setattr__(self, "rule_version", _required_text(self.rule_version, "费用规则版本"))
        object.__setattr__(
            self,
            "calculation_detail",
            _required_text(self.calculation_detail, "费用计算说明"),
        )
        if self.source_type not in {
            "real_data",
            "confirmed_rule",
            "regional_proxy",
            "demo_placeholder",
        }:
            raise TransportContractError(f"不支持的费用来源类型：{self.source_type}")
        object.__setattr__(self, "amount_yuan", _positive_decimal(self.amount_yuan, "费用组成金额"))

    @property
    def is_demo_placeholder(self) -> bool:
        return self.source_type == "demo_placeholder"


@dataclass(frozen=True)
class CostComposition:
    components: tuple[CostComponent, ...]

    def __post_init__(self) -> None:
        components = tuple(self.components)
        if not components:
            raise TransportContractError("费用组成至少包含一项。")
        object.__setattr__(self, "components", components)

    @property
    def total_cost_yuan(self) -> Decimal:
        return sum((item.amount_yuan for item in self.components), Decimal("0"))

    def validate_total(self, expected_total_yuan: object) -> None:
        expected = _positive_decimal(expected_total_yuan, "运输段总费用")
        if self.total_cost_yuan != expected:
            raise TransportContractError(
                f"费用组成合计 {self.total_cost_yuan} 元与运输段总费用 {expected} 元不一致。"
            )


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TransportContractError(f"{field_name}必须是大于 0 的有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise TransportContractError(f"{field_name}必须是大于 0 的有限数值。") from None
    if not number.is_finite() or number <= 0:
        raise TransportContractError(f"{field_name}必须是大于 0 的有限数值。")
    return number


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise TransportContractError(f"{field_name}不能为空。")
    return text


def validate_stage_time_scope(
    transport_stage: TransportStage | None,
    time_scope: TimeScope | None,
) -> None:
    if transport_stage is not None and transport_stage not in ALLOWED_TRANSPORT_STAGES:
        raise TransportContractError(f"不支持的运输阶段：{transport_stage}")
    if time_scope is not None and time_scope not in ALLOWED_TIME_SCOPES:
        raise TransportContractError(f"不支持的运输时间范围：{time_scope}")
    if transport_stage is None or time_scope is None:
        return
    allowed_scopes = ALLOWED_TIME_SCOPES_BY_STAGE[transport_stage]
    if time_scope not in allowed_scopes:
        raise TransportContractError(
            f"运输阶段 {transport_stage} 不允许使用时间范围 {time_scope}。"
        )
