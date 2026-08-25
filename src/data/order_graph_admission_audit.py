from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, fields, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.data.loaders import (
    RealDataBundle,
    build_order_edge_candidates_for_request,
)
from src.data.port_reference import load_port_reference_tables
from src.domain.cost_rules import is_truck_transport_mode
from src.domain.freight_rate import FreightRate
from src.domain.node_role import (
    NodeRole,
    PortWaterwayRole,
    allows_north_south_bulk_candidate,
    infer_node_role_from_name,
    infer_port_waterway_role,
    north_south_bulk_exclusion_reason,
)
from src.domain.route_request import (
    ALLOWED_TRADE_TYPES,
    PACKAGING_QUANTITY_UNITS,
    RouteRequest,
)
from src.routing.bulk_shipping_provider import (
    BulkShippingMatch,
    BulkShippingWorkbook,
    classify_bulk_shipping_destination,
    parse_vessel_capacity,
)
from src.routing.port_operation_fee_provider import (
    PortOperationFeeQuote,
    SouthPortOperationFeeProvider,
    TablePortOperationFeeProvider,
    find_optional_port_operation_fee_file,
)


BULK_RATE_FILE_NAME = "散船运价表.xlsx"
DEFAULT_OUTPUT_DIR = Path("output")
BASE_BULK_QUANTITIES = (Decimal("500"), Decimal("2450"))
NON_BULK_QUANTITIES = (Decimal("1"), Decimal("500"))
PACKAGE_ORDER = ("散粮", "集装箱")
UNIT_ORDER = ("吨", "箱", "柜")
TRADE_TYPE_ORDER = ("内贸", "外贸")
COMMODITY_ORDER = ("玉米", "小麦", "大豆")


@dataclass(frozen=True)
class OrderScenario:
    scenario_id: str
    quantity: str
    quantity_unit: str
    package_type: str
    commodity: str
    trade_type: str

    def to_request(self) -> RouteRequest:
        return RouteRequest(
            quantity=self.quantity,
            quantity_unit=self.quantity_unit,
            package_type=self.package_type,
            commodity=self.commodity,
            trade_type=self.trade_type,
        )


@dataclass(frozen=True)
class TransferOrigin:
    node_id: str
    port_name: str
    source_names: tuple[str, ...]
    inferred_node_role: NodeRole
    port_waterway_role: PortWaterwayRole
    has_bulk_freight_origin_evidence: bool
    is_automatic_port_candidate: bool
    rates: tuple[FreightRate, ...]

    @property
    def selection_scope(self) -> str:
        if self.is_automatic_port_candidate:
            return "automatic_port_candidate"
        if self.inferred_node_role == "railway_station":
            return "excluded_railway_station"
        if self.inferred_node_role == "customer_facility":
            return "excluded_customer_facility"
        if self.port_waterway_role == "inland_port":
            return "excluded_inland_port"
        if north_south_bulk_exclusion_reason(
            self.port_name,
            *self.source_names,
        ) is not None:
            return "excluded_bulk_capability"
        if (
            self.inferred_node_role == "port"
            and self.port_waterway_role == "unknown_port"
            and not self.has_bulk_freight_origin_evidence
        ):
            if any(rate.package_type == "集装箱" for rate in self.rates):
                return "potential_transfer_port_pending_confirmation"
            return "registered_port_manual_only"
        if self.inferred_node_role == "port":
            return "registered_port_manual_only"
        return "exact_customer_rate_preferred_only"


@dataclass(frozen=True)
class PortAdmissionRow:
    scenario_id: str
    quantity: str
    quantity_unit: str
    package_type: str
    commodity: str
    trade_type: str
    port_node_id: str
    port_name: str
    source_names: str
    inferred_node_role: str
    port_waterway_role: str
    selection_scope: str
    matching_last_mile_rate_count: int
    last_mile_source_status: str
    bulk_shipping_status: str
    bulk_destination_label: str
    bulk_time_region: str
    selected_vessel_type: str
    selected_vessel_max_tons: str
    bulk_shipping_message: str
    operation_fee_status: str
    operation_fee_source_type: str
    operation_fee_reference_port: str
    operation_fee_message: str
    offline_admission_status: str
    manual_selection_status: str
    blocking_codes: str
    tencent_road_status: str


@dataclass(frozen=True)
class AdmissionIssueRow:
    scenario_id: str
    quantity: str
    quantity_unit: str
    package_type: str
    commodity: str
    trade_type: str
    port_node_id: str
    port_name: str
    inferred_node_role: str
    selection_scope: str
    stage: str
    issue_code: str
    issue_category: str
    review_priority: str
    manual_confirmation_required: bool
    message: str
    suggested_action: str


@dataclass(frozen=True)
class ScenarioSummaryRow:
    scenario_id: str
    quantity: str
    quantity_unit: str
    package_type: str
    commodity: str
    trade_type: str
    rate_candidates: int
    rate_graph_ready_candidates: int
    rate_missing_node_candidates: int
    rate_manual_review_items: int
    automatic_port_origin_count: int
    automatic_order_candidate_count: int
    not_order_candidate_count: int
    ready_pending_tencent_count: int
    blocked_before_tencent_count: int
    conditional_origin_count: int
    issue_count: int
    manual_confirmation_issue_count: int


@dataclass(frozen=True)
class ManualReviewGroup:
    review_priority: str
    stage: str
    issue_code: str
    issue_category: str
    port_node_id: str
    port_name: str
    inferred_node_role: str
    selection_scope: str
    scenario_count: int
    scenario_ids: str
    package_types: str
    quantity_units: str
    commodities: str
    trade_types: str
    quantities: str
    example_message: str
    suggested_action: str


@dataclass(frozen=True)
class OrderGraphAdmissionAudit:
    audit_scope: str
    tencent_called: bool
    scenario_count: int
    transfer_origin_count: int
    automatic_port_origin_count: int
    conditional_origin_count: int
    commodities: tuple[str, ...]
    package_unit_pairs: tuple[str, ...]
    trade_types: tuple[str, ...]
    bulk_quantity_profiles: tuple[str, ...]
    non_bulk_quantity_profiles: tuple[str, ...]
    scenario_rows: tuple[ScenarioSummaryRow, ...]
    port_rows: tuple[PortAdmissionRow, ...]
    issue_rows: tuple[AdmissionIssueRow, ...]
    manual_review_rows: tuple[ManualReviewGroup, ...]


def discover_order_scenarios(
    bundle: RealDataBundle,
    workbook: BulkShippingWorkbook,
) -> tuple[OrderScenario, ...]:
    commodities = _discover_commodities(bundle.freight_rates)
    bulk_quantities = discover_bulk_quantity_profiles(workbook)
    scenarios: list[OrderScenario] = []

    package_types = sorted(
        PACKAGING_QUANTITY_UNITS,
        key=lambda value: (_ordered_index(value, PACKAGE_ORDER), value),
    )
    trade_types = sorted(
        ALLOWED_TRADE_TYPES,
        key=lambda value: (_ordered_index(value, TRADE_TYPE_ORDER), value),
    )
    for package_type in package_types:
        units = sorted(
            PACKAGING_QUANTITY_UNITS[package_type],
            key=lambda value: (_ordered_index(value, UNIT_ORDER), value),
        )
        for quantity_unit in units:
            quantities = (
                bulk_quantities
                if package_type == "散粮" and quantity_unit == "吨"
                else NON_BULK_QUANTITIES
            )
            for commodity in commodities:
                for trade_type in trade_types:
                    for quantity in quantities:
                        scenarios.append(
                            OrderScenario(
                                scenario_id=f"S{len(scenarios) + 1:03d}",
                                quantity=_decimal_text(quantity),
                                quantity_unit=quantity_unit,
                                package_type=package_type,
                                commodity=commodity,
                                trade_type=trade_type,
                            )
                        )
    return tuple(scenarios)


def discover_bulk_quantity_profiles(
    workbook: BulkShippingWorkbook,
) -> tuple[Decimal, ...]:
    capacities = sorted(
        {
            capacity.max_tons
            for column in workbook.columns
            if (capacity := parse_vessel_capacity(column.vessel_type)) is not None
        }
    )
    values = set(BASE_BULK_QUANTITIES)
    for capacity in capacities:
        values.add(capacity)
        values.add(capacity + Decimal("1"))
    return tuple(sorted(values))


def discover_transfer_origins(bundle: RealDataBundle) -> tuple[TransferOrigin, ...]:
    grouped: dict[str, list[FreightRate]] = defaultdict(list)
    names: dict[str, set[str]] = defaultdict(set)
    registry = bundle.node_registry

    for rate in bundle.freight_rates:
        key = rate.from_node_id or f"name:{_normalize_name(rate.origin_name)}"
        grouped[key].append(rate)
        names[key].add(rate.origin_name)

    origins: list[TransferOrigin] = []
    for key, rates in grouped.items():
        node_id = rates[0].from_node_id or ""
        node = registry.nodes.get(node_id) if registry is not None and node_id else None
        port_name = node.canonical_name if node is not None else sorted(names[key])[0]
        inferred_role = infer_node_role_from_name(port_name)
        source_names = tuple(sorted(names[key]))
        aliases = node.aliases if node is not None else ()
        has_bulk_evidence = any(rate.package_type == "散粮" for rate in rates)
        waterway_role = infer_port_waterway_role(
            port_name,
            *source_names,
            *aliases,
        )
        origins.append(
            TransferOrigin(
                node_id=node_id,
                port_name=port_name,
                source_names=tuple(dict.fromkeys((*source_names, *aliases))),
                inferred_node_role=inferred_role,
                port_waterway_role=waterway_role,
                has_bulk_freight_origin_evidence=has_bulk_evidence,
                is_automatic_port_candidate=(
                    inferred_role == "port"
                    and allows_north_south_bulk_candidate(
                        port_name,
                        *source_names,
                        *aliases,
                        has_bulk_freight_origin_evidence=has_bulk_evidence,
                    )
                ),
                rates=tuple(rates),
            )
        )
    if registry is not None:
        grouped_node_ids = {
            rate.from_node_id
            for rates in grouped.values()
            for rate in rates
            if rate.from_node_id is not None
        }
        for node in registry.nodes.values():
            inferred_role = infer_node_role_from_name(node.canonical_name)
            waterway_role = infer_port_waterway_role(
                node.canonical_name,
                *node.aliases,
            )
            if node.node_id in grouped_node_ids or inferred_role != "port":
                continue
            origins.append(
                TransferOrigin(
                    node_id=node.node_id,
                    port_name=node.canonical_name,
                    source_names=(node.canonical_name, *node.aliases),
                    inferred_node_role=inferred_role,
                    port_waterway_role=waterway_role,
                    has_bulk_freight_origin_evidence=False,
                    is_automatic_port_candidate=False,
                    rates=(),
                )
            )
    return tuple(
        sorted(
            origins,
            key=lambda item: (
                not item.is_automatic_port_candidate,
                item.port_name,
                item.node_id,
            ),
        )
    )


def build_order_graph_admission_audit(
    bundle: RealDataBundle,
    *,
    workbook: BulkShippingWorkbook,
    operation_fee_provider: SouthPortOperationFeeProvider | None,
    scenarios: Sequence[OrderScenario] | None = None,
) -> OrderGraphAdmissionAudit:
    resolved_scenarios = tuple(scenarios or discover_order_scenarios(bundle, workbook))
    origins = discover_transfer_origins(bundle)
    port_rows: list[PortAdmissionRow] = []
    issue_rows: list[AdmissionIssueRow] = []
    scenario_rows: list[ScenarioSummaryRow] = []

    for scenario in resolved_scenarios:
        request = scenario.to_request()
        rate_result = build_order_edge_candidates_for_request(bundle, request)
        scenario_port_rows: list[PortAdmissionRow] = []
        scenario_issues: list[AdmissionIssueRow] = []
        matching_port_like_count = sum(
            origin.is_automatic_port_candidate
            and bool(_matching_origin_rates(origin, request))
            for origin in origins
        )

        for origin in origins:
            scenario_origin = origin
            if (
                not origin.is_automatic_port_candidate
                and origin.inferred_node_role == "unclassified"
                and matching_port_like_count < 2
                and _matching_origin_rates(origin, request)
            ):
                scenario_origin = replace(
                    origin,
                    is_automatic_port_candidate=True,
                )
            port_row, port_issues = _audit_port_for_scenario(
                scenario_origin,
                scenario,
                request=request,
                workbook=workbook,
                operation_fee_provider=operation_fee_provider,
            )
            scenario_port_rows.append(port_row)
            scenario_issues.extend(port_issues)

        automatic_rows = [
            row
            for row in scenario_port_rows
            if row.selection_scope == "automatic_port_candidate"
        ]
        scenario_rows.append(
            ScenarioSummaryRow(
                scenario_id=scenario.scenario_id,
                quantity=scenario.quantity,
                quantity_unit=scenario.quantity_unit,
                package_type=scenario.package_type,
                commodity=scenario.commodity,
                trade_type=scenario.trade_type,
                rate_candidates=len(rate_result.candidates),
                rate_graph_ready_candidates=len(rate_result.graph_ready_candidates),
                rate_missing_node_candidates=rate_result.missing_node_candidate_count,
                rate_manual_review_items=rate_result.manual_review_count,
                automatic_port_origin_count=len(automatic_rows),
                automatic_order_candidate_count=sum(
                    row.last_mile_source_status
                    in {"resolved", "confirmed_rule_fallback"}
                    for row in automatic_rows
                ),
                not_order_candidate_count=sum(
                    row.offline_admission_status == "not_candidate_for_order"
                    for row in automatic_rows
                ),
                ready_pending_tencent_count=sum(
                    row.offline_admission_status == "ready_pending_tencent"
                    for row in automatic_rows
                ),
                blocked_before_tencent_count=sum(
                    row.offline_admission_status == "blocked_before_tencent"
                    for row in automatic_rows
                ),
                conditional_origin_count=sum(
                    row.offline_admission_status == "conditional_exact_customer_rate"
                    for row in scenario_port_rows
                ),
                issue_count=len(scenario_issues),
                manual_confirmation_issue_count=sum(
                    issue.manual_confirmation_required for issue in scenario_issues
                ),
            )
        )
        port_rows.extend(scenario_port_rows)
        issue_rows.extend(scenario_issues)

    package_unit_pairs = tuple(
        f"{package_type}/{unit}"
        for package_type in sorted(
            PACKAGING_QUANTITY_UNITS,
            key=lambda value: (_ordered_index(value, PACKAGE_ORDER), value),
        )
        for unit in sorted(
            PACKAGING_QUANTITY_UNITS[package_type],
            key=lambda value: (_ordered_index(value, UNIT_ORDER), value),
        )
    )
    bulk_quantities = discover_bulk_quantity_profiles(workbook)
    commodities = tuple(
        sorted(
            {scenario.commodity for scenario in resolved_scenarios},
            key=lambda value: (_ordered_index(value, COMMODITY_ORDER), value),
        )
    )
    trades = tuple(
        sorted(
            {scenario.trade_type for scenario in resolved_scenarios},
            key=lambda value: (_ordered_index(value, TRADE_TYPE_ORDER), value),
        )
    )
    manual_review_rows = build_manual_review_groups(issue_rows)
    return OrderGraphAdmissionAudit(
        audit_scope=(
            "当前 full-flow 候选来源、散船干线和码头作业费的离线准入；"
            "不调用 Tencent，不证明道路段已实际入图"
        ),
        tencent_called=False,
        scenario_count=len(resolved_scenarios),
        transfer_origin_count=len(origins),
        automatic_port_origin_count=sum(
            origin.is_automatic_port_candidate for origin in origins
        ),
        conditional_origin_count=sum(
            not origin.is_automatic_port_candidate for origin in origins
        ),
        commodities=commodities,
        package_unit_pairs=package_unit_pairs,
        trade_types=trades,
        bulk_quantity_profiles=tuple(_decimal_text(value) for value in bulk_quantities),
        non_bulk_quantity_profiles=tuple(
            _decimal_text(value) for value in NON_BULK_QUANTITIES
        ),
        scenario_rows=tuple(scenario_rows),
        port_rows=tuple(port_rows),
        issue_rows=tuple(issue_rows),
        manual_review_rows=manual_review_rows,
    )


def _audit_port_for_scenario(
    origin: TransferOrigin,
    scenario: OrderScenario,
    *,
    request: RouteRequest,
    workbook: BulkShippingWorkbook,
    operation_fee_provider: SouthPortOperationFeeProvider | None,
) -> tuple[PortAdmissionRow, tuple[AdmissionIssueRow, ...]]:
    issues: list[AdmissionIssueRow] = []
    bulk_exclusion_reason = north_south_bulk_exclusion_reason(
        origin.port_name,
        *origin.source_names,
    )
    matching_freight_origin_rates = _matching_freight_origin_rates(origin, request)
    matching_rates = _matching_origin_rates(origin, request)
    has_scenario_bulk_evidence = (
        request.package_type == "散粮"
        and request.quantity_unit == "吨"
        and bool(matching_freight_origin_rates)
    )
    last_mile_status = (
        "resolved"
        if matching_rates
        else "confirmed_rule_fallback"
        if has_scenario_bulk_evidence
        else "missing"
    )
    eligible_bulk_candidate = allows_north_south_bulk_candidate(
        origin.port_name,
        *origin.source_names,
        has_bulk_freight_origin_evidence=has_scenario_bulk_evidence,
    )
    excluded_confirmed_role = origin.inferred_node_role in {
        "railway_station",
        "customer_facility",
    } or origin.port_waterway_role == "inland_port" or (
        origin.inferred_node_role == "port" and not eligible_bulk_candidate
    ) or bulk_exclusion_reason is not None
    if not matching_rates:
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="candidate_source",
                issue_code="no_matching_last_mile_origin_rate",
                issue_category="data_gap",
                manual_confirmation_required=not has_scenario_bulk_evidence,
                message=(
                    f"{origin.port_name} 没有匹配 {request.package_type}/"
                    f"{request.commodity} 的南港至客户汽运始发记录；"
                    + (
                        "该港已有适用散粮始发运价证据，腾讯道路结果可用时将采用已确认陌生汽运规则。"
                        if has_scenario_bulk_evidence
                        else "当前不会进入本订单的自动南港候选池。"
                    )
                ),
                suggested_action=(
                    "后续可补充对应包装和品种的已维护汽运价；"
                    "在此之前保留已确认陌生汽运规则及其来源标签。"
                    if has_scenario_bulk_evidence
                    else "确认该节点是否应作为本订单类型的南港候选；如应进入，补充适用的散粮始发运价证据。"
                ),
            )
        )
    if not origin.node_id:
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="node_registration",
                issue_code="missing_standard_node_id",
                issue_category="data_gap",
                message=f"{origin.port_name} 缺少标准 node_id，不能形成正式运输边端点。",
                suggested_action="补充标准节点坐标和唯一 node_id，并通过名称字典维护明确别名。",
            )
        )
    if origin.inferred_node_role in {"railway_station", "customer_facility"}:
        role_text = (
            "铁路站点"
            if origin.inferred_node_role == "railway_station"
            else "客户工厂/仓库"
        )
        issue_code = (
            "railway_origin_not_south_port"
            if origin.inferred_node_role == "railway_station"
            else "customer_origin_not_south_port"
        )
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="candidate_selection",
                issue_code=issue_code,
                issue_category="confirmed_node_role",
                manual_confirmation_required=False,
                message=(
                    f"{origin.port_name} 按已确认名称规则属于{role_text}，"
                    "不作为自动南港候选。"
                ),
                suggested_action=(
                    "无需补成南港；若该客户存在自有码头，应另行维护独立港口/码头节点及其关系。"
                ),
            )
        )
    elif (
        not origin.is_automatic_port_candidate
        and origin.inferred_node_role != "port"
        and origin.port_waterway_role != "inland_port"
        and bulk_exclusion_reason is None
    ):
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="candidate_selection",
                issue_code="non_port_origin_label",
                issue_category="node_role_confirmation",
                message=(
                    f"{origin.port_name} 的标准名称不含“港”或“码头”，"
                    "当前仅在命中客户精确维护运价时作为优先候选，不属于自动港口候选。"
                ),
                suggested_action=(
                    "确认该节点是仓库/车站/客户节点还是港口；若确为港口，维护正式港口身份字段，"
                    "不要仅依赖名称包含关系。"
                ),
            )
        )
    if origin.port_waterway_role == "inland_port":
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="candidate_selection",
                issue_code="inland_port_not_bulk_trunk_destination",
                issue_category="confirmed_node_role",
                manual_confirmation_required=False,
                message=(
                    f"{origin.port_name} 已确认为内河码头，"
                    "不作为北港散船干线终点。"
                ),
                suggested_action=(
                    "仅在南港后的内河/末段运输阶段按适用航费、航时和端点能力使用。"
                ),
            )
        )
    if (
        origin.port_waterway_role == "unknown_port"
        and bulk_exclusion_reason is None
        and not has_scenario_bulk_evidence
    ):
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="candidate_selection",
                issue_code="bulk_freight_origin_evidence_missing",
                issue_category="candidate_evidence_gap",
                message=(
                    f"{origin.port_name} 尚无已确认海港/海河双用标识，且没有本订单适用的"
                    "散粮始发运价证据，不作为北港散船干线的南港终点。"
                ),
                suggested_action=(
                    "若仅有集装箱运价，保留为潜在中转港待人工确认；"
                    "后续在节点主数据中维护独立的中转港功能角色。"
                ),
            )
        )
    if bulk_exclusion_reason is not None:
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="candidate_selection",
                issue_code="confirmed_bulk_capability_not_applicable",
                issue_category="confirmed_port_capability",
                manual_confirmation_required=False,
                message=(
                    f"{origin.port_name} 当前不作为北港散粮散船干线终点："
                    f"{bulk_exclusion_reason}"
                ),
                suggested_action=(
                    "保留已确认港口身份；仅在相应包装方式、运价和航时接口完成后"
                    "生成适用运输边。"
                ),
            )
        )

    bulk_match = workbook.match(origin.port_name, request)
    if not bulk_match.is_resolved:
        issues.append(_bulk_issue(scenario, origin, request, workbook, bulk_match))

    if operation_fee_provider is None:
        operation_quote = None
        operation_status = "not_connected"
        operation_message = (
            "南港码头作业费 Provider 未接入；本审计不把缺失费用解释为 0。"
        )
        issues.append(
            _make_issue(
                scenario,
                origin,
                stage="port_operation_fee",
                issue_code="operation_fee_provider_not_connected",
                issue_category="data_interface_gap",
                message=operation_message,
                suggested_action="接入正式南港码头作业费表后重新运行审计。",
            )
        )
    else:
        operation_quote = operation_fee_provider.quote(
            port_name=origin.port_name,
            port_node_id=origin.node_id or None,
            request=request,
        )
        operation_status = operation_quote.status
        operation_message = operation_quote.message
        if not operation_quote.allows_route:
            issues.append(_operation_fee_issue(scenario, origin, operation_quote))

    if excluded_confirmed_role:
        issues = [
            issue
            for issue in issues
            if issue.stage in {"node_registration", "candidate_selection"}
        ]
        operation_status = "not_applicable_confirmed_node_role"
        operation_message = "该节点已按确认角色或能力排除出本场景，不检查码头作业费。"

    manual_selection_blocking_codes = [
        issue.issue_code
        for issue in issues
        if issue.stage not in {"candidate_selection", "candidate_source"}
        and issue.issue_category != "runtime_dependency"
    ]
    if origin.port_waterway_role == "inland_port":
        manual_selection_status = "excluded_inland_port"
    elif bulk_exclusion_reason is not None:
        manual_selection_status = "excluded_bulk_capability"
    elif origin.port_waterway_role == "unknown_port" and not has_scenario_bulk_evidence:
        manual_selection_status = "excluded_no_bulk_origin_evidence"
    elif origin.inferred_node_role in {"railway_station", "customer_facility"}:
        manual_selection_status = "excluded_confirmed_node_role"
    elif manual_selection_blocking_codes:
        manual_selection_status = "blocked_before_tencent"
    else:
        manual_selection_status = "ready_pending_tencent"

    if origin.port_waterway_role == "inland_port":
        offline_status = "excluded_inland_port"
    elif bulk_exclusion_reason is not None:
        offline_status = "excluded_bulk_capability"
    elif origin.port_waterway_role == "unknown_port" and not has_scenario_bulk_evidence:
        offline_status = "excluded_no_bulk_origin_evidence"
    elif origin.inferred_node_role in {"railway_station", "customer_facility"}:
        offline_status = "excluded_confirmed_node_role"
    elif not has_scenario_bulk_evidence:
        offline_status = "not_candidate_for_order"
    elif manual_selection_blocking_codes:
        offline_status = "blocked_before_tencent"
    elif not origin.is_automatic_port_candidate:
        offline_status = "conditional_exact_customer_rate"
    else:
        offline_status = "ready_pending_tencent"
    blocking_codes = [
        issue.issue_code
        for issue in issues
        if issue.stage not in {"candidate_selection", "candidate_source"}
        and issue.issue_category != "runtime_dependency"
    ]

    source_type = ""
    reference_port = ""
    if operation_quote is not None and operation_quote.rate is not None:
        source_type = operation_quote.rate.source_type
        reference_port = operation_quote.rate.reference_port_name or ""
    elif operation_quote is not None and operation_quote.exemption is not None:
        source_type = "not_applicable"

    return (
        PortAdmissionRow(
            scenario_id=scenario.scenario_id,
            quantity=scenario.quantity,
            quantity_unit=scenario.quantity_unit,
            package_type=scenario.package_type,
            commodity=scenario.commodity,
            trade_type=scenario.trade_type,
            port_node_id=origin.node_id,
            port_name=origin.port_name,
            source_names="；".join(origin.source_names),
            inferred_node_role=origin.inferred_node_role,
            port_waterway_role=origin.port_waterway_role,
            selection_scope=origin.selection_scope,
            matching_last_mile_rate_count=len(matching_rates),
            last_mile_source_status=last_mile_status,
            bulk_shipping_status=(
                "not_applicable_confirmed_node_role"
                if excluded_confirmed_role
                else bulk_match.status
            ),
            bulk_destination_label=(
                "" if excluded_confirmed_role else bulk_match.destination_label or ""
            ),
            bulk_time_region=(
                "" if excluded_confirmed_role else bulk_match.shipping_time_region or ""
            ),
            selected_vessel_type=(
                bulk_match.capacity.vessel_type
                if not excluded_confirmed_role and bulk_match.capacity is not None
                else ""
            ),
            selected_vessel_max_tons=(
                _decimal_text(bulk_match.capacity.max_tons)
                if not excluded_confirmed_role and bulk_match.capacity is not None
                else ""
            ),
            bulk_shipping_message=(
                "该节点已按确认角色或能力排除出本场景，不检查北港散船干线。"
                if excluded_confirmed_role
                else bulk_match.message
            ),
            operation_fee_status=operation_status,
            operation_fee_source_type=source_type,
            operation_fee_reference_port=reference_port,
            operation_fee_message=operation_message,
            offline_admission_status=offline_status,
            manual_selection_status=manual_selection_status,
            blocking_codes="；".join(dict.fromkeys(blocking_codes)),
            tencent_road_status="not_called_runtime_dependency",
        ),
        tuple(issues),
    )


def _bulk_issue(
    scenario: OrderScenario,
    origin: TransferOrigin,
    request: RouteRequest,
    workbook: BulkShippingWorkbook,
    match: BulkShippingMatch,
) -> AdmissionIssueRow:
    if request.package_type != "散粮" or request.quantity_unit != "吨":
        return _make_issue(
            scenario,
            origin,
            stage="north_to_south_bulk_shipping",
            issue_code="bulk_shipping_order_not_implemented",
            issue_category="implementation_scope",
            manual_confirmation_required=False,
            message=match.message,
            suggested_action=(
                "这是当前仅实现散粮散船干线的已知范围，不按码头数据错误处理；"
                "集装箱北港至南港模块上线后再复核。"
            ),
        )

    destination_label, time_region = classify_bulk_shipping_destination(origin.port_name)
    if destination_label is None or time_region is None:
        return _make_issue(
            scenario,
            origin,
            stage="north_to_south_bulk_shipping",
            issue_code="bulk_destination_or_time_mapping_missing",
            issue_category="business_rule_confirmation",
            message=match.message,
            suggested_action=(
                "确认该节点是否可接收北港散粮散船；若可以，确认散船费率目的组和完整航运段"
                "时效分区；若只是内河/末段节点，明确标为不得接收北港散船。"
            ),
        )

    columns = [
        column
        for column in workbook.columns
        if column.destination_label == destination_label
    ]
    if not columns:
        return _make_issue(
            scenario,
            origin,
            stage="north_to_south_bulk_shipping",
            issue_code="bulk_rate_group_missing",
            issue_category="data_gap",
            message=match.message,
            suggested_action=f"补充或确认散船运价表目的组 {destination_label} 的最新有效报价。",
        )
    capacities = [
        capacity
        for column in columns
        if (capacity := parse_vessel_capacity(column.vessel_type)) is not None
    ]
    if not capacities:
        return _make_issue(
            scenario,
            origin,
            stage="north_to_south_bulk_shipping",
            issue_code="bulk_vessel_type_unparseable",
            issue_category="data_quality",
            message=match.message,
            suggested_action=f"规范目的组 {destination_label} 的船型文本和吨位范围。",
        )
    max_capacity = max(capacity.max_tons for capacity in capacities)
    if request.quantity > max_capacity:
        return _make_issue(
            scenario,
            origin,
            stage="north_to_south_bulk_shipping",
            issue_code="bulk_vessel_capacity_exceeded",
            issue_category="business_rule_confirmation",
            message=match.message,
            suggested_action=(
                f"确认订单超过 {max_capacity} 吨时采用更大船型、拆单还是判定不可行；"
                "当前模型不会自动拆单。"
            ),
        )
    return _make_issue(
        scenario,
        origin,
        stage="north_to_south_bulk_shipping",
        issue_code="bulk_shipping_unresolved",
        issue_category="data_or_rule_gap",
        message=match.message,
        suggested_action="核查散船目的组、船型、报价和时效映射的组合。",
    )


def _operation_fee_issue(
    scenario: OrderScenario,
    origin: TransferOrigin,
    quote: PortOperationFeeQuote,
) -> AdmissionIssueRow:
    message = quote.message
    if scenario.package_type == "集装箱" and scenario.quantity_unit == "柜":
        return _make_issue(
            scenario,
            origin,
            stage="port_operation_fee",
            issue_code="operation_fee_quantity_unit_not_supported",
            issue_category="implementation_scope",
            manual_confirmation_required=False,
            message=message,
            suggested_action=(
                "当前码头作业费接口只正式支持元/吨和元/箱；后续取得元/柜费率或"
                "明确箱柜业务关系后再扩展，当前不得自动换算。"
            ),
        )
    if "同时存在" in message:
        code = "operation_fee_conflict"
        category = "data_conflict"
        action = "确认正数费率与不适用规则哪一条有效，并删除冲突记录后重跑。"
    elif "多条" in message:
        code = "operation_fee_duplicate"
        category = "data_conflict"
        action = "去重同一订单维度下可同时命中的码头作业费或区域映射。"
    elif "尚未确认的作业费区域映射" in message:
        code = "operation_fee_region_mapping_pending"
        category = "business_rule_confirmation"
        action = "人工确认现有作业费区域映射；确认前不启用最近区域代理。"
    elif "无法安全确定所在区域" in message:
        code = "operation_fee_region_unresolved"
        category = "business_rule_confirmation"
        action = "补充或确认码头业务区域映射，以便选择同区域最近正式参考费率。"
    elif "缺少标准 node_id" in message or "缺少坐标" in message:
        code = "operation_fee_node_or_coordinate_missing"
        category = "data_gap"
        action = "补充标准 node_id 和坐标后重新执行作业费匹配。"
    elif "没有唯一适用且具备坐标" in message or "没有唯一适用参考费率" in message:
        code = "operation_fee_reference_rate_missing"
        category = "data_gap"
        action = (
            "按当前包装、品种和贸易类型补充区域内正式参考码头费率，"
            "或确认目标港精确费率。"
        )
    else:
        code = "operation_fee_unresolved"
        category = "data_or_rule_gap"
        action = (
            "核查该码头在当前包装、品种、贸易类型和费用单位下的精确费率、"
            "不适用规则及区域参考费率。"
        )
    return _make_issue(
        scenario,
        origin,
        stage="port_operation_fee",
        issue_code=code,
        issue_category=category,
        message=message,
        suggested_action=action,
    )


def _make_issue(
    scenario: OrderScenario,
    origin: TransferOrigin,
    *,
    stage: str,
    issue_code: str,
    issue_category: str,
    message: str,
    suggested_action: str,
    manual_confirmation_required: bool = True,
) -> AdmissionIssueRow:
    return AdmissionIssueRow(
        scenario_id=scenario.scenario_id,
        quantity=scenario.quantity,
        quantity_unit=scenario.quantity_unit,
        package_type=scenario.package_type,
        commodity=scenario.commodity,
        trade_type=scenario.trade_type,
        port_node_id=origin.node_id,
        port_name=origin.port_name,
        inferred_node_role=origin.inferred_node_role,
        selection_scope=origin.selection_scope,
        stage=stage,
        issue_code=issue_code,
        issue_category=issue_category,
        review_priority=_review_priority(scenario, manual_confirmation_required),
        manual_confirmation_required=manual_confirmation_required,
        message=message,
        suggested_action=suggested_action,
    )


def build_manual_review_groups(
    issues: Iterable[AdmissionIssueRow],
) -> tuple[ManualReviewGroup, ...]:
    grouped: dict[tuple[str, ...], list[AdmissionIssueRow]] = defaultdict(list)
    for issue in issues:
        if not issue.manual_confirmation_required:
            continue
        key = (
            issue.port_node_id,
            issue.port_name,
            issue.inferred_node_role,
            issue.selection_scope,
            issue.stage,
            issue.issue_code,
            issue.issue_category,
            issue.suggested_action,
        )
        grouped[key].append(issue)

    rows: list[ManualReviewGroup] = []
    for key, matches in grouped.items():
        priorities = sorted(
            {item.review_priority for item in matches},
            key=lambda value: int(value.removeprefix("P")),
        )
        rows.append(
            ManualReviewGroup(
                review_priority=priorities[0],
                stage=key[4],
                issue_code=key[5],
                issue_category=key[6],
                port_node_id=key[0],
                port_name=key[1],
                inferred_node_role=key[2],
                selection_scope=key[3],
                scenario_count=len({item.scenario_id for item in matches}),
                scenario_ids="；".join(
                    sorted({item.scenario_id for item in matches})
                ),
                package_types=_joined_values(item.package_type for item in matches),
                quantity_units=_joined_values(item.quantity_unit for item in matches),
                commodities=_joined_values(
                    (item.commodity for item in matches),
                    preferred=COMMODITY_ORDER,
                ),
                trade_types=_joined_values(
                    (item.trade_type for item in matches),
                    preferred=TRADE_TYPE_ORDER,
                ),
                quantities=_joined_decimal_values(item.quantity for item in matches),
                example_message=matches[0].message,
                suggested_action=key[7],
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                int(item.review_priority.removeprefix("P")),
                _stage_order(item.stage),
                item.issue_code,
                item.port_name,
            ),
        )
    )


def load_operation_fee_provider(
    bundle: RealDataBundle,
) -> tuple[SouthPortOperationFeeProvider | None, str | None]:
    fee_file = find_optional_port_operation_fee_file(bundle.data_dir)
    if fee_file is None:
        return None, None
    registry = bundle.node_registry
    port_reference = load_port_reference_tables(bundle.data_dir, registry=registry)
    return (
        TablePortOperationFeeProvider.from_csv(
            fee_file,
            registry=registry,
            region_assignments=port_reference.operation_fee_region_assignments,
            region_mappings=port_reference.region_mappings,
        ),
        str(fee_file),
    )


def find_bulk_workbook(data_dir: Path) -> Path | None:
    matches = sorted(data_dir.rglob(BULK_RATE_FILE_NAME))
    return matches[0] if matches else None


def write_audit_outputs(
    audit: OrderGraphAdmissionAudit,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown": output_dir / "order_graph_admission_audit.md",
        "json": output_dir / "order_graph_admission_audit.json",
        "scenarios": output_dir / "order_graph_admission_scenarios.csv",
        "ports": output_dir / "order_graph_port_admission.csv",
        "issues": output_dir / "order_graph_admission_issues.csv",
        "manual_review": output_dir / "order_graph_manual_review.csv",
    }
    paths["markdown"].write_text(render_markdown(audit), encoding="utf-8")
    paths["json"].write_text(
        json.dumps(asdict(audit), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(
        paths["scenarios"],
        [asdict(row) for row in audit.scenario_rows],
        fieldnames=[field.name for field in fields(ScenarioSummaryRow)],
    )
    _write_csv(
        paths["ports"],
        [asdict(row) for row in audit.port_rows],
        fieldnames=[field.name for field in fields(PortAdmissionRow)],
    )
    _write_csv(
        paths["issues"],
        [asdict(row) for row in audit.issue_rows],
        fieldnames=[field.name for field in fields(AdmissionIssueRow)],
    )
    _write_csv(
        paths["manual_review"],
        [asdict(row) for row in audit.manual_review_rows],
        fieldnames=[field.name for field in fields(ManualReviewGroup)],
    )
    return paths


def render_markdown(audit: OrderGraphAdmissionAudit) -> str:
    issue_counts: dict[str, int] = defaultdict(int)
    for row in audit.manual_review_rows:
        issue_counts[row.issue_code] += 1
    p1_rows = [
        row for row in audit.manual_review_rows if row.review_priority == "P1"
    ]
    lines = [
        "# 订单参数与港口入图准入审计",
        "",
        "本报告由只读工具生成，不写回真实数据，也不调用 Tencent。",
        "`ready_pending_tencent` 仅表示候选来源、散船干线和码头作业费已通过离线前置检查；",
        "仍需在具体客户输入下取得腾讯道路距离/时间后，才能证明末段汽运边实际进入搜索图。",
        "",
        "## 1. 覆盖范围",
        "",
        f"- 订单场景：{audit.scenario_count}",
        f"- 受审计节点：{audit.transfer_origin_count}",
        f"- 港口名称启发式节点：{audit.automatic_port_origin_count}",
        f"- 非自动节点（含已确认排除项）：{audit.conditional_origin_count}",
        "- 已确认名称规则：含“站”或“地名+方位”按铁路站排除；"
        "含“库/仓/公司”按客户工厂/仓库排除；客户自有码头须另建港口/码头节点。",
        f"- 品种：{'、'.join(audit.commodities)}",
        f"- 包装/计费单位：{'、'.join(audit.package_unit_pairs)}",
        f"- 贸易类型：{'、'.join(audit.trade_types)}",
        f"- 散粮重量（吨）：{'、'.join(audit.bulk_quantity_profiles)}",
        f"- 非散粮代表数量：{'、'.join(audit.non_bulk_quantity_profiles)}",
        "",
        "## 2. 人工确认汇总",
        "",
        f"- 去重人工确认项：{len(audit.manual_review_rows)}",
        f"- 当前散粮内贸优先项（P1）：{len(p1_rows)}",
    ]
    for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{code}`：{count} 个节点级去重项")
    lines.extend(["", "## 3. P1 节点清单", ""])
    p1_by_code: dict[str, list[ManualReviewGroup]] = defaultdict(list)
    for row in p1_rows:
        p1_by_code[row.issue_code].append(row)
    for code, rows in sorted(
        p1_by_code.items(),
        key=lambda item: (_stage_order(item[1][0].stage), item[0]),
    ):
        port_names = "、".join(sorted({row.port_name for row in rows}))
        lines.extend(
            [
                f"### `{code}`（{len(rows)} 个节点）",
                "",
                f"- 阶段：{rows[0].stage}",
                f"- 节点：{port_names}",
                f"- 建议：{rows[0].suggested_action}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## 4. 输出文件说明",
            "",
            "- `order_graph_admission_scenarios.csv`：每个订单场景的候选数、离线就绪数和阻塞数。",
            "- `order_graph_port_admission.csv`：每个订单场景 × 始发节点的各阶段状态。",
            "- `order_graph_admission_issues.csv`：未聚合的逐场景问题明细。",
            "- `order_graph_manual_review.csv`：按节点和问题类型聚合后的人工确认主清单。",
            "",
            "集装箱散船干线尚未实现的场景会标为 `implementation_scope`，",
            "不会伪装成某个码头的数据缺失；吨、箱、柜之间不做任何自动换算。",
        ]
    )
    return "\n".join(lines) + "\n"


def _discover_commodities(rates: Sequence[FreightRate]) -> tuple[str, ...]:
    values = {
        item
        for rate in rates
        for item in _split_scope(rate.commodity_scope)
        if item != "*"
    }
    return tuple(
        sorted(
            values,
            key=lambda value: (_ordered_index(value, COMMODITY_ORDER), value),
        )
    )


def _split_scope(value: str) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in re.split(r"[、,，/；;]+", value or "")
        if part.strip()
    )


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value).strip())


def _matching_origin_rates(
    origin: TransferOrigin,
    request: RouteRequest,
) -> list[FreightRate]:
    return [
        rate
        for rate in origin.rates
        if is_truck_transport_mode(rate.transport_mode)
        and rate.package_type == request.package_type
        and rate.supports_commodity(request.commodity)
    ]


def _matching_freight_origin_rates(
    origin: TransferOrigin,
    request: RouteRequest,
) -> list[FreightRate]:
    return [
        rate
        for rate in origin.rates
        if rate.package_type == request.package_type
        and rate.supports_commodity(request.commodity)
    ]


def _review_priority(
    scenario: OrderScenario,
    manual_confirmation_required: bool,
) -> str:
    if not manual_confirmation_required:
        return "P4"
    if (
        scenario.package_type == "散粮"
        and scenario.quantity_unit == "吨"
        and scenario.trade_type == "内贸"
    ):
        return "P1"
    if scenario.package_type == "散粮" and scenario.quantity_unit == "吨":
        return "P2"
    return "P3"


def _stage_order(stage: str) -> int:
    values = (
        "node_registration",
        "candidate_selection",
        "candidate_source",
        "north_to_south_bulk_shipping",
        "port_operation_fee",
    )
    return _ordered_index(stage, values)


def _ordered_index(value: str, preferred: Sequence[str]) -> int:
    try:
        return preferred.index(value)
    except ValueError:
        return len(preferred)


def _joined_values(
    values: Iterable[str],
    *,
    preferred: Sequence[str] = (),
) -> str:
    unique = set(values)
    return "；".join(
        sorted(
            unique,
            key=lambda value: (_ordered_index(value, preferred), value),
        )
    )


def _joined_decimal_values(values: Iterable[str]) -> str:
    unique = {Decimal(str(value)) for value in values}
    return "；".join(_decimal_text(value) for value in sorted(unique))


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
