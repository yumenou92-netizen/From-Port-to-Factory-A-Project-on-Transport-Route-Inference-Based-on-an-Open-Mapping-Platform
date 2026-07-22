from decimal import Decimal

import pytest

from src.routing.shipping_time_provider import (
    ApiShippingTimeProvider,
    DatabaseShippingTimeProvider,
    JsonShippingTimeProvider,
    ManualShippingTimeProvider,
    ShippingTimeRequest,
    ShippingTimeResult,
    ShippingTimeProviderError,
)


def make_request(duration_value, duration_unit: str = "小时") -> ShippingTimeRequest:
    return ShippingTimeRequest(
        stage="南港至客户工厂",
        transport_mode="汽运",
        duration_value=duration_value,
        duration_unit=duration_unit,
        source="人工确认测试",
    )


def test_manual_shipping_time_provider_resolves_positive_hours():
    provider = ManualShippingTimeProvider()

    result = provider.get_shipping_time(make_request("36.5", "小时"))

    assert result.status == "resolved"
    assert result.is_resolved
    assert result.duration_hours == Decimal("36.5")
    assert result.source == "manual_shipping_time"
    assert "人工" in result.message
    assert result.time_scope is None


def test_manual_shipping_time_provider_converts_days_to_hours():
    provider = ManualShippingTimeProvider()

    result = provider.get_shipping_time(make_request("2", "天"))

    assert result.status == "resolved"
    assert result.duration_hours == Decimal("48")
    assert result.input_unit == "天"


def test_shipping_time_result_preserves_pure_sailing_scope():
    provider = ManualShippingTimeProvider()
    request = ShippingTimeRequest(
        stage="北港至南港",
        transport_mode="散船",
        duration_value="4",
        duration_unit="天",
        source="区域纯航行时效测试",
        time_scope="pure_sailing",
    )

    result = provider.get_shipping_time(request)

    assert result.duration_hours == Decimal("96")
    assert result.time_scope == "pure_sailing"


def test_manual_shipping_time_provider_converts_minutes_to_hours():
    provider = ManualShippingTimeProvider()

    result = provider.get_shipping_time(make_request("90", "分钟"))

    assert result.status == "resolved"
    assert result.duration_hours == Decimal("1.5")
    assert result.input_unit == "分钟"


def test_manual_shipping_time_provider_requires_duration_value():
    provider = ManualShippingTimeProvider()

    result = provider.get_shipping_time(make_request(None))

    assert result.status == "manual_review"
    assert not result.is_resolved
    assert result.duration_hours is None
    assert "缺少人工运输时间" in result.message


def test_manual_shipping_time_provider_rejects_zero_negative_and_non_numeric_values():
    provider = ManualShippingTimeProvider()

    for bad_value in (0, "-1", "abc"):
        result = provider.get_shipping_time(make_request(bad_value))

        assert result.status == "manual_review"
        assert result.duration_hours is None
        assert "必须是大于 0 的有限数值" in result.message


def test_manual_shipping_time_provider_rejects_unsupported_unit():
    provider = ManualShippingTimeProvider()

    result = provider.get_shipping_time(make_request("10", "班次"))

    assert result.status == "manual_review"
    assert result.duration_hours is None
    assert "不支持的运输时间单位" in result.message


def test_placeholder_providers_return_unconfigured_manual_review():
    request = ShippingTimeRequest(
        stage="北港至南港",
        transport_mode="散船",
        duration_value="12",
        source="测试",
        time_scope="pure_sailing",
    )

    for provider in (
        JsonShippingTimeProvider(),
        DatabaseShippingTimeProvider(),
        ApiShippingTimeProvider(),
    ):
        result = provider.get_shipping_time(request)

        assert result.status == "manual_review"
        assert result.duration_hours is None
        assert "尚未配置" in result.message
        assert result.time_scope == "pure_sailing"


def test_manual_review_preserves_explicit_time_scope():
    request = ShippingTimeRequest(
        stage="北港至南港",
        transport_mode="散船",
        duration_value=None,
        source="测试",
        time_scope="pure_sailing",
    )

    result = ManualShippingTimeProvider().get_shipping_time(request)

    assert result.status == "manual_review"
    assert result.time_scope == "pure_sailing"


def test_request_and_result_reject_unsupported_time_scope():
    with pytest.raises(ShippingTimeProviderError, match="不支持的运输时间范围"):
        ShippingTimeRequest(
            stage="北港至南港",
            transport_mode="散船",
            duration_value="4",
            source="测试",
            time_scope="unknown_scope",
        )

    with pytest.raises(ShippingTimeProviderError, match="不支持的运输时间范围"):
        ShippingTimeResult(
            status="resolved",
            duration_hours="96",
            source="测试",
            message="测试",
            time_scope="unknown_scope",
        )


def test_resolved_result_requires_positive_duration():
    try:
        ShippingTimeResult(
            status="resolved",
            duration_hours=0,
            source="test",
            message="bad",
        )
    except ShippingTimeProviderError as exc:
        assert "有效运输时间必须大于 0" in str(exc)
    else:
        raise AssertionError("Expected ShippingTimeProviderError")


def test_manual_review_result_must_not_contain_duration():
    try:
        ShippingTimeResult(
            status="manual_review",
            duration_hours=1,
            source="test",
            message="bad",
        )
    except ShippingTimeProviderError as exc:
        assert "人工复核结果不得包含可用运输时间" in str(exc)
    else:
        raise AssertionError("Expected ShippingTimeProviderError")
