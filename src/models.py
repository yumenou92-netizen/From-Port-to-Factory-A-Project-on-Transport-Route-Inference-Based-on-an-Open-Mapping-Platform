from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class Node:
    node_id: str
    node_name: str
    node_type: str
    longitude: float
    latitude: float
    region: str = ""
    is_active: bool = True

@dataclass
class Customer:
    customer_id: str
    customer_name: str
    factory_longitude: float
    factory_latitude: float
    address: str
    region: str
    has_private_terminal: bool
    private_terminal_id: Optional[str] = None

@dataclass
class RouteSegment:
    from_node: str
    to_node: str
    mode: str
    cost: float
    time: float
    distance: Optional[float] = None
    distance_unit: Optional[str] = None
    cost_source: Optional[str] = None

@dataclass
class RouteResult:
    recommendation_type: str
    path: List[str]
    segments: List[RouteSegment]
    total_cost: float
    total_time: float
    missing_data_flag: bool = False
    explanation: str = ""
