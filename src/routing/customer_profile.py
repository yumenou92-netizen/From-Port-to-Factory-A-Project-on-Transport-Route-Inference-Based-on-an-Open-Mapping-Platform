from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from heapq import nsmallest
from typing import Iterable, Literal


CustomerRouteStatus = Literal["resolved", "manual_review"]
CustomerRouteBranch = Literal["private_terminal", "transfer_terminal"]
CustomerCompatibilityStatus = Literal["eligible", "not_applicable", "manual_review"]
TransferPortSelectionStatus = Literal["resolved", "not_applicable", "manual_review"]
CustomerProfileConfirmationStatus = Literal["confirmed", "manual_review"]
CustomerTerminalRelationType = Literal["owned_terminal"]


class CustomerProfileError(ValueError):
    """Raised when customer-route structures cannot be represented safely."""


@dataclass(frozen=True)
class CustomerProfile:
    customer_id: str
    customer_name: str
    factory_node_id: str
    has_private_terminal: bool | None
    profile_source: str
    private_terminal_node_id: str | None = None
    private_terminal_flag_source: str | None = None
    private_terminal_node_source: str | None = None
    allowed_package_types: tuple[str, ...] | None = None
    allowed_commodities: tuple[str, ...] | None = None
    allowed_transport_modes: tuple[str, ...] | None = None
    confirmation_status: CustomerProfileConfirmationStatus = "manual_review"
    maintained_at: date | None = None

    def __post_init__(self) -> None:
        if self.has_private_terminal is not None and not isinstance(self.has_private_terminal, bool):
            raise CustomerProfileError("自有码头标志必须是布尔值或空值。")

        object.__setattr__(self, "customer_id", _required_text(self.customer_id, "客户 ID"))
        object.__setattr__(self, "customer_name", _required_text(self.customer_name, "客户名称"))
        object.__setattr__(self, "factory_node_id", _required_text(self.factory_node_id, "客户工厂节点"))
        object.__setattr__(self, "profile_source", _required_text(self.profile_source, "客户画像来源"))
        object.__setattr__(
            self,
            "private_terminal_node_id",
            _optional_text(self.private_terminal_node_id),
        )
        object.__setattr__(
            self,
            "private_terminal_flag_source",
            _optional_text(self.private_terminal_flag_source),
        )
        object.__setattr__(
            self,
            "private_terminal_node_source",
            _optional_text(self.private_terminal_node_source),
        )
        object.__setattr__(
            self,
            "allowed_package_types",
            _normalize_optional_values(self.allowed_package_types, "允许包装方式"),
        )
        object.__setattr__(
            self,
            "allowed_commodities",
            _normalize_optional_values(self.allowed_commodities, "允许品种"),
        )
        object.__setattr__(
            self,
            "allowed_transport_modes",
            _normalize_optional_values(self.allowed_transport_modes, "允许运输方式"),
        )
        if self.confirmation_status not in {"confirmed", "manual_review"}:
            raise CustomerProfileError(f"不支持的客户画像确认状态：{self.confirmation_status}")
        if self.maintained_at is not None and not isinstance(self.maintained_at, date):
            raise CustomerProfileError("客户画像维护日期必须是 date 或 None。")


@dataclass(frozen=True)
class CustomerTerminalRelation:
    """Source-backed relation between a customer and its private terminal node."""

    customer_id: str
    terminal_node_id: str
    source: str
    relation_type: CustomerTerminalRelationType = "owned_terminal"
    confirmation_status: CustomerProfileConfirmationStatus = "manual_review"
    maintained_at: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_id", _required_text(self.customer_id, "客户 ID"))
        object.__setattr__(
            self,
            "terminal_node_id",
            _required_text(self.terminal_node_id, "客户自有码头节点 ID"),
        )
        object.__setattr__(self, "source", _required_text(self.source, "客户码头关系来源"))
        if self.relation_type != "owned_terminal":
            raise CustomerProfileError(f"不支持的客户码头关系类型：{self.relation_type}")
        if self.confirmation_status not in {"confirmed", "manual_review"}:
            raise CustomerProfileError(
                f"不支持的客户码头关系确认状态：{self.confirmation_status}"
            )
        if self.maintained_at is not None and not isinstance(self.maintained_at, date):
            raise CustomerProfileError("客户码头关系维护日期必须是 date 或 None。")

    @property
    def is_confirmed(self) -> bool:
        return self.confirmation_status == "confirmed"


@dataclass(frozen=True)
class CustomerRouteDecision:
    status: CustomerRouteStatus
    branch: CustomerRouteBranch | None
    customer_id: str
    south_port_node_id: str
    factory_node_id: str
    private_terminal_node_id: str | None
    profile_source: str
    private_terminal_flag_source: str | None
    private_terminal_node_source: str | None
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "private_terminal_node_id",
            _optional_text(self.private_terminal_node_id),
        )
        object.__setattr__(
            self,
            "private_terminal_flag_source",
            _optional_text(self.private_terminal_flag_source),
        )
        object.__setattr__(
            self,
            "private_terminal_node_source",
            _optional_text(self.private_terminal_node_source),
        )

        if self.status not in {"resolved", "manual_review"}:
            raise CustomerProfileError(f"不支持的客户路线状态：{self.status}")
        if self.branch not in {None, "private_terminal", "transfer_terminal"}:
            raise CustomerProfileError(f"不支持的客户路线分支：{self.branch}")
        if self.status == "resolved" and self.branch is None:
            raise CustomerProfileError("已确认的客户路线必须包含路线分支。")
        if self.status == "manual_review" and self.branch is not None:
            raise CustomerProfileError("人工复核路线不得包含可执行分支。")
        if self.status == "resolved" and self.private_terminal_flag_source is None:
            raise CustomerProfileError("已确认的客户路线必须包含自有码头标志来源。")
        if self.branch == "private_terminal" and not self.private_terminal_node_id:
            raise CustomerProfileError("自有码头路线必须包含码头节点。")
        if self.branch == "private_terminal" and self.private_terminal_node_source is None:
            raise CustomerProfileError("自有码头路线必须包含码头节点来源。")
        if self.branch == "transfer_terminal" and self.private_terminal_node_id is not None:
            raise CustomerProfileError("中转港路线不得携带客户自有码头节点。")
        if self.branch == "transfer_terminal" and self.private_terminal_node_source is not None:
            raise CustomerProfileError("中转港路线不得携带客户自有码头节点来源。")

        object.__setattr__(self, "customer_id", _required_text(self.customer_id, "客户 ID"))
        object.__setattr__(self, "south_port_node_id", _required_text(self.south_port_node_id, "南港节点"))
        object.__setattr__(self, "factory_node_id", _required_text(self.factory_node_id, "客户工厂节点"))
        object.__setattr__(self, "profile_source", _required_text(self.profile_source, "客户画像来源"))
        object.__setattr__(self, "message", _required_text(self.message, "客户路线说明"))

    @property
    def requires_transfer_port(self) -> bool:
        return self.status == "resolved" and self.branch == "transfer_terminal"

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


@dataclass(frozen=True)
class CustomerCompatibilityResult:
    status: CustomerCompatibilityStatus
    customer_id: str
    package_type: str
    commodity: str
    source: str
    issues: tuple[str, ...]
    message: str

    @property
    def is_eligible(self) -> bool:
        return self.status == "eligible"

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


@dataclass(frozen=True)
class TransferPortCandidate:
    port_node_id: str
    distance_km: Decimal | object
    distance_source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "port_node_id", _required_text(self.port_node_id, "候选中转港节点"))
        object.__setattr__(self, "distance_km", _positive_decimal(self.distance_km, "候选港距离"))
        object.__setattr__(self, "distance_source", _required_text(self.distance_source, "候选港距离来源"))


@dataclass(frozen=True)
class TransferPortSelection:
    status: TransferPortSelectionStatus
    selected_candidates: tuple[TransferPortCandidate, ...]
    requested_k: int
    available_candidate_count: int
    selection_rule: str
    requires_cost_time_comparison: bool
    message: str

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "not_applicable", "manual_review"}:
            raise CustomerProfileError(f"不支持的候选港筛选状态：{self.status}")
        if self.requested_k <= 0:
            raise CustomerProfileError("候选港 K 必须是正整数。")
        if self.available_candidate_count < 0:
            raise CustomerProfileError("候选港数量不能为负数。")
        if self.status == "resolved":
            if not self.selected_candidates:
                raise CustomerProfileError("已完成的候选港筛选必须包含候选港。")
            if not self.requires_cost_time_comparison:
                raise CustomerProfileError("距离预筛后必须继续比较总费用和总时间。")
        elif self.selected_candidates or self.requires_cost_time_comparison:
            raise CustomerProfileError("非有效候选港筛选不得包含可执行候选。")

        object.__setattr__(self, "selection_rule", _required_text(self.selection_rule, "候选港筛选规则"))
        object.__setattr__(self, "message", _required_text(self.message, "候选港筛选说明"))

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


def resolve_customer_route(
    profile: CustomerProfile,
    *,
    south_port_node_id: str,
) -> CustomerRouteDecision:
    """Resolve the mutually exclusive second-stage route branch."""
    south_port = _required_text(south_port_node_id, "南港节点")

    if profile.confirmation_status != "confirmed":
        return _manual_route_review(profile, south_port, "客户画像尚未确认，不能生成可执行路线分支。")
    if profile.has_private_terminal is None:
        return _manual_route_review(profile, south_port, "客户是否有自有码头尚未确认，不能猜测路线分支。")
    if profile.private_terminal_flag_source is None:
        return _manual_route_review(profile, south_port, "自有码头字段来源缺失，不能形成可追溯路线。")

    if profile.has_private_terminal:
        if profile.private_terminal_node_id is None:
            return _manual_route_review(profile, south_port, "客户标记为有自有码头，但缺少码头节点。")
        if profile.private_terminal_node_source is None:
            return _manual_route_review(profile, south_port, "客户自有码头节点来源缺失，不能形成可追溯路线。")
        return CustomerRouteDecision(
            status="resolved",
            branch="private_terminal",
            customer_id=profile.customer_id,
            south_port_node_id=south_port,
            factory_node_id=profile.factory_node_id,
            private_terminal_node_id=profile.private_terminal_node_id,
            profile_source=profile.profile_source,
            private_terminal_flag_source=profile.private_terminal_flag_source,
            private_terminal_node_source=profile.private_terminal_node_source,
            message="客户有自有码头，只允许南港至客户自有码头的水路交付分支。",
        )

    if profile.private_terminal_node_id is not None or profile.private_terminal_node_source is not None:
        return _manual_route_review(
            profile,
            south_port,
            "客户标记为无自有码头，但档案仍包含自有码头节点信息，字段相互矛盾。",
        )

    return CustomerRouteDecision(
        status="resolved",
        branch="transfer_terminal",
        customer_id=profile.customer_id,
        south_port_node_id=south_port,
        factory_node_id=profile.factory_node_id,
        private_terminal_node_id=None,
        profile_source=profile.profile_source,
        private_terminal_flag_source=profile.private_terminal_flag_source,
        private_terminal_node_source=None,
        message="客户无自有码头，只允许经候选中转港和短途汽运到客户工厂的分支。",
    )


def evaluate_customer_compatibility(
    profile: CustomerProfile,
    *,
    package_type: str,
    commodity: str,
) -> CustomerCompatibilityResult:
    """Evaluate explicit customer package and commodity restrictions."""
    normalized_package = _required_text(package_type, "包装方式")
    normalized_commodity = _required_text(commodity, "货物品种")
    if profile.confirmation_status != "confirmed":
        return CustomerCompatibilityResult(
            status="manual_review",
            customer_id=profile.customer_id,
            package_type=normalized_package,
            commodity=normalized_commodity,
            source=profile.profile_source,
            issues=("客户画像尚未确认。",),
            message="客户画像尚未确认，不能据此判断包装方式或货物品种可行性。",
        )
    issues: list[str] = []
    missing_rules = False
    unsupported = False

    if profile.allowed_package_types is None:
        missing_rules = True
        issues.append("客户允许包装方式尚未配置。")
    elif normalized_package not in profile.allowed_package_types:
        unsupported = True
        issues.append(f"客户档案不支持包装方式 {normalized_package}。")

    if profile.allowed_commodities is None:
        missing_rules = True
        issues.append("客户允许品种尚未配置。")
    elif normalized_commodity not in profile.allowed_commodities:
        unsupported = True
        issues.append(f"客户档案不支持货物品种 {normalized_commodity}。")

    if missing_rules:
        status: CustomerCompatibilityStatus = "manual_review"
        message = "；".join(issues) + "请补充完整、可追溯的客户档案后再判断。"
    elif unsupported:
        status: CustomerCompatibilityStatus = "not_applicable"
        message = "；".join(issues)
    else:
        status = "eligible"
        message = "包装方式和货物品种均在客户档案允许范围内。"

    return CustomerCompatibilityResult(
        status=status,
        customer_id=profile.customer_id,
        package_type=normalized_package,
        commodity=normalized_commodity,
        source=profile.profile_source,
        issues=tuple(issues),
        message=message,
    )


def prefilter_transfer_ports(
    route_decision: CustomerRouteDecision,
    candidates: Iterable[TransferPortCandidate],
    *,
    k: int,
) -> TransferPortSelection:
    """Select nearest K transfer ports without treating distance as final optimality."""
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise CustomerProfileError("候选港 K 必须是正整数。")

    candidate_list = list(candidates)
    if any(not isinstance(candidate, TransferPortCandidate) for candidate in candidate_list):
        raise CustomerProfileError("候选港列表只能包含 TransferPortCandidate。")

    base_kwargs = {
        "requested_k": k,
        "available_candidate_count": len(candidate_list),
        "selection_rule": "distance_ascending_then_node_id",
    }

    if route_decision.requires_manual_review:
        return TransferPortSelection(
            status="manual_review",
            selected_candidates=(),
            requires_cost_time_comparison=False,
            message="客户路线分支尚未确认，不能生成候选中转港。",
            **base_kwargs,
        )

    if route_decision.branch == "private_terminal":
        return TransferPortSelection(
            status="not_applicable",
            selected_candidates=(),
            requires_cost_time_comparison=False,
            message="客户有自有码头，不得生成中转港路线。",
            **base_kwargs,
        )

    if not route_decision.requires_transfer_port:
        return TransferPortSelection(
            status="manual_review",
            selected_candidates=(),
            requires_cost_time_comparison=False,
            message="客户路线不是已确认的中转港分支，不能生成候选中转港。",
            **base_kwargs,
        )

    if not candidate_list:
        return TransferPortSelection(
            status="manual_review",
            selected_candidates=(),
            requires_cost_time_comparison=False,
            message="客户无自有码头，但没有可用的候选中转港。",
            **base_kwargs,
        )

    candidate_id_counts = Counter(candidate.port_node_id for candidate in candidate_list)
    duplicate_ids = sorted(
        node_id for node_id, count in candidate_id_counts.items() if count > 1
    )
    if duplicate_ids:
        return TransferPortSelection(
            status="manual_review",
            selected_candidates=(),
            requires_cost_time_comparison=False,
            message=f"候选中转港节点重复：{'、'.join(duplicate_ids)}，请先合并或确认距离记录。",
            **base_kwargs,
        )

    selected = tuple(
        nsmallest(
            k,
            candidate_list,
            key=lambda candidate: (
                candidate.distance_km,
                candidate.port_node_id,
                candidate.distance_source,
            ),
        )
    )
    return TransferPortSelection(
        status="resolved",
        selected_candidates=selected,
        requires_cost_time_comparison=True,
        message=(
            f"已按确认距离升序预筛前 {k} 个候选中转港；距离仅用于预筛，"
            "保留候选仍必须分别比较全链路总费用和总时间。"
        ),
        **base_kwargs,
    )


def _manual_route_review(
    profile: CustomerProfile,
    south_port_node_id: str,
    message: str,
) -> CustomerRouteDecision:
    return CustomerRouteDecision(
        status="manual_review",
        branch=None,
        customer_id=profile.customer_id,
        south_port_node_id=south_port_node_id,
        factory_node_id=profile.factory_node_id,
        private_terminal_node_id=None,
        profile_source=profile.profile_source,
        private_terminal_flag_source=profile.private_terminal_flag_source,
        private_terminal_node_source=profile.private_terminal_node_source,
        message=message,
    )


def _normalize_optional_values(
    values: tuple[str, ...] | Iterable[str] | None,
    field_name: str,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise CustomerProfileError(f"{field_name}必须是字符串集合，不能是单个字符串。")

    normalized: list[str] = []
    for value in values:
        text = _required_text(value, field_name)
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise CustomerProfileError(f"{field_name}必须是大于 0 的有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise CustomerProfileError(f"{field_name}必须是大于 0 的有限数值。") from None
    if not number.is_finite() or number <= 0:
        raise CustomerProfileError(f"{field_name}必须是大于 0 的有限数值。")
    return number


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise CustomerProfileError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
