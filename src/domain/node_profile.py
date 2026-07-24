from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Sequence


InfrastructureType = Literal[
    "seaport",
    "inland_port",
    "rail_station",
    "factory",
    "warehouse",
    "customer_terminal",
    "unknown",
]

ShippingTimeRegion = Literal["福建", "珠三角", "粤西", "海南", "广西"]
ProfileConfirmationStatus = Literal["confirmed", "manual_review"]

ALLOWED_INFRASTRUCTURE_TYPES = {
    "seaport",
    "inland_port",
    "rail_station",
    "factory",
    "warehouse",
    "customer_terminal",
    "unknown",
}
ALLOWED_SHIPPING_TIME_REGIONS = {"福建", "珠三角", "粤西", "海南", "广西"}
ALLOWED_PROFILE_CONFIRMATION_STATUSES = {"confirmed", "manual_review"}


class NodeProfileError(ValueError):
    """Raised when a source-backed node profile is internally inconsistent."""


@dataclass(frozen=True)
class NodeProfile:
    """Business capabilities attached to one standard physical node."""

    node_id: str
    infrastructure_type: InfrastructureType
    capabilities: tuple[str, ...]
    source: str
    province: str | None = None
    city: str | None = None
    port_area: str | None = None
    shipping_time_region: ShippingTimeRegion | None = None
    region_code: str | None = None
    supported_package_types: tuple[str, ...] | None = None
    supported_commodities: tuple[str, ...] | None = None
    supported_transport_modes: tuple[str, ...] | None = None
    confirmation_status: ProfileConfirmationStatus = "manual_review"
    maintained_at: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _required_text(self.node_id, "节点 ID"))
        object.__setattr__(self, "source", _required_text(self.source, "节点画像来源"))
        object.__setattr__(self, "province", _optional_text(self.province))
        object.__setattr__(self, "city", _optional_text(self.city))
        object.__setattr__(self, "port_area", _optional_text(self.port_area))
        object.__setattr__(self, "region_code", _optional_text(self.region_code))

        if self.infrastructure_type not in ALLOWED_INFRASTRUCTURE_TYPES:
            raise NodeProfileError(f"不支持的基础设施类型：{self.infrastructure_type}")
        if (
            self.shipping_time_region is not None
            and self.shipping_time_region not in ALLOWED_SHIPPING_TIME_REGIONS
        ):
            raise NodeProfileError(f"不支持的纯航行时效分区：{self.shipping_time_region}")
        if self.confirmation_status not in ALLOWED_PROFILE_CONFIRMATION_STATUSES:
            raise NodeProfileError(f"不支持的节点画像确认状态：{self.confirmation_status}")
        if self.maintained_at is not None and not isinstance(self.maintained_at, date):
            raise NodeProfileError("节点画像维护日期必须是 date 或 None。")

        try:
            normalized_capabilities = tuple(
                sorted({_required_text(value, "节点作业能力") for value in self.capabilities})
            )
        except TypeError:
            raise NodeProfileError("节点作业能力必须是可迭代的文本集合。") from None
        object.__setattr__(self, "capabilities", normalized_capabilities)
        object.__setattr__(
            self,
            "supported_package_types",
            _normalize_optional_values(self.supported_package_types, "支持包装方式"),
        )
        object.__setattr__(
            self,
            "supported_commodities",
            _normalize_optional_values(self.supported_commodities, "支持货物品种"),
        )
        object.__setattr__(
            self,
            "supported_transport_modes",
            _normalize_optional_values(self.supported_transport_modes, "支持运输方式"),
        )

    @property
    def is_bulk_shipping_port(self) -> bool:
        return self.infrastructure_type == "seaport" and bool(
            {"散粮", "散船"}.intersection(self.capabilities)
        )

    @property
    def standard_location_label(self) -> str | None:
        return self.port_area or self.city

    @property
    def capability_data_confirmed(self) -> bool:
        """Whether route-relevant capability fields may be used for filtering."""

        return (
            self.confirmation_status == "confirmed"
            and self.supported_package_types is not None
            and self.supported_commodities is not None
            and self.supported_transport_modes is not None
        )


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise NodeProfileError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_optional_values(
    values: Sequence[object] | None,
    field_name: str,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    try:
        normalized = tuple(sorted({_required_text(value, field_name) for value in values}))
    except TypeError:
        raise NodeProfileError(f"{field_name}必须是可迭代文本或 None。") from None
    return normalized
