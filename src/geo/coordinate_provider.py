from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

try:
    from .node_registry import NodeRegistry
except ImportError:  # Support direct script-style imports used by demo scripts.
    from src.domain.node_registry import NodeRegistry


CoordinateResolutionStatus = Literal["resolved", "manual_review"]


class CoordinateProviderError(ValueError):
    """Raised when a coordinate query is structurally invalid."""


@dataclass(frozen=True)
class CoordinateResolution:
    status: CoordinateResolutionStatus
    query_name: str
    node_id: str | None
    canonical_name: str | None
    longitude: float | None
    latitude: float | None
    source: str
    message: str

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class CoordinateProvider(Protocol):
    def resolve(self, name: str) -> CoordinateResolution:
        """Resolve a location name into coordinates or a manual-review result."""


class LocalFirstCoordinateProvider:
    """Resolve coordinates from known node tables before falling back.

    The fallback is intentionally abstract. Tencent Maps or any other external
    service must be hidden behind a provider and must not be called directly by
    cost rules, graph construction, or path search.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        fallback_provider: CoordinateProvider | None = None,
    ) -> None:
        self._registry = registry
        self._fallback_provider = fallback_provider

    def resolve(self, name: str) -> CoordinateResolution:
        query_name = _required_location_name(name)
        node = self._registry.lookup(query_name)
        if node is not None:
            return CoordinateResolution(
                status="resolved",
                query_name=query_name,
                node_id=node.node_id,
                canonical_name=node.canonical_name,
                longitude=node.longitude,
                latitude=node.latitude,
                source="node_registry",
                message="已从本地标准节点注册表确认坐标。",
            )

        if self._fallback_provider is not None:
            return self._fallback_provider.resolve(query_name)

        return CoordinateResolution(
            status="manual_review",
            query_name=query_name,
            node_id=None,
            canonical_name=None,
            longitude=None,
            latitude=None,
            source="missing_local_coordinate",
            message="本地标准节点注册表未找到该地点坐标，且未配置外部坐标 Provider。",
        )


class DisabledTencentMapCoordinateProvider:
    """Placeholder for future Tencent Maps geocoding.

    This class records the intended fallback path without making network calls.
    Implementing the real provider requires API key, request parameters, return
    field mapping, ambiguity handling, cache policy, and tests.
    """

    def resolve(self, name: str) -> CoordinateResolution:
        query_name = _required_location_name(name)
        return CoordinateResolution(
            status="manual_review",
            query_name=query_name,
            node_id=None,
            canonical_name=None,
            longitude=None,
            latitude=None,
            source="tencent_map_api_disabled",
            message=(
                "本地坐标未命中；腾讯地图坐标抓取 Provider 尚未配置，"
                "需要 API 密钥、查询参数、返回字段和人工确认策略。"
            ),
        )


def _required_location_name(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise CoordinateProviderError("地点名称不能为空。")
    return text
