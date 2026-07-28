from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from src.routing.bulk_shipping_provider import classify_bulk_shipping_destination
from src.routing.inland_waterway_provider import RegionMappingRecord


BUSINESS_REGION_CODES = {
    "福建": "fujian",
    "珠三角": "pearl_river_delta",
    "粤西": "western_guangdong",
    "广西": "guangxi",
    "海南": "hainan",
}


@dataclass(frozen=True)
class PortRegionResolution:
    status: str
    message: str
    region_code: str | None = None
    source: str | None = None
    mapping_basis: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved" and self.region_code is not None


class PortRegionResolver(Protocol):
    def resolve(self, *names: str) -> PortRegionResolution:
        """Resolve one port to a traceable business region."""


class RuleBasedPortRegionResolver:
    """Resolve a port region without depending on a concrete storage backend.

    Formal region-mapping rows take priority. The confirmed bulk-shipping
    destination rules remain a compatibility fallback while the standalone
    prototype has not yet connected to the company data platform.
    """

    def __init__(self, region_mappings: Sequence[RegionMappingRecord] = ()) -> None:
        self.region_mappings = tuple(region_mappings)

    def resolve(self, *names: str) -> PortRegionResolution:
        normalized_names = tuple(
            dict.fromkeys(str(name).strip() for name in names if str(name).strip())
        )
        if not normalized_names:
            return PortRegionResolution(
                status="manual_review",
                message="缺少可用于区域判断的港口名称。",
            )

        formal_matches: dict[str, list[RegionMappingRecord]] = {}
        for name in normalized_names:
            for record in self.region_mappings:
                if record.matches(name):
                    region_code = (
                        BUSINESS_REGION_CODES.get(record.bulk_time_region)
                        if record.bulk_time_region
                        else record.region_code
                    )
                    formal_matches.setdefault(region_code or record.region_code, []).append(
                        record
                    )

        if len(formal_matches) > 1:
            codes = "、".join(sorted(formal_matches))
            return PortRegionResolution(
                status="manual_review",
                message=f"港口名称同时命中多个区域：{codes}。",
            )
        if len(formal_matches) == 1:
            region_code, records = next(iter(formal_matches.items()))
            sources = tuple(dict.fromkeys(record.source for record in records))
            return PortRegionResolution(
                status="resolved",
                region_code=region_code,
                source="；".join(sources),
                mapping_basis=(
                    "正式区域映射表关键词命中："
                    + " / ".join(normalized_names)
                ),
                message=f"已由正式区域映射表解析到区域 {region_code}。",
            )

        fallback_regions: dict[str, tuple[str, str]] = {}
        for name in normalized_names:
            destination_group, shipping_time_region = (
                classify_bulk_shipping_destination(name)
            )
            if destination_group is None or shipping_time_region is None:
                continue
            region_code = BUSINESS_REGION_CODES[shipping_time_region]
            fallback_regions[region_code] = (destination_group, shipping_time_region)

        if len(fallback_regions) > 1:
            codes = "、".join(sorted(fallback_regions))
            return PortRegionResolution(
                status="manual_review",
                message=f"港口名称按已确认散船规则命中多个区域：{codes}。",
            )
        if len(fallback_regions) == 1:
            region_code, (destination_group, time_region) = next(
                iter(fallback_regions.items())
            )
            return PortRegionResolution(
                status="resolved",
                region_code=region_code,
                source="confirmed_bulk_shipping_destination_mapping",
                mapping_basis=(
                    f"已确认散船目的组/航时区映射："
                    f"{destination_group}/{time_region}"
                ),
                message=f"已由散船目的组/航时区规则解析到区域 {region_code}。",
            )

        return PortRegionResolution(
            status="manual_review",
            message=(
                "区域映射表和已确认散船目的组规则均无法判断港口所在区域。"
            ),
        )
