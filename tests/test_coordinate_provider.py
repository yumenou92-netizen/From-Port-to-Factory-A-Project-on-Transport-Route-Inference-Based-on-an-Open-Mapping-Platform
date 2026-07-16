from src.coordinate_provider import (
    CoordinateProviderError,
    DisabledTencentMapCoordinateProvider,
    LocalFirstCoordinateProvider,
)
from src.data_loaders import NodeRecord, make_node_id
from src.node_registry import build_node_registry


def test_local_first_coordinate_provider_resolves_known_node():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="南港B", longitude=111.1, latitude=23.1),
        ]
    )
    provider = LocalFirstCoordinateProvider(registry)

    result = provider.resolve("南港B")

    assert result.is_resolved
    assert result.node_id == make_node_id("南港B")
    assert result.canonical_name == "南港B"
    assert result.longitude == 111.1
    assert result.latitude == 23.1
    assert result.source == "node_registry"


def test_local_first_coordinate_provider_resolves_alias_from_registry():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="怀化西", longitude=109.91, latitude=27.55),
            NodeRecord(node_id="raw_2", name="怀化西站", longitude=109.915, latitude=27.555),
        ]
    )
    provider = LocalFirstCoordinateProvider(registry)

    plain = provider.resolve("怀化西")
    alias = provider.resolve("怀化西站")

    assert plain.is_resolved
    assert alias.is_resolved
    assert plain.node_id == alias.node_id
    assert alias.canonical_name == "怀化西"


def test_missing_local_coordinate_falls_back_to_disabled_tencent_provider():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="南港B", longitude=111.1, latitude=23.1),
        ]
    )
    provider = LocalFirstCoordinateProvider(
        registry,
        fallback_provider=DisabledTencentMapCoordinateProvider(),
    )

    result = provider.resolve("未知客户工厂")

    assert not result.is_resolved
    assert result.status == "manual_review"
    assert result.source == "tencent_map_api_disabled"
    assert "腾讯地图" in result.message
    assert result.longitude is None
    assert result.latitude is None


def test_missing_local_coordinate_without_fallback_requires_manual_review():
    registry = build_node_registry(
        [
            NodeRecord(node_id="raw_1", name="南港B", longitude=111.1, latitude=23.1),
        ]
    )
    provider = LocalFirstCoordinateProvider(registry)

    result = provider.resolve("未知客户工厂")

    assert result.status == "manual_review"
    assert result.source == "missing_local_coordinate"
    assert "未配置外部坐标 Provider" in result.message


def test_coordinate_provider_rejects_empty_location_name():
    registry = build_node_registry([])
    provider = LocalFirstCoordinateProvider(registry)

    try:
        provider.resolve(" ")
    except CoordinateProviderError as exc:
        assert "地点名称不能为空" in str(exc)
    else:
        raise AssertionError("Expected CoordinateProviderError")
