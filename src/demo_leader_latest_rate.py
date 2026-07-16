from __future__ import annotations

from freight_rate import FreightRate, create_freight_rate
from latest_rate_selector import effective_maintained_at, select_latest_freight_rates


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("最新有效运价选择展示")
    print("=" * 52)

    legacy_rate = make_demo_rate(raw_price=20, maintained_at=None, source_row_number=1)
    baseline = select_latest_freight_rates([legacy_rate])

    print("一、历史运价缺少维护日期")
    print(f"原始维护日期: {legacy_rate.maintained_at or '空值'}")
    print(f"排序使用日期: {effective_maintained_at(legacy_rate)}（系统基准日期）")
    print(f"系统采用记录: {len(baseline.selected_rates)} 条")

    latest_rate = make_demo_rate(
        raw_price=22,
        maintained_at="2026-05-01",
        source_row_number=2,
    )
    selected = select_latest_freight_rates([legacy_rate, latest_rate])

    print("\n二、同一路线录入了带日期的新运价")
    print(f"历史基准记录: 1970-01-01，{legacy_rate.raw_price}{legacy_rate.raw_price_unit}")
    print(
        f"最新记录: {latest_rate.maintained_at}，"
        f"{latest_rate.raw_price}{latest_rate.raw_price_unit}"
    )
    print(f"系统采用最新记录: {selected.selected_rates[0].maintained_at}")
    print(f"不再参与计费的历史记录: {selected.superseded_rate_count} 条")

    conflict = make_demo_rate(raw_price=23, maintained_at="2026-05-01", source_row_number=3)
    conflicted = select_latest_freight_rates([latest_rate, conflict])

    print("\n三、同一天维护了两条不同运价")
    print(f"自动采用记录: {len(conflicted.selected_rates)} 条")
    print(f"人工复核记录: {conflicted.review_rate_count} 条")
    print(f"处理说明: {conflicted.review_issues[0].message}")

    print("\n四、业务结论")
    print("缺少日期的历史运价按 1970-01-01 参与排序，但原始日期仍保持为空。")
    print("后续录入带正常日期的新运价时，系统自动优先采用新记录。")
    print("同一有效日期存在不同价格或来源时，仍转交人工确认。")
    print("原始历史记录仍完整保留，数据审计不受筛选影响。")


def make_demo_rate(
    *,
    raw_price: int,
    maintained_at: str | None,
    source_row_number: int,
) -> FreightRate:
    return create_freight_rate(
        origin_name="测试南港",
        destination_name="测试客户工厂",
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="测试粮种",
        raw_price=raw_price,
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="脱敏测试台账",
        maintained_at=maintained_at,
        source_file="测试运价表.json",
        source_row_number=source_row_number,
    )


if __name__ == "__main__":
    main()
