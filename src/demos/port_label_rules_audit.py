from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Sequence

from src.data.loaders import data_dir_from_env, load_real_data_bundle
from src.data.name_dictionary import find_name_dictionary_file, load_name_dictionary_entries
from src.data.port_label_rules import (
    PortLabelRuleError,
    PortLabelTencentReview,
    collect_port_label_tencent_locations,
    find_optional_port_label_rule_file,
    load_port_label_rule_bundle,
    port_label_tencent_review_to_row,
    query_port_label_tencent_candidates,
)
from src.dev.runtime_env import DEFAULT_ENV_FILE, load_runtime_env
from src.geo.tencent_map_provider import TencentMapCoordinateProvider


DEFAULT_OUTPUT_DIR = Path("output")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else data_dir_from_env()
    bundle = load_real_data_bundle(data_dir)
    source_file = Path(args.source) if args.source else find_optional_port_label_rule_file(data_dir)
    if source_file is None:
        raise SystemExit("未找到 部分码头标签.json。")
    dictionary_path = find_name_dictionary_file(data_dir)
    dictionary_entries = (
        load_name_dictionary_entries(dictionary_path)
        if dictionary_path is not None
        else ()
    )

    try:
        result = load_port_label_rule_bundle(
            source_file,
            registry=bundle.node_registry,
            dictionary_entries=dictionary_entries,
        )
    except PortLabelRuleError as exc:
        raise SystemExit(f"部分码头标签审计失败：{exc}") from exc

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "port_label_rules_review.csv"
    json_path = output_dir / "port_label_rules_review.json"
    tencent_pending_path = output_dir / "port_label_tencent_pending.jsonl"
    tencent_review_path = output_dir / "port_label_tencent_review.jsonl"
    write_csv(csv_path, result.audit_rows)
    tencent_locations = collect_port_label_tencent_locations(result.audit_rows)
    pending_reviews = tuple(
        PortLabelTencentReview(location=location, resolutions=())
        for location in tencent_locations
    )
    write_tencent_jsonl(tencent_pending_path, pending_reviews)
    if args.query_tencent:
        load_runtime_env(DEFAULT_ENV_FILE)
        provider = TencentMapCoordinateProvider.from_env(region=args.region, page_size=5)
        tencent_reviews = query_port_label_tencent_candidates(tencent_locations, provider)
        write_tencent_jsonl(tencent_review_path, tencent_reviews)
    json_path.write_text(
        json.dumps(
            {
                "source_file": str(result.path),
                "name_dictionary_file": str(dictionary_path) if dictionary_path else "",
                "version": result.version,
                "description": result.description,
                "last_updated": result.last_updated,
                "expanded_rate_count": len(result.rates),
                "review_row_count": sum(1 for row in result.audit_rows if row["conversion_status"] != "converted"),
                "direct_node_match_count": sum(
                    1 for row in result.audit_rows if row["registry_match_status"] == "direct"
                ),
                "dictionary_node_match_count": sum(
                    1
                    for row in result.audit_rows
                    if row["registry_match_status"] == "dictionary_suffix_unique"
                ),
                "unmatched_node_count": sum(1 for row in result.audit_rows if not row["node_id"]),
                "unmatched_unique_name_count": len(tencent_locations),
                "tencent_query_executed": bool(args.query_tencent),
                "rows": list(result.audit_rows),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"部分码头标签规则：{len(result.rates)} 条展开费率")
    print(f"需人工复核规则行：{sum(1 for row in result.audit_rows if row['conversion_status'] != 'converted')} 条")
    print(f"节点直接命中：{sum(1 for row in result.audit_rows if row['registry_match_status'] == 'direct')} 条")
    print(
        "名称字典唯一后缀匹配："
        f"{sum(1 for row in result.audit_rows if row['registry_match_status'] == 'dictionary_suffix_unique')} 条"
    )
    print(f"节点未命中：{sum(1 for row in result.audit_rows if not row['node_id'])} 条")
    print(f"待 Tencent 复核的去重名称：{len(tencent_locations)} 个")
    print(f"名称字典：{dictionary_path if dictionary_path else '未找到'}")
    print(f"Tencent 地点检索：{'已执行，仅输出候选' if args.query_tencent else '未执行'}")
    print(f"人工复核 CSV：{csv_path}")
    print(f"人工复核 JSON：{json_path}")
    print(f"Tencent 待查询 JSONL：{tencent_pending_path}")
    if args.query_tencent:
        print(f"Tencent 候选 JSONL：{tencent_review_path}")
    else:
        print("Tencent 候选 JSONL：未生成；已有候选文件不会被本次只读审计覆盖")
    print("本工具不会写入 港口能力表.csv、南港码头作业费.csv 或地点经纬度.json。")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读审计 部分码头标签.json。")
    parser.add_argument("--data-dir", help="可选：显式指定 DATA_DIR；未提供时读取环境变量 DATA_DIR。")
    parser.add_argument("--source", help="可选：显式指定 部分码头标签.json 路径。")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录，默认 output。")
    parser.add_argument("--query-tencent", action="store_true", help="调用 Tencent 地点搜索，仅输出候选。")
    parser.add_argument("--region", default="全国", help="Tencent 地点搜索区域，默认全国。")
    return parser.parse_args(list(argv) if argv is not None else None)


def write_csv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    fieldnames = (
        "rule_no",
        "port_name",
        "node_id",
        "registry_match_status",
        "canonical_name",
        "dictionary_status",
        "dictionary_rows",
        "dictionary_candidates",
        "tencent_query_names",
        "trade_type",
        "package_type",
        "fee_type",
        "source_fee_type",
        "unit_price",
        "fee_unit",
        "commodity_scope",
        "source",
        "conversion_status",
        "issue",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_tencent_jsonl(
    path: Path,
    reviews: Sequence[PortLabelTencentReview],
) -> None:
    text = "\n".join(
        json.dumps(port_label_tencent_review_to_row(review), ensure_ascii=False, default=str)
        for review in reviews
    )
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
