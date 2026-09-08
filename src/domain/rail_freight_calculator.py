"""Auditable reproduction of the supplied railway freight workbook.

This calculator is intentionally separate from railway route construction.
It reproduces the current workbook's arithmetic for quotation review only;
the result does not constitute a real-data TransportEdge or a routing price.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class RailFreightCalculatorError(ValueError):
    """Raised when a calculator input is absent or unsafe to evaluate."""


@dataclass(frozen=True)
class RailFreightCalculatorInput:
    """Inputs corresponding to the editable cells in ``计算器.xlsx``.

    ``*_adjusted_base_yuan`` and ``*_adjusted_yuan`` deliberately remain
    separate from full-price values.  In the source workbook those cells are
    manually maintained rather than derived from the full-price column.
    """

    load_tons: Decimal
    total_freight_yuan: Decimal
    discount_ratio: Decimal
    electrified_km: Decimal
    stamp_tax_yuan: Decimal = Decimal("0.5")
    jingjiu_diversion_yuan: Decimal = Decimal("0")
    rail_construction_fund_adjusted_base_yuan: Decimal = Decimal("0")
    # 地方运费为可增删的动态项，每项仅一个折算基数（按下浮率折算）
    local_freight_adjusted_bases: tuple[Decimal, ...] = ()
    origin_handling_adjusted_yuan: Decimal = Decimal("0")
    destination_handling_adjusted_yuan: Decimal = Decimal("0")
    pickup_delivery_adjusted_yuan: Decimal = Decimal("0")
    other_adjusted_yuan: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "load_tons", _positive(self.load_tons, "整车装载吨数"))
        object.__setattr__(self, "total_freight_yuan", _non_negative(self.total_freight_yuan, "运费"))
        discount_ratio = _non_negative(self.discount_ratio, "下浮率")
        if discount_ratio >= Decimal("1"):
            raise RailFreightCalculatorError("下浮率必须小于 1。")
        object.__setattr__(self, "discount_ratio", discount_ratio)
        object.__setattr__(self, "electrified_km", _non_negative(self.electrified_km, "电气化里程"))
        for field_name, label in (
            ("stamp_tax_yuan", "印花税"),
            ("jingjiu_diversion_yuan", "京九分流"),
            ("rail_construction_fund_adjusted_base_yuan", "铁建基金折算基数"),
            ("origin_handling_adjusted_yuan", "发站装卸费"),
            ("destination_handling_adjusted_yuan", "到站装卸费"),
            ("pickup_delivery_adjusted_yuan", "取送车费"),
            ("other_adjusted_yuan", "其他费"),
        ):
            object.__setattr__(self, field_name, _non_negative(getattr(self, field_name), label))
        object.__setattr__(
            self,
            "local_freight_adjusted_bases",
            tuple(
                _non_negative(value, f"地方运费第{index}项折算基数")
                for index, value in enumerate(self.local_freight_adjusted_bases, start=1)
            ),
        )


@dataclass(frozen=True)
class RailFreightCalculatorLine:
    name: str
    full_price_yuan: Decimal | None
    divided_by_0991_yuan: Decimal | None
    divided_by_09911_yuan: Decimal | None
    adjusted_yuan: Decimal | None
    note: str | None = None


@dataclass(frozen=True)
class RailFreightCalculatorResult:
    """Calculation result retaining every meaningful workbook column."""

    lines: tuple[RailFreightCalculatorLine, ...]
    full_price_total_yuan: Decimal
    user_full_price_total_yuan: Decimal
    adjusted_total_yuan: Decimal
    local_freight_adjusted_total_yuan: Decimal
    original_workbook_unit_price_yuan_per_ton: Decimal
    input_load_unit_price_yuan_per_ton: Decimal
    warnings: tuple[str, ...]


def calculate_rail_freight_workbook(
    values: RailFreightCalculatorInput,
) -> RailFreightCalculatorResult:
    """Reproduce the formulas currently present in ``计算器.xlsx``.

    ``地方运费2`` uses the confirmed correction ``1 - 下浮率`` rather than the
    source workbook's erroneous ``1 - 电气化里程``.  The source workbook's
    hard-coded 60-tonne unit-price denominator remains visible for comparison.
    """

    electric_fee = Decimal("0.007") * values.load_tons * values.electrified_km
    base_freight = values.total_freight_yuan - electric_fee
    if base_freight < 0:
        raise RailFreightCalculatorError(
            "电气化费（0.007 × 整车装载吨数 × 电气化里程）大于输入运费，无法按原表计算基础运费。"
        )

    discount_factor = Decimal("1") - values.discount_ratio
    stamp_adjusted = values.stamp_tax_yuan * (discount_factor - Decimal("0.02"))
    jingjiu_09911 = values.jingjiu_diversion_yuan / Decimal("0.9911")
    jingjiu_adjusted = jingjiu_09911 * discount_factor
    base_0991 = base_freight / Decimal("0.991")
    base_09911 = base_0991 / Decimal("0.9911")
    base_adjusted = base_09911 * discount_factor

    lines = (
        RailFreightCalculatorLine(
            "印花税", values.stamp_tax_yuan, values.stamp_tax_yuan,
            values.stamp_tax_yuan, stamp_adjusted, "按下浮率加 2 个百分点折算。",
        ),
        RailFreightCalculatorLine(
            "京九分流", values.jingjiu_diversion_yuan, None,
            jingjiu_09911, jingjiu_adjusted, "按下浮率折算。",
        ),
        RailFreightCalculatorLine(
            "铁建基金", None, None,
            values.rail_construction_fund_adjusted_base_yuan,
            values.rail_construction_fund_adjusted_base_yuan * discount_factor,
            "原表的 0.9911 折算基数为人工维护值。",
        ),
        *(
            RailFreightCalculatorLine(
                f"地方运费{index}", None, None, base,
                base * discount_factor,
                "已按业务确认勘误：折算基数 × (1 - 下浮率)。",
            )
            for index, base in enumerate(values.local_freight_adjusted_bases, start=1)
        ),
        RailFreightCalculatorLine(
            "基础运费", base_freight, base_0991, base_09911,
            base_adjusted, None,
        ),
        RailFreightCalculatorLine(
            "电气化费", electric_fee, None, None, Decimal("0"),
            "原表在下浮列按零处理。",
        ),
        RailFreightCalculatorLine(
            "发站装卸费", None, None, None,
            values.origin_handling_adjusted_yuan, "原表的下浮后金额为人工维护值。",
        ),
        RailFreightCalculatorLine(
            "到站装卸费", None, None, None,
            values.destination_handling_adjusted_yuan, "原表第二条“发站装卸费”按业务含义标为到站装卸费。",
        ),
        RailFreightCalculatorLine(
            "取送车费", None, None, None,
            values.pickup_delivery_adjusted_yuan, "原表的下浮后金额为人工维护值。",
        ),
        RailFreightCalculatorLine(
            "其他费", None, None, None,
            values.other_adjusted_yuan, "原表为空时按未录入处理。",
        ),
    )
    full_price_total = sum(
        (line.full_price_yuan or Decimal("0"))
        for line in lines[1:]
    )
    # 用户口径全价合计：在原表全价合计基础上加入印花税、铁建基金与发站/到站
    # 装卸费（按截图口径：铁建基金直接以 0.9911 折算基数金额计入，不除以
    # 0.9911 折算为全价；装卸费以下浮后人工维护金额计入）。
    # 仍不含取送车费/其他费。
    user_full_price_total = (
        full_price_total
        + values.stamp_tax_yuan
        + values.rail_construction_fund_adjusted_base_yuan
        + values.origin_handling_adjusted_yuan
        + values.destination_handling_adjusted_yuan
    )
    adjusted_total = sum(
        (line.adjusted_yuan or Decimal("0")) for line in lines
    )
    # 地方运费下浮后合计：Σ 折算基数 × (1 - 下浮率)，与上方动态行一致
    local_freight_adjusted_total = (
        sum(values.local_freight_adjusted_bases, Decimal("0")) * discount_factor
    )
    return RailFreightCalculatorResult(
        lines=lines,
        full_price_total_yuan=full_price_total,
        user_full_price_total_yuan=user_full_price_total,
        adjusted_total_yuan=adjusted_total,
        local_freight_adjusted_total_yuan=local_freight_adjusted_total,
        original_workbook_unit_price_yuan_per_ton=adjusted_total / Decimal("60"),
        input_load_unit_price_yuan_per_ton=adjusted_total / values.load_tons,
        warnings=(
            "本页仅复刻“计算器.xlsx”的报价试算，不构成正式铁路运输边或路径规划结果。",
            "地方运费2已按业务确认勘误：折算基数 × (1 - 下浮率)，覆盖原表错误公式。",
            "原表单吨价固定除以 60 吨；本页同时给出按本次输入装载吨数折算的单吨价。",
            "“用户全价合计”按截图口径 = 原表全价合计 + 印花税 + 铁建基金 + 发站/到站装卸费。",
        ),
    )


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise RailFreightCalculatorError(f"{label}必须是数值。")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise RailFreightCalculatorError(f"{label}必须是数值。") from None
    if not result.is_finite():
        raise RailFreightCalculatorError(f"{label}必须是有限数值。")
    return result


def _positive(value: object, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise RailFreightCalculatorError(f"{label}必须大于 0。")
    return result


def _non_negative(value: object, label: str) -> Decimal:
    result = _decimal(value, label)
    if result < 0:
        raise RailFreightCalculatorError(f"{label}不得小于 0。")
    return result
