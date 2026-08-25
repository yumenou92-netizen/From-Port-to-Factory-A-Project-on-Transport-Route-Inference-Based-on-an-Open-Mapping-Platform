from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from src.data.loaders import data_dir_from_env, load_real_data_bundle
from src.data.order_graph_admission_audit import (
    DEFAULT_OUTPUT_DIR,
    build_order_graph_admission_audit,
    find_bulk_workbook,
    load_operation_fee_provider,
    write_audit_outputs,
)
from src.dev.runtime_env import load_runtime_env
from src.routing.bulk_shipping_provider import BulkShippingWorkbook


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "只读审计全部已声明订单维度下，当前南港候选在 Tencent 调用前的入图准入状态。"
        )
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bulk-workbook", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    load_runtime_env()
    bundle = load_real_data_bundle(data_dir_from_env())
    workbook_path = args.bulk_workbook or find_bulk_workbook(bundle.data_dir)
    if workbook_path is None:
        raise SystemExit("未找到散船运价表.xlsx，无法执行散船干线准入审计。")
    workbook = BulkShippingWorkbook.load(workbook_path)
    operation_fee_provider, operation_fee_source = load_operation_fee_provider(bundle)
    audit = build_order_graph_admission_audit(
        bundle,
        workbook=workbook,
        operation_fee_provider=operation_fee_provider,
    )
    paths = write_audit_outputs(audit, args.output_dir)

    print("订单参数与港口入图准入审计已完成")
    print("本工具未调用 Tencent，也未写回任何真实数据。")
    print(f"散船运价表：{workbook_path}")
    print(f"码头作业费：{operation_fee_source or '未接入'}")
    print(f"订单场景：{audit.scenario_count}")
    print(
        "受审计节点："
        f"{audit.transfer_origin_count}（北港散船候选样式 {audit.automatic_port_origin_count}；"
        f"非自动/已排除节点 {audit.conditional_origin_count}）"
    )
    print(f"人工确认去重项：{len(audit.manual_review_rows)}")
    print(f"人工确认主清单：{paths['manual_review']}")
    print(f"审计报告：{paths['markdown']}")
    print(f"逐场景端口明细：{paths['ports']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
