from src.demos.tencent_map_probe import _select_manual_candidate_if_needed
from src.geo.coordinate_provider import CoordinateCandidate, CoordinateResolution


def test_probe_manual_candidate_selection_accepts_rank(monkeypatch):
    monkeypatch.setenv("TENCENT_MAP_PROBE_INTERACTIVE", "true")
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    result = _manual_review_result()

    selected = _select_manual_candidate_if_needed("destination", result)

    assert selected.is_resolved
    assert selected.canonical_name == "福建湘大骆驼饲料有限公司-东南门"
    assert selected.longitude == 117.896795
    assert selected.latitude == 24.371773
    assert selected.source_confidence == "manual_selected_candidate"


def test_probe_manual_candidate_selection_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TENCENT_MAP_PROBE_INTERACTIVE", "false")
    result = _manual_review_result()

    selected = _select_manual_candidate_if_needed("destination", result)

    assert selected is result
    assert not selected.is_resolved


def _manual_review_result() -> CoordinateResolution:
    return CoordinateResolution(
        status="manual_review",
        query_name="福建湘大骆驼饲料有限公司",
        node_id=None,
        canonical_name=None,
        longitude=None,
        latitude=None,
        source="tencent_map_place_search",
        message="候选不唯一，请人工确认坐标。",
        source_confidence="manual_top5_candidates",
        candidates=(
            CoordinateCandidate(
                rank=1,
                title="福建湘大骆驼饲料有限公司-东南门",
                address="福建省漳州市龙海区东园镇东园开发区",
                category="室内及附属设施:通行设施类:门/出入口",
                longitude=117.896795,
                latitude=24.371773,
                city="漳州市",
                district="龙海区",
            ),
        ),
    )
