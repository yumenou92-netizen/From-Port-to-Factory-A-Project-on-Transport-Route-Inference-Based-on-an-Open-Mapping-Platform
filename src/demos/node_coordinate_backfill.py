from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.loaders import (
    build_order_edge_candidates_for_request,
    data_dir_from_env,
    load_real_data_bundle,
)
from src.data.name_dictionary import find_name_dictionary_file, load_name_dictionary_entries
from src.data.node_coordinate_backfill import (
    CoordinateBackfillReview,
    backfill_review_to_row,
    collect_missing_node_locations,
    query_coordinate_candidates,
)
from src.dev.runtime_env import DEFAULT_ENV_FILE, load_runtime_env
from src.domain.route_request import RouteRequest
from src.geo.tencent_map_provider import TencentMapCoordinateProvider


def main() -> None:
    args = _parse_args()
    load_runtime_env(DEFAULT_ENV_FILE)
    data_dir = data_dir_from_env()
    bundle = load_real_data_bundle(data_dir)
    dictionary_path = find_name_dictionary_file(data_dir)
    dictionary_entries = load_name_dictionary_entries(dictionary_path) if dictionary_path else ()
    locations = collect_missing_node_locations(
        build_order_edge_candidates_for_request(bundle, _demo_request()).candidates,
        dictionary_entries,
    )

    reviews: tuple[CoordinateBackfillReview, ...]
    if args.query_tencent:
        provider = TencentMapCoordinateProvider.from_env(region=args.region, page_size=5)
        reviews = query_coordinate_candidates(locations, provider)
    else:
        reviews = tuple(CoordinateBackfillReview(location, ()) for location in locations)

    output_path = Path(args.output) if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(
            json.dumps(backfill_review_to_row(review), ensure_ascii=False, default=str)
            for review in reviews
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"待补坐标的去重地点：{len(locations)} 个")
    print(f"名称字典：{dictionary_path if dictionary_path else '未找到'}")
    print(f"腾讯地点检索：{'已执行，仅输出候选' if args.query_tencent else '未执行'}")
    print(f"人工复核清单：{output_path}")
    print("本工具不会写入地点经纬度.json，也不会自动注册节点或别名。")


def _demo_request() -> RouteRequest:
    return RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="散粮",
        commodity="玉米",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成缺失节点坐标补全的人工复核清单")
    parser.add_argument("--query-tencent", action="store_true", help="调用腾讯地点搜索，仅写出候选结果")
    parser.add_argument("--region", default="全国", help="腾讯地点搜索区域")
    parser.add_argument("--output", help="JSONL 输出路径；默认写入项目 output 目录")
    return parser.parse_args()


def _default_output_path() -> Path:
    return Path(__file__).resolve().parents[2] / "output" / "node_coordinate_backfill_review.jsonl"


if __name__ == "__main__":
    main()
