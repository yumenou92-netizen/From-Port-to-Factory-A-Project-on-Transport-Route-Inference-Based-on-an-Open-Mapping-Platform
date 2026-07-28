from decimal import Decimal
from pathlib import Path

import pytest

from src.data.loaders import AdditionalFee, NodeRecord, RealDataBundle, make_node_id
from src.demos.leader_full_flow import (
    SOURCE_CONFIRMED_RULE,
    SOURCE_DEMO_PLACEHOLDER,
    SOURCE_CONFIRMED_TIME,
    SOURCE_REAL_DATA,
    SOURCE_TENCENT,
    FullFlowDemoError,
    _format_decimal,
    build_full_flow_demo,
    print_full_flow_result,
)
from src.routing.bulk_shipping_provider import BulkRateColumn, BulkShippingWorkbook
from src.domain.freight_rate import create_freight_rate
from src.geo.coordinate_provider import CoordinateResolution
from src.geo.distance_provider import RoadRouteResult
from src.routing.port_operation_fee_provider import (
    PortOperationFeeExemption,
    PortOperationFeeRate,
    PortOperationFeeRegionAssignment,
    TablePortOperationFeeProvider,
)


def test_full_flow_prefers_real_rate_and_limits_placeholders_to_trunk(capsys):
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=2,
        bulk_workbook=make_bulk_workbook(),
    )

    assert result.graph_edge_count == 4
    assert result.recommendations.lowest_cost.is_resolved
    assert result.recommendations.fastest_time.is_resolved
    assert result.recommendations.lowest_cost.path_node_ids != (
        result.recommendations.fastest_time.path_node_ids
    )

    traces = tuple(result.edge_sources.values())
    assert sum(trace.labels == (SOURCE_DEMO_PLACEHOLDER,) for trace in traces) == 0
    assert sum(trace.labels == (SOURCE_REAL_DATA, SOURCE_CONFIRMED_TIME) for trace in traces) == 2
    assert any(trace.labels == (SOURCE_REAL_DATA, SOURCE_TENCENT) for trace in traces)
    assert any(trace.labels == (SOURCE_CONFIRMED_RULE, SOURCE_TENCENT) for trace in traces)
    route_segments = (
        result.recommendations.lowest_cost.segments
        + result.recommendations.fastest_time.segments
    )
    assert {
        segment.transport_mode
        for segment in route_segments
        if result.edge_sources[segment.edge_key].labels == (SOURCE_REAL_DATA, SOURCE_CONFIRMED_TIME)
    } == {"散船"}

    print_full_flow_result(result)
    output = capsys.readouterr().out
    assert "费用最低路线" in output
    assert "时间最短路线" in output
    assert "真实业务数据" in output
    assert "演示占位数据" in output
    assert "坐标置信等级：北港=未提供；客户工厂=未提供" in output
    assert "地点节点：北港=已注册标准节点；客户工厂=已注册标准节点" in output
    assert "本次搜索图运输边=4 条（真实散船干线边=2 条；南港至客户汽运边=2 条）" in output
    assert "候选南港（本次均已形成可搜索的南港至客户汽运段）" in output
    assert "钦州港；预筛直线距离=" in output
    assert "候选预筛口径（当前原型启发式）：候选来源于可用汽运运价始发端" in output
    assert "方式=散船干线" in output
    assert "总费用组成（已计入）" in output
    assert "散船干线：北港A -> 钦州港；24500元" in output
    assert "汽运：钦州港 -> 客户工厂B；49000元" in output
    assert "已计入合计：73500元" in output
    assert "未计入项：AdditionalFee（原始记录已加载，逐条适用条件未确认）" in output
    assert "南港码头作业费表=未接入（当前不计入；缺失不代表费用为 0）" in output
    assert "未计入项：南港码头作业费（正式表未接入；缺失不解释为 0）" in output
    assert "散船运费：24500元" in output
    assert "AdditionalFee 原始记录=1 条" in output
    assert "仅完成结构化加载，未计入本次总费用" in output
    assert "缺失不代表费用为 0" in output
    assert "逐条适用条件未确认前不计入，也不解释为 0" in output
    assert "时效口径提示：本模型将已确认船运时效直接视为对应航运段总时间" in output
    assert "未配置正式时效的运输段仍不得补零" in output
    assert "三、测试版数据边界说明" in output


def test_full_flow_explains_tencent_runtime_nodes_without_treating_them_as_registered(capsys):
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=TemporaryCoordinateProvider(),
        road_route_provider=FractionalRoadRouteProvider(),
        candidate_limit=1,
        bulk_workbook=make_bulk_workbook(),
    )

    print_full_flow_result(result)

    output = capsys.readouterr().out
    assert "地点节点：北港=腾讯坐标生成的本次运行临时节点（可参与构图）" in output
    assert "客户工厂=腾讯坐标生成的本次运行临时节点（可参与构图）" in output
    assert "总费用：73500 元；总时间：169.57 小时" in output
    assert "费用=49000元；时间=1.57小时" in output
    assert "在本次候选范围和当前真实散船干线参数下" in output
    assert "两项目标仍由系统独立搜索" in output


def test_leader_decimal_format_rounds_half_up_and_removes_unneeded_zeroes():
    assert _format_decimal(Decimal("49.5666666667")) == "49.57"
    assert _format_decimal(Decimal("77270.4000")) == "77270.4"
    assert _format_decimal(Decimal("48")) == "48"


def test_full_flow_stops_when_input_coordinate_is_not_resolved():
    with pytest.raises(FullFlowDemoError, match="北港点 A坐标未确认"):
        build_full_flow_demo(
            "无法解析的北港",
            "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=UnresolvedOriginProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
        )


def test_known_real_route_is_prioritized_over_closer_unknown_origin():
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=FactoryNearSecondPortCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=1,
        bulk_workbook=make_bulk_workbook(),
    )

    assert result.candidate_ports[0].name == "钦州港"
    assert any(
        trace.labels == (SOURCE_REAL_DATA, SOURCE_TENCENT)
        for trace in result.edge_sources.values()
    )


def test_full_flow_includes_resolved_south_port_operation_fee(capsys):
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=1,
        bulk_workbook=make_bulk_workbook(),
        port_operation_fee_provider=TablePortOperationFeeProvider(
            (
                PortOperationFeeRate(
                    port_name="钦州港",
                    package_type="散粮",
                    fee_type="码头作业费",
                    unit_price_yuan_per_ton=Decimal("8"),
                    source="test_fee_table#row=1",
                    node_id=make_node_id("钦州港"),
                ),
            )
        ),
        port_operation_fee_source="test_fee_table",
    )

    assert result.port_operation_fee_included_count == 1
    assert result.recommendations.lowest_cost.total_cost_yuan == Decimal("93100")
    trunk_segment = result.recommendations.lowest_cost.segments[0]
    assert trunk_segment.cost_yuan == Decimal("44100")
    assert [component.component_type for component in trunk_segment.cost_components] == [
        "bulk_shipping_freight",
        "south_port_operation_fee",
    ]

    print_full_flow_result(result)
    output = capsys.readouterr().out
    assert "南港码头作业费表=test_fee_table；已计入散船干线边=1 条" in output
    assert "散船干线：北港A -> 钦州港；44100元" in output
    assert "散船运费：24500元" in output
    assert "码头作业费：19600元" in output
    assert "已计入合计：93100元" in output


def test_full_flow_keeps_candidate_when_operation_fee_is_explicitly_not_applicable(capsys):
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=1,
        bulk_workbook=make_bulk_workbook(),
        port_operation_fee_provider=TablePortOperationFeeProvider(
            exemptions=(
                PortOperationFeeExemption(
                    port_name="钦州港",
                    node_id=make_node_id("钦州港"),
                    package_type="散粮",
                    fee_type="码头作业费",
                    source="business_confirmation",
                    reason="客户自有码头，经业务确认无需码头作业费",
                ),
            )
        ),
        port_operation_fee_source="test_fee_table",
    )

    assert result.graph_edge_count == 2
    assert result.port_operation_fee_included_count == 0
    assert result.port_operation_fee_not_applicable_count == 1
    assert result.recommendations.lowest_cost.total_cost_yuan == Decimal("73500")
    assert [
        component.component_type
        for component in result.recommendations.lowest_cost.segments[0].cost_components
    ] == ["bulk_shipping_freight"]

    print_full_flow_result(result)
    output = capsys.readouterr().out
    assert "明确不适用=1 条" in output
    assert "客户自有码头等明确不适用规则按 0 元通过且保留原因" in output


def test_full_flow_includes_traceable_regional_proxy_operation_fee(capsys):
    provider = TablePortOperationFeeProvider(
        (
            PortOperationFeeRate(
                port_name="区域参考港",
                package_type="散粮",
                fee_type="码头作业费",
                unit_price_yuan_per_ton=Decimal("8"),
                source="test_fee_table#reference",
                node_id="node-region-reference",
                operation_fee_region_code="test-operation-fee-region",
                is_region_reference=True,
            ),
        ),
        region_assignments=(
            PortOperationFeeRegionAssignment(
                port_node_id=make_node_id("钦州港"),
                operation_fee_region_code="test-operation-fee-region",
                source="test_region_mapping#row=1",
                mapping_basis="测试人工确认同一作业费区域",
                mapping_rule_id="operation_fee_region_manual_mapping",
                mapping_rule_version="1.0",
                confirmation_status="confirmed",
            ),
        ),
    )
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=1,
        bulk_workbook=make_bulk_workbook(),
        port_operation_fee_provider=provider,
        port_operation_fee_source="test_fee_table+test_region_mapping",
    )

    trunk_component = result.recommendations.lowest_cost.segments[0].cost_components[1]
    assert trunk_component.source_type == "regional_proxy"
    assert "参考码头node_id=node-region-reference" in trunk_component.calculation_detail
    assert "不是目标码头精确真实费率" in trunk_component.calculation_detail

    print_full_flow_result(result)
    output = capsys.readouterr().out
    assert "来源=同区域最近码头代理费率" in output


def test_full_flow_excludes_candidate_with_missing_operation_fee_when_provider_is_connected():
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=2,
        bulk_workbook=make_bulk_workbook(),
        port_operation_fee_provider=TablePortOperationFeeProvider(
            (
                PortOperationFeeRate(
                    port_name="漳州港",
                    package_type="散粮",
                    fee_type="码头作业费",
                    unit_price_yuan_per_ton=Decimal("6"),
                    source="test_fee_table#row=2",
                    node_id=make_node_id("漳州港"),
                ),
            )
        ),
        port_operation_fee_source="test_fee_table",
    )

    assert [port.name for port in result.candidate_ports] == ["漳州港"]
    assert result.graph_edge_count == 2
    assert result.port_operation_fee_included_count == 1
    assert any("钦州港" in warning and "南港码头作业费未确认" in warning for warning in result.warnings)


class FakeCoordinateProvider:
    def resolve(self, name: str) -> CoordinateResolution:
        values = {
            "北港A": (make_node_id("北港A"), 116.0, 38.0, "tencent_map_place_search"),
            "客户工厂B": (make_node_id("客户工厂B"), 117.2, 24.2, "node_registry"),
        }
        node_id, longitude, latitude, source = values[name]
        return CoordinateResolution(
            status="resolved",
            query_name=name,
            node_id=node_id,
            canonical_name=name,
            longitude=longitude,
            latitude=latitude,
            source=source,
            message="测试坐标已解析。",
        )


class UnresolvedOriginProvider(FakeCoordinateProvider):
    def resolve(self, name: str) -> CoordinateResolution:
        if name == "无法解析的北港":
            return CoordinateResolution(
                status="manual_review",
                query_name=name,
                node_id=None,
                canonical_name=None,
                longitude=None,
                latitude=None,
                source="tencent_map_place_search",
                message="候选地点仍需人工确认。",
            )
        return super().resolve(name)


class TemporaryCoordinateProvider(FakeCoordinateProvider):
    def resolve(self, name: str) -> CoordinateResolution:
        result = super().resolve(name)
        return CoordinateResolution(
            status="resolved",
            query_name=name,
            node_id=None,
            canonical_name=result.canonical_name,
            longitude=result.longitude,
            latitude=result.latitude,
            source="tencent_map_place_search",
            message="测试坐标已解析为本次运行临时节点。",
            source_confidence="auto_top1_name_match",
        )


class FactoryNearSecondPortCoordinateProvider(FakeCoordinateProvider):
    def resolve(self, name: str) -> CoordinateResolution:
        result = super().resolve(name)
        if name != "客户工厂B":
            return result
        return CoordinateResolution(
            status="resolved",
            query_name=name,
            node_id=result.node_id,
            canonical_name=name,
            longitude=118.1,
            latitude=24.1,
            source="node_registry",
            message="测试坐标已解析。",
        )


class FakeRoadRouteProvider:
    def get_route(self, request) -> RoadRouteResult:
        if request.origin.longitude == Decimal("117.0"):
            distance, duration = Decimal("20"), Decimal("6")
        else:
            distance, duration = Decimal("80"), Decimal("2")
        return RoadRouteResult(
            status="resolved",
            distance_km=distance,
            duration_hours=duration,
            source="tencent_map_driving_route",
            message="测试驾车路线已解析。",
        )


class FractionalRoadRouteProvider:
    def get_route(self, request) -> RoadRouteResult:
        return RoadRouteResult(
            status="resolved",
            distance_km=Decimal("20"),
            duration_hours=Decimal("1.5666666667"),
            source="tencent_map_driving_route",
            message="测试驾车路线已解析。",
        )


def make_bundle() -> RealDataBundle:
    north_port = NodeRecord(make_node_id("北港A"), "北港A", 116.0, 38.0)
    south_port_1 = NodeRecord(make_node_id("钦州港"), "钦州港", 117.0, 24.0)
    south_port_2 = NodeRecord(make_node_id("漳州港"), "漳州港", 118.0, 24.0)
    destination = NodeRecord(make_node_id("客户工厂B"), "客户工厂B", 117.2, 24.2)
    other_factory = NodeRecord(make_node_id("其他工厂"), "其他工厂", 118.2, 24.2)

    known_rate = create_freight_rate(
        origin_name=south_port_1.name,
        destination_name=destination.name,
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price="20",
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="真实维护运价",
        maintained_at="2026-07-01",
        from_node_id=south_port_1.node_id,
        to_node_id=destination.node_id,
        source_file="运价表.json",
        source_row_number=1,
    )
    candidate_origin_rate = create_freight_rate(
        origin_name=south_port_2.name,
        destination_name=other_factory.name,
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price="22",
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="真实维护运价",
        maintained_at="2026-07-01",
        from_node_id=south_port_2.node_id,
        to_node_id=other_factory.node_id,
        source_file="运价表.json",
        source_row_number=2,
    )
    return RealDataBundle(
        data_dir=Path("test-data"),
        freight_rates=[known_rate, candidate_origin_rate],
        nodes=[north_port, south_port_1, south_port_2, destination, other_factory],
        additional_fees=[
            AdditionalFee(
                node_name=south_port_1.name,
                packaging="散粮",
                fee_type="作业费",
                unit_price=Decimal("8"),
                fee_unit="元/吨",
            )
        ],
    )


def make_bulk_workbook() -> BulkShippingWorkbook:
    return BulkShippingWorkbook(
        (
            BulkRateColumn(
                destination_label="钦州",
                vessel_type="2.5-3万吨",
                rate_yuan_per_ton=Decimal("10"),
                cell_ref="Q9",
                latest_date_label="7/6 周一",
                workbook_path="test-data/散船运价表.xlsx",
                scope="project_scope_confirmed",
            ),
            BulkRateColumn(
                destination_label="漳州",
                vessel_type="1.5-1.6万吨",
                rate_yuan_per_ton=Decimal("44"),
                cell_ref="J9",
                latest_date_label="7/6 周一",
                workbook_path="test-data/散船运价表.xlsx",
                scope="project_scope_confirmed",
            ),
        )
    )
