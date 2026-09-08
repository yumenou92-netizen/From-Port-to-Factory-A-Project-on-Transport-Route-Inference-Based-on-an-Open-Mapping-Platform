from pathlib import Path

from src.application.rail_container_planning import RailContainerPlanningService
from src.demos.rail_container_platform_demo import load_platform_demo


def test_platform_demo_fixture_runs_through_the_application_service():
    root = Path(__file__).resolve().parents[1]
    request, data = load_platform_demo(root / "sample_data" / "rail_container_platform_demo.json")

    response = RailContainerPlanningService(data).plan(request)

    assert response.graph_edge_count == 4
    assert response.recommendations.lowest_cost.status == "resolved"
    assert response.recommendations.fastest_time.status == "resolved"
    assert response.recommendations.lowest_cost.path_node_ids != response.recommendations.fastest_time.path_node_ids
