from __future__ import annotations

import os
import sys

from src.dev.runtime_env import DEFAULT_ENV_FILE, load_runtime_env

DEFAULT_PROBE_REGION = "北京"
DEFAULT_PROBE_ORIGIN = "北京大学"
DEFAULT_PROBE_DESTINATION = "北京站"

try:
    from .coordinate_provider import CoordinateResolution
    from .distance_provider import RoadRouteRequest
    from .tencent_map_provider import (
        TENCENT_MAP_API_KEY_ENV,
        TencentMapConfigError,
        TencentMapCoordinateProvider,
        TencentMapDrivingRouteProvider,
        make_geo_point,
    )
except ImportError:  # Support direct script execution fallback.
    from src.geo.coordinate_provider import CoordinateResolution
    from src.geo.distance_provider import RoadRouteRequest
    from src.geo.tencent_map_provider import (
        TENCENT_MAP_API_KEY_ENV,
        TencentMapConfigError,
        TencentMapCoordinateProvider,
        TencentMapDrivingRouteProvider,
        make_geo_point,
    )


def main() -> None:
    """Run a Tencent Maps coordinate and route probe with local-only settings."""
    env_result = load_runtime_env(DEFAULT_ENV_FILE)
    _sync_pythonpath_to_sys_path()
    print("腾讯地图坐标与驾车距离探针")
    print("一、本地运行环境")
    print(f"- 环境配置文件：{env_result.env_file}")
    print(f"- 是否使用示例模板：{'是' if env_result.used_example else '否'}")

    try:
        coordinate_provider = TencentMapCoordinateProvider.from_env(
            region=os.environ.get("TENCENT_MAP_PROBE_REGION", DEFAULT_PROBE_REGION),
            page_size=20,
        )
        route_provider = TencentMapDrivingRouteProvider.from_env()
    except TencentMapConfigError as exc:
        print(f"腾讯地图探针已跳过：{exc}")
        print(f"请先在本地配置 {TENCENT_MAP_API_KEY_ENV}，不要把 Key 写入代码或 Git。")
        return

    origin_name = os.environ.get("TENCENT_MAP_PROBE_ORIGIN", DEFAULT_PROBE_ORIGIN)
    destination_name = os.environ.get("TENCENT_MAP_PROBE_DESTINATION", DEFAULT_PROBE_DESTINATION)
    origin = coordinate_provider.resolve(origin_name)
    destination = coordinate_provider.resolve(destination_name)

    print("\n二、地点坐标解析")
    print(f"- 检索区域：{os.environ.get('TENCENT_MAP_PROBE_REGION', DEFAULT_PROBE_REGION)}")
    _print_coordinate_result("起点", origin)
    _print_coordinate_result("终点", destination)
    origin = _select_manual_candidate_if_needed("起点", origin)
    destination = _select_manual_candidate_if_needed("终点", destination)

    if not origin.is_resolved or not destination.is_resolved:
        print("\n三、驾车路线距离")
        print("坐标解析未得到两个可用点，本次不继续请求驾车路线。")
        return

    route = route_provider.get_route(
        RoadRouteRequest(
            origin=make_geo_point(origin.longitude, origin.latitude),
            destination=make_geo_point(destination.longitude, destination.latitude),
        )
    )

    print("\n三、驾车路线距离")
    print(f"- 路线状态：{_display_status(route.status)}（{route.status}），来源：{route.source}")
    if route.is_resolved:
        print(f"- 腾讯普通驾车距离：{route.distance_km} 公里")
        print(f"- 腾讯预计驾车时间：{route.duration_hours} 小时")
        print(f"- 预估过路费：{route.toll_yuan} 元")
        print(f"- 路线标签：{', '.join(route.route_tags) if route.route_tags else '无'}")
    else:
        print(f"- 说明：{route.message}")
    print("\n四、展示说明")
    print("- 本探针只证明坐标解析和普通驾车距离可用。")
    print("- 后续进入汽运计费时，还需要订单吨数或箱量、包装方式和品种等输入。")


def _sync_pythonpath_to_sys_path() -> None:
    for path_text in reversed(os.environ.get("PYTHONPATH", "").split(os.pathsep)):
        if path_text and path_text not in sys.path:
            sys.path.insert(0, path_text)


def _print_coordinate_result(label: str, result) -> None:
    print(f"- {label}解析状态：{_display_status(result.status)}（{result.status}）")
    print(f"  坐标来源：{result.source}")
    print(f"  识别名称：{result.canonical_name or '未确定'}")
    print(f"  置信等级：{_display_confidence(result.source_confidence)}")
    print(f"  说明：{result.message}")
    if not result.candidates:
        return

    candidate_heading = "候选追溯" if result.is_resolved else "待人工确认候选"
    print(f"  {candidate_heading}：")
    for candidate in result.candidates:
        location = f"{candidate.latitude},{candidate.longitude}"
        area_parts = [value for value in (candidate.city, candidate.district) if value]
        area = "/".join(area_parts) if area_parts else "未知区域"
        print(
            f"  {candidate.rank}. {candidate.title} | {candidate.address or '无地址'} | "
            f"{candidate.category or '无分类'} | {area} | {location}"
        )


def _select_manual_candidate_if_needed(label: str, result) -> CoordinateResolution:
    if result.is_resolved or not result.candidates:
        return result

    if not _manual_candidate_selection_enabled():
        print(f"- {label}人工候选选择已跳过：当前为非交互运行。")
        print("  如需在本地控制台手动选择，请设置 TENCENT_MAP_PROBE_INTERACTIVE=true。")
        return result

    ranks = {candidate.rank: candidate for candidate in result.candidates}
    prompt = f"请输入{label}候选编号继续；直接回车则跳过："
    while True:
        try:
            choice = input(prompt).strip()
        except EOFError:
            print(f"- {label}人工候选选择已跳过：当前没有可用输入。")
            return result
        if not choice:
            print(f"- {label}人工候选选择已由用户跳过。")
            return result
        try:
            rank = int(choice)
        except ValueError:
            print(f"- {label}候选编号无效：{choice}")
            continue
        candidate = ranks.get(rank)
        if candidate is None:
            available = ", ".join(str(value) for value in sorted(ranks))
            print(f"- {label}候选编号无效：{rank}；可选编号：{available}")
            continue

        print(f"- {label}已选择候选：{candidate.rank}. {candidate.title}")
        return CoordinateResolution(
            status="resolved",
            query_name=result.query_name,
            node_id=None,
            canonical_name=candidate.title,
            longitude=candidate.longitude,
            latitude=candidate.latitude,
            source="tencent_map_place_search_manual_selection",
            message=f"已人工选择第 {candidate.rank} 个候选。",
            source_confidence="manual_selected_candidate",
            candidates=result.candidates,
        )


def _manual_candidate_selection_enabled() -> bool:
    value = os.environ.get("TENCENT_MAP_PROBE_INTERACTIVE", "auto").strip().lower()
    if value in {"1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    return sys.stdin.isatty()


def _display_status(status: str) -> str:
    return {
        "resolved": "已解析",
        "manual_review": "需人工复核",
        "not_available": "不可用",
        "failed": "失败",
    }.get(status, status)


def _display_confidence(confidence: str | None) -> str:
    if not confidence:
        return "无"
    labels = {
        "exact_unique": "唯一精确命中",
        "unique_candidate": "唯一候选",
        "auto_top1_name_match": "自动选择首位：名称匹配",
        "auto_top1_nearby_cluster": "自动选择首位：前排候选距离接近",
        "auto_top1_unclustered": "自动选择首位：低置信，建议抽检",
        "manual_top5_candidates": "候选不唯一，待人工确认",
        "manual_selected_candidate": "人工已选择候选",
        "manual_review": "人工复核",
    }
    label = labels.get(confidence, confidence)
    return f"{label}（{confidence}）"


if __name__ == "__main__":
    main()
