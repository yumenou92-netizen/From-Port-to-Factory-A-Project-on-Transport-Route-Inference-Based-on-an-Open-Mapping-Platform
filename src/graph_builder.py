import networkx as nx
import pandas as pd


def build_directed_graph(edges_df: pd.DataFrame) -> nx.DiGraph:
    """Build a directed weighted graph from transport_edges.csv.

    Required columns:
    - from_node_id
    - to_node_id
    - transport_mode
    - base_cost
    - base_time
    """
    G = nx.DiGraph()

    active_edges = edges_df[edges_df["is_active"].astype(str).str.lower().isin(["true", "1", "yes"])]

    for _, row in active_edges.iterrows():
        G.add_edge(
            row["from_node_id"],
            row["to_node_id"],
            edge_id=row.get("edge_id"),
            mode=row.get("transport_mode"),
            cost=float(row.get("base_cost", 0)),
            time=float(row.get("base_time", 0)),
            distance=float(row.get("distance", 0)) if not pd.isna(row.get("distance", 0)) else None,
            distance_unit=row.get("distance_unit"),
            cost_source=row.get("cost_source"),
            rule_type=row.get("rule_type"),
        )

    return G
