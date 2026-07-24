from decimal import Decimal

import pytest

from src.domain.route_request import RouteRequest
from src.routing.port_operation_fee_provider import (
    DemoPortOperationFeeProvider,
    PortOperationFeeError,
    PortOperationFeeRate,
    PortOperationFeeRegionAssignment,
    TablePortOperationFeeProvider,
    load_port_operation_fee_rates,
)


def test_table_provider_quotes_yuan_per_ton_operation_fee_component():
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="秀屿港",
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("8"),
                source="south_port_operation_fee.csv#row=2",
                trade_type="内贸",
                node_id="node-xiuyu",
                commodity_scope=("玉米", "小麦"),
            ),
        )
    )

    quote = provider.quote(
        port_name="莆田秀屿港",
        port_node_id="node-xiuyu",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "resolved"
    assert quote.total_cost_yuan == Decimal("4000")
    assert quote.component is not None
    assert quote.component.component_type == "south_port_operation_fee"
    assert quote.component.source_type == "real_data"
    assert quote.component.amount_yuan == Decimal("4000")
    assert quote.component.rule_id == "south_port_operation_fee_yuan_per_ton"


def test_missing_operation_fee_rate_requires_manual_review_not_zero():
    quote = TablePortOperationFeeProvider().quote(
        port_name="秀屿港",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "manual_review"
    assert quote.total_cost_yuan is None
    assert quote.component is None
    assert "不解释为 0" in quote.message


def test_operation_fee_requires_matching_trade_type():
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="广州新港",
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("6"),
                source="south_port_operation_fee.csv#row=2",
                trade_type="外贸",
            ),
        )
    )

    quote = provider.quote(
        port_name="广州新港",
        request=RouteRequest(500, "吨", "散粮", "玉米", trade_type="内贸"),
    )

    assert quote.status == "manual_review"
    assert quote.component is None
    assert "不解释为 0" in quote.message


def test_operation_fee_supports_container_yuan_per_box_without_unit_conversion():
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="广州新港",
                package_type="集装箱",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("500"),
                fee_unit="元/箱",
                source="south_port_operation_fee.csv#row=5",
            ),
        )
    )

    quote = provider.quote(
        port_name="广州新港",
        request=RouteRequest(12, "箱", "集装箱", "玉米"),
    )

    assert quote.status == "resolved"
    assert quote.total_cost_yuan == Decimal("6000")
    assert quote.component is not None
    assert quote.component.rule_id == "south_port_operation_fee_yuan_per_box"


def test_operation_fee_does_not_convert_container_box_to_container_load():
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="广州新港",
                package_type="集装箱",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("500"),
                fee_unit="元/箱",
                source="south_port_operation_fee.csv#row=5",
            ),
        )
    )

    quote = provider.quote(
        port_name="广州新港",
        request=RouteRequest(12, "柜", "集装箱", "玉米"),
    )

    assert quote.status == "manual_review"
    assert quote.component is None
    assert "不解释为 0" in quote.message


def test_duplicate_operation_fee_rates_require_manual_review():
    rates = (
        PortOperationFeeRate(
            port_name="广州新港",
            package_type="散粮",
            fee_type="码头作业费",
            unit_price_yuan_per_ton=Decimal("6"),
            source="south_port_operation_fee.csv#row=2",
        ),
        PortOperationFeeRate(
            port_name="广州新港",
            package_type="散粮",
            fee_type="码头作业费",
            unit_price_yuan_per_ton=Decimal("7"),
            source="south_port_operation_fee.csv#row=3",
        ),
    )

    quote = TablePortOperationFeeProvider(rates).quote(
        port_name="广州新港",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "manual_review"
    assert quote.component is None
    assert "多条可匹配" in quote.message


def test_exact_port_rate_has_priority_over_confirmed_region_proxy():
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="目标港",
                node_id="node-target",
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("7"),
                source="exact_rate.csv#row=2",
            ),
            PortOperationFeeRate(
                port_name="参考港",
                node_id="node-reference",
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("8"),
                source="reference_rate.csv#row=3",
                operation_fee_region_code="region-a",
                is_region_reference=True,
            ),
        ),
        region_assignments=(
            PortOperationFeeRegionAssignment(
                port_node_id="node-target",
                operation_fee_region_code="region-a",
                source="region_mapping.csv#row=2",
                mapping_basis="人工确认同一作业费区域",
                mapping_rule_id="operation_fee_region_manual_mapping",
                mapping_rule_version="1.0",
                confirmation_status="confirmed",
            ),
        ),
    )

    quote = provider.quote(
        port_name="目标港",
        port_node_id="node-target",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "resolved"
    assert quote.total_cost_yuan == Decimal("3500")
    assert quote.component is not None
    assert quote.component.source_type == "real_data"


def test_confirmed_region_proxy_preserves_reference_and_mapping_trace():
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="漳州港",
                node_id="node-reference-zhangzhou",
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("8"),
                source="south_port_operation_fee.csv#row=2",
                operation_fee_region_code="fujian_zhangzhou",
                is_region_reference=True,
            ),
        ),
        region_assignments=(
            PortOperationFeeRegionAssignment(
                port_node_id="node-nearby-port",
                operation_fee_region_code="fujian_zhangzhou",
                source="region_mapping.csv#row=2",
                mapping_basis="业务人工确认同属漳州作业费区域",
                mapping_rule_id="operation_fee_region_manual_mapping",
                mapping_rule_version="1.0",
                confirmation_status="confirmed",
            ),
        ),
    )

    quote = provider.quote(
        port_name="漳州附近港口",
        port_node_id="node-nearby-port",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "resolved"
    assert quote.total_cost_yuan == Decimal("4000")
    assert quote.rate is not None
    assert quote.rate.source_type == "regional_proxy"
    assert quote.rate.reference_port_node_id == "node-reference-zhangzhou"
    assert quote.rate.mapping_source == "region_mapping.csv#row=2"
    assert quote.component is not None
    assert quote.component.source_type == "regional_proxy"
    assert quote.component.rule_id == "south_port_operation_fee_regional_proxy"
    assert quote.component.rule_version == "1.0"
    assert "不是目标码头精确真实费率" in quote.component.calculation_detail
    assert "映射来源=region_mapping.csv#row=2" in quote.component.calculation_detail
    assert "regional_proxy" in quote.message


def test_region_proxy_requires_standard_node_id_and_one_confirmed_assignment():
    reference_rate = PortOperationFeeRate(
        port_name="参考港",
        node_id="node-reference",
        package_type="散粮",
        fee_type="码头作业费",
        unit_price_yuan_per_ton=Decimal("8"),
        source="reference_rate.csv#row=2",
        operation_fee_region_code="region-a",
        is_region_reference=True,
    )
    provider = TablePortOperationFeeProvider(
        (reference_rate,),
        region_assignments=(
            PortOperationFeeRegionAssignment(
                port_node_id="node-target",
                operation_fee_region_code="region-a",
                source="region_mapping.csv#row=2",
                mapping_basis="待人工确认",
                mapping_rule_id="operation_fee_region_manual_mapping",
                mapping_rule_version="1.0",
                confirmation_status="manual_review",
            ),
        ),
    )

    missing_id = provider.quote(
        port_name="目标港",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )
    unconfirmed_mapping = provider.quote(
        port_name="目标港",
        port_node_id="node-target",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert missing_id.status == "manual_review"
    assert "不得按名称或坐标猜测" in missing_id.message
    assert unconfirmed_mapping.status == "manual_review"
    assert unconfirmed_mapping.total_cost_yuan is None
    assert "地域代理不启用" in unconfirmed_mapping.message


def test_duplicate_confirmed_region_assignments_require_manual_review():
    reference_rate = PortOperationFeeRate(
        port_name="参考港",
        node_id="node-reference",
        package_type="散粮",
        fee_type="码头作业费",
        unit_price_yuan_per_ton=Decimal("8"),
        source="reference_rate.csv#row=2",
        operation_fee_region_code="region-a",
        is_region_reference=True,
    )
    assignments = tuple(
        PortOperationFeeRegionAssignment(
            port_node_id="node-target",
            operation_fee_region_code=region_code,
            source=f"region_mapping.csv#row={row}",
            mapping_basis="人工确认",
            mapping_rule_id="operation_fee_region_manual_mapping",
            mapping_rule_version="1.0",
            confirmation_status="confirmed",
        )
        for region_code, row in (("region-a", 2), ("region-b", 3))
    )

    quote = TablePortOperationFeeProvider(
        (reference_rate,),
        region_assignments=assignments,
    ).quote(
        port_name="目标港",
        port_node_id="node-target",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "manual_review"
    assert "存在多条已确认映射" in quote.message


def test_duplicate_region_reference_rates_require_manual_review():
    reference_rates = tuple(
        PortOperationFeeRate(
            port_name=f"参考港{row}",
            node_id=f"node-reference-{row}",
            package_type="散粮",
            fee_type="码头作业费",
            unit_price_yuan_per_ton=Decimal(price),
            source=f"reference_rate.csv#row={row}",
            operation_fee_region_code="region-a",
            is_region_reference=True,
        )
        for row, price in ((2, "8"), (3, "9"))
    )
    assignment = PortOperationFeeRegionAssignment(
        port_node_id="node-target",
        operation_fee_region_code="region-a",
        source="region_mapping.csv#row=2",
        mapping_basis="人工确认",
        mapping_rule_id="operation_fee_region_manual_mapping",
        mapping_rule_version="1.0",
        confirmation_status="confirmed",
    )

    quote = TablePortOperationFeeProvider(
        reference_rates,
        region_assignments=(assignment,),
    ).quote(
        port_name="目标港",
        port_node_id="node-target",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "manual_review"
    assert "存在多条适用参考费率" in quote.message


def test_demo_provider_marks_operation_fee_as_placeholder():
    quote = DemoPortOperationFeeProvider(unit_price_yuan_per_ton=Decimal("5")).quote(
        port_name="任意南港",
        request=RouteRequest(500, "吨", "散粮", "玉米"),
    )

    assert quote.status == "resolved"
    assert quote.total_cost_yuan == Decimal("2500")
    assert quote.component is not None
    assert quote.component.is_demo_placeholder
    assert quote.component.rule_id == "demo_placeholder_south_port_operation_fee"


def test_csv_loader_rejects_unsupported_operation_fee_units(tmp_path):
    path = tmp_path / "南港码头作业费.csv"
    write_csv(
        path,
        ["港口名称", "包装方式", "费用类型", "单价", "费用单位", "数据来源"],
        [["秀屿港", "散粮", "码头作业费", "8", "元/柜", "bad_fixture"]],
    )

    with pytest.raises(PortOperationFeeError, match="当前仅支持"):
        load_port_operation_fee_rates(path)


def test_csv_loader_rejects_unsupported_trade_type(tmp_path):
    path = tmp_path / "南港码头作业费.csv"
    write_csv(
        path,
        ["港口名称", "包装方式", "费用类型", "单价", "费用单位", "贸易类型", "数据来源"],
        [["秀屿港", "散粮", "码头作业费", "8", "元/吨", "转口", "bad_fixture"]],
    )

    with pytest.raises(PortOperationFeeError, match="不支持的贸易类型"):
        load_port_operation_fee_rates(path)


def test_csv_loader_rejects_directly_maintained_regional_proxy(tmp_path):
    path = tmp_path / "南港码头作业费.csv"
    write_csv(
        path,
        [
            "港口名称",
            "包装方式",
            "费用类型",
            "单价",
            "费用单位",
            "来源类型",
            "数据来源",
        ],
        [["目标港", "散粮", "码头作业费", "8", "元/吨", "regional_proxy", "bad_fixture"]],
    )

    with pytest.raises(PortOperationFeeError, match="不得直接维护 regional_proxy"):
        load_port_operation_fee_rates(path)


def test_csv_loader_reads_operation_fee_rates(tmp_path):
    path = tmp_path / "南港码头作业费.csv"
    write_csv(
        path,
        ["港口名称", "包装方式", "费用类型", "单价", "费用单位", "数据来源", "适用品种", "贸易类型"],
        [["秀屿港", "散粮", "码头作业费", "8", "元/吨", "manual_confirmed", "玉米；小麦", "外贸"]],
    )

    rates = load_port_operation_fee_rates(path)

    assert len(rates) == 1
    assert rates[0].port_name == "秀屿港"
    assert rates[0].unit_price_yuan_per_ton == Decimal("8")
    assert rates[0].commodity_scope == ("玉米", "小麦")
    assert rates[0].trade_type == "外贸"


def write_csv(path, headers, rows):
    path.write_text(
        ",".join(headers)
        + "\n"
        + "\n".join(",".join(str(value) for value in row) for row in rows),
        encoding="utf-8-sig",
    )
