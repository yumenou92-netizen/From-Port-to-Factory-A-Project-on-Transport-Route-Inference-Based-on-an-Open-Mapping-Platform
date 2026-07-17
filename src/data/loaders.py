from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.domain.cost_rules import DEFAULT_COST_RULE_ENGINE, is_truck_transport_mode
from src.domain.freight_rate import FreightRate, FreightRateError, create_freight_rate
from src.domain.latest_rate_selector import (
    LATEST_RATE_RULE_ID,
    LATEST_RATE_RULE_VERSION,
    LatestRateSelectionIssue,
    effective_maintained_at,
    select_latest_freight_rates,
)
from src.domain.route_request import (
    RequestBillingValidation,
    RouteRequest,
    validate_request_billing,
)


REAL_RATE_FILE = "运价表.json"
REAL_COORDINATE_FILE = "地点经纬度.json"
REAL_ADDITIONAL_FEE_FILE = "其他费用表.json"


class DataLoadError(Exception):
    """Raised when business data cannot be loaded into standard objects."""


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    name: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class AdditionalFee:
    node_name: str
    packaging: str
    fee_type: str
    unit_price: Decimal
    fee_unit: str


@dataclass(frozen=True)
class EdgeCandidate:
    rate_id: str
    from_node_id: str | None
    to_node_id: str | None
    origin: str
    destination: str
    transport_mode: str
    packaging: str
    product_scope: str
    raw_price: Decimal
    raw_price_unit: str
    total_cost: Decimal
    price_source: str
    maintenance_date: str | None
    effective_maintenance_date: str
    maintenance_date_defaulted: bool
    price_type: str
    calculation_rule_id: str
    calculation_rule_version: str
    calculation_detail: str
    source_file: str | None
    source_row_number: int | None


@dataclass(frozen=True)
class EdgeReviewItem:
    rate_id: str
    origin: str
    destination: str
    transport_mode: str
    packaging: str
    quantity: str
    quantity_unit: str
    raw_price: Decimal
    raw_price_unit: str
    price_source: str
    maintenance_date: str | None
    effective_maintenance_date: str
    maintenance_date_defaulted: bool
    review_reason: str
    price_type: str
    calculation_rule_id: str
    calculation_rule_version: str
    calculation_detail: str
    source_file: str | None
    source_row_number: int | None


@dataclass(frozen=True)
class EdgeBuildResult:
    candidates: list[EdgeCandidate]
    request_validation: RequestBillingValidation = field(
        default_factory=lambda: RequestBillingValidation(status="valid")
    )
    skipped_packaging: int = 0
    skipped_product: int = 0
    manual_review_items: list[EdgeReviewItem] = field(default_factory=list)
    superseded_rate_count: int = 0
    duplicate_rate_count: int = 0
    defaulted_maintenance_date_count: int = 0

    @property
    def manual_review_count(self) -> int:
        request_review_count = int(self.request_validation.requires_manual_review)
        return request_review_count + len(self.manual_review_items)

    @property
    def graph_ready_candidates(self) -> list[EdgeCandidate]:
        return [
            candidate
            for candidate in self.candidates
            if candidate.from_node_id is not None and candidate.to_node_id is not None
        ]

    @property
    def missing_node_candidate_count(self) -> int:
        return len(self.candidates) - len(self.graph_ready_candidates)


@dataclass(frozen=True)
class RealDataBundle:
    data_dir: Path
    freight_rates: list[FreightRate]
    nodes: list[NodeRecord]
    additional_fees: list[AdditionalFee]

    @property
    def node_by_name(self) -> dict[str, NodeRecord]:
        return {node.name: node for node in self.nodes}

    @property
    def transport_modes(self) -> Counter[str]:
        return Counter(rate.transport_mode for rate in self.freight_rates)

    @property
    def fee_units(self) -> Counter[str]:
        units = Counter(rate.raw_price_unit for rate in self.freight_rates)
        units.update(fee.fee_unit for fee in self.additional_fees)
        return units

    @property
    def packaging_types(self) -> Counter[str]:
        values = Counter(rate.package_type for rate in self.freight_rates)
        values.update(fee.packaging for fee in self.additional_fees)
        return values


def data_dir_from_env() -> Path:
    value = os.environ.get("DATA_DIR")
    if not value:
        raise DataLoadError("缺少环境变量 DATA_DIR。请设置为本地真实业务数据目录，例如 .\\data_REAL。")

    data_dir = Path(value)
    if not data_dir.exists():
        raise DataLoadError(f"DATA_DIR 不存在: {data_dir}")
    if not data_dir.is_dir():
        raise DataLoadError(f"DATA_DIR 不是目录: {data_dir}")
    return data_dir


def load_real_data_bundle(data_dir: str | Path) -> RealDataBundle:
    root = Path(data_dir)
    rate_rows = read_json_lines(find_required_file(root, REAL_RATE_FILE))
    coordinate_rows = read_json_lines(find_required_file(root, REAL_COORDINATE_FILE))
    additional_fee_rows = read_json_lines(find_required_file(root, REAL_ADDITIONAL_FEE_FILE))
    nodes = [parse_node_record(row, index) for index, row in enumerate(coordinate_rows, start=1)]
    from src.domain.node_registry import build_node_registry

    node_registry = build_node_registry(nodes)
    freight_rates = []
    for index, row in enumerate(rate_rows, start=1):
        rate = parse_freight_rate(row, index)
        origin_node = node_registry.lookup(rate.origin_name)
        destination_node = node_registry.lookup(rate.destination_name)
        freight_rates.append(
            rate.bind_node_ids(
                origin_node.node_id if origin_node else None,
                destination_node.node_id if destination_node else None,
            )
        )

    return RealDataBundle(
        data_dir=root,
        freight_rates=freight_rates,
        nodes=nodes,
        additional_fees=[parse_additional_fee(row, index) for index, row in enumerate(additional_fee_rows, start=1)],
    )


def find_required_file(data_dir: Path, file_name: str) -> Path:
    matches = sorted(data_dir.rglob(file_name))
    if not matches:
        raise DataLoadError(f"DATA_DIR 下缺少必要文件: {file_name}")
    if len(matches) > 1:
        joined = "; ".join(str(path) for path in matches)
        raise DataLoadError(f"DATA_DIR 下存在多个 {file_name}，请先明确数据来源: {joined}")
    return matches[0]


def read_json_lines(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DataLoadError(f"{path.name} 第 {line_no} 行不是合法 JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise DataLoadError(f"{path.name} 第 {line_no} 行不是 JSON 对象。")
        records.append(record)
    return records


def parse_freight_rate(row: dict[str, Any], row_no: int) -> FreightRate:
    required = ["始发", "到达", "运输方式", "包装方式", "适用品种", "费用", "费用单位", "价格来源"]
    require_fields(row, required, REAL_RATE_FILE, row_no)
    try:
        return create_freight_rate(
            origin_name=parse_required_text(row["始发"], REAL_RATE_FILE, row_no, "始发"),
            destination_name=parse_required_text(row["到达"], REAL_RATE_FILE, row_no, "到达"),
            transport_mode=parse_required_text(row["运输方式"], REAL_RATE_FILE, row_no, "运输方式"),
            package_type=parse_required_text(row["包装方式"], REAL_RATE_FILE, row_no, "包装方式"),
            commodity_scope=parse_required_text(row["适用品种"], REAL_RATE_FILE, row_no, "适用品种"),
            raw_price=parse_decimal(row["费用"], REAL_RATE_FILE, row_no, "费用"),
            raw_price_unit=parse_required_text(row["费用单位"], REAL_RATE_FILE, row_no, "费用单位"),
            price_type="unit_price",
            price_source=parse_required_text(row["价格来源"], REAL_RATE_FILE, row_no, "价格来源"),
            maintained_at=parse_optional_text(row.get("维护日期"), REAL_RATE_FILE, row_no, "维护日期"),
            source_file=REAL_RATE_FILE,
            source_row_number=row_no,
        )
    except FreightRateError as exc:
        raise DataLoadError(f"{REAL_RATE_FILE} 第 {row_no} 行费率结构无效: {exc}") from exc


def parse_node_record(row: dict[str, Any], row_no: int) -> NodeRecord:
    required = ["名称", "经度", "纬度"]
    require_fields(row, required, REAL_COORDINATE_FILE, row_no)
    name = str(row["名称"]).strip()
    return NodeRecord(
        node_id=make_node_id(name),
        name=name,
        longitude=parse_float(row["经度"], REAL_COORDINATE_FILE, row_no, "经度"),
        latitude=parse_float(row["纬度"], REAL_COORDINATE_FILE, row_no, "纬度"),
    )


def parse_additional_fee(row: dict[str, Any], row_no: int) -> AdditionalFee:
    required = ["节点简称", "包装类型", "费用类型", "单价", "费用单位"]
    require_fields(row, required, REAL_ADDITIONAL_FEE_FILE, row_no)
    return AdditionalFee(
        node_name=str(row["节点简称"]).strip(),
        packaging=str(row["包装类型"]).strip(),
        fee_type=str(row["费用类型"]).strip(),
        unit_price=parse_decimal(row["单价"], REAL_ADDITIONAL_FEE_FILE, row_no, "单价"),
        fee_unit=str(row["费用单位"]).strip(),
    )


def require_fields(row: dict[str, Any], fields: list[str], file_name: str, row_no: int) -> None:
    missing = [field for field in fields if is_blank(row.get(field))]
    if missing:
        raise DataLoadError(f"{file_name} 第 {row_no} 行缺少必填字段: {', '.join(missing)}")


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_required_text(value: Any, file_name: str, row_no: int, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 必须是非空文本。")
    return value.strip()


def parse_optional_text(value: Any, file_name: str, row_no: int, field_name: str) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 必须是文本或空值。")
    return value.strip()


def parse_decimal(value: Any, file_name: str, row_no: int, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有效数值: {value}") from exc
    if not number.is_finite():
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有限数值: {value}")
    return number


def parse_float(value: Any, file_name: str, row_no: int, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有效数值: {value}") from exc
    if not math.isfinite(number):
        raise DataLoadError(f"{file_name} 第 {row_no} 行字段 {field_name} 不是有限数值: {value}")
    return number


def make_node_id(name: str) -> str:
    normalized = normalize_node_name(name)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"node_{digest}"


def normalize_node_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name).strip())


def build_order_edge_candidates(
    bundle: RealDataBundle,
    quantity: int | float | str | Decimal,
    quantity_unit: str,
    packaging: str,
    product: str,
) -> EdgeBuildResult:
    request = RouteRequest(
        quantity=quantity,
        quantity_unit=quantity_unit,
        package_type=packaging,
        commodity=product,
    )
    return build_order_edge_candidates_for_request(bundle, request)


def build_order_edge_candidates_for_request(
    bundle: RealDataBundle,
    request: RouteRequest,
) -> EdgeBuildResult:
    request_validation = validate_request_billing(request)
    if request_validation.requires_manual_review:
        return EdgeBuildResult(candidates=[], request_validation=request_validation)

    candidates: list[EdgeCandidate] = []
    manual_review_items: list[EdgeReviewItem] = []
    skipped_packaging = 0
    applicable_rates = [
        rate for rate in bundle.freight_rates if rate.supports_commodity(request.commodity)
    ]
    skipped_product = len(bundle.freight_rates) - len(applicable_rates)
    selection = select_latest_freight_rates(applicable_rates)

    for issue in selection.review_issues:
        manual_review_items.extend(make_latest_rate_review_items(issue, request))

    for rate in selection.selected_rates:
        evaluation = (
            DEFAULT_COST_RULE_ENGINE.calculate_last_mile_truck(request, known_rate=rate)
            if is_truck_transport_mode(rate.transport_mode)
            else rate.evaluate_for_request(request)
        )
        if evaluation.status == "not_applicable":
            skipped_packaging += 1
            continue
        if evaluation.requires_manual_review:
            manual_review_items.append(
                make_edge_review_item(
                    rate,
                    request.quantity,
                    request.quantity_unit,
                    evaluation.message,
                    evaluation.rule_id,
                    evaluation.rule_version,
                    evaluation.calculation_detail,
                )
            )
            continue
        if evaluation.total_cost is None:
            raise DataLoadError("有效运价评估缺少运输段总费用。")
        total_cost = evaluation.total_cost

        candidates.append(
            EdgeCandidate(
                rate_id=rate.rate_id,
                from_node_id=rate.from_node_id,
                to_node_id=rate.to_node_id,
                origin=rate.origin_name,
                destination=rate.destination_name,
                transport_mode=rate.transport_mode,
                packaging=rate.package_type,
                product_scope=rate.commodity_scope,
                raw_price=rate.raw_price,
                raw_price_unit=rate.raw_price_unit,
                total_cost=total_cost,
                price_source=rate.price_source,
                maintenance_date=rate.maintained_at.isoformat() if rate.maintained_at else None,
                effective_maintenance_date=effective_maintained_at(rate).isoformat(),
                maintenance_date_defaulted=rate.maintained_at is None,
                price_type=rate.price_type,
                calculation_rule_id=evaluation.rule_id,
                calculation_rule_version=evaluation.rule_version,
                calculation_detail=evaluation.calculation_detail,
                source_file=rate.source_file,
                source_row_number=rate.source_row_number,
            )
        )

    return EdgeBuildResult(
        candidates=candidates,
        request_validation=request_validation,
        skipped_packaging=skipped_packaging,
        skipped_product=skipped_product,
        manual_review_items=manual_review_items,
        superseded_rate_count=selection.superseded_rate_count,
        duplicate_rate_count=selection.duplicate_rate_count,
        defaulted_maintenance_date_count=selection.defaulted_date_count,
    )


def make_latest_rate_review_items(
    issue: LatestRateSelectionIssue,
    request: RouteRequest,
) -> list[EdgeReviewItem]:
    return [
        make_edge_review_item(
            rate,
            request.quantity,
            request.quantity_unit,
            issue.message,
            LATEST_RATE_RULE_ID,
            LATEST_RATE_RULE_VERSION,
            f"最新运价选择未通过：{issue.code}。{issue.message}",
        )
        for rate in issue.rates
    ]


def make_edge_review_item(
    rate: FreightRate,
    quantity: int | float | str | Decimal,
    quantity_unit: str,
    review_reason: str,
    calculation_rule_id: str,
    calculation_rule_version: str,
    calculation_detail: str,
) -> EdgeReviewItem:
    return EdgeReviewItem(
        rate_id=rate.rate_id,
        origin=rate.origin_name,
        destination=rate.destination_name,
        transport_mode=rate.transport_mode,
        packaging=rate.package_type,
        quantity=str(quantity),
        quantity_unit=str(quantity_unit).strip(),
        raw_price=rate.raw_price,
        raw_price_unit=rate.raw_price_unit,
        price_source=rate.price_source,
        maintenance_date=rate.maintained_at.isoformat() if rate.maintained_at else None,
        effective_maintenance_date=effective_maintained_at(rate).isoformat(),
        maintenance_date_defaulted=rate.maintained_at is None,
        review_reason=review_reason,
        price_type=rate.price_type,
        calculation_rule_id=calculation_rule_id,
        calculation_rule_version=calculation_rule_version,
        calculation_detail=calculation_detail,
        source_file=rate.source_file,
        source_row_number=rate.source_row_number,
    )


def edge_candidate_to_row(candidate: EdgeCandidate) -> dict[str, Any]:
    return {
        "rate_id": candidate.rate_id,
        "from_node_id": candidate.from_node_id,
        "to_node_id": candidate.to_node_id,
        "origin": candidate.origin,
        "destination": candidate.destination,
        "transport_mode": candidate.transport_mode,
        "packaging": candidate.packaging,
        "product_scope": candidate.product_scope,
        "raw_price": str(candidate.raw_price),
        "raw_price_unit": candidate.raw_price_unit,
        "total_cost": str(candidate.total_cost),
        "price_source": candidate.price_source,
        "maintenance_date": candidate.maintenance_date or "",
        "effective_maintenance_date": candidate.effective_maintenance_date,
        "maintenance_date_defaulted": candidate.maintenance_date_defaulted,
        "price_type": candidate.price_type,
        "calculation_rule_id": candidate.calculation_rule_id,
        "calculation_rule_version": candidate.calculation_rule_version,
        "calculation_detail": candidate.calculation_detail,
        "source_file": candidate.source_file or "",
        "source_row_number": candidate.source_row_number or "",
    }


def edge_review_item_to_row(item: EdgeReviewItem) -> dict[str, Any]:
    return {
        "rate_id": item.rate_id,
        "validation_status": "manual_review",
        "validation_scope": "freight_rate",
        "origin": item.origin,
        "destination": item.destination,
        "transport_mode": item.transport_mode,
        "packaging": item.packaging,
        "quantity": item.quantity,
        "quantity_unit": item.quantity_unit,
        "raw_price": str(item.raw_price),
        "raw_price_unit": item.raw_price_unit,
        "price_source": item.price_source,
        "maintenance_date": item.maintenance_date or "",
        "effective_maintenance_date": item.effective_maintenance_date,
        "maintenance_date_defaulted": item.maintenance_date_defaulted,
        "review_reason": item.review_reason,
        "price_type": item.price_type,
        "calculation_rule_id": item.calculation_rule_id,
        "calculation_rule_version": item.calculation_rule_version,
        "calculation_detail": item.calculation_detail,
        "source_file": item.source_file or "",
        "source_row_number": item.source_row_number or "",
    }


def build_review_rows(result: EdgeBuildResult, request: RouteRequest) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if result.request_validation.requires_manual_review:
        rows.append(
            {
                "rate_id": "",
                "validation_status": "manual_review",
                "validation_scope": "request",
                "origin": "",
                "destination": "",
                "transport_mode": "",
                "packaging": request.package_type,
                "quantity": str(request.quantity),
                "quantity_unit": request.quantity_unit,
                "raw_price": "",
                "raw_price_unit": "",
                "price_source": "",
                "maintenance_date": "",
                "effective_maintenance_date": "",
                "maintenance_date_defaulted": "",
                "review_reason": "；".join(result.request_validation.issues),
                "price_type": "",
                "calculation_rule_id": "",
                "calculation_rule_version": "",
                "calculation_detail": "",
                "source_file": "",
                "source_row_number": "",
            }
        )
    rows.extend(edge_review_item_to_row(item) for item in result.manual_review_items)
    return rows
