from __future__ import annotations

import re
from typing import Literal


NodeRole = Literal[
    "port",
    "railway_station",
    "customer_facility",
    "unclassified",
]
PortWaterwayRole = Literal[
    "sea_port",
    "inland_port",
    "sea_inland_dual_use",
    "unknown_port",
    "not_port",
]

CUSTOMER_FACILITY_MARKERS = ("库", "仓", "公司")
PORT_MARKERS = ("港", "码头")
CARDINAL_SUFFIXES = ("东", "南", "西", "北")
CONFIRMED_CUSTOMER_FACILITY_NAMES = frozenset(
    {
        "东莞深粮",
        "平和县储备粮",
    }
)
CONFIRMED_SEA_PORT_NAMES = frozenset(
    {
        "漳州港",
        "揭阳港",
        "湛江港",
        "钦州港",
        "秀屿港",
        "马村港",
        "洋浦港",
        "福州松下码头",
        "福建松下码头",
        "松下码头",
    }
)
CONFIRMED_SEA_INLAND_DUAL_USE_NAMES = frozenset(
    {
        "广州南沙港",
        "广州港黄埔新港港区",
        "东莞新沙港",
        "深圳蛇口港",
        "深圳赤湾港",
        "军航码头",
        "福建军航码头",
        "福州马尾港",
        "马尾港",
    }
)
CONFIRMED_INLAND_PORT_NAMES = frozenset(
    {
        "南平港",
        "清远清新码头",
        "苏湾港",
        "贵港白沙码头",
        "贵港白沙",
        "韶关北江国际港（白土码头）",
    }
)
CONFIRMED_BULK_TRUNK_EXCLUSIONS = {
    "百达码头": "已按人工确认忽略，不作为当前路径规划节点。",
    "红东码头": "已按人工确认忽略，不作为当前路径规划节点。",
    "福州马尾港": "海河一体港，但当前仅确认集装箱玉米/小麦能力，不支持散粮散船干线。",
    "马尾港": "海河一体港，但当前仅确认集装箱玉米/小麦能力，不支持散粮散船干线。",
    "福州松下码头": "已确认海港身份，但散粮散船承接能力尚未确认。",
    "福建松下码头": "已确认海港身份，但散粮散船承接能力尚未确认。",
    "松下码头": "已确认海港身份，但散粮散船承接能力尚未确认。",
}


def infer_node_role_from_name(name: str) -> NodeRole:
    """Infer a conservative node role from the confirmed naming rules.

    Customer-facility markers take precedence over incidental ``港`` text in a
    company name. A customer-owned terminal must therefore be maintained as a
    separately named terminal node (normally containing ``港`` or ``码头`` but
    not the customer-company marker).
    """

    normalized = re.sub(r"\s+", "", str(name).strip())
    if normalized in CONFIRMED_CUSTOMER_FACILITY_NAMES:
        return "customer_facility"
    if any(marker in normalized for marker in CUSTOMER_FACILITY_MARKERS):
        return "customer_facility"
    if "站" in normalized or _looks_like_place_direction_station(normalized):
        return "railway_station"
    if any(marker in normalized for marker in PORT_MARKERS):
        return "port"
    return "unclassified"


def is_south_port_name(name: str) -> bool:
    return infer_node_role_from_name(name) == "port"


def infer_port_waterway_role(name: str, *aliases: str) -> PortWaterwayRole:
    roles = {
        role
        for candidate in (name, *aliases)
        if (role := _infer_single_port_waterway_role(candidate))
        not in {"unknown_port", "not_port"}
    }
    if len(roles) == 1:
        return next(iter(roles))
    if len(roles) > 1:
        return "unknown_port"
    if any(infer_node_role_from_name(candidate) == "port" for candidate in (name, *aliases)):
        return "unknown_port"
    return "not_port"


def _infer_single_port_waterway_role(name: str) -> PortWaterwayRole:
    normalized = re.sub(r"\s+", "", str(name).strip())
    if infer_node_role_from_name(normalized) != "port":
        return "not_port"
    if normalized in CONFIRMED_INLAND_PORT_NAMES:
        return "inland_port"
    if normalized in CONFIRMED_SEA_INLAND_DUAL_USE_NAMES:
        return "sea_inland_dual_use"
    if normalized in CONFIRMED_SEA_PORT_NAMES:
        return "sea_port"
    return "unknown_port"


def allows_north_south_bulk_candidate(
    name: str,
    *aliases: str,
    has_bulk_freight_origin_evidence: bool = False,
) -> bool:
    """Whether a port may receive the implemented north-to-south bulk trunk.

    Explicit port-role decisions take precedence. An otherwise unknown port may
    also enter the candidate pool when real freight data proves that it is an
    origin for an applicable bulk-grain route. Confirmed inland ports
    and explicit bulk-capability exclusions remain blocked even when such
    freight evidence exists.
    """

    if north_south_bulk_exclusion_reason(name, *aliases) is not None:
        return False
    waterway_role = infer_port_waterway_role(name, *aliases)
    if waterway_role in {"sea_port", "sea_inland_dual_use"}:
        return True
    return waterway_role == "unknown_port" and has_bulk_freight_origin_evidence


def has_confirmed_sea_access(name: str, *aliases: str) -> bool:
    """Whether the node has an explicit sea-port or sea/inland marker."""

    return infer_port_waterway_role(name, *aliases) in {
        "sea_port",
        "sea_inland_dual_use",
    }


def north_south_bulk_exclusion_reason(name: str, *aliases: str) -> str | None:
    reasons = {
        reason
        for candidate in (name, *aliases)
        if (
            reason := CONFIRMED_BULK_TRUNK_EXCLUSIONS.get(
                re.sub(r"\s+", "", str(candidate).strip())
            )
        )
        is not None
    }
    if not reasons:
        return None
    if len(reasons) == 1:
        return next(iter(reasons))
    return "同一标准节点的名称命中了多条不同散粮准入限制，需人工复核。"


def _looks_like_place_direction_station(name: str) -> bool:
    return len(name) >= 2 and name.endswith(CARDINAL_SUFFIXES)
