from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Mapping

try:
    from .route_request import evaluate_freight_charge, validate_request_billing
    from .unit_conversion import UnitConversionError, calculate_total_cost
except ImportError:  # Support direct script-style imports used by the current demo.
    from src.domain.route_request import evaluate_freight_charge, validate_request_billing
    from src.domain.unit_conversion import UnitConversionError, calculate_total_cost

if TYPE_CHECKING:
    try:
        from .freight_rate import FreightRate
        from .route_request import RouteRequest
    except ImportError:
        from src.domain.freight_rate import FreightRate
        from src.domain.route_request import RouteRequest


PriceMode = Literal["index", "manual"]
ManualPriceType = Literal["unit_price", "total_price"]
CostStage = Literal["trunk_shipping", "last_mile_truck", "railway"]
CostCalculationStatus = Literal["valid", "not_applicable", "manual_review"]


class CostRuleError(ValueError):
    """Raised when a cost rule cannot calculate a defensible cost."""


class DisabledCostRuleError(CostRuleError):
    """Raised when code tries to execute a registered but disabled rule."""


@dataclass(frozen=True)
class CostRuleConfig:
    rule_id: str
    rule_version: str
    rule_name: str
    rule_type: str
    enabled: bool
    parameters: Mapping[str, Any] = field(default_factory=dict)
    disabled_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("rule_id", "rule_version", "rule_name", "rule_type"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CostRuleError(f"{field_name} 必须是非空文本。")
            object.__setattr__(self, field_name, value.strip())
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        if not self.enabled and not self.disabled_reason:
            raise CostRuleError("禁用规则必须说明 disabled_reason。")


@dataclass(frozen=True)
class CostCalculationResult:
    status: CostCalculationStatus
    total_cost_yuan: Decimal | None
    rule_id: str
    rule_version: str
    calculation_detail: str
    price_source: str
    transport_mode: str
    rate_packaging: str
    price_unit: str
    message: str
    total_cost: Decimal | None = field(init=False)

    def __post_init__(self) -> None:
        if self.status not in {"valid", "not_applicable", "manual_review"}:
            raise CostRuleError(f"不支持的计费结果状态: {self.status}")
        for field_name in ("rule_id", "rule_version", "calculation_detail", "message"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CostRuleError(f"计费结果字段 {field_name} 必须是非空文本。")
        if self.status == "valid":
            if (
                self.total_cost_yuan is None
                or not self.total_cost_yuan.is_finite()
                or self.total_cost_yuan <= 0
            ):
                raise CostRuleError("有效计费结果必须包含大于 0 的人民币总费用。")
        elif self.total_cost_yuan is not None:
            raise CostRuleError("非有效计费结果不得包含总费用。")
        object.__setattr__(self, "total_cost", self.total_cost_yuan)

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


FREIGHT_RATE_UNIT_PRICE_RULE = CostRuleConfig(
    rule_id="freight_rate_unit_price",
    rule_version="1.0",
    rule_name="既定运价单价计费",
    rule_type="unit_price",
    enabled=True,
)

FREIGHT_RATE_TOTAL_PRICE_RULE = CostRuleConfig(
    rule_id="freight_rate_total_price",
    rule_version="1.0",
    rule_name="人工总价计费",
    rule_type="total_price",
    enabled=True,
)

KNOWN_TRUCK_MAINTAINED_RATE_RULE = CostRuleConfig(
    rule_id="known_truck_maintained_rate",
    rule_version="1.0",
    rule_name="熟悉汽运路线既定运价",
    rule_type="maintained_truck_rate",
    enabled=True,
    parameters={
        "route_policy": "freight_rate_first",
        "required_transport_mode": "汽运",
        "next_step": "latest_rate_selection",
    },
)

BULK_SHIPPING_INDEX_RULE = CostRuleConfig(
    rule_id="bulk_shipping_index",
    rule_version="1.0",
    rule_name="散船指数测算",
    rule_type="index_formula",
    enabled=True,
    parameters={
        "index_multiplier": Decimal("1.12"),
        "harbor_sailing_fee_yuan_per_ton": Decimal("2"),
        "profit_fee_yuan_per_ton": Decimal("5"),
        "price_unit": "元/吨",
    },
)

BULK_SHIPPING_MANUAL_UNIT_RULE = CostRuleConfig(
    rule_id="bulk_shipping_manual_unit_price",
    rule_version="1.0",
    rule_name="散船人工单价报价",
    rule_type="manual_unit_price",
    enabled=True,
)

BULK_SHIPPING_MANUAL_TOTAL_RULE = CostRuleConfig(
    rule_id="bulk_shipping_manual_total_price",
    rule_version="1.0",
    rule_name="散船人工总价报价",
    rule_type="manual_total_price",
    enabled=True,
)

BULK_SHIPPING_MANUAL_VALIDATION_RULE = CostRuleConfig(
    rule_id="bulk_shipping_manual_quote_validation",
    rule_version="1.0",
    rule_name="散船人工报价口径校验",
    rule_type="manual_quote_validation",
    enabled=True,
)

UNKNOWN_TRUCK_BULK_RULE = CostRuleConfig(
    rule_id="unknown_truck_bulk_distance_tier",
    rule_version="draft-2",
    rule_name="陌生汽运路线散粮阶梯计费",
    rule_type="distance_tier",
    enabled=False,
    parameters={
        "requires_distance_provider": True,
        "distance_unit": "km",
        "result_unit": "元/吨",
        "total_cost_formula": "unit_price_yuan_per_ton * quantity_tons",
        "segments": (
            {"max_km": Decimal("20"), "formula": "15"},
            {"max_km": Decimal("30"), "formula": "20"},
            {"max_km": Decimal("100"), "formula": "20 + (x - 30) * 0.7"},
            {"max_km": Decimal("150"), "formula": "69 + (x - 100) * 0.6"},
            {"max_km": Decimal("250"), "formula": "99 + (x - 150) * 0.5"},
            {"max_km": None, "formula": "149 + (x - 250) * 0.3"},
        ),
    },
    disabled_reason=(
        "等待腾讯地图 DistanceProvider、最新运价选择器、业务验收和边界测试完成后启用；"
        "当前不得参与自动推荐。"
    ),
)

UNKNOWN_TRUCK_CONTAINER_RULE = CostRuleConfig(
    rule_id="unknown_truck_container_distance",
    rule_version="draft-1",
    rule_name="陌生汽运路线集装箱计费",
    rule_type="distance_formula",
    enabled=False,
    parameters={
        "requires_distance_provider": True,
        "distance_unit": "km",
        "price_unit": "元/箱",
        "within_20_km_yuan_per_box": Decimal("500"),
        "over_20_formula_text": "500-(distance_km-20)*30*0.55",
        "over_20_formula_status": "requires_business_reconfirmation",
        "ton_per_box_reference": Decimal("30"),
        "unit_conversion_status": "do_not_auto_convert_box_to_ton",
    },
    disabled_reason=(
        "无既定汽运运价时才可考虑该草案；20 公里以上公式方向和箱吨换算口径"
        "均待业务复核，当前不得参与自动推荐。"
    ),
)


DEFAULT_COST_RULES = (
    FREIGHT_RATE_UNIT_PRICE_RULE,
    FREIGHT_RATE_TOTAL_PRICE_RULE,
    KNOWN_TRUCK_MAINTAINED_RATE_RULE,
    BULK_SHIPPING_INDEX_RULE,
    BULK_SHIPPING_MANUAL_UNIT_RULE,
    BULK_SHIPPING_MANUAL_TOTAL_RULE,
    BULK_SHIPPING_MANUAL_VALIDATION_RULE,
    UNKNOWN_TRUCK_BULK_RULE,
    UNKNOWN_TRUCK_CONTAINER_RULE,
)


class CostRuleEngine:
    """Single calculation entry point for configured freight cost rules."""

    def __init__(self, rules: tuple[CostRuleConfig, ...] = DEFAULT_COST_RULES) -> None:
        self._rules = {rule.rule_id: rule for rule in rules}
        if len(self._rules) != len(rules):
            raise CostRuleError("计费规则编号不能重复。")

    @property
    def rules(self) -> tuple[CostRuleConfig, ...]:
        return tuple(self._rules.values())

    def get_rule(self, rule_id: str) -> CostRuleConfig:
        try:
            return self._rules[rule_id]
        except KeyError:
            raise CostRuleError(f"找不到计费规则: {rule_id}") from None

    def require_enabled(self, rule_id: str) -> CostRuleConfig:
        rule = self.get_rule(rule_id)
        if not rule.enabled:
            raise DisabledCostRuleError(
                f"计费规则 {rule.rule_id} 当前未启用：{rule.disabled_reason}"
            )
        return rule

    def evaluate_freight_rate(
        self,
        rate: FreightRate,
        request: RouteRequest,
    ) -> CostCalculationResult:
        rule = self.require_enabled(
            FREIGHT_RATE_UNIT_PRICE_RULE.rule_id
            if rate.price_type == "unit_price"
            else FREIGHT_RATE_TOTAL_PRICE_RULE.rule_id
        )

        if not rate.supports_commodity(request.commodity):
            return self._result(
                rule,
                status="not_applicable",
                rate=rate,
                total_cost_yuan=None,
                calculation_detail="未计算：订单品种不在运价适用范围内。",
                message=f"该运价不适用于订单品种 {request.commodity}。",
            )

        if rate.price_type == "unit_price":
            legacy_result = evaluate_freight_charge(
                request,
                transport_mode=rate.transport_mode,
                rate_packaging=rate.package_type,
                raw_price=rate.raw_price,
                price_unit=rate.raw_price_unit,
            )
            detail = (
                f"{request.quantity}{request.quantity_unit} × "
                f"{rate.raw_price}{rate.raw_price_unit} = {legacy_result.total_cost}元"
                if legacy_result.total_cost is not None
                else f"未计算：{legacy_result.message}"
            )
            return self._result(
                rule,
                status=legacy_result.status,
                rate=rate,
                total_cost_yuan=legacy_result.total_cost,
                calculation_detail=detail,
                message=legacy_result.message,
            )

        return self._evaluate_freight_rate_total_price(rule, rate, request)

    def calculate_last_mile_truck(
        self,
        request: RouteRequest,
        *,
        known_rate: FreightRate | None = None,
        price_source: str = "最后一公里汽运规则",
    ) -> CostCalculationResult:
        """Evaluate last-mile truck cost under the current business boundary.

        Known truck routes use maintained freight rates. Unknown truck routes
        are recorded as draft rules and must not auto-calculate until a distance
        provider and business-confirmed formulas are available.
        """
        if known_rate is not None:
            rule = self.require_enabled(KNOWN_TRUCK_MAINTAINED_RATE_RULE.rule_id)
            if not is_truck_transport_mode(known_rate.transport_mode):
                message = f"该运价运输方式为 {known_rate.transport_mode}，不是汽运既定路线。"
                return self._result(
                    rule,
                    "not_applicable",
                    known_rate,
                    None,
                    f"未计算：{message}",
                    message,
                )

            freight_result = self.evaluate_freight_rate(known_rate, request)
            detail = (
                f"熟悉汽运路线使用维护运价；"
                f"原计费规则={freight_result.rule_id}/{freight_result.rule_version}；"
                f"{freight_result.calculation_detail}"
            )
            message = (
                "已按熟悉汽运路线维护运价计算当前订单运输段总费用。"
                if freight_result.status == "valid"
                else freight_result.message
            )
            return CostCalculationResult(
                status=freight_result.status,
                total_cost_yuan=freight_result.total_cost_yuan,
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                calculation_detail=detail,
                price_source=known_rate.price_source,
                transport_mode=known_rate.transport_mode,
                rate_packaging=known_rate.package_type,
                price_unit=known_rate.raw_price_unit,
                message=message,
            )

        return self._unknown_truck_review(request, price_source)

    def calculate_bulk_shipping(
        self,
        request: RouteRequest,
        *,
        price_mode: PriceMode,
        coal_index: int | float | str | Decimal | None = None,
        manual_quote_price: int | float | str | Decimal | None = None,
        manual_price_type: ManualPriceType | None = None,
        manual_price_unit: str | None = None,
        price_source: str = "散船计费规则",
    ) -> CostCalculationResult:
        if price_mode == "index":
            rule = self.require_enabled(BULK_SHIPPING_INDEX_RULE.rule_id)
            validation = validate_request_billing(request)
            if validation.requires_manual_review:
                return self._standalone_review(
                    rule,
                    request,
                    price_source,
                    "；".join(validation.issues),
                )
            try:
                index_multiplier = rule.parameters["index_multiplier"]
                harbor_sailing_fee = rule.parameters["harbor_sailing_fee_yuan_per_ton"]
                profit_fee = rule.parameters["profit_fee_yuan_per_ton"]
                index_price_unit = str(rule.parameters["price_unit"])
                unit_price = calculate_bulk_shipping_unit_price(
                    coal_index=coal_index,
                    index_multiplier=index_multiplier,
                    harbor_sailing_fee=harbor_sailing_fee,
                    profit_fee=profit_fee,
                )
                total_cost = calculate_total_cost(
                    unit_price,
                    index_price_unit,
                    request.quantity,
                    request.quantity_unit,
                )
            except KeyError as exc:
                return self._standalone_review(
                    rule,
                    request,
                    price_source,
                    f"计费规则缺少参数: {exc.args[0]}",
                )
            except (CostRuleError, UnitConversionError, TypeError) as exc:
                return self._standalone_review(rule, request, price_source, str(exc))
            return CostCalculationResult(
                status="valid",
                total_cost_yuan=total_cost,
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                calculation_detail=(
                    f"单位运费={coal_index}×{index_multiplier}+{harbor_sailing_fee}+"
                    f"{profit_fee}={unit_price}{index_price_unit}；"
                    f"总费用={unit_price}{index_price_unit}×"
                    f"{request.quantity}{request.quantity_unit}={total_cost}元"
                ),
                price_source=price_source,
                transport_mode="散船",
                rate_packaging=request.package_type,
                price_unit=index_price_unit,
                message="已按散船指数规则计算当前订单运输段总费用。",
            )

        if price_mode != "manual":
            raise CostRuleError(f"未知散船计价模式: {price_mode}")

        if manual_price_type not in {"unit_price", "total_price"}:
            rule = self.require_enabled(BULK_SHIPPING_MANUAL_VALIDATION_RULE.rule_id)
            return self._standalone_review(
                rule,
                request,
                price_source,
                "人工报价必须显式区分 manual_price_type=unit_price 或 total_price",
            )

        rule = self.require_enabled(
            BULK_SHIPPING_MANUAL_TOTAL_RULE.rule_id
            if manual_price_type == "total_price"
            else BULK_SHIPPING_MANUAL_UNIT_RULE.rule_id
        )
        validation = validate_request_billing(request)
        if validation.requires_manual_review:
            return self._standalone_review(
                rule,
                request,
                price_source,
                "；".join(validation.issues),
            )
        try:
            total_cost = calculate_manual_shipping_cost(
                manual_quote_price=manual_quote_price,
                manual_price_type=manual_price_type,
                manual_price_unit=manual_price_unit,
                quantity=request.quantity,
                quantity_unit=request.quantity_unit,
            )
        except (CostRuleError, UnitConversionError) as exc:
            return self._standalone_review(rule, request, price_source, str(exc))

        if manual_price_type == "total_price":
            detail = f"人工总价 {total_cost}元，直接作为当前订单运输段总费用。"
            price_unit = "元"
        else:
            detail = (
                f"{request.quantity}{request.quantity_unit} × "
                f"{manual_quote_price}{manual_price_unit} = {total_cost}元"
            )
            price_unit = manual_price_unit or ""
        return CostCalculationResult(
            status="valid",
            total_cost_yuan=total_cost,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            calculation_detail=detail,
            price_source=price_source,
            transport_mode="散船",
            rate_packaging=request.package_type,
            price_unit=price_unit,
            message="已按散船人工报价规则计算当前订单运输段总费用。",
        )

    def _evaluate_freight_rate_total_price(
        self,
        rule: CostRuleConfig,
        rate: FreightRate,
        request: RouteRequest,
    ) -> CostCalculationResult:
        validation = validate_request_billing(request)
        if validation.requires_manual_review:
            message = "；".join(validation.issues)
            return self._result(rule, "manual_review", rate, None, f"未计算：{message}", message)
        if rate.package_type != request.package_type:
            message = f"订单包装方式为 {request.package_type}，该运价适用于 {rate.package_type}。"
            return self._result(rule, "not_applicable", rate, None, f"未计算：{message}", message)
        if _normalize_total_price_unit(rate.raw_price_unit) != "元":
            message = f"total_price 必须使用总金额单位元，当前单位为 {rate.raw_price_unit}。"
            return self._result(rule, "manual_review", rate, None, f"未计算：{message}", message)
        if rate.raw_price <= 0:
            message = "人工总价必须大于 0，请人工确认该报价。"
            return self._result(rule, "manual_review", rate, None, f"未计算：{message}", message)
        return self._result(
            rule,
            "valid",
            rate,
            rate.raw_price,
            f"人工总价 {rate.raw_price}元，直接作为当前订单运输段总费用。",
            "该记录为 total_price，已直接作为当前订单运输段总费用。",
        )

    @staticmethod
    def _result(
        rule: CostRuleConfig,
        status: CostCalculationStatus,
        rate: FreightRate,
        total_cost_yuan: Decimal | None,
        calculation_detail: str,
        message: str,
    ) -> CostCalculationResult:
        return CostCalculationResult(
            status=status,
            total_cost_yuan=total_cost_yuan,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            calculation_detail=calculation_detail,
            price_source=rate.price_source,
            transport_mode=rate.transport_mode,
            rate_packaging=rate.package_type,
            price_unit=rate.raw_price_unit,
            message=message,
        )

    @staticmethod
    def _standalone_review(
        rule: CostRuleConfig,
        request: RouteRequest,
        price_source: str,
        message: str,
    ) -> CostCalculationResult:
        return CostCalculationResult(
            status="manual_review",
            total_cost_yuan=None,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            calculation_detail=f"未计算：{message}",
            price_source=price_source,
            transport_mode="散船",
            rate_packaging=request.package_type,
            price_unit="",
            message=message,
        )

    def _unknown_truck_review(
        self,
        request: RouteRequest,
        price_source: str,
    ) -> CostCalculationResult:
        if request.package_type == "散粮":
            rule = self.get_rule(UNKNOWN_TRUCK_BULK_RULE.rule_id)
            message = (
                "未找到既定汽运运价；陌生汽运散粮规则仅作为草案登记，"
                "需要 DistanceProvider 提供公路距离并完成业务验收后才能计算。"
            )
            price_unit = "元/吨"
        elif request.package_type == "集装箱":
            rule = self.get_rule(UNKNOWN_TRUCK_CONTAINER_RULE.rule_id)
            message = (
                "未找到既定汽运运价；陌生汽运集装箱规则仅作为草案登记，"
                "20 公里以上公式方向和箱吨换算口径待业务复核，当前不能计算。"
            )
            price_unit = "元/箱"
        else:
            rule = self.get_rule(UNKNOWN_TRUCK_BULK_RULE.rule_id)
            message = f"包装方式 {request.package_type} 暂无陌生汽运规则，请人工确认。"
            price_unit = ""

        return CostCalculationResult(
            status="manual_review",
            total_cost_yuan=None,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            calculation_detail=f"未计算：{message}",
            price_source=price_source,
            transport_mode="汽运",
            rate_packaging=request.package_type,
            price_unit=price_unit,
            message=message,
        )


DEFAULT_COST_RULE_ENGINE = CostRuleEngine()


def calculate_bulk_shipping_cost(
    price_mode: str,
    coal_index: float | None = None,
    manual_quote_price: float | None = None,
    index_multiplier: float = 1.12,
    harbor_sailing_fee: float = 2,
    profit_fee: float = 5,
) -> float:
    """Legacy unit-price helper kept for the current demo and existing tests.

    For new route construction, use calculate_bulk_shipping_total_cost so the
    result is the current order segment total cost in yuan.
    """
    if price_mode == "index":
        if coal_index is None:
            raise ValueError("指数测算模式必须提供 coal_index")
        return round(coal_index * index_multiplier + harbor_sailing_fee + profit_fee, 2)

    if price_mode == "manual":
        if manual_quote_price is None:
            raise ValueError("线下询价模式必须提供 manual_quote_price")
        return manual_quote_price

    raise ValueError(f"未知散船计价模式: {price_mode}")


def calculate_bulk_shipping_unit_price(
    coal_index: int | float | str | Decimal,
    index_multiplier: int | float | str | Decimal = Decimal("1.12"),
    harbor_sailing_fee: int | float | str | Decimal = Decimal("2"),
    profit_fee: int | float | str | Decimal = Decimal("5"),
) -> Decimal:
    """Calculate index-based bulk shipping unit price.

    Business rule:
    unit price = coal index * 1.12 + 2 yuan harbor sailing fee + 5 yuan profit.
    """
    coal_index_value = _to_decimal(coal_index, "煤炭指数")
    multiplier_value = _to_decimal(index_multiplier, "指数系数")
    harbor_fee_value = _to_decimal(harbor_sailing_fee, "港驶费")
    profit_fee_value = _to_decimal(profit_fee, "利润")

    return coal_index_value * multiplier_value + harbor_fee_value + profit_fee_value


def calculate_bulk_shipping_total_cost(
    price_mode: PriceMode,
    quantity: int | float | str | Decimal,
    quantity_unit: str,
    coal_index: int | float | str | Decimal | None = None,
    manual_quote_price: int | float | str | Decimal | None = None,
    manual_price_type: ManualPriceType | None = None,
    manual_price_unit: str | None = None,
    index_price_unit: str = "元/吨",
    index_multiplier: int | float | str | Decimal = Decimal("1.12"),
    harbor_sailing_fee: int | float | str | Decimal = Decimal("2"),
    profit_fee: int | float | str | Decimal = Decimal("5"),
) -> Decimal:
    """Calculate first-stage north-port to south-port bulk shipping total cost.

    Returns the total cost for the current order segment, in yuan.
    """
    if price_mode == "index":
        if coal_index is None:
            raise CostRuleError("指数测算模式必须提供 coal_index")
        unit_price = calculate_bulk_shipping_unit_price(
            coal_index=coal_index,
            index_multiplier=index_multiplier,
            harbor_sailing_fee=harbor_sailing_fee,
            profit_fee=profit_fee,
        )
        return calculate_total_cost(unit_price, index_price_unit, quantity, quantity_unit)

    if price_mode == "manual":
        return calculate_manual_shipping_cost(
            manual_quote_price=manual_quote_price,
            manual_price_type=manual_price_type,
            manual_price_unit=manual_price_unit,
            quantity=quantity,
            quantity_unit=quantity_unit,
        )

    raise CostRuleError(f"未知散船计价模式: {price_mode}")


def calculate_manual_shipping_cost(
    manual_quote_price: int | float | str | Decimal | None,
    manual_price_type: ManualPriceType | None,
    manual_price_unit: str | None,
    quantity: int | float | str | Decimal,
    quantity_unit: str,
) -> Decimal:
    """Calculate manually quoted shipping cost.

    Manual quotes must explicitly state whether the quote is a unit price or total price.
    """
    if manual_quote_price is None:
        raise CostRuleError("人工报价模式必须提供 manual_quote_price")
    if manual_price_type not in ("unit_price", "total_price"):
        raise CostRuleError("人工报价必须显式区分 manual_price_type=unit_price 或 total_price")

    if manual_price_type == "unit_price":
        if not manual_price_unit:
            raise CostRuleError("人工单价报价必须提供 manual_price_unit")
        return calculate_total_cost(manual_quote_price, manual_price_unit, quantity, quantity_unit)

    total_cost = _to_decimal(manual_quote_price, "人工总价")
    if total_cost <= 0:
        raise CostRuleError(f"人工总价必须大于 0，当前值：{manual_quote_price}")
    return total_cost


def calculate_edge_cost(stage: CostStage, **kwargs) -> Decimal:
    """Unified cost calculation entry point for future TransportEdge construction."""
    if stage == "trunk_shipping":
        return calculate_bulk_shipping_total_cost(**kwargs)

    if stage == "last_mile_truck":
        raise CostRuleError("最后一公里汽运规则已记录，但尚未接入正式费用计算。")

    if stage == "railway":
        raise CostRuleError("铁路费用规则当前仍为旧版函数，尚未接入统一边费用计算。")

    raise CostRuleError(f"未知费用计算阶段: {stage}")


def calculate_railway_cost(
    origin_operation_fee: float,
    railway_freight_fee: float,
    destination_unloading_fee: float,
    short_truck_fee: float,
    is_open_top_container: bool = False,
    tarpaulin_return_fee: float = 0,
) -> float:
    total = origin_operation_fee + railway_freight_fee + destination_unloading_fee + short_truck_fee
    if is_open_top_container:
        total += tarpaulin_return_fee
    return total


def calculate_truck_cost(distance: float, rate_per_km: float, minimum_fee: float = 0) -> float:
    return max(distance * rate_per_km, minimum_fee)


def is_truck_transport_mode(value: str) -> bool:
    normalized = str(value).strip().replace(" ", "")
    return normalized in {"汽运", "汽车运输", "公路运输"}


def _to_decimal(value: int | float | str | Decimal, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise CostRuleError(f"{field_name}必须是数值，当前值：{value}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise CostRuleError(f"{field_name}必须是数值，当前值：{value}") from None
    if not number.is_finite():
        raise CostRuleError(f"{field_name}必须是有限数值，当前值：{value}")
    return number


def _normalize_total_price_unit(value: str) -> str:
    return str(value).strip().replace(" ", "").replace("／", "/")
