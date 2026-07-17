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
        raise SystemExit(f"Real_Data_Load_Failed!: {exc}") from exc

    print("Demo_Version_of_the_Model_for_Inferring_Freight_Supply_Chain_Transport_Routes")
    print("Demo_with_REAL_Data")
    print("=" * 52)
    print(f"DATA_DIR: {data_dir}")
    print(f"Number_Of_Trans_Fee_Record: {len(bundle.freight_rates)}")
    print(f"Number_Of_Nodes_Coordinates: {len(bundle.nodes)}")
    print(f"Number of node surcharge records: {len(bundle.additional_fees)}")
    print(f"Trans_Model: {format_counter(bundle.transport_modes)}")
    print(f"Fee_Unit: {format_counter(bundle.fee_units)}")
    print(f"Packaging_model: {format_counter(bundle.packaging_types)}")

    registry = build_node_registry(bundle.nodes)
    node_report = analyze_freight_rate_node_coverage(registry, bundle.freight_rates)

    print("")
    print("Stander_Node_Structure_Preview")
    print(f"Number_of_Stander_Node: {len(registry.nodes)}")
    print(f"Auto-recognition_of_alias_groups: {len(registry.alias_groups)}")
    print(f"Manual_Confirm_alias_groups: {len(registry.alias_review_groups)}")
    print(f"Coordinate_Conflict_Warning: {len(registry.coordinate_conflicts)}")
    print(f"Unique_Location_Names_In_Freight_Rate_Table: {node_report.unique_location_names}")
    print(f"Matched_Location_Names: {node_report.matched_location_names}")
    print(f"Unmatched_Location_Names: {node_report.unmatched_location_names}")
    print(f"Freight_Rate_Records_With_Both_Endpoints_Matched: {node_report.matched_rate_records}")

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
    formal_route_status = "not_run"
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
                    f"lowest_cost={formal_route.recommendations.lowest_cost.status}; "
                    f"fastest_time={formal_route.recommendations.fastest_time.status}"
                )
                formal_route_note = (
                    "已使用本地演示人工时间将具备双端节点的真实候选接入正式图搜索；"
                    "该时间仅用于本地链路验证，不代表真实业务时效。"
                )

    print("")
    print("Order_Edge_Candidate_Preview")
    print(
        f"Order_Sample: {request.quantity}{request.quantity_unit}, "
        f"Packaging={request.package_type}, Product={request.commodity}"
    )
    print(f"Route_Request_Validation_Status: {request_validation.status}")
    print(f"Billed_Edge_Candidates: {len(result.candidates)}")
    print(f"Graph_Ready_Edge_Candidates: {len(result.graph_ready_candidates)}")
    print(f"Candidates_Missing_Node_ID: {result.missing_node_candidate_count}")
    print(f"Manual_Review_Records: {result.manual_review_count}")
    print(f"Superseded_Freight_Rates: {result.superseded_rate_count}")
    print(f"Duplicate_Latest_Rates: {result.duplicate_rate_count}")
    print(f"Defaulted_Maintenance_Dates: {result.defaulted_maintenance_date_count}")
    print(f"Skipped_For_Packaging_Mismatch: {result.skipped_packaging}")
    print(f"Skipped_For_Product_Mismatch: {result.skipped_product}")
    print(f"Local_Edge_Candidate_Preview_Output: {output_path}")
    print(f"Local_Manual_Review_Output: {review_output_path}")
    print("")
    print("Formal_Transport_Edge_Bridge")
    print(f"Transport_Edges_Built: {len(transport_edges)}")
    print(f"Available_Transport_Edges: {available_edge_count}")
    print(f"Manual_Review_Transport_Edges: {manual_review_edge_count}")
    print(f"Formal_Graph_Added_Edges: {graph_added_edges}")
    print(f"Formal_Graph_Excluded_Edges: {graph_excluded_edges}")
    print(f"Formal_Route_Status: {formal_route_status}")
    if formal_route_status != "not_run":
        print(f"Local_Route_Recommendation_Output: {route_output_path}")
    print(f"Formal_Route_Note: {formal_route_note}")
    print("")
    print("Current_Limit: Real data can be loaded, billed, converted into TransportEdge, and connected to formal graph/search only when manual shipping time is explicitly provided. Customer-owned dock fields, north-port-to-south-port shipping data, and AdditionalFee segment attribution are still not connected.")


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


if __name__ == "__main__":
    main()
