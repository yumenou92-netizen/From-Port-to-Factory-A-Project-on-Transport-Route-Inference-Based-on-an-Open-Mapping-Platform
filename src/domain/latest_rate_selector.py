from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal

try:
    from .freight_rate import FreightRate
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.domain.freight_rate import FreightRate


LATEST_RATE_RULE_ID = "latest_maintained_freight_rate"
LATEST_RATE_RULE_VERSION = "1.2"
DEFAULT_MAINTENANCE_DATE = date(1970, 1, 1)

LatestRateIssueCode = Literal[
    "same_day_conflict",
]


@dataclass(frozen=True)
class LatestRateSelectionIssue:
    code: LatestRateIssueCode
    business_route_key: tuple[str, ...]
    rates: tuple[FreightRate, ...]
    message: str


@dataclass(frozen=True)
class LatestRateSelectionResult:
    selected_rates: tuple[FreightRate, ...]
    review_issues: tuple[LatestRateSelectionIssue, ...]
    superseded_rate_count: int = 0
    duplicate_rate_count: int = 0
    defaulted_date_count: int = 0
    source_preference_resolution_count: int = 0

    @property
    def review_rate_count(self) -> int:
        return sum(len(issue.rates) for issue in self.review_issues)


def select_latest_freight_rates(
    rates: Iterable[FreightRate],
) -> LatestRateSelectionResult:
    """Select one latest unambiguous rate for each business route."""
    grouped: dict[tuple[str, ...], list[FreightRate]] = defaultdict(list)
    for rate in rates:
        grouped[rate.business_route_key].append(rate)

    selected_rates: list[FreightRate] = []
    review_issues: list[LatestRateSelectionIssue] = []
    superseded_rate_count = 0
    duplicate_rate_count = 0
    defaulted_date_count = 0
    source_preference_resolution_count = 0

    for business_route_key, route_rates in grouped.items():
        defaulted_date_count += sum(rate.maintained_at is None for rate in route_rates)
        latest_date = max(effective_maintained_at(rate) for rate in route_rates)
        latest_rates = [
            rate for rate in route_rates if effective_maintained_at(rate) == latest_date
        ]
        superseded_rate_count += len(route_rates) - len(latest_rates)

        candidate_rates, used_transaction_preference = (
            _prefer_transaction_rates_over_inquiry_rates(latest_rates)
        )
        rates_by_id: dict[str, list[FreightRate]] = defaultdict(list)
        for rate in candidate_rates:
            rates_by_id[rate.rate_id].append(rate)
        duplicate_rate_count += sum(len(items) - 1 for items in rates_by_id.values())

        if len(rates_by_id) > 1:
            date_description = (
                f"系统基准日期 {DEFAULT_MAINTENANCE_DATE.isoformat()}"
                if any(rate.maintained_at is None for rate in latest_rates)
                else f"最新维护日期 {latest_date.isoformat()}"
            )
            review_issues.append(
                LatestRateSelectionIssue(
                    code="same_day_conflict",
                    business_route_key=business_route_key,
                    rates=tuple(_sort_for_trace(latest_rates)),
                    message=(
                        f"同一业务路线在{date_description} "
                        "存在不同运价或价格来源，程序不能自动决定采用哪一条；"
                        "该路线暂不生成候选边，请人工确认。"
                    ),
                )
            )
            continue

        representative_group = next(iter(rates_by_id.values()))
        selected_rates.append(_sort_for_trace(representative_group)[0])
        if used_transaction_preference:
            source_preference_resolution_count += 1

    return LatestRateSelectionResult(
        selected_rates=tuple(selected_rates),
        review_issues=tuple(review_issues),
        superseded_rate_count=superseded_rate_count,
        duplicate_rate_count=duplicate_rate_count,
        defaulted_date_count=defaulted_date_count,
        source_preference_resolution_count=source_preference_resolution_count,
    )


def effective_maintained_at(rate: FreightRate) -> date:
    """Return the comparison date without changing the original rate record."""
    return rate.maintained_at or DEFAULT_MAINTENANCE_DATE


def _sort_for_trace(rates: Iterable[FreightRate]) -> list[FreightRate]:
    return sorted(
        rates,
        key=lambda rate: (
            rate.source_file or "",
            rate.source_row_number if rate.source_row_number is not None else 2**31,
            rate.rate_id,
        ),
    )


def _prefer_transaction_rates_over_inquiry_rates(
    latest_rates: list[FreightRate],
) -> tuple[list[FreightRate], bool]:
    """Apply the confirmed source priority only to an inquiry-versus-deal clash.

    Source labels are business-maintained text.  The narrow rule deliberately
    recognises only labels containing ``成交`` and ``询价``; all other same-day
    differences remain subject to the normal conflict review path.
    """

    has_inquiry_rate = any(_is_inquiry_rate(rate) for rate in latest_rates)
    transaction_rates = [
        rate for rate in latest_rates if _is_transaction_rate(rate)
    ]
    if has_inquiry_rate and transaction_rates:
        return transaction_rates, True
    return latest_rates, False


def _is_transaction_rate(rate: FreightRate) -> bool:
    return "成交" in rate.price_source


def _is_inquiry_rate(rate: FreightRate) -> bool:
    return "询价" in rate.price_source
