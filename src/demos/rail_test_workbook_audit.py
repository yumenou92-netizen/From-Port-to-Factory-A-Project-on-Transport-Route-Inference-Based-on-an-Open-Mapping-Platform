"""Read-only admission audit for the first railway-container test workbook."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from src.data.rail_test_workbook import (
    RailTestWorkbookError,
    load_confirmed_rail_station_nodes,
    load_confirmed_rail_test_workbook,
)
from src.domain.node_registry import build_node_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="铁路集装箱首批测试路线只读准入审计")
    parser.add_argument("--workbook", required=True, help="领导提供的铁路测试工作簿路径")
    parser.add_argument("--data-dir", required=True, help="包含铁路北/南站确认主数据的本地 data_REAL 目录")
    args = parser.parse_args(argv)
    try:
        registry = build_node_registry(load_confirmed_rail_station_nodes(args.data_dir), auto_alias=False)
        result = load_confirmed_rail_test_workbook(args.workbook, node_registry=registry)
    except RailTestWorkbookError as exc:
        print(f"审计未完成：{exc}")
        return 2

    status_counts = Counter(item.status for item in result.admissions)
    print("铁路集装箱首批测试路线只读准入审计")
    print("=" * 48)
    print(f"来源：{Path(args.workbook).name}")
    print("确认口径：内贸；玉米/小麦；敞顶箱；铁路干线元/组÷2 箱/组。")
    print(f"普通北南站 real_data 记录：{result.admitted_count} 条")
    for status, count in sorted(status_counts.items()):
        print(f"{status}：{count} 条")
    print("费用组成：铁路干线费 + 上/下站装卸费（韶关市 195、其他 136.5 元/箱）+ 篷布费 250 元/箱。")
    print("堆存、延箱：当前不考虑；站转专用线：保留给后续专用线末端方案，不作为普通南站干线边。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
