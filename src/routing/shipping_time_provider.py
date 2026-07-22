from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

try:
    from .transport_contracts import ALLOWED_TIME_SCOPES, TimeScope
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.routing.transport_contracts import ALLOWED_TIME_SCOPES, TimeScope


ShippingTimeStatus = Literal["resolved", "manual_review"]


class ShippingTimeProviderError(ValueError):
    """Raised when shipping-time structures are internally inconsistent."""


@dataclass(frozen=True)
class ShippingTimeRequest:
    stage: str
    transport_mode: str
    duration_value: object | None = None
    duration_unit: str = "小时"
    source: str = "manual_input"
    time_scope: TimeScope | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _required_text(self.stage, "运输阶段"))
        object.__setattr__(self, "transport_mode", _required_text(self.transport_mode, "运输方式"))
        object.__setattr__(self, "duration_unit", _required_text(self.duration_unit, "运输时间单位"))
        object.__setattr__(self, "source", _required_text(self.source, "运输时间来源"))
        if self.time_scope is not None and self.time_scope not in ALLOWED_TIME_SCOPES:
            raise ShippingTimeProviderError(f"不支持的运输时间范围：{self.time_scope}")


@dataclass(frozen=True)
class ShippingTimeResult:
    status: ShippingTimeStatus
    duration_hours: Decimal | None
    source: str
    message: str
    stage: str | None = None
    transport_mode: str | None = None
    input_value: str | None = None
    input_unit: str | None = None
    time_scope: TimeScope | None = None

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "manual_review"}:
            raise ShippingTimeProviderError(f"不支持的运输时间状态：{self.status}")

        duration = self.duration_hours
        if duration is not None:
            duration = _to_decimal(duration)
            object.__setattr__(self, "duration_hours", duration)

        if self.status == "resolved":
            if duration is None or duration <= 0:
                raise ShippingTimeProviderError("有效运输时间必须大于 0。")
        elif duration is not None:
            raise ShippingTimeProviderError("人工复核结果不得包含可用运输时间。")

        object.__setattr__(self, "source", _required_text(self.source, "运输时间结果来源"))
        object.__setattr__(self, "message", _required_text(self.message, "运输时间结果说明"))
        object.__setattr__(self, "stage", _optional_text(self.stage))
        object.__setattr__(self, "transport_mode", _optional_text(self.transport_mode))
        object.__setattr__(self, "input_value", _optional_text(self.input_value))
        object.__setattr__(self, "input_unit", _optional_text(self.input_unit))
        if self.time_scope is not None and self.time_scope not in ALLOWED_TIME_SCOPES:
            raise ShippingTimeProviderError(f"不支持的运输时间范围：{self.time_scope}")

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


class ShippingTimeProvider(Protocol):
    def get_shipping_time(self, request: ShippingTimeRequest) -> ShippingTimeResult:
        """Return shipping time in hours, or a manual-review result."""


class ManualShippingTimeProvider:
    """First enabled shipping-time provider based on explicitly confirmed input."""

    def get_shipping_time(self, request: ShippingTimeRequest) -> ShippingTimeResult:
        if request.duration_value is None:
            return _manual_review(request, "缺少人工运输时间，不能自动形成可用时效。")

        try:
            value = _positive_decimal(request.duration_value)
        except ShippingTimeProviderError as exc:
            return _manual_review(request, str(exc))

        try:
            duration_hours = _convert_to_hours(value, request.duration_unit)
        except ShippingTimeProviderError as exc:
            return _manual_review(request, str(exc))

        return ShippingTimeResult(
            status="resolved",
            duration_hours=duration_hours,
            source="manual_shipping_time",
            message="已采用人工确认运输时间并统一换算为小时。",
            stage=request.stage,
            transport_mode=request.transport_mode,
            input_value=str(request.duration_value),
            input_unit=request.duration_unit,
            time_scope=request.time_scope,
        )


class JsonShippingTimeProvider:
    """Placeholder for a future JSON-backed shipping-time source."""

    def get_shipping_time(self, request: ShippingTimeRequest) -> ShippingTimeResult:
        return _unconfigured_provider_result(request, "json_shipping_time_provider")


class DatabaseShippingTimeProvider:
    """Placeholder for a future database-backed shipping-time source."""

    def get_shipping_time(self, request: ShippingTimeRequest) -> ShippingTimeResult:
        return _unconfigured_provider_result(request, "database_shipping_time_provider")


class ApiShippingTimeProvider:
    """Placeholder for a future API-backed shipping-time source."""

    def get_shipping_time(self, request: ShippingTimeRequest) -> ShippingTimeResult:
        return _unconfigured_provider_result(request, "api_shipping_time_provider")


def _manual_review(request: ShippingTimeRequest, message: str) -> ShippingTimeResult:
    return ShippingTimeResult(
        status="manual_review",
        duration_hours=None,
        source="manual_shipping_time",
        message=message,
        stage=request.stage,
        transport_mode=request.transport_mode,
        input_value=str(request.duration_value) if request.duration_value is not None else None,
        input_unit=request.duration_unit,
        time_scope=request.time_scope,
    )


def _unconfigured_provider_result(request: ShippingTimeRequest, source: str) -> ShippingTimeResult:
    return ShippingTimeResult(
        status="manual_review",
        duration_hours=None,
        source=source,
        message=f"{source} 尚未配置，不能自动获取运输时间。",
        stage=request.stage,
        transport_mode=request.transport_mode,
        input_value=str(request.duration_value) if request.duration_value is not None else None,
        input_unit=request.duration_unit,
        time_scope=request.time_scope,
    )


def _convert_to_hours(value: Decimal, unit: str) -> Decimal:
    normalized = unit.strip().lower()
    if normalized in {"小时", "时", "hour", "hours", "h"}:
        return value
    if normalized in {"天", "日", "day", "days", "d"}:
        return value * Decimal("24")
    if normalized in {"分钟", "分", "minute", "minutes", "min", "m"}:
        return value / Decimal("60")
    raise ShippingTimeProviderError(f"不支持的运输时间单位：{unit}")


def _positive_decimal(value: object) -> Decimal:
    number = _to_decimal(value)
    if number <= 0:
        raise ShippingTimeProviderError("运输时间必须是大于 0 的有限数值。")
    return number


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ShippingTimeProviderError("运输时间必须是大于 0 的有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise ShippingTimeProviderError("运输时间必须是大于 0 的有限数值。") from None
    if not number.is_finite():
        raise ShippingTimeProviderError("运输时间必须是大于 0 的有限数值。")
    return number


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ShippingTimeProviderError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
