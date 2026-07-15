from __future__ import annotations

from data_loaders import (
    DataLoadError,
    build_order_edge_candidates_for_request,
    data_dir_from_env,
    load_real_data_bundle,
)
from route_request import RouteRequest


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("真实业务数据接入状态展示")
    print("=" * 52)

    try:
        data_dir = data_dir_from_env()
        bundle = load_real_data_bundle(data_dir)
    except DataLoadError as exc:
        raise SystemExit(f"真实业务数据加载失败: {exc}") from exc

    print("一、当前已接入的数据")
    print(f"运价记录: {len(bundle.freight_rates)} 条")
    print(f"地点坐标: {len(bundle.nodes)} 条")
    print(f"节点附加费用: {len(bundle.additional_fees)} 条")
    print(f"运输方式: {format_counter(bundle.transport_modes)}")
    print(f"费用单位: {format_counter(bundle.fee_units)}")

    print("\n二、系统如何使用这些数据")
    print("运价表用于生成候选运输边，地点经纬度用于生成节点坐标，其他费用表用于后续补充节点作业费用。")
    print("费用进入路径搜索前，必须结合订单数量换算成该运输段总金额，不能直接相加原始单价。")

    request = RouteRequest(
        quantity=500,
        quantity_unit="吨",
        package_type="散粮",
        commodity="玉米",
    )
    result = build_order_edge_candidates_for_request(bundle, request)

    print("\n三、示例订单校验")
    print("示例订单: 500吨，散粮，玉米")
    print(f"已完成订单段计费的候选记录: {len(result.candidates)} 条")
    print(f"两端节点齐全、可进入后续图构建: {len(result.graph_ready_candidates)} 条")
    print(f"仍缺少节点匹配的候选记录: {result.missing_node_candidate_count} 条")
    print(f"需人工确认的计费记录: {len(result.manual_review_items)} 条")
    print(f"因包装方式不匹配跳过: {result.skipped_packaging} 条")
    print(f"因适用品种不匹配跳过: {result.skipped_product} 条")

    print("\n四、当前边界")
    print("真实运价和坐标已经可以本地读取；但客户是否有自有码头、运输时效、外部距离 API 尚未接入。")
    print("因此当前展示只说明真实数据接入和费用换算能力，不输出最终路径推荐。")


def format_counter(counter) -> str:
    return "；".join(f"{key}{value}条" for key, value in counter.most_common()) or "暂无"


if __name__ == "__main__":
    main()
