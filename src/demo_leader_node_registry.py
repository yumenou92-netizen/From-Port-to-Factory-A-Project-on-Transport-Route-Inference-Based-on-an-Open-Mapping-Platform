from __future__ import annotations

from data_loaders import DataLoadError, data_dir_from_env, load_real_data_bundle
from node_registry import analyze_freight_rate_node_coverage, build_node_registry


def main() -> None:
    print("运输路径推断demo")
    print("节点标准化展示demo")
    print("=" * 52)

    try:
        data_dir = data_dir_from_env()
        bundle = load_real_data_bundle(data_dir)
    except DataLoadError as exc:
        raise SystemExit(f"真实业务数据加载失败: {exc}") from exc

    registry = build_node_registry(bundle.nodes)
    report = analyze_freight_rate_node_coverage(registry, bundle.freight_rates)

    print("1.Node Register Preview")
    print(f"Original_Coordinates_Record: {len(bundle.nodes)} 条")
    print(f"Number_of Stander_Nodes: {len(registry.nodes)} 个")
    print(f"Auto-recognition_of_alias_groups: {len(registry.alias_groups)} 组")
    print(f"Manual_Confirm_alias_groups: {len(registry.alias_review_groups)} 组")
    print(f"Coordinate_Conflict_Warning: {len(registry.coordinate_conflicts)} 组")

    print("\n二、运价表地点匹配结果")
    print(f"运价记录: {report.total_rate_records} 条")
    print(f"始发/到达去重地点: {report.unique_location_names} 个")
    print(f"已匹配地点: {report.matched_location_names} 个")
    print(f"未匹配地点: {report.unmatched_location_names} 个")
    print(f"两端均可匹配的运价记录: {report.matched_rate_records} 条")
    print(f"存在未匹配端点的运价记录: {report.unmatched_rate_records} 条")

    print("\n三、当前边界")
    print("本模块已经把地点文本注册为标准 node_id，并对明显站点别名做识别。")
    print("坐标接近的别名会自动合并；坐标差异较大的疑似别名会进入人工确认，不直接合并。")
    print("南方港口同一物理节点的强制合并机制已预留；需要业务确认具体港口名称后再启用。")



if __name__ == "__main__":
    main()
