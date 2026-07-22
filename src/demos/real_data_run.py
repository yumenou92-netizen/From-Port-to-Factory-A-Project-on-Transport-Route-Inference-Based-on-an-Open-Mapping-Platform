from __future__ import annotations

import os
from pathlib import Path

from src.data.loaders import (
    DataLoadError,
    build_review_rows,
    build_order_edge_candidates_for_request,
    data_dir_from_env,
    edge_candidate_to_row,
    load_real_data_bundle,
)
from src.data.io_utils import write_result_csv
from src.domain.node_registry import analyze_freight_rate_node_coverage, build_node_registry
from src.domain.route_request import RouteRequest, validate_request_billing
from src.routing.real_data_bridge import (
    ManualTimeInput,
    build_real_candidate_route_recommendations,
    build_transport_edges_from_candidates,
)
from src.routing.route_result import route_result_to_rows


def main() -> None:
    try:
        data_dir = data_dir_from_env()
        bundle = load_real_data_bundle(data_dir)
    except DataLoadError as exc:
        raise SystemExit(f"真实数据加载失败：{exc}") from exc

    print("北港至客户工厂全链路运输路径推断原型")
    print("真实业务数据接入与正式搜索链路展示")
    print("=" * 52)
    print(f"真实数据目录：{data_dir}")
    print(f"运价记录数量：{len(bundle.freight_rates)} 条")
    print(f"标准地点坐标数量：{len(bundle.nodes)} 条")
    print(f"节点附加费用记录数量：{len(bundle.additional_fees)} 条")
    print(f"运输方式分布：{format_counter(bundle.transport_modes)}")
    print(f"费用单位分布：{format_counter(bundle.fee_units)}")
    print(f"包装方式分布：{format_counter(bundle.packaging_types)}")

    registry = bundle.node_registry or build_node_registry(bundle.nodes)
    node_report = analyze_freight_rate_node_coverage(registry, bundle.freight_rates)

    print("")
    print("一、标准节点匹配情况")
    print(f"标准节点数量：{len(registry.nodes)} 个")
    print(f"自动识别别名组：{len(registry.alias_groups)} 组")
    print(f"需人工确认别名组：{len(registry.alias_review_groups)} 组")
    print(f"坐标冲突预警：{len(registry.coordinate_conflicts)} 条")
    print(f"运价表中不同地点名称：{node_report.unique_location_names} 个")
    print(f"已匹配地点名称：{node_report.matched_location_names} 个")
    print(f"未匹配地点名称：{node_report.unmatched_location_names} 个")
    print(f"两端都已匹配节点的运价记录：{node_report.matched_rate_records} 条")

    request = RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="散粮",
        commodity="玉米",
        origin_port_id="NP_DEMO",
        south_port_id="SP_DEMO",
        customer_id="CUSTOMER_DEMO",
    )
    request_validation = validate_request_billing(request)
    result = build_order_edge_candidates_for_request(bundle, request)

    project_root = Path(__file__).resolve().parents[2]
    output_path = project_root / "output" / "real_data_edge_candidates.csv"
    review_output_path = project_root / "output" / "real_data_edge_reviews.csv"
    route_output_path = project_root / "output" / "real_data_route_recommendations.csv"
    write_result_csv([edge_candidate_to_row(candidate) for candidate in result.candidates], output_path)
    write_result_csv(build_review_rows(result, request), review_output_path)

    manual_time_input = manual_time_from_env()
    transport_edges = build_transport_edges_from_candidates(
        result.candidates,
        commodity=request.commodity,
        default_manual_time=manual_time_input,
    )
    graph_ready_edges = build_transport_edges_from_candidates(
        result.graph_ready_candidates,
        commodity=request.commodity,
        default_manual_time=manual_time_input,
    )
    available_edge_count = sum(1 for edge in transport_edges if edge.is_available)
    manual_review_edge_count = sum(1 for edge in transport_edges if edge.requires_manual_review)
    formal_route_status = "未运行"
    formal_route_note = "缺少人工确认运输时间，正式图只保留人工复核边，不执行真实路线推荐。"
    graph_added_edges = 0
    graph_excluded_edges = 0
    if manual_time_input is not None and graph_ready_edges:
        start_node_id = graph_ready_edges[0].from_node_id
        end_node_id = graph_ready_edges[0].to_node_id
        if start_node_id and end_node_id:
            formal_route = build_real_candidate_route_recommendations(
                result.graph_ready_candidates,
                commodity=request.commodity,
                node_registry=registry,
                start_node_id=start_node_id,
                end_node_id=end_node_id,
                default_manual_time=manual_time_input,
            )
            graph_added_edges = formal_route.graph_result.added_edge_count
            graph_excluded_edges = formal_route.graph_result.excluded_edge_count
            if formal_route.recommendations is not None:
                route_rows = (
                    route_result_to_rows(formal_route.recommendations.lowest_cost)
                    + route_result_to_rows(formal_route.recommendations.fastest_time)
                )
                write_result_csv(route_rows, route_output_path)
                formal_route_status = (
                    f"成本最低={_display_status(formal_route.recommendations.lowest_cost.status)}"
                    f"（{formal_route.recommendations.lowest_cost.status}）；"
                    f"时效最优={_display_status(formal_route.recommendations.fastest_time.status)}"
                    f"（{formal_route.recommendations.fastest_time.status}）"
                )
                formal_route_note = (
                    "已使用本地演示人工时间将具备双端节点的真实候选接入正式图搜索；"
                    "该时间仅用于本地链路验证，不代表真实业务时效。"
                )

    print("")
    print("二、示例订单计费候选")
    print(
        f"示例订单：{request.quantity}{request.quantity_unit}，"
        f"包装方式={request.package_type}，品种={request.commodity}"
    )
    print(f"订单校验状态：{_display_status(request_validation.status)}（{request_validation.status}）")
    print(f"已完成计费的候选运输段：{len(result.candidates)} 条")
    print(f"两端节点齐全、可进入正式图的候选：{len(result.graph_ready_candidates)} 条")
    print(f"缺少标准节点 ID 的候选：{result.missing_node_candidate_count} 条")
    print(f"需要人工复核的记录：{result.manual_review_count} 条")
    print(f"已排除的历史旧运价：{result.superseded_rate_count} 条")
    print(f"识别出的同内容重复最新运价：{result.duplicate_rate_count} 条")
    print(f"缺维护日期并按系统基准日期参与筛选：{result.defaulted_maintenance_date_count} 条")
    print(f"因包装方式不匹配跳过：{result.skipped_packaging} 条")
    print(f"因品种不匹配跳过：{result.skipped_product} 条")
    print(f"本地候选运输段输出：{output_path}")
    print(f"本地人工复核输出：{review_output_path}")
    print("")
    print("三、正式 TransportEdge 与路径搜索链路")
    print(f"已构建标准运输边：{len(transport_edges)} 条")
    print(f"可进入正式搜索图的运输边：{available_edge_count} 条")
    print(f"仍需人工复核的运输边：{manual_review_edge_count} 条")
    print(f"正式图新增边数：{graph_added_edges} 条")
    print(f"正式图排除边数：{graph_excluded_edges} 条")
    print(f"正式路线搜索状态：{formal_route_status}")
    if formal_route_status != "未运行":
        print(f"本地路线推荐输出：{route_output_path}")
    print(f"正式链路说明：{formal_route_note}")
    print("")
    print("四、当前边界")
    print("真实数据已经可以读取、计费、转换为 TransportEdge，并在显式提供人工运输时间时接入正式图搜索。")
    print("客户自有码头字段、北港至南港船运数据、AdditionalFee 归属段仍未接入，展示时不能表述为完整生产系统。")


def format_counter(counter) -> str:
    return "; ".join(f"{key}:{value}" for key, value in counter.most_common()) or "-"


def manual_time_from_env() -> ManualTimeInput | None:
    value = os.environ.get("REAL_DATA_DEMO_MANUAL_TIME_HOURS")
    if value is None or not value.strip():
        return None
    return ManualTimeInput(
        duration_value=value,
        duration_unit=os.environ.get("REAL_DATA_DEMO_MANUAL_TIME_UNIT", "小时"),
        source="REAL_DATA_DEMO_MANUAL_TIME_HOURS",
    )


def _display_status(status: str) -> str:
    return {
        "valid": "有效",
        "resolved": "已解析",
        "manual_review": "需人工复核",
        "no_path": "无可用路径",
        "not_available": "不可用",
        "failed": "失败",
    }.get(status, status)


if __name__ == "__main__":
    main()
