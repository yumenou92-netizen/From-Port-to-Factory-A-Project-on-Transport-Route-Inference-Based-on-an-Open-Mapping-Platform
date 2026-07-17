from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from src.data.loaders import (
    DataLoadError,
    build_order_edge_candidates_for_request,
    data_dir_from_env,
    load_real_data_bundle,
)
from src.dev.runtime_env import (
    DEFAULT_ENV_FILE,
    PROJECT_ROOT,
    RuntimeEnvLoadResult,
    env_snapshot,
    load_runtime_env,
)
from src.domain.cost_rules import (
    DEFAULT_COST_RULE_ENGINE,
    CostCalculationResult,
    UNKNOWN_TRUCK_BULK_RULE,
    UNKNOWN_TRUCK_CONTAINER_RULE,
)
from src.domain.freight_rate import create_freight_rate
from src.domain.latest_rate_selector import (
    effective_maintained_at,
    select_latest_freight_rates,
)
from src.domain.route_request import PACKAGING_QUANTITY_UNITS, RouteRequest

ENV_KEYS_TO_REPORT = (
    "DATA_DIR",
    "TENCENT_MAP_API_KEY",
    "REAL_DATA_DEMO_MANUAL_TIME_HOURS",
    "REAL_DATA_DEMO_MANUAL_TIME_UNIT",
    "SMOKE_RUN_REAL_DATA",
    "SMOKE_RUN_TENCENT_PROBE",
)


@dataclass(frozen=True)
class DemoCostCase:
    label: str
    request: RouteRequest
    distance_km: Decimal | None
    result: CostCalculationResult


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()

    print_header("Developer Feature Demo")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python executable: {sys.executable}")
    print("Purpose: show current core model behavior after feature changes.")
    print("Boundary: demo output only; use src.dev.smoke_test for pass/fail checks.")

    env_result = load_runtime_env(args.env_file)
    sync_pythonpath_to_sys_path()
    print_runtime_env(env_result)
    show_cost_rule_demo()
    show_latest_rate_demo()
    show_formal_route_demo()
    show_real_data_snapshot(skip=args.skip_real_data)
    show_update_contract()

    print_header("Demo Complete")
    print(f"Elapsed seconds: {time.perf_counter() - started:.2f}")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show the current developer-facing feature demo."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Local runtime env CSV. Defaults to local_env/runtime_env.csv.",
    )
    parser.add_argument(
        "--skip-real-data",
        action="store_true",
        help="Skip optional DATA_DIR snapshot.",
    )
    return parser.parse_args(argv)


def sync_pythonpath_to_sys_path() -> None:
    for path_text in reversed(os.environ.get("PYTHONPATH", "").split(os.pathsep)):
        if path_text and path_text not in sys.path:
            sys.path.insert(0, path_text)


def print_runtime_env(result: RuntimeEnvLoadResult) -> None:
    print_header("1. Runtime Env Snapshot")
    print(f"Runtime env file: {result.env_file}")
    print(f"Using example template: {result.used_example}")
    print(f"Loaded entries: {result.loaded_count}")
    print(f"Skipped optional empty entries: {result.skipped_count}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")
    if result.missing_required:
        print("Missing required entries:")
        for entry in result.missing_required:
            print(f"  - {entry.key}: {entry.message}")
    print("Selected environment values:")
    for key, value in env_snapshot(ENV_KEYS_TO_REPORT).items():
        print(f"  - {key}: {value}")


def show_cost_rule_demo() -> None:
    print_header("2. Cost Rules")
    bulk_case = make_last_mile_case(
        "unknown bulk truck",
        UNKNOWN_TRUCK_BULK_RULE.rule_id,
        Decimal("126"),
    )
    container_case = make_last_mile_case(
        "unknown container truck",
        UNKNOWN_TRUCK_CONTAINER_RULE.rule_id,
        Decimal("45"),
    )
    missing_distance = DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(
        container_case.request,
        distance_km=None,
        distance_source=None,
    )

    for case in (bulk_case, container_case):
        print_cost_case(case)

    print("Missing distance guard:")
    print(f"  - rule: {missing_distance.rule_id}/{missing_distance.rule_version}")
    print(f"  - status: {missing_distance.status}")
    print(f"  - total_cost_yuan: {format_decimal(missing_distance.total_cost_yuan)}")
    print("  - expected: manual_review until geo layer supplies distance_km and source")


def make_last_mile_case(label: str, rule_id: str, distance_km: Decimal) -> DemoCostCase:
    for package_type, quantity_units in PACKAGING_QUANTITY_UNITS.items():
        for quantity_unit in sorted(quantity_units):
            try:
                request = RouteRequest(
                    quantity=Decimal("10"),
                    quantity_unit=quantity_unit,
                    package_type=package_type,
                    commodity="demo-commodity",
                )
            except Exception:
                continue
            result = DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(
                request,
                distance_km=distance_km,
                distance_source="confirmed_geo_provider",
            )
            if result.rule_id == rule_id and result.status == "valid":
                return DemoCostCase(label, request, distance_km, result)
    raise RuntimeError(f"Cannot find a valid demo request for rule {rule_id}")


def print_cost_case(case: DemoCostCase) -> None:
    unit_total = case.result.total_cost_yuan / case.request.quantity
    print(f"{case.label}:")
    print(f"  - rule: {case.result.rule_id}/{case.result.rule_version}")
    print(f"  - request quantity: {case.request.quantity} {case.request.quantity_unit}")
    print(f"  - package_type: {case.request.package_type}")
    print(f"  - distance_km: {case.distance_km}")
    print(f"  - status: {case.result.status}")
    print(f"  - unit price implied by total: {format_decimal(unit_total)}")
    print(f"  - total_cost_yuan: {format_decimal(case.result.total_cost_yuan)}")


def show_latest_rate_demo() -> None:
    print_header("3. Latest Freight Rate Selection")
    old_rate = create_freight_rate(
        origin_name="demo-origin-a",
        destination_name="demo-destination-a",
        transport_mode="truck",
        package_type="demo-package",
        commodity_scope="demo-commodity",
        raw_price=20,
        raw_price_unit="CNY/demo-unit",
        price_type="unit_price",
        price_source="demo-ledger-old",
        maintained_at=None,
    )
    latest_rate = create_freight_rate(
        origin_name="demo-origin-a",
        destination_name="demo-destination-a",
        transport_mode="truck",
        package_type="demo-package",
        commodity_scope="demo-commodity",
        raw_price=18,
        raw_price_unit="CNY/demo-unit",
        price_type="unit_price",
        price_source="demo-ledger-latest",
        maintained_at="2026-07-01",
    )
    conflict_a = create_freight_rate(
        origin_name="demo-origin-conflict",
        destination_name="demo-destination-conflict",
        transport_mode="truck",
        package_type="demo-package",
        commodity_scope="demo-commodity",
        raw_price=21,
        raw_price_unit="CNY/demo-unit",
        price_type="unit_price",
        price_source="demo-ledger-a",
        maintained_at="2026-07-02",
    )
    conflict_b = create_freight_rate(
        origin_name="demo-origin-conflict",
        destination_name="demo-destination-conflict",
        transport_mode="truck",
        package_type="demo-package",
        commodity_scope="demo-commodity",
        raw_price=22,
        raw_price_unit="CNY/demo-unit",
        price_type="unit_price",
        price_source="demo-ledger-b",
        maintained_at="2026-07-02",
    )

    selection = select_latest_freight_rates((old_rate, latest_rate, conflict_a, conflict_b))
    print(f"Input rates: 4")
    print(f"Selected rates: {len(selection.selected_rates)}")
    print(f"Review issues: {len(selection.review_issues)}")
    print(f"Superseded rate count: {selection.superseded_rate_count}")
    print(f"Defaulted maintenance date count: {selection.defaulted_date_count}")
    for rate in selection.selected_rates:
        print(
            "  - selected:"
            f" route=({rate.origin_name}->{rate.destination_name});"
            f" price={rate.raw_price};"
            f" effective_maintained_at={effective_maintained_at(rate).isoformat()}"
        )
    for issue in selection.review_issues:
        print(
            "  - review:"
            f" code={issue.code}; rate_count={len(issue.rates)};"
            " reason=same route has conflicting latest records"
        )


def show_formal_route_demo() -> None:
    from src.routing.route_result import build_route_recommendations
    from src.routing.route_search import search_cost_and_time_paths
    from src.routing.transport_graph import build_transport_multidigraph

    print_header("4. TransportEdge -> MultiDiGraph -> Route Search")
    edges = [
        make_demo_edge("edge-a-b-cheap", "node-a", "node-b", "10", "10"),
        make_demo_edge("edge-b-d-cheap", "node-b", "node-d", "10", "10"),
        make_demo_edge("edge-a-c-fast", "node-a", "node-c", "20", "2"),
        make_demo_edge("edge-c-d-fast", "node-c", "node-d", "20", "2"),
        make_demo_edge("edge-a-b-fast", "node-a", "node-b", "15", "1"),
    ]
    graph_result = build_transport_multidigraph(edges, allow_unregistered_nodes=True)
    searches = search_cost_and_time_paths(graph_result.graph, "node-a", "node-d")
    recommendations = build_route_recommendations(graph_result.graph, searches)

    print(f"Available demo edges: {len(edges)}")
    print(f"Graph nodes: {graph_result.graph.number_of_nodes()}")
    print(f"Graph added edges: {graph_result.added_edge_count}")
    print(f"Graph issues: {len(graph_result.issues)}")
    print_route_result("lowest_cost", recommendations.lowest_cost)
    print_route_result("fastest_time", recommendations.fastest_time)


def make_demo_edge(
    edge_id: str,
    start: str,
    end: str,
    cost: str,
    time_hours: str,
) -> TransportEdge:
    from src.routing.transport_edge import TransportEdge

    return TransportEdge(
        edge_id=edge_id,
        status="available",
        from_node_id=start,
        to_node_id=end,
        transport_mode="truck",
        package_type="demo-package",
        commodity="demo-commodity",
        cost_yuan=Decimal(cost),
        time_hours=Decimal(time_hours),
        raw_price=Decimal(cost),
        raw_price_unit="CNY/demo-unit",
        price_source=f"demo-source-{edge_id}",
        maintained_at=None,
        distance_km=Decimal("10"),
        distance_source="demo-distance",
        time_source="demo-manual-time",
        cost_rule_id="demo_cost_rule",
        cost_rule_version="1.0",
        calculation_detail=f"demo edge {edge_id}: fixed cost {cost}",
        data_source=f"developer_feature_demo#{edge_id}",
    )


def print_route_result(label: str, result) -> None:
    print(f"{label}:")
    print(f"  - status: {result.status}")
    print(f"  - path: {' -> '.join(result.path_node_ids) if result.path_node_ids else '<none>'}")
    print(f"  - total_cost_yuan: {format_decimal(result.total_cost_yuan)}")
    print(f"  - total_time_hours: {format_decimal(result.total_time_hours)}")
    print(f"  - segment_count: {len(result.segments)}")
    for segment in result.segments:
        print(
            "    *"
            f" {segment.segment_no}: {segment.from_node_id}->{segment.to_node_id};"
            f" edge={segment.edge_key};"
            f" cost={segment.cost_yuan};"
            f" time={segment.time_hours}"
        )


def show_real_data_snapshot(*, skip: bool) -> None:
    print_header("5. Optional Real Data Snapshot")
    if skip:
        print("Skipped by --skip-real-data.")
        return
    try:
        data_dir = data_dir_from_env()
    except DataLoadError as exc:
        print(f"Skipped: {exc}")
        return

    try:
        bundle = load_real_data_bundle(data_dir)
    except DataLoadError as exc:
        print(f"Failed to load real data: {exc}")
        return

    print(f"DATA_DIR: {data_dir}")
    print(f"Freight rates: {len(bundle.freight_rates)}")
    print(f"Nodes: {len(bundle.nodes)}")
    print(f"Additional fees: {len(bundle.additional_fees)}")
    print_counter("Top transport modes", bundle.transport_modes)
    print_counter("Top packaging types", bundle.packaging_types)
    print_counter("Top fee units", bundle.fee_units)

    sample = choose_real_data_candidate_sample(bundle)
    if sample is None:
        print("Candidate build sample: skipped; no compatible sample request found.")
        return

    request, result = sample
    print("Candidate build sample:")
    print(f"  - quantity: {request.quantity} {request.quantity_unit}")
    print(f"  - package_type: {request.package_type}")
    print(f"  - commodity: {request.commodity}")
    print(f"  - candidates: {len(result.candidates)}")
    print(f"  - graph_ready_candidates: {len(result.graph_ready_candidates)}")
    print(f"  - missing_node_candidates: {result.missing_node_candidate_count}")
    print(f"  - manual_review_count: {result.manual_review_count}")
    print(f"  - superseded_rate_count: {result.superseded_rate_count}")
    print(f"  - defaulted_maintenance_date_count: {result.defaulted_maintenance_date_count}")


def choose_real_data_candidate_sample(bundle):
    fallback = None
    for rate in bundle.freight_rates:
        quantity_units = PACKAGING_QUANTITY_UNITS.get(rate.package_type)
        if not quantity_units:
            continue
        for commodity in candidate_commodities(rate.commodity_scope):
            if not rate.supports_commodity(commodity):
                continue
            for quantity_unit in sorted(quantity_units):
                try:
                    request = RouteRequest(
                        quantity=Decimal("10"),
                        quantity_unit=quantity_unit,
                        package_type=rate.package_type,
                        commodity=commodity,
                    )
                    result = build_order_edge_candidates_for_request(bundle, request)
                except Exception:
                    continue
                if result.candidates:
                    return request, result
                if fallback is None:
                    fallback = (request, result)
    return fallback


def candidate_commodities(scope: str) -> tuple[str, ...]:
    candidates = [scope.strip()]
    candidates.extend(
        part.strip() for part in re.split(r"[,，、;；|/]+", scope) if part.strip()
    )
    unique: list[str] = []
    for value in candidates:
        if value and value not in unique:
            unique.append(value)
    return tuple(unique)


def print_counter(title: str, counter) -> None:
    print(f"{title}:")
    for value, count in counter.most_common(5):
        print(f"  - {value}: {count}")


def show_update_contract() -> None:
    print_header("6. Maintenance Contract")
    print("When a core feature changes, update this file in the same commit.")
    print("Add one compact section that shows input, status, total, and review boundary.")
    print("Do not call Tencent Maps here by default; keep external API checks in smoke_test.")
    print("Do not print API keys, raw secrets, or full customer-sensitive business details.")


def format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "<none>"
    return format(value.normalize(), "f")


def print_header(title: str) -> None:
    print("")
    print("=" * 72)
    print(title)
    print("=" * 72)


if __name__ == "__main__":
    raise SystemExit(main())
