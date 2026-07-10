from typing import List
import networkx as nx
from models import RouteResult, RouteSegment


def shortest_route(G: nx.DiGraph, start: str, end: str, weight: str, recommendation_type: str) -> RouteResult:
    path = nx.shortest_path(G, source=start, target=end, weight=weight)
    segments: List[RouteSegment] = []
    total_cost = 0.0
    total_time = 0.0

    for i in range(len(path) - 1):
        u = path[i]
        v = path[i + 1]
        data = G[u][v]
        seg = RouteSegment(
            from_node=u,
            to_node=v,
            mode=data.get("mode", ""),
            cost=float(data.get("cost", 0)),
            time=float(data.get("time", 0)),
            distance=data.get("distance"),
            distance_unit=data.get("distance_unit"),
            cost_source=data.get("cost_source"),
        )
        segments.append(seg)
        total_cost += seg.cost
        total_time += seg.time

    return RouteResult(
        recommendation_type=recommendation_type,
        path=path,
        segments=segments,
        total_cost=total_cost,
        total_time=total_time,
        explanation=f"按 {weight} 权重求得的最短路径。",
    )


def route_result_to_rows(result: RouteResult):
    rows = []
    for idx, seg in enumerate(result.segments, start=1):
        rows.append({
            "recommendation_type": result.recommendation_type,
            "segment_no": idx,
            "from_node": seg.from_node,
            "to_node": seg.to_node,
            "mode": seg.mode,
            "cost": seg.cost,
            "time": seg.time,
            "distance": seg.distance,
            "distance_unit": seg.distance_unit,
            "cost_source": seg.cost_source,
            "total_cost": result.total_cost,
            "total_time": result.total_time,
            "path": " -> ".join(result.path),
        })
    return rows
