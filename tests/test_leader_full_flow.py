from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.demos.leader_full_flow as leader_full_flow_module
from src.application.route_planning import RoutePlanningRequest, RoutePlanningResponse
from src.data.loaders import AdditionalFee, NodeRecord, RealDataBundle, make_node_id
from src.demos.leader_full_flow import (
    SOURCE_CONFIRMED_RULE,
    SOURCE_DEMO_PLACEHOLDER,
    SOURCE_CONFIRMED_TIME,
    SOURCE_REAL_DATA,
    SOURCE_TENCENT,
    FullFlowDemoError,
    _cost_per_ton_wan,
    _format_decimal,
    build_full_flow_demo,
    main as leader_full_flow_main,
    plan_full_flow,
    print_full_flow_result,
)
from src.routing.bulk_shipping_provider import BulkRateColumn, BulkShippingWorkbook
from src.routing.formal_inland_waterway_provider import (
    ExactOdInlandWaterwayBargeProvider,
    TableInlandWaterwayBargeProvider,
)
from src.routing.inland_waterway_freight_provider import (
    InlandWaterwayFreightRecord,
)
from src.routing.inland_waterway_provider import (
    InlandWaterwayEndpointCandidate,
    InlandWaterwayTimeRecord,
    PortCapabilityRecord,
    RegionMappingRecord,
)
from src.domain.freight_rate import create_freight_rate
from src.domain.route_request import RouteRequest
from src.geo.coordinate_provider import CoordinateResolution
from src.geo.distance_provider import GeoPoint, RoadRouteResult
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
    assert len(result.edge_geometries) == 2
    assert all(
        geometry.kind == "tencent_driving_polyline"
        and geometry.is_schematic is False
        for geometry in result.edge_geometries.values()
    )
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
    assert (
            "本次搜索图运输边=4 条（真实散船干线边=2 条；"
            "汽运边=2 条；内河驳船边=0 条）"
    ) in output
    assert "候选南港（本次均已形成至少一种可搜索的南港后运输方案）" in output
    assert "钦州港；预筛直线距离=" in output
    assert "候选预筛口径（当前原型启发式）：候选来源于适用当前订单的真实运价始发端" in output
    assert "候选准入决策（身份筛选、排序与构边结果）" in output
    assert all(
        decision.status == "included"
        for decision in result.candidate_decisions
        if decision.name in {"钦州港", "漳州港"}
    )
    assert "方式=散船干线" in output
    assert "总费用组成（已计入）" in output
    assert "散船干线：北港A -> 钦州港；31600元" in output
    assert "汽运：钦州港 -> 客户工厂B；63200元" in output
    assert "已计入合计：94800元" in output
    assert "折合运价：0.003 万元/吨（总费用÷订单吨数）" in output
    assert "未计入项：AdditionalFee（原始记录已加载，逐条适用条件未确认）" in output
    assert "南港码头作业费表=未接入（当前不计入；缺失不代表费用为 0）" in output
    assert "未计入项：南港码头作业费（正式表未接入；缺失不解释为 0）" in output
    assert "散船运费：31600元" in output
    assert "AdditionalFee 原始记录=1 条" in output
    assert "仅完成结构化加载，未计入本次总费用" in output
    assert "缺失不代表费用为 0" in output
    assert "逐条适用条件未确认前不计入，也不解释为 0" in output
    assert "时效口径提示：本模型将已确认船运时效直接视为对应航运段总时间" in output
    assert "未配置正式时效的运输段仍不得补零" in output
    assert "三、数据边界说明" in output


def test_cost_per_ton_wan_only_supports_ton_orders():
    ton_request = RouteRequest(Decimal("3160"), "吨", "散粮", "玉米")
    box_request = RouteRequest(Decimal("200"), "箱", "集装箱", "玉米")

    assert _cost_per_ton_wan(Decimal("94800"), ton_request) == Decimal("0.003")
    assert _cost_per_ton_wan(Decimal("94800"), box_request) is None


def test_application_contract_runs_the_existing_full_flow_engine():
    requested_regions: list[str] = []
    planning_request = RoutePlanningRequest(
        origin="北港A",
        destination="客户工厂B",
        south_port="钦州港",
        request=RouteRequest(Decimal("2450"), "吨", "散粮", "玉米"),
    )

    result = plan_full_flow(
        planning_request,
        bundle=make_bundle(),
        coordinate_provider_factory=lambda region: (
            requested_regions.append(region) or FakeCoordinateProvider()
        ),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
    )

    assert isinstance(result, RoutePlanningResponse)
    assert result.origin_name == planning_request.origin
    assert result.destination_name == planning_request.destination
    assert result.selected_south_port == planning_request.south_port
    assert result.request is planning_request.request
    assert requested_regions == ["全国"]
    assert result.recommendations.lowest_cost.is_resolved
    assert result.recommendations.fastest_time.is_resolved


def test_cli_formats_application_contract_validation_error():
    with pytest.raises(
        SystemExit,
        match="全流程演示未完成：出发北港不能为空",
    ):
        leader_full_flow_main(
            [
                "--origin",
                " ",
                "--destination",
                "客户工厂B",
            ]
        )


def test_cli_passes_transport_conditions_through_application_service(monkeypatch):
    captured = {}
    response = RoutePlanningResponse.__new__(RoutePlanningResponse)

    def fake_plan_full_flow(request, **dependencies):
        captured["request"] = request
        captured["dependencies"] = dependencies
        return response

    monkeypatch.setattr(
        leader_full_flow_module,
        "data_dir_from_env",
        lambda: Path("test-data"),
    )
    monkeypatch.setattr(
        leader_full_flow_module,
        "load_real_data_bundle",
        lambda _data_dir: SimpleNamespace(node_registry=object()),
    )
    monkeypatch.setattr(
        leader_full_flow_module,
        "plan_full_flow",
        fake_plan_full_flow,
    )
    monkeypatch.setattr(
        leader_full_flow_module.TencentMapDrivingRouteProvider,
        "from_env",
        lambda: object(),
    )
    monkeypatch.setattr(
        leader_full_flow_module,
        "print_full_flow_result",
        lambda result: captured.setdefault("printed", result),
    )

    leader_full_flow_main(
        [
            "--origin",
            "北良港",
            "--destination",
            "客户工厂B",
            "--south-port",
            "钦州港",
            "--region",
            "广东",
        ]
    )

    request = captured["request"]
    assert isinstance(request, RoutePlanningRequest)
    assert request.origin == "北良港"
    assert request.destination == "客户工厂B"
    assert request.south_port == "钦州港"
    assert request.region == "广东"
    assert captured["dependencies"]["bundle"].node_registry is not None
    assert captured["printed"] is response


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
    assert "总费用：94800 元；总时间：169.57 小时" in output
    assert "费用=63200元；时间=1.57小时" in output
    assert "在本次候选范围和当前真实散船干线参数下" in output
    assert "两项目标仍由系统独立搜索" in output


def test_full_flow_adds_minjiang_barge_and_inland_truck_transfer_path():
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle_with_minjiang_transfer(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
        inland_waterway_provider=make_test_barge_provider(),
        inland_waterway_source="test_barge_rate+time",
        selected_south_port="军航码头",
    )

    assert result.graph_edge_count == 4
    assert result.trunk_edge_count == 1
    assert result.truck_edge_count == 2
    assert result.barge_edge_count == 1
    assert result.south_to_customer_options_by_port[make_node_id("军航码头")] == (
        "汽运",
        "驳船经南平港中转",
    )
    assert [port.name for port in result.intermediate_ports] == ["南平港"]
    assert result.node_names[make_node_id("南平港")] == "南平港"
    assert any(
        segment.transport_mode == "驳船"
        for segment in result.recommendations.lowest_cost.segments
    )


def test_full_flow_adds_exact_od_direct_barge_delivery():
    bundle = make_bundle()
    south_port = next(node for node in bundle.nodes if node.name == "钦州港")
    customer = next(node for node in bundle.nodes if node.name == "客户工厂B")
    provider = ExactOdInlandWaterwayBargeProvider(
        port_capabilities=(
            make_exact_capability(
                south_port,
                region_code="test_delta",
                infrastructure_type="sea_river_integrated_port",
                is_transfer_port=False,
                can_receive_bulk_shipping=True,
            ),
            make_exact_capability(
                customer,
                region_code="test_delta",
                infrastructure_type="customer_barge_receiver",
                is_transfer_port=False,
                can_receive_bulk_shipping=False,
            ),
        ),
        exact_od_rates=(
            make_exact_barge_rate(
                south_port,
                customer,
                price=Decimal("1"),
                row=20,
            ),
        ),
        time_records=(
            InlandWaterwayTimeRecord(
                origin_region_code="test_delta",
                destination_region_code="test_delta",
                duration_value=Decimal("1"),
                duration_unit="小时",
                time_scope="complete_segment",
                bidirectional=True,
                source_type="real_data",
                source="test_exact_time",
                rule_id="test_exact_time",
                rule_version="1.0",
            ),
        ),
    )

    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=bundle,
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=1,
        bulk_workbook=make_bulk_workbook(),
        inland_waterway_provider=provider,
        inland_waterway_source="test_exact_od",
    )

    assert result.barge_edge_count == 1
    assert result.south_to_customer_options_by_port[south_port.node_id] == (
        "汽运",
        "驳船直达客户",
    )
    assert any(
        segment.transport_mode == "驳船"
        and segment.edge_role == "delivery"
        for segment in result.recommendations.lowest_cost.segments
    )
    barge_traces = [
        trace
        for edge_id, trace in result.edge_sources.items()
        if any(
            segment.edge_key == edge_id and segment.transport_mode == "驳船"
            for segment in result.recommendations.lowest_cost.segments
        )
    ]
    assert barge_traces
    assert barge_traces[0].labels == (
        SOURCE_REAL_DATA,
        SOURCE_CONFIRMED_TIME,
    )


def test_full_flow_skips_unusable_near_transfers_and_keeps_farther_valid_path():
    bundle = make_bundle()
    south_port = next(node for node in bundle.nodes if node.name == "钦州港")
    transfers = [
        NodeRecord(make_node_id(f"测试中转港{index}"), f"测试中转港{index}", 117.2 + index * 0.01, 24.2)
        for index in range(1, 5)
    ]
    bundle = RealDataBundle(
        data_dir=bundle.data_dir,
        freight_rates=bundle.freight_rates,
        nodes=[*bundle.nodes, *transfers],
        additional_fees=bundle.additional_fees,
    )
    exact_rates = []
    row = 30
    for transfer in transfers[:3]:
        exact_rates.extend(
            (
                make_exact_barge_rate(
                    south_port,
                    transfer,
                    price=Decimal("1"),
                    row=row,
                ),
                make_exact_barge_rate(
                    south_port,
                    transfer,
                    price=Decimal("2"),
                    row=row + 1,
                ),
            )
        )
        row += 2
    exact_rates.append(
        make_exact_barge_rate(
            south_port,
            transfers[3],
            price=Decimal("1"),
            row=row,
        )
    )
    provider = ExactOdInlandWaterwayBargeProvider(
        port_capabilities=(
            make_exact_capability(
                south_port,
                region_code="test_delta",
                infrastructure_type="sea_river_integrated_port",
                is_transfer_port=False,
                can_receive_bulk_shipping=True,
            ),
            *(
                make_exact_capability(
                    transfer,
                    region_code="test_inland",
                    infrastructure_type="inland_port",
                    is_transfer_port=True,
                    can_receive_bulk_shipping=False,
                )
                for transfer in transfers
            ),
        ),
        exact_od_rates=tuple(exact_rates),
        time_records=(
            InlandWaterwayTimeRecord(
                origin_region_code="test_delta",
                destination_region_code="test_inland",
                duration_value=Decimal("1"),
                duration_unit="小时",
                time_scope="complete_segment",
                bidirectional=True,
                source_type="real_data",
                source="test_exact_time",
                rule_id="test_exact_time",
                rule_version="1.0",
            ),
        ),
    )

    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=bundle,
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        candidate_limit=1,
        bulk_workbook=make_bulk_workbook(),
        inland_waterway_provider=provider,
        inland_waterway_source="test_exact_od",
    )

    assert result.barge_edge_count == 1
    assert (
        "驳船经测试中转港4中转"
        in result.south_to_customer_options_by_port[south_port.node_id]
    )
    assert sum("冲突报价" in warning for warning in result.warnings) == 3
    assert any(
        port.node_id == transfers[3].node_id
        for port in result.intermediate_ports
    )
    for segment in result.recommendations.lowest_cost.segments:
        if segment.transport_mode == "散船":
            assert (segment.transport_stage, segment.edge_role) == (
                "north_to_south",
                "trunk",
            )
            assert segment.time_scope == "complete_segment"
        elif segment.transport_mode == "驳船":
            assert (segment.transport_stage, segment.edge_role) == (
                "south_to_customer",
                "transfer",
            )
            assert segment.time_scope == "complete_segment"
        elif segment.transport_mode == "汽运":
            assert (segment.transport_stage, segment.edge_role) == (
                "south_to_customer",
                "delivery",
            )
            assert segment.time_scope == "road_driving"


def test_full_flow_uses_provider_declared_transfer_port_instead_of_nanping_constant():
    transfer_name = "测试内河中转港"
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle_with_transfer(transfer_name),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
        inland_waterway_provider=make_test_barge_provider(
            transfer_name=transfer_name,
            region_code="test_inland_corridor",
        ),
        inland_waterway_source="test_generic_barge_rate+time",
        selected_south_port="军航码头",
    )

    assert [port.name for port in result.intermediate_ports] == [transfer_name]
    assert result.south_to_customer_options_by_port[make_node_id("军航码头")] == (
        "汽运",
        f"驳船经{transfer_name}中转",
    )
    assert any(
        segment.to_node_id == make_node_id(transfer_name)
        and segment.transport_mode == "驳船"
        and segment.edge_role == "transfer"
        for segment in result.recommendations.lowest_cost.segments
    )


def test_full_flow_warns_when_provider_endpoint_is_not_registered():
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle_with_minjiang_transfer(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
        inland_waterway_provider=UnregisteredEndpointProvider(),
        inland_waterway_source="test_unregistered_endpoint",
        selected_south_port="军航码头",
    )

    assert result.barge_edge_count == 0
    assert any(
        "未解析到唯一标准节点" in warning
        and "测试未注册中转港" in warning
        for warning in result.warnings
    )


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


def test_user_selected_south_port_bypasses_automatic_candidate_ranking():
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle(),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
        selected_south_port="漳州港",
    )

    assert result.selected_south_port == "漳州港"
    assert [port.name for port in result.candidate_ports] == ["漳州港"]


def test_user_selected_south_port_must_be_registered():
    with pytest.raises(FullFlowDemoError, match="尚未注册为标准节点"):
        build_full_flow_demo(
            "北港A",
            "客户工厂B",
            bundle=make_bundle(),
            coordinate_provider=FakeCoordinateProvider(),
            road_route_provider=FakeRoadRouteProvider(),
            bulk_workbook=make_bulk_workbook(),
            selected_south_port="不存在的南港",
        )


def test_user_selected_south_port_rejects_confirmed_customer_facility_role():
    with pytest.raises(FullFlowDemoError, match="属于客户工厂/仓库"):
        build_full_flow_demo(
            "北港A",
            "客户工厂B",
            bundle=make_bundle(),
            coordinate_provider=FakeCoordinateProvider(),
            road_route_provider=FakeRoadRouteProvider(),
            bulk_workbook=make_bulk_workbook(),
            selected_south_port="测试饲料有限公司",
        )


def test_user_selected_south_port_rejects_confirmed_inland_port():
    with pytest.raises(FullFlowDemoError, match="已确认为内河码头"):
        build_full_flow_demo(
            "北港A",
            "客户工厂B",
            bundle=make_bundle_with_inland_port(),
            coordinate_provider=FakeCoordinateProvider(),
            road_route_provider=FakeRoadRouteProvider(),
            bulk_workbook=make_bulk_workbook(),
            selected_south_port="清远清新码头",
        )


def test_user_selected_unmarked_port_uses_bulk_freight_origin_evidence():
    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=make_bundle_with_port_origin_rate(
            "广州新港",
            "散粮",
            transport_mode="驳船",
        ),
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
        selected_south_port="广州新港",
    )

    assert result.selected_south_port == "广州新港"
    assert [port.name for port in result.candidate_ports] == ["广州新港"]


def test_user_selected_south_port_rejects_confirmed_container_only_port_for_bulk():
    with pytest.raises(FullFlowDemoError, match="仅确认集装箱"):
        build_full_flow_demo(
            "北港A",
            "客户工厂B",
            bundle=make_bundle_with_named_port("福州马尾港"),
            coordinate_provider=FakeCoordinateProvider(),
            road_route_provider=FakeRoadRouteProvider(),
            bulk_workbook=make_bulk_workbook(),
            selected_south_port="福州马尾港",
        )


def test_user_selected_south_port_rejects_container_only_origin_evidence():
    with pytest.raises(FullFlowDemoError, match="没有适用的散粮始发运价证据"):
        build_full_flow_demo(
            "北港A",
            "客户工厂B",
            bundle=make_bundle_with_port_origin_rate("广州花都港", "集装箱"),
            coordinate_provider=FakeCoordinateProvider(),
            road_route_provider=FakeRoadRouteProvider(),
            bulk_workbook=make_bulk_workbook(),
            selected_south_port="广州花都港",
        )


def test_exact_customer_rate_does_not_promote_customer_company_to_south_port():
    bundle = make_bundle()
    customer_company = next(
        node for node in bundle.nodes if node.name == "测试饲料有限公司"
    )
    destination = next(node for node in bundle.nodes if node.name == "客户工厂B")
    company_rate = create_freight_rate(
        origin_name=customer_company.name,
        destination_name=destination.name,
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price="18",
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="真实维护运价",
        maintained_at="2026-07-01",
        from_node_id=customer_company.node_id,
        to_node_id=destination.node_id,
        source_file="运价表.json",
        source_row_number=3,
    )
    bundle = RealDataBundle(
        data_dir=bundle.data_dir,
        freight_rates=[*bundle.freight_rates, company_rate],
        nodes=bundle.nodes,
        additional_fees=bundle.additional_fees,
    )

    result = build_full_flow_demo(
        "北港A",
        "客户工厂B",
        bundle=bundle,
        coordinate_provider=FakeCoordinateProvider(),
        road_route_provider=FakeRoadRouteProvider(),
        bulk_workbook=make_bulk_workbook(),
    )

    assert "测试饲料有限公司" not in {
        port.name for port in result.candidate_ports
    }
    company_decision = next(
        decision
        for decision in result.candidate_decisions
        if decision.name == "测试饲料有限公司"
    )
    assert company_decision.status == "excluded"
    assert company_decision.stage == "identity"
    assert "不是港口/码头" in company_decision.reason


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
    assert result.recommendations.lowest_cost.total_cost_yuan == Decimal("120080")
    trunk_segment = result.recommendations.lowest_cost.segments[0]
    assert trunk_segment.cost_yuan == Decimal("56880")
    assert [component.component_type for component in trunk_segment.cost_components] == [
        "bulk_shipping_freight",
        "south_port_operation_fee",
    ]

    print_full_flow_result(result)
    output = capsys.readouterr().out
    assert "南港码头作业费表=test_fee_table；已计入散船干线边=1 条" in output
    assert "散船干线：北港A -> 钦州港；56880元" in output
    assert "散船运费：31600元" in output
    assert "码头作业费：25280元" in output
    assert "已计入合计：120080元" in output


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
    assert result.recommendations.lowest_cost.total_cost_yuan == Decimal("94800")
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
            polyline_points=_test_road_polyline(request),
        )


class UnregisteredEndpointProvider:
    def list_destination_candidates(self, **_kwargs):
        return (
            InlandWaterwayEndpointCandidate(
                node_id="node-unregistered-transfer",
                canonical_name="测试未注册中转港",
                source="test_capability",
            ),
        )

    def build_barge_edge(self, **_kwargs):
        raise AssertionError("未注册候选端点不应进入驳船构边")


class FractionalRoadRouteProvider:
    def get_route(self, request) -> RoadRouteResult:
        return RoadRouteResult(
            status="resolved",
            distance_km=Decimal("20"),
            duration_hours=Decimal("1.5666666667"),
            source="tencent_map_driving_route",
            message="测试驾车路线已解析。",
            polyline_points=_test_road_polyline(request),
        )


def _test_road_polyline(request) -> tuple[GeoPoint, ...]:
    midpoint = GeoPoint(
        longitude=(request.origin.longitude + request.destination.longitude)
        / Decimal("2"),
        latitude=(request.origin.latitude + request.destination.latitude)
        / Decimal("2"),
    )
    return (request.origin, midpoint, request.destination)


def make_bundle() -> RealDataBundle:
    north_port = NodeRecord(make_node_id("北港A"), "北港A", 116.0, 38.0)
    south_port_1 = NodeRecord(make_node_id("钦州港"), "钦州港", 117.0, 24.0)
    south_port_2 = NodeRecord(make_node_id("漳州港"), "漳州港", 118.0, 24.0)
    destination = NodeRecord(make_node_id("客户工厂B"), "客户工厂B", 117.2, 24.2)
    other_factory = NodeRecord(make_node_id("其他工厂"), "其他工厂", 118.2, 24.2)
    customer_company = NodeRecord(
        make_node_id("测试饲料有限公司"),
        "测试饲料有限公司",
        117.4,
        24.4,
    )
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
        nodes=[
            north_port,
            south_port_1,
            south_port_2,
            destination,
            other_factory,
            customer_company,
        ],
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


def make_bundle_with_inland_port() -> RealDataBundle:
    return make_bundle_with_named_port("清远清新码头")


def make_bundle_with_minjiang_transfer() -> RealDataBundle:
    return make_bundle_with_transfer("南平港")


def make_bundle_with_transfer(transfer_name: str) -> RealDataBundle:
    bundle = make_bundle()
    military = NodeRecord(
        make_node_id("军航码头"),
        "军航码头",
        119.511455860655,
        26.056622741731,
    )
    transfer = NodeRecord(
        make_node_id(transfer_name),
        transfer_name,
        118.253608691065,
        26.550324144747,
    )
    destination = next(node for node in bundle.nodes if node.name == "客户工厂B")
    other_factory = next(node for node in bundle.nodes if node.name == "其他工厂")
    military_candidate_rate = create_freight_rate(
        origin_name=military.name,
        destination_name=other_factory.name,
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price="18",
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="真实维护运价",
        maintained_at="2026-07-01",
        from_node_id=military.node_id,
        to_node_id=other_factory.node_id,
        source_file="运价表.json",
        source_row_number=3,
    )
    transfer_customer_rate = create_freight_rate(
        origin_name=transfer.name,
        destination_name=destination.name,
        transport_mode="汽运",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price="1",
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="真实维护运价",
        maintained_at="2026-07-01",
        from_node_id=transfer.node_id,
        to_node_id=destination.node_id,
        source_file="运价表.json",
        source_row_number=4,
    )
    return RealDataBundle(
        data_dir=bundle.data_dir,
        freight_rates=[
            *bundle.freight_rates,
            military_candidate_rate,
            transfer_customer_rate,
        ],
        nodes=[*bundle.nodes, military, transfer],
        additional_fees=bundle.additional_fees,
    )


def make_bundle_with_named_port(name: str) -> RealDataBundle:
    bundle = make_bundle()
    port = NodeRecord(
        make_node_id(name),
        name,
        113.1,
        23.6,
    )
    return RealDataBundle(
        data_dir=bundle.data_dir,
        freight_rates=bundle.freight_rates,
        nodes=[*bundle.nodes, port],
        additional_fees=bundle.additional_fees,
    )


def make_bundle_with_port_origin_rate(
    name: str,
    package_type: str,
    *,
    transport_mode: str = "汽运",
) -> RealDataBundle:
    bundle = make_bundle_with_named_port(name)
    port = next(node for node in bundle.nodes if node.name == name)
    other_factory = next(node for node in bundle.nodes if node.name == "其他工厂")
    rate = create_freight_rate(
        origin_name=port.name,
        destination_name=other_factory.name,
        transport_mode=transport_mode,
        package_type=package_type,
        commodity_scope="玉米、小麦",
        raw_price="18",
        raw_price_unit="元/吨" if package_type == "散粮" else "元/箱",
        price_type="unit_price",
        price_source="真实维护运价",
        maintained_at="2026-07-01",
        from_node_id=port.node_id,
        to_node_id=other_factory.node_id,
        source_file="运价表.json",
        source_row_number=5,
    )
    return RealDataBundle(
        data_dir=bundle.data_dir,
        freight_rates=[*bundle.freight_rates, rate],
        nodes=bundle.nodes,
        additional_fees=bundle.additional_fees,
    )


def make_exact_capability(
    node: NodeRecord,
    *,
    region_code: str,
    infrastructure_type: str,
    is_transfer_port: bool,
    can_receive_bulk_shipping: bool,
) -> PortCapabilityRecord:
    return PortCapabilityRecord(
        node_id=node.node_id,
        canonical_name=node.name,
        region_code=region_code,
        can_handle_barge=True,
        supported_package_types=("散粮",),
        supported_commodities=("玉米", "小麦"),
        source=f"test_capability:{node.name}",
        infrastructure_type=infrastructure_type,
        can_receive_bulk_shipping=can_receive_bulk_shipping,
        is_transfer_port=is_transfer_port,
        supported_transport_modes=("驳船",),
        confirmation_status="confirmed",
    )


def make_exact_barge_rate(
    origin: NodeRecord,
    destination: NodeRecord,
    *,
    price: Decimal,
    row: int,
):
    return create_freight_rate(
        origin_name=origin.name,
        destination_name=destination.name,
        transport_mode="驳船",
        package_type="散粮",
        commodity_scope="玉米、小麦",
        raw_price=price,
        raw_price_unit="元/吨",
        price_type="unit_price",
        price_source="测试精确OD驳船运价",
        maintained_at=date(2026, 7, 31),
        from_node_id=origin.node_id,
        to_node_id=destination.node_id,
        source_file="运价表.json",
        source_row_number=row,
    )


def make_bulk_workbook() -> BulkShippingWorkbook:
    return BulkShippingWorkbook(
        (
            BulkRateColumn(
                destination_label="珠三角",
                vessel_type="2-3万吨",
                rate_yuan_per_ton=Decimal("30"),
                cell_ref="C9",
                latest_date_label="7/6 周一",
                workbook_path="test-data/散船运价表.xlsx",
                scope="project_scope_confirmed",
            ),
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
            BulkRateColumn(
                destination_label="马尾",
                vessel_type="1万吨",
                rate_yuan_per_ton=Decimal("20"),
                cell_ref="M9",
                latest_date_label="7/6 周一",
                workbook_path="test-data/散船运价表.xlsx",
                scope="project_scope_confirmed",
            ),
        )
    )


def make_test_barge_provider(
    *,
    transfer_name: str = "南平港",
    region_code: str = "fujian_minjiang",
) -> TableInlandWaterwayBargeProvider:
    region = RegionMappingRecord(
        region_code=region_code,
        region_name="测试内河走廊",
        city_keywords=("军航码头", transfer_name),
        port_keywords=("军航码头", transfer_name),
        source="test_region_mapping",
    )
    capabilities = (
        PortCapabilityRecord(
            node_id=make_node_id("军航码头"),
            canonical_name="军航码头",
            region_code=region.region_code,
            can_handle_barge=True,
            supported_package_types=("散粮",),
            supported_commodities=("玉米", "小麦"),
            source="test_capability_military",
            infrastructure_type="sea_river_integrated_port",
            can_receive_bulk_shipping=True,
            is_transfer_port=True,
            supported_transport_modes=("散船", "驳船"),
            confirmation_status="confirmed",
        ),
        PortCapabilityRecord(
            node_id=make_node_id(transfer_name),
            canonical_name=transfer_name,
            region_code=region.region_code,
            can_handle_barge=True,
            supported_package_types=("散粮", "集装箱"),
            supported_commodities=("玉米", "小麦"),
            source="test_capability_nanping",
            infrastructure_type="inland_port",
            can_receive_bulk_shipping=False,
            is_transfer_port=True,
            supported_transport_modes=("驳船", "铁路"),
            confirmation_status="confirmed",
        ),
    )
    freight = InlandWaterwayFreightRecord(
        origin_region_code=region.region_code,
        destination_region_code=region.region_code,
        package_type="散粮",
        commodity_scope=("玉米", "小麦"),
        unit_price_yuan_per_ton=Decimal("1"),
        fee_unit="元/吨",
        trade_type="内贸",
        bidirectional=True,
        source_type="real_data",
        source="test_barge_rate",
        rule_id="test_barge_rate",
        rule_version="1.0",
    )
    time = InlandWaterwayTimeRecord(
        origin_region_code=region.region_code,
        destination_region_code=region.region_code,
        duration_value=Decimal("1"),
        duration_unit="小时",
        time_scope="complete_segment",
        bidirectional=True,
        source_type="real_data",
        source="test_barge_time",
        rule_id="test_barge_time",
        rule_version="1.0",
    )
    return TableInlandWaterwayBargeProvider(
        port_capabilities=capabilities,
        region_mappings=(region,),
        freight_records=(freight,),
        time_records=(time,),
    )
