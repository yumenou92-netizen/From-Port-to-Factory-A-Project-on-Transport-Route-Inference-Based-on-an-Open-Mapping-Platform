from pathlib import Path

from src.data.inland_waterway_freight import load_inland_waterway_freight_records
from src.data.inland_waterway_time import load_inland_waterway_time_records
from src.data.port_reference import (
    load_operation_fee_region_assignments,
    load_port_capability_records,
    load_region_mapping_records,
)
from src.routing.port_operation_fee_provider import (
    load_port_operation_fee_exemptions,
    load_port_operation_fee_rates,
)


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "docs" / "data_templates"


def test_w3_w5_data_templates_match_current_loaders():
    capabilities = load_port_capability_records(TEMPLATE_DIR / "港口能力表.example.csv")
    mappings = load_region_mapping_records(TEMPLATE_DIR / "区域映射表.example.csv")
    operation_fees = load_port_operation_fee_rates(TEMPLATE_DIR / "南港码头作业费.example.csv")
    operation_fee_exemptions = load_port_operation_fee_exemptions(
        TEMPLATE_DIR / "南港码头作业费.example.csv"
    )
    operation_fee_assignments = load_operation_fee_region_assignments(
        TEMPLATE_DIR / "区域映射表.example.csv"
    )
    inland_waterway_times = load_inland_waterway_time_records(
        TEMPLATE_DIR / "内河驳船运输时效.example.csv"
    )
    inland_waterway_freight = load_inland_waterway_freight_records(
        TEMPLATE_DIR / "内河驳船运输费率.example.csv"
    )

    assert len(capabilities) == 2
    assert capabilities[0].canonical_name == "示例海港A"
    assert capabilities[0].can_receive_bulk_shipping is True
    assert capabilities[0].is_transfer_port is False
    assert capabilities[0].capability_data_confirmed
    assert capabilities[1].can_receive_bulk_shipping is None
    assert capabilities[1].is_transfer_port is None
    assert capabilities[1].can_handle_barge is None
    assert not capabilities[1].capability_data_confirmed

    assert len(mappings) == 2
    assert mappings[0].bulk_rate_destination_group == "珠三角"
    assert mappings[1].bulk_rate_destination_group == "秀屿"
    assert mappings[1].bulk_time_region == "福建"

    assert len(operation_fee_assignments) == 2
    assert all(item.is_confirmed for item in operation_fee_assignments)

    assert len(operation_fees) == 1
    assert operation_fees[0].port_name == "示例海港A"
    assert operation_fees[0].fee_type == "码头作业费"
    assert operation_fees[0].trade_type == "内贸"
    assert operation_fees[0].source_type == "real_data"
    assert operation_fees[0].operation_fee_region_code == "operation_fee_prd"
    assert operation_fees[0].is_region_reference
    assert len(operation_fee_exemptions) == 1
    assert operation_fee_exemptions[0].port_name == "示例客户自有码头"

    assert len(inland_waterway_times) == 1
    assert inland_waterway_times[0].time_scope == "complete_segment"
    assert inland_waterway_times[0].bidirectional

    assert len(inland_waterway_freight) == 1
    assert inland_waterway_freight[0].package_type == "散粮"
    assert inland_waterway_freight[0].commodity_scope == ("*",)
    assert inland_waterway_freight[0].fee_unit == "元/吨"
    assert inland_waterway_freight[0].bidirectional
