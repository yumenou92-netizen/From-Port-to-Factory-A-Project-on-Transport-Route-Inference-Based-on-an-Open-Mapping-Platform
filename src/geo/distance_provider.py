from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol


RouteDistanceStatus = Literal["resolved", "manual_review"]


class DistanceProviderError(ValueError):
    """Raised when a distance or route query is structurally invalid."""


@dataclass(frozen=True)
class GeoPoint:
    longitude: Decimal
    latitude: Decimal

    def __post_init__(self) -> None:
        longitude = _decimal_in_range(self.longitude, "longitude", Decimal("-180"), Decimal("180"))
        latitude = _decimal_in_range(self.latitude, "latitude", Decimal("-90"), Decimal("90"))
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "latitude", latitude)

    def to_tencent_lat_lng(self) -> str:
        return f"{_format_decimal(self.latitude)},{_format_decimal(self.longitude)}"


@dataclass(frozen=True)
class DrivingProfile:
    """Optional passenger-car route parameters for Tencent driving route service."""

    plate_number: str | None = None
    cartype: int | None = None

    def to_tencent_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {}
        if self.plate_number:
            params["plate_number"] = self.plate_number.strip()
        if self.cartype is not None:
            params["cartype"] = self.cartype
        return params


@dataclass(frozen=True)
class TruckProfile:
    """Truck parameters accepted by Tencent Maps truck route service.

    Keep all fields optional so the project can start with basic route probing
    and only add stricter vehicle constraints after business confirmation.
    """

    size: int | None = None
    height_m: Decimal | None = None
    width_m: Decimal | None = None
    length_m: Decimal | None = None
    weight_ton: Decimal | None = None
    axle_weight_ton: Decimal | None = None
    axle_count: int | None = None
    plate_number: str | None = None
    plate_color: int | None = None
    pass_type: int | None = None

    def to_tencent_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {}
        if self.size is not None:
            params["size"] = self.size
        if self.height_m is not None:
            params["height"] = _format_decimal(_positive_decimal(self.height_m, "height_m"))
        if self.width_m is not None:
            params["width"] = _format_decimal(_positive_decimal(self.width_m, "width_m"))
        if self.length_m is not None:
            params["length"] = _format_decimal(_positive_decimal(self.length_m, "length_m"))
        if self.weight_ton is not None:
            params["weight"] = _format_decimal(_positive_decimal(self.weight_ton, "weight_ton"))
        if self.axle_weight_ton is not None:
            params["axle_weight"] = _format_decimal(
                _positive_decimal(self.axle_weight_ton, "axle_weight_ton")
            )
        if self.axle_count is not None:
            params["axle_count"] = self.axle_count
        if self.plate_number:
            params["plate_number"] = self.plate_number.strip()
        if self.plate_color is not None:
            params["plate_color"] = self.plate_color
        if self.pass_type is not None:
            params["pass_type"] = self.pass_type
        return params


@dataclass(frozen=True)
class RoadRouteRequest:
    origin: GeoPoint
    destination: GeoPoint
    driving_profile: DrivingProfile | None = None


@dataclass(frozen=True)
class TruckRouteRequest:
    origin: GeoPoint
    destination: GeoPoint
    truck_profile: TruckProfile | None = None


@dataclass(frozen=True)
class RoadRouteResult:
    status: RouteDistanceStatus
    distance_km: Decimal | None
    duration_hours: Decimal | None
    source: str
    message: str
    raw_distance_meters: int | None = None
    raw_duration_minutes: int | None = None
    toll_yuan: Decimal | None = None
    route_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "manual_review"}:
            raise DistanceProviderError(f"Unsupported route distance status: {self.status}")
        if self.status == "resolved":
            if self.distance_km is None or self.duration_hours is None:
                raise DistanceProviderError("Resolved route result requires distance and duration.")
            if self.distance_km <= 0 or self.duration_hours <= 0:
                raise DistanceProviderError("Resolved route distance and duration must be positive.")
        elif self.distance_km is not None or self.duration_hours is not None:
            raise DistanceProviderError("Manual-review route result must not contain usable values.")

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class RoadRouteProvider(Protocol):
    def get_route(self, request: RoadRouteRequest) -> RoadRouteResult:
        """Return road distance and time, or a manual-review result."""


class TruckRouteProvider(Protocol):
    def get_truck_route(self, request: TruckRouteRequest) -> RoadRouteResult:
        """Return truck road distance and time, or a manual-review result."""


class DisabledRoadRouteProvider:
    """Placeholder route provider used when external map API is not configured."""

    def get_route(self, request: RoadRouteRequest) -> RoadRouteResult:
        return RoadRouteResult(
            status="manual_review",
            distance_km=None,
            duration_hours=None,
            source="road_route_provider_disabled",
            message="道路路线 Provider 尚未配置，不能自动获取汽车行驶距离和耗时。",
        )


class DisabledTruckRouteProvider:
    """Placeholder truck-route provider used when external map API is not configured."""

    def get_truck_route(self, request: TruckRouteRequest) -> RoadRouteResult:
        return RoadRouteResult(
            status="manual_review",
            distance_km=None,
            duration_hours=None,
            source="truck_route_provider_disabled",
            message="货车路线 Provider 尚未配置，不能自动获取货车道路距离和耗时。",
        )


def _decimal_in_range(value: object, field_name: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    number = _to_decimal(value, field_name)
    if number < minimum or number > maximum:
        raise DistanceProviderError(f"{field_name} must be between {minimum} and {maximum}.")
    return number


def _positive_decimal(value: object, field_name: str) -> Decimal:
    number = _to_decimal(value, field_name)
    if number <= 0:
        raise DistanceProviderError(f"{field_name} must be positive.")
    return number


def _to_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise DistanceProviderError(f"{field_name} must be numeric.")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise DistanceProviderError(f"{field_name} must be numeric.") from None
    if not number.is_finite():
        raise DistanceProviderError(f"{field_name} must be finite.")
    return number


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
