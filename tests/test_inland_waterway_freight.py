from decimal import Decimal

from src.data.inland_waterway_freight import (
    load_inland_waterway_freight_records,
)
from src.domain.route_request import RouteRequest
from src.routing.inland_waterway_freight_provider import (
    TableInlandWaterwayFreightProvider,
)


def test_fujian_minjiang_bulk_grain_rate_applies_both_directions(tmp_path):
    path = tmp_path / "内河驳船运输费率.csv"
    path.write_text(
        "origin_region_code,destination_region_code,package_type,commodity_scope,"
        "unit_price,fee_unit,trade_type,bidirectional,source_type,source,"
        "rule_id,rule_version,maintained_at\n"
        "fujian_minjiang,fujian_minjiang,散粮,*,50,元/吨,内贸,是,real_data,"
        "business_confirmation_2026-07-28,fujian_minjiang_barge_freight,"
        "1.0,2026-07-28\n",
        encoding="utf-8-sig",
    )
    records = load_inland_waterway_freight_records(path)
    provider = TableInlandWaterwayFreightProvider(records)

    quote = provider.quote(
        origin_region_code="fujian_minjiang",
        destination_region_code="fujian_minjiang",
        request=RouteRequest(Decimal("2450"), "吨", "散粮", "小麦"),
    )

    assert quote.status == "resolved"
    assert quote.total_cost_yuan == Decimal("122500")
    assert quote.record is not None
    assert quote.record.source_type == "real_data"


def test_inland_waterway_freight_missing_request_dimensions_do_not_fall_back_to_zero():
    quote = TableInlandWaterwayFreightProvider(()).quote(
        origin_region_code="fujian_minjiang",
        destination_region_code="fujian_minjiang",
        request=RouteRequest(Decimal("500"), "吨", "散粮", "玉米"),
    )

    assert quote.status == "manual_review"
    assert quote.total_cost_yuan is None
    assert "不得补零" in quote.message
