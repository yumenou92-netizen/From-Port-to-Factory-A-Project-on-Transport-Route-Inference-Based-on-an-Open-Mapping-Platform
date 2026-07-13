from __future__ import annotations

import sys
from collections.abc import Callable

from demo_leader_cost_rules import main as run_cost_rules_demo
from demo_leader_real_data import main as run_real_data_demo


DemoRunner = Callable[[], None]


LEADER_DEMOS: dict[str, tuple[str, DemoRunner]] = {
    "real-data": ("真实业务数据接入状态展示", run_real_data_demo),
    "cost-rules": ("费用计算与单位校验展示", run_cost_rules_demo),
}


def main() -> None:
    if len(sys.argv) > 1:
        demo_key = sys.argv[1]
        if demo_key in {"-h", "--help", "help"}:
            print_menu()
            return
        run_demo(demo_key)
        return

    print("北港至客户工厂全链路运输路径推断原型")
    print("领导展示 Demo 入口")
    print("=" * 52)
    print("当前可展示模块：")
    print_menu()
    print("\n默认运行最新已完成模块展示：真实业务数据接入状态。")
    print("=" * 52)
    run_real_data_demo()


def print_menu() -> None:
    for demo_key, (title, _) in LEADER_DEMOS.items():
        print(f"- {demo_key}: {title}")
    print("\n运行方式示例：python src/demo_leader.py real-data")


def run_demo(demo_key: str) -> None:
    demo = LEADER_DEMOS.get(demo_key)
    if demo is None:
        available = ", ".join(LEADER_DEMOS)
        raise SystemExit(f"未知展示模块: {demo_key}。可用模块: {available}")

    title, runner = demo
    print(f"正在运行领导展示模块：{title}")
    print("=" * 52)
    runner()


if __name__ == "__main__":
    main()
