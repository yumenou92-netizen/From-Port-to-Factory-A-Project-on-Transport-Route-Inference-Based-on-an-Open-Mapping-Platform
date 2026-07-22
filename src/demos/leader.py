from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable

from src.dev.runtime_env import DEFAULT_ENV_FILE, load_runtime_env


DemoRunner = Callable[[], None]


LEADER_DEMOS: dict[str, tuple[str, str]] = {
    "full-flow": ("北港至客户工厂全流程双目标推荐", "src.demos.leader_full_flow"),
    "route-search": ("MultiDiGraph 路径搜索与解释结果展示", "src.demos.leader_route_search"),
    "transport-graph": ("正式 MultiDiGraph 展示", "src.demos.leader_transport_graph"),
    "transport-edge": ("标准 TransportEdge 展示", "src.demos.leader_transport_edge"),
    "customer-profile": ("客户画像与路线分支展示", "src.demos.leader_customer_profile"),
    "latest-rate": ("最新有效运价选择展示", "src.demos.leader_latest_rate"),
    "shipping-time": ("运输时间 Provider 展示", "src.demos.leader_shipping_time"),
    "freight-rate": ("标准运价记录展示", "src.demos.leader_freight_rate"),
    "route-request": ("订单输入与计费校验展示", "src.demos.leader_route_request"),
    "node-registry": ("节点标准化能力展示", "src.demos.leader_node_registry"),
    "real-data": ("真实业务数据接入状态展示", "src.demos.leader_real_data"),
    "cost-rules": ("费用计算与单位校验展示", "src.demos.leader_cost_rules"),
}


def main() -> None:
    _load_runtime_env()
    if len(sys.argv) > 1:
        demo_key = sys.argv[1]
        if demo_key in {"-h", "--help", "help"}:
            print_menu()
            return
        run_demo(demo_key)
        return

    print("全链路运输路径推断原型")
    print("展示 Demo 入口")
    print("=" * 52)
    print("当前模块：")
    print_menu()
    print("\n默认运行最新已完成模块展示：MultiDiGraph 路径搜索与解释结果。")
    print("=" * 52)
    _load_runner("route-search")()


def print_menu() -> None:
    for demo_key, (title, _) in LEADER_DEMOS.items():
        print(f"- {demo_key}: {title}")
    print("\n正式全流程演示：python -m src.demos.leader full-flow")
    print("模块演示示例：python -m src.demos.leader freight-rate")


def run_demo(demo_key: str) -> None:
    demo = LEADER_DEMOS.get(demo_key)
    if demo is None:
        available = ", ".join(LEADER_DEMOS)
        raise SystemExit(f"未知展示模块: {demo_key}。可用模块: {available}")

    title, _ = demo
    print(f"正在运行展示模块：{title}")
    print("=" * 52)
    _load_runner(demo_key)()


def _load_runtime_env() -> None:
    load_runtime_env(DEFAULT_ENV_FILE)
    _sync_pythonpath_to_sys_path()


def _sync_pythonpath_to_sys_path() -> None:
    for path_text in reversed(os.environ.get("PYTHONPATH", "").split(os.pathsep)):
        if path_text and path_text not in sys.path:
            sys.path.insert(0, path_text)


def _load_runner(demo_key: str) -> DemoRunner:
    module_name = LEADER_DEMOS[demo_key][1]
    module = importlib.import_module(module_name)
    runner = getattr(module, "main", None)
    if not callable(runner):
        raise SystemExit(f"展示模块缺少 main() 入口: {module_name}")
    return runner


if __name__ == "__main__":
    main()
