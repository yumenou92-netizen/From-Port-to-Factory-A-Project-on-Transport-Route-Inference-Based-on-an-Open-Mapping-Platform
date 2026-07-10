from pathlib import Path
from io_utils import read_csv_table, write_result_csv
from graph_builder import build_directed_graph
from route_planner import shortest_route, route_result_to_rows


def main():
    root = Path(__file__).resolve().parents[1]
    edges = read_csv_table(root / "sample_data" / "transport_edges.csv")
    G = build_directed_graph(edges)

    start = "NP_A"
    end = "CUST_001"

    cost_result = shortest_route(G, start, end, weight="cost", recommendation_type="成本最低方案")
    time_result = shortest_route(G, start, end, weight="time", recommendation_type="时效最优方案")

    rows = route_result_to_rows(cost_result) + route_result_to_rows(time_result)
    output_path = root / "output" / "route_results.csv"
    write_result_csv(rows, output_path)

    print("已输出结果:", output_path)
    print("成本最低路径:", " -> ".join(cost_result.path), "总费用:", cost_result.total_cost, "总时效:", cost_result.total_time)
    print("时效最优路径:", " -> ".join(time_result.path), "总费用:", time_result.total_cost, "总时效:", time_result.total_time)


if __name__ == "__main__":
    main()
