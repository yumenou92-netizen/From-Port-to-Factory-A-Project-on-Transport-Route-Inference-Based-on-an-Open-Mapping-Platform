from __future__ import annotations

from pathlib import Path

from data_loaders import (
    DataLoadError,
    build_order_edge_candidates,
    data_dir_from_env,
    edge_candidate_to_row,
    load_real_data_bundle,
)
from io_utils import write_result_csv
from node_registry import analyze_freight_rate_node_coverage, build_node_registry


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

    quantity = 500
    quantity_unit = "吨"
    packaging = "散粮"
    product = "玉米"
    result = build_order_edge_candidates(
        bundle,
        quantity=quantity,
        quantity_unit=quantity_unit,
        packaging=packaging,
        product=product,
    )

    project_root = Path(__file__).resolve().parents[1]
    output_path = project_root / "output" / "real_data_edge_candidates.csv"
    write_result_csv([edge_candidate_to_row(candidate) for candidate in result.candidates], output_path)

    print("")
    print("Order_Edge_Candidate_Preview")
    print(f"Order_Sample: {quantity}{quantity_unit}, Packaging={packaging}, Product={product}")
    print(f"Available_Edge_Candidates: {len(result.candidates)}")
    print(f"Skipped_For_Fee_Unit_Mismatch: {result.skipped_unit_mismatch}")
    print(f"Skipped_For_Packaging_Mismatch: {result.skipped_packaging}")
    print(f"Skipped_For_Product_Mismatch: {result.skipped_product}")
    print(f"Local_Edge_Candidate_Preview_Output: {output_path}")
    print("")
    print("Current_Limit: Real data can be loaded and converted into total cost per order segment; shipping time and customer-owned dock fields are not connected yet, so full route search is not executed yet.")


def format_counter(counter) -> str:
    return "; ".join(f"{key}:{value}" for key, value in counter.most_common()) or "-"


if __name__ == "__main__":
    main()
