from __future__ import annotations

from shipping_time_provider import (
    ApiShippingTimeProvider,
    DatabaseShippingTimeProvider,
    JsonShippingTimeProvider,
    ManualShippingTimeProvider,
    ShippingTimeRequest,
)


def main() -> None:
    print("北港至客户工厂全链路运输路径推断原型")
    print("运输时间 Provider 展示")
    print("=" * 52)
    print("本次展示聚焦运输时间如何统一进入小时制；完整搜索能力由 route-search 展示。")

    show_manual_provider()
    show_invalid_inputs()
    show_placeholder_providers()
    show_current_boundary()


def show_manual_provider() -> None:
    print("\n一、人工确认时间进入统一 Provider")
    provider = ManualShippingTimeProvider()
    scenarios = [
        ("南港至客户工厂", "汽运", "36", "小时"),
        ("北港至南港", "散船", "2", "天"),
        ("短途倒运", "汽运", "90", "分钟"),
    ]
    for stage, transport_mode, duration_value, duration_unit in scenarios:
        result = provider.get_shipping_time(
            ShippingTimeRequest(
                stage=stage,
                transport_mode=transport_mode,
                duration_value=duration_value,
                duration_unit=duration_unit,
                source="人工确认演示",
            )
        )
        print(
            f"{stage}（{transport_mode}）: "
            f"{duration_value}{duration_unit} -> {result.duration_hours}小时，状态={result.status}"
        )


def show_invalid_inputs() -> None:
    print("\n二、缺失或非法时间不进入路径搜索")
    provider = ManualShippingTimeProvider()
    scenarios = [
        (None, "小时"),
        ("0", "小时"),
        ("-2", "小时"),
        ("待确认", "小时"),
        ("10", "班次"),
    ]
    for duration_value, duration_unit in scenarios:
        result = provider.get_shipping_time(
            ShippingTimeRequest(
                stage="南港至客户工厂",
                transport_mode="汽运",
                duration_value=duration_value,
                duration_unit=duration_unit,
                source="人工确认演示",
            )
        )
        print(f"输入={duration_value}{duration_unit}，状态={result.status}；提示={result.message}")


def show_placeholder_providers() -> None:
    print("\n三、未接入数据源保持占位")
    request = ShippingTimeRequest(
        stage="南港至客户工厂",
        transport_mode="汽运",
        duration_value="12",
        duration_unit="小时",
        source="人工确认演示",
    )
    providers = [
        JsonShippingTimeProvider(),
        DatabaseShippingTimeProvider(),
        ApiShippingTimeProvider(),
    ]
    for provider in providers:
        result = provider.get_shipping_time(request)
        print(f"{result.source}: 状态={result.status}；提示={result.message}")


def show_current_boundary() -> None:
    print("\n四、当前边界")
    print("第一版运输时间只采用人工确认输入，统一换算为小时。")
    print("JSON、数据库和 API 时间源尚未确认，因此只保留 Provider 占位。")
    print("腾讯普通驾车耗时可作为道路参考数据，但不能直接替代完整散船或作业运输时间。")


if __name__ == "__main__":
    main()
