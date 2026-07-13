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


def main() -> None:
    try:
        data_dir = data_dir_from_env()
        bundle = load_real_data_bundle(data_dir)
    except DataLoadError as exc:
        raise SystemExit(f"真实业务数据加载失败: {exc}") from exc

    print("北港至客户工厂全链路运输路径推断原型")
    print("开发期真实数据集成 Demo")
    print("=" * 52)
    print(f"DATA_DIR: {data_dir}")
    print(f"运价记录数: {len(bundle.freight_rates)}")
    print(f"坐标节点数: {len(bundle.nodes)}")
    print(f"节点附加费用记录数: {len(bundle.additional_fees)}")
    print(f"运输方式: {format_counter(bundle.transport_modes)}")
    print(f"费用单位: {format_counter(bundle.fee_units)}")
    print(f"包装类型: {format_counter(bundle.packaging_types)}")

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
    print("订单候选边预览")
    print(f"订单示例: {quantity}{quantity_unit}, 包装={packaging}, 品种={product}")
    print(f"可形成候选运输边: {len(result.candidates)}")
    print(f"因费用单位不匹配跳过: {result.skipped_unit_mismatch}")
    print(f"因包装方式不匹配跳过: {result.skipped_packaging}")
    print(f"因适用品种不匹配跳过: {result.skipped_product}")
    print(f"已输出本地候选边预览: {output_path}")
    print("")
    print("当前边界: 真实数据已经可读取并换算为订单段总费用；运输时效和客户自有码头字段仍未接入，因此暂不执行完整路径搜索。")


def format_counter(counter) -> str:
    return "; ".join(f"{key}:{value}" for key, value in counter.most_common()) or "-"


if __name__ == "__main__":
    main()
