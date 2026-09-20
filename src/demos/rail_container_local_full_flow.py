"""Run formal railway-container planning from registered local Excel tables."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from src.application.rail_container_planning import RailContainerPlanningRequest, RailContainerPlanningService
from src.data.loaders import data_dir_from_env, load_real_data_bundle
from src.data.rail_container_data import RailContainerLocalDataError, load_rail_container_runtime_data
from src.domain.route_request import RouteRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="铁路集装箱本地正式数据全链路试算")
    parser.add_argument("--manifest", required=True, help="DATA_DIR 下本地 Excel 数据源清单 JSON")
    parser.add_argument("--data-dir", help="本地业务数据目录；默认读取 DATA_DIR")
    parser.add_argument("--north-station", required=True)
    parser.add_argument("--customer", required=True)
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--quantity", required=True, type=Decimal)
    parser.add_argument("--container-type", required=True, choices=("顶开门箱", "敞顶箱"))
    parser.add_argument("--trade-type", default="内贸", choices=("内贸", "外贸"))
    parser.add_argument("--south-station")
    args = parser.parse_args(_module_args())

    data_dir = Path(args.data_dir) if args.data_dir else data_dir_from_env()
    try:
        base_bundle = load_real_data_bundle(data_dir)
        runtime = load_rail_container_runtime_data(
            args.manifest,
            data_dir=data_dir,
            base_registry=base_bundle.node_registry,
        )
        response = RailContainerPlanningService(runtime.planning_data()).plan(
            RailContainerPlanningRequest(
                north_station_name=args.north_station,
                customer_name=args.customer,
                south_station_name=args.south_station,
                container_type=args.container_type,
                request=RouteRequest(
                    quantity=args.quantity,
                    quantity_unit="箱",
                    package_type="集装箱",
                    commodity=args.commodity,
                    trade_type=args.trade_type,
                ),
            )
        )
    except (RailContainerLocalDataError, ValueError) as exc:
        print(f"铁路集装箱试算未形成搜索图：{exc}")
        return

    print("铁路集装箱本地正式数据全链路试算")
    print("=" * 48)
    print(f"干线准入：{runtime.local_data.admitted_count}/{len(runtime.local_data.admissions)} 条")
    print(f"搜索图边数：{response.graph_edge_count}")
    for outcome in response.candidate_outcomes:
        plan = outcome.terminal_plan_type or "铁路干线"
        print(f"- {outcome.south_station_name} / {plan} / {outcome.status}：{outcome.message}")
    for label, route in (("费用最低", response.recommendations.lowest_cost), ("时间最短", response.recommendations.fastest_time)):
        if route.status != "resolved":
            print(f"{label}：{route.message}")
            continue
        print(f"{label}：总费用={route.total_cost_yuan}元；总时效={route.total_time_hours}小时")
        for segment in route.segments:
            print(f"  {segment.origin_name} -> {segment.destination_name}；{segment.transport_mode}；{segment.cost_yuan}元；{segment.time_hours}小时")


def _module_args() -> list[str]:
    args = list(sys.argv[1:])
    if args and args[0] == "rail-container-full-flow":
        return args[1:]
    return args


if __name__ == "__main__":
    main()
