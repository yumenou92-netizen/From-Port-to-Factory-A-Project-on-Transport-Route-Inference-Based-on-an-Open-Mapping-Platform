from src.domain.freight_rate import create_freight_rate
from datetime import date

from src.domain.latest_rate_selector import (
    DEFAULT_MAINTENANCE_DATE,
    effective_maintained_at,
    select_latest_freight_rates,
)


def make_rate(**overrides):
    values = {
        "origin_name": "测试南港",
        "destination_name": "测试客户工厂",
        "transport_mode": "汽运",
        "package_type": "散粮",
        "commodity_scope": "玉米、小麦",
        "raw_price": 20,
        "raw_price_unit": "元/吨",
        "price_type": "unit_price",
        "price_source": "测试台账",
        "maintained_at": "2026-04-15",
        "source_file": "测试运价表.json",
        "source_row_number": 1,
    }
    values.update(overrides)
    return create_freight_rate(**values)


def test_selects_latest_rate_and_counts_superseded_history():
    old_rate = make_rate(raw_price=20, maintained_at="2026-04-15", source_row_number=1)
    latest_rate = make_rate(raw_price=22, maintained_at="2026-05-01", source_row_number=2)

    result = select_latest_freight_rates([old_rate, latest_rate])

    assert result.selected_rates == (latest_rate,)
    assert result.superseded_rate_count == 1
    assert result.review_issues == ()


def test_missing_date_uses_1970_baseline_and_can_be_selected():
    undated_rate = make_rate(maintained_at=None)

    result = select_latest_freight_rates([undated_rate])

    assert DEFAULT_MAINTENANCE_DATE == date(1970, 1, 1)
    assert effective_maintained_at(undated_rate) == DEFAULT_MAINTENANCE_DATE
    assert result.selected_rates == (undated_rate,)
    assert result.defaulted_date_count == 1
    assert result.review_issues == ()


def test_dated_rate_supersedes_undated_baseline_rate():
    dated_rate = make_rate(maintained_at="2026-05-01", source_row_number=1)
    undated_rate = make_rate(maintained_at=None, raw_price=99, source_row_number=2)

    result = select_latest_freight_rates([undated_rate, dated_rate])

    assert result.selected_rates == (dated_rate,)
    assert result.superseded_rate_count == 1
    assert result.defaulted_date_count == 1
    assert result.review_issues == ()


def test_conflicting_undated_rates_share_1970_baseline_and_require_review():
    first = make_rate(maintained_at=None, raw_price=20, source_row_number=1)
    second = make_rate(maintained_at=None, raw_price=21, source_row_number=2)

    result = select_latest_freight_rates([first, second])

    assert result.selected_rates == ()
    assert result.review_issues[0].code == "same_day_conflict"
    assert "1970-01-01" in result.review_issues[0].message
    assert "系统基准日期" in result.review_issues[0].message


def test_same_day_conflicting_rates_require_review():
    first = make_rate(raw_price=20, source_row_number=1)
    second = make_rate(raw_price=21, source_row_number=2)

    result = select_latest_freight_rates([first, second])

    assert result.selected_rates == ()
    assert result.review_issues[0].code == "same_day_conflict"
    assert result.review_issues[0].rates == (first, second)


def test_exact_same_day_duplicates_select_one_traceable_record():
    first = make_rate(source_row_number=1)
    duplicate = make_rate(source_row_number=2)

    result = select_latest_freight_rates([duplicate, first])

    assert result.selected_rates == (first,)
    assert result.duplicate_rate_count == 1
    assert result.review_issues == ()


def test_different_business_route_keys_are_selected_independently():
    bulk_rate = make_rate()
    container_rate = make_rate(
        package_type="集装箱",
        raw_price=500,
        raw_price_unit="元/箱",
        source_row_number=2,
    )

    result = select_latest_freight_rates([bulk_rate, container_rate])

    assert result.selected_rates == (bulk_rate, container_rate)
    assert result.review_issues == ()
