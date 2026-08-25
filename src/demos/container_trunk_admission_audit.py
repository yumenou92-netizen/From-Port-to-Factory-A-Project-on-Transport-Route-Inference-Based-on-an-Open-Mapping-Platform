from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from src.data.container_trunk_admission_audit import (
    load_container_trunk_admission_audit,
    write_container_trunk_audit_outputs,
)
from src.data.loaders import data_dir_from_env, load_real_data_bundle


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读审计集装箱船北港—南港数据接口与南港准入状态。"
    )
    parser.add_argument("--data-dir", type=Path, help="真实数据目录；缺省时读取 DATA_DIR。")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    data_dir = args.data_dir or data_dir_from_env()
    audit = load_container_trunk_admission_audit(load_real_data_bundle(data_dir))
    paths = write_container_trunk_audit_outputs(audit, args.output_dir)
    print("集装箱船北港—南港准入审计已完成")
    print("本工具只读，不调用 Tencent，不写回真实数据，也不生成图边。")
    print(f"运价时效源状态：{audit.rate_time_source_status}")
    print(f"已读取集装箱船记录：{audit.rate_time_record_count} 条")
    print(f"具备南港身份和集装箱能力的候选：{audit.eligible_port_count} 个")
    print(f"CSV：{paths['csv']}")
    print(f"Markdown：{paths['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
