from decimal import Decimal

import pytest

from src.data.inland_waterway_time import (
    InlandWaterwayTimeLoadError,
    load_inland_waterway_time_records,
)
from src.routing.inland_waterway_provider import (
    InlandWaterwayTimeRecord,
    TableInlandWaterwayTimeProvider,
)


def test_complete_segment_barge_time_converts_days_and_resolves_both_directions():
    record = make_record(duration_value="1.5", bidirectional=True)
    provider = TableInlandWaterwayTimeProvider((record,))

    outbound = provider.get_time(
        origin_region_code="example_origin",
        destination_region_code="example_destination",
        origin_name="示例起点港",
        destination_name="示例终点港",
    )
    inbound = provider.get_time(
        origin_region_code="example_destination",
        destination_region_code="example_origin",
        origin_name="示例终点港",
        destination_name="示例起点港",
    )

    assert record.duration_hours == Decimal("36.0")
    assert outbound.status == "resolved"
    assert outbound.duration_hours == Decimal("36.0")
    assert outbound.time_scope == "complete_segment"
    assert outbound.source.startswith("real_data:")
    assert "只解决时效" in outbound.message
    assert inbound.duration_hours == outbound.duration_hours


def test_missing_or_duplicate_barge_time_requires_manual_review():
    provider = TableInlandWaterwayTimeProvider(())
    missing = provider.get_time(
        origin_region_code="example_origin",
        destination_region_code="example_destination",
        origin_name="示例起点港",
        destination_name="示例终点港",
    )
    duplicate_provider = TableInlandWaterwayTimeProvider(
        (make_record(), make_record(source="example.csv#row=3"))
    )
    duplicate = duplicate_provider.get_time(
        origin_region_code="example_origin",
        destination_region_code="example_destination",
        origin_name="示例起点港",
        destination_name="示例终点港",
    )

    assert missing.status == "manual_review"
    assert missing.duration_hours is None
    assert duplicate.status == "manual_review"
    assert duplicate.duration_hours is None
    assert "多条" in duplicate.message


def test_loader_reads_source_backed_complete_segment_time(tmp_path):
    path = tmp_path / "内河驳船运输时效.csv"
    path.write_text(
        "origin_region_code,destination_region_code,duration_value,duration_unit,"
        "time_scope,bidirectional,source_type,source,rule_id,rule_version,maintained_at\n"
        "example_origin,example_destination,2,天,complete_segment,是,real_data,"
        "example_source,example_rule,1.0,2026-07-27\n",
        encoding="utf-8-sig",
    )

    records = load_inland_waterway_time_records(path)

    assert len(records) == 1
    assert records[0].duration_hours == Decimal("48")
    assert records[0].bidirectional
    assert records[0].time_scope == "complete_segment"


def test_loader_rejects_unsupported_time_unit(tmp_path):
    path = tmp_path / "内河驳船运输时效.csv"
    path.write_text(
        "origin_region_code,destination_region_code,duration_value,duration_unit,"
        "time_scope,bidirectional,source_type,source,rule_id,rule_version,maintained_at\n"
        "example_origin,example_destination,2,周,complete_segment,是,real_data,"
        "example_source,example_rule,1.0,2026-07-27\n",
        encoding="utf-8-sig",
    )

    with pytest.raises(InlandWaterwayTimeLoadError, match="不支持的驳船时效单位"):
        load_inland_waterway_time_records(path)


def test_loader_rejects_pure_sailing_scope_for_current_barge_model(tmp_path):
    path = tmp_path / "内河驳船运输时效.csv"
    path.write_text(
        "origin_region_code,destination_region_code,duration_value,duration_unit,"
        "time_scope,bidirectional,source_type,source,rule_id,rule_version,maintained_at\n"
        "example_origin,example_destination,2,天,pure_sailing,是,real_data,"
        "example_source,example_rule,1.0,2026-07-27\n",
        encoding="utf-8-sig",
    )

    with pytest.raises(InlandWaterwayTimeLoadError, match="必须是 complete_segment"):
        load_inland_waterway_time_records(path)


def make_record(
    *,
    duration_value: str = "2",
    bidirectional: bool = True,
    source: str = "example.csv#row=2",
) -> InlandWaterwayTimeRecord:
    return InlandWaterwayTimeRecord(
        origin_region_code="example_origin",
        destination_region_code="example_destination",
        duration_value=Decimal(duration_value),
        duration_unit="天",
        time_scope="complete_segment",
        bidirectional=bidirectional,
        source_type="real_data",
        source=source,
        rule_id="example_complete_barge_time",
        rule_version="1.0",
        maintained_at="2026-07-27",
    )
