from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from src.data.name_dictionary import NameDictionaryEntry
from src.domain.node_registry import StandardNode, normalize_lookup_name
from src.geo.coordinate_provider import CoordinateProvider, CoordinateResolution
from src.routing.port_operation_fee_provider import (
    PORT_OPERATION_FEE_TYPE,
    PORT_OPERATION_FEE_UNIT,
    PortOperationFeeRate,
)

if TYPE_CHECKING:
    from src.domain.node_registry import NodeRegistry


PORT_LABEL_RULE_FILE_NAME = "部分码头标签.json"
PORT_LABEL_SOURCE_FEE_TYPE = "入库"
PORT_LABEL_PACKAGE_TYPE = "散粮"
PORT_NAME_SUFFIXES = ("作业区", "港区", "码头", "港")
W5_ADMISSION_ELIGIBLE = "可申请准入"
W5_ADMISSION_PENDING_NODE = "节点待确认"
W5_ADMISSION_PENDING_FEE_MEANING = "费用含义待确认"
W5_FORMAL_APPLICABILITY_CHARGEABLE = "chargeable"
W5_FORMAL_APPLICABILITY_NOT_APPLICABLE = "not_applicable"


class PortLabelRuleError(ValueError):
    """Raised when the partial port-label JSON cannot be converted safely."""


@dataclass(frozen=True)
class PortLabelRuleBundle:
    path: Path
    version: str
    description: str
    last_updated: str
    rates: tuple[PortOperationFeeRate, ...]
    audit_rows: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class PortLabelNameMatch:
    node: StandardNode | None
    match_status: str
    dictionary_status: str
    dictionary_rows: tuple[int, ...]
    dictionary_candidates: tuple[str, ...]
    tencent_query_names: tuple[str, ...]


@dataclass(frozen=True)
class PortLabelTencentLocation:
    port_name: str
    query_names: tuple[str, ...]
    dictionary_status: str
    dictionary_rows: tuple[int, ...]
    dictionary_candidates: tuple[str, ...]


@dataclass(frozen=True)
class PortLabelTencentReview:
    location: PortLabelTencentLocation
    resolutions: tuple[CoordinateResolution, ...]


def find_optional_port_label_rule_file(data_dir: Path) -> Path | None:
    matches = sorted(data_dir.rglob(PORT_LABEL_RULE_FILE_NAME))
    if not matches:
        return None
    if len(matches) > 1:
        joined = "; ".join(str(path) for path in matches)
        raise PortLabelRuleError(f"DATA_DIR 下存在多个 {PORT_LABEL_RULE_FILE_NAME}，请先明确数据来源：{joined}")
    return matches[0]


def load_port_label_rule_bundle(
    path: Path,
    *,
    registry: NodeRegistry | None = None,
    dictionary_entries: Iterable[NameDictionaryEntry] = (),
) -> PortLabelRuleBundle:
    data = _read_json_object(path)
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise PortLabelRuleError(f"{path.name} 缺少 rules 列表。")

    dictionary_entries = tuple(dictionary_entries)
    rates: list[PortOperationFeeRate] = []
    audit_rows: list[dict[str, str]] = []
    for rule_no, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise PortLabelRuleError(f"{path.name} 第 {rule_no} 条规则不是对象。")
        trade_type = _required_text(rule.get("tradeType"), f"第 {rule_no} 条 tradeType")
        port_names = _text_list(rule.get("portName"), f"第 {rule_no} 条 portName")
        varieties = _text_list(rule.get("variety"), f"第 {rule_no} 条 variety")
        service_fees = rule.get("serviceFees")
        if not isinstance(service_fees, dict) or PORT_LABEL_SOURCE_FEE_TYPE not in service_fees:
            raise PortLabelRuleError(f"{path.name} 第 {rule_no} 条缺少 serviceFees.{PORT_LABEL_SOURCE_FEE_TYPE}。")
        raw_unit_price = service_fees[PORT_LABEL_SOURCE_FEE_TYPE]
        try:
            unit_price = _positive_decimal(
                raw_unit_price,
                f"第 {rule_no} 条 {PORT_LABEL_SOURCE_FEE_TYPE}费率",
            )
        except PortLabelRuleError as exc:
            for port_name in port_names:
                name_match = match_port_label_name(
                    port_name,
                    registry=registry,
                    dictionary_entries=dictionary_entries,
                )
                audit_rows.append(
                    make_audit_row(
                        rule_no=rule_no,
                        port_name=port_name,
                        name_match=name_match,
                        trade_type=trade_type,
                        unit_price=str(raw_unit_price),
                        varieties=varieties,
                        source=f"{path.name}#rule={rule_no}:{PORT_LABEL_SOURCE_FEE_TYPE}",
                        conversion_status="manual_review",
                        issue=str(exc),
                    )
                )
            continue

        for port_name in port_names:
            name_match = match_port_label_name(
                port_name,
                registry=registry,
                dictionary_entries=dictionary_entries,
            )
            rate = PortOperationFeeRate(
                port_name=port_name,
                package_type=PORT_LABEL_PACKAGE_TYPE,
                fee_type=PORT_OPERATION_FEE_TYPE,
                unit_price_yuan_per_ton=unit_price,
                source=f"{path.name}#rule={rule_no}:{PORT_LABEL_SOURCE_FEE_TYPE}",
                fee_unit=PORT_OPERATION_FEE_UNIT,
                trade_type=trade_type,
                node_id=name_match.node.node_id if name_match.node is not None else None,
                commodity_scope=tuple(varieties),
                maintained_at=str(data.get("lastUpdated") or ""),
            )
            rates.append(rate)
            audit_rows.append(
                make_audit_row(
                    rule_no=rule_no,
                    port_name=port_name,
                    name_match=name_match,
                    trade_type=trade_type,
                    unit_price=str(unit_price),
                    varieties=varieties,
                    source=rate.source,
                    conversion_status="converted",
                    issue="",
                )
            )

    return PortLabelRuleBundle(
        path=path,
        version=str(data.get("version") or ""),
        description=str(data.get("description") or ""),
        last_updated=str(data.get("lastUpdated") or ""),
        rates=tuple(rates),
        audit_rows=tuple(audit_rows),
    )


def make_audit_row(
    *,
    rule_no: int,
    port_name: str,
    name_match: PortLabelNameMatch,
    trade_type: str,
    unit_price: str,
    varieties: tuple[str, ...],
    source: str,
    conversion_status: str,
    issue: str,
) -> dict[str, str]:
    registry_node = name_match.node
    return {
        "rule_no": str(rule_no),
        "port_name": port_name,
        "node_id": registry_node.node_id if registry_node is not None else "",
        "registry_match_status": name_match.match_status,
        "canonical_name": registry_node.canonical_name if registry_node is not None else "",
        "dictionary_status": name_match.dictionary_status,
        "dictionary_rows": "；".join(str(row) for row in name_match.dictionary_rows),
        "dictionary_candidates": "；".join(name_match.dictionary_candidates),
        "tencent_query_names": "；".join(name_match.tencent_query_names),
        "trade_type": trade_type,
        "package_type": PORT_LABEL_PACKAGE_TYPE,
        "fee_type": PORT_OPERATION_FEE_TYPE,
        "source_fee_type": PORT_LABEL_SOURCE_FEE_TYPE,
        "unit_price": unit_price,
        "fee_unit": PORT_OPERATION_FEE_UNIT,
        "commodity_scope": "；".join(varieties),
        "source": source,
        "conversion_status": conversion_status,
        "issue": issue,
    }


def build_w5_admission_review_rows(
    audit_rows: Iterable[dict[str, str]],
) -> tuple[dict[str, str], ...]:
    """Create a human-review gate without writing the formal W5 source table."""

    review_rows: list[dict[str, str]] = []
    for row in audit_rows:
        unit_price = str(row.get("unit_price") or "").strip()
        conversion_status = str(row.get("conversion_status") or "").strip()
        node_id = str(row.get("node_id") or "").strip()
        if conversion_status != "converted":
            suggested_status = W5_ADMISSION_PENDING_FEE_MEANING
            question = str(row.get("issue") or "").strip() or "费率含义或格式需要人工确认。"
        elif not node_id:
            suggested_status = W5_ADMISSION_PENDING_NODE
            question = "尚未绑定唯一标准 node_id；确认、忽略或补录节点后再决定是否准入。"
        else:
            suggested_status = W5_ADMISSION_ELIGIBLE
            question = "请确认节点绑定、适用条件和费率后，方可手工写入正式 W5 表。"

        review_rows.append(
            {
                "港口原名": str(row.get("port_name") or ""),
                "标准港口名称": str(row.get("canonical_name") or ""),
                "node_id": node_id,
                "包装方式": str(row.get("package_type") or ""),
                "trade_type": str(row.get("trade_type") or ""),
                "品种范围": str(row.get("commodity_scope") or ""),
                "入库费率": unit_price,
                "费用单位": str(row.get("fee_unit") or ""),
                "节点匹配方式": str(row.get("registry_match_status") or ""),
                "数据来源": str(row.get("source") or ""),
                "建议处理状态": suggested_status,
                "待确认问题": question,
                "人工确认结果": "",
            }
        )
    return tuple(review_rows)


def render_w5_admission_review_markdown(
    review_rows: Iterable[dict[str, str]],
) -> str:
    rows = tuple(review_rows)
    counts = {
        status: sum(1 for row in rows if row["建议处理状态"] == status)
        for status in (
            W5_ADMISSION_ELIGIBLE,
            W5_ADMISSION_PENDING_NODE,
            W5_ADMISSION_PENDING_FEE_MEANING,
        )
    }
    lines = [
        "# W5 正式数据准入人工复核清单",
        "",
        "本清单只用于人工审核，不会自动写入 `南港码头作业费.csv`。",
        "",
        "## 分组统计",
        "",
        f"- 可申请准入：{counts[W5_ADMISSION_ELIGIBLE]} 条",
        f"- 节点待确认：{counts[W5_ADMISSION_PENDING_NODE]} 条",
        f"- 费用含义待确认：{counts[W5_ADMISSION_PENDING_FEE_MEANING]} 条",
        "",
        "## 审核要求",
        "",
        "- 可申请准入不等于已经批准；必须填写人工确认结果。",
        "- 节点待确认项不得按名称猜测或自动注册。",
        "- 零值、无效值或费用含义不明项不得解释为免费。",
        "- 只有节点、包装、品种、贸易类型、单位、费率和来源均确认后，才可手工写入正式 W5 表。",
        "",
    ]
    for status in (
        W5_ADMISSION_ELIGIBLE,
        W5_ADMISSION_PENDING_NODE,
        W5_ADMISSION_PENDING_FEE_MEANING,
    ):
        lines.extend((f"## {status}", ""))
        matching = [row for row in rows if row["建议处理状态"] == status]
        if not matching:
            lines.extend(("- 无", ""))
            continue
        for row in matching:
            label = row["标准港口名称"] or row["港口原名"]
            lines.extend(
                (
                    f"- {label}；node_id={row['node_id'] or '未确认'}；"
                    f"{row['trade_type']}；{row['包装方式']}；"
                    f"{row['入库费率']}{row['费用单位']}；"
                    f"品种={row['品种范围'] or '未提供'}",
                    f"  - 待确认：{row['待确认问题']}",
                )
            )
        lines.append("")
    return "\n".join(lines)


def build_w5_formal_rows(
    audit_rows: Iterable[dict[str, str]],
    *,
    approve_zero_as_customer_owned_exemption: bool,
    confirmation_source: str,
    maintained_at: str,
) -> tuple[dict[str, str], ...]:
    """Promote only approved positive rows and explicit customer-owned zero exemptions.

    Positive rows require a standard node ID. Every other unbound positive row
    is ignored. Zero rows are admitted only when the caller explicitly confirms
    the customer-owned-terminal exemption policy.
    """

    formal_rows: list[dict[str, str]] = []
    for row in audit_rows:
        conversion_status = str(row.get("conversion_status") or "").strip()
        node_id = str(row.get("node_id") or "").strip()
        raw_price = str(row.get("unit_price") or "").strip()
        is_zero = False
        try:
            is_zero = Decimal(raw_price) == 0
        except (InvalidOperation, ValueError):
            pass

        if conversion_status == "converted" and node_id:
            applicability = W5_FORMAL_APPLICABILITY_CHARGEABLE
            exemption_reason = ""
        elif is_zero and approve_zero_as_customer_owned_exemption:
            applicability = W5_FORMAL_APPLICABILITY_NOT_APPLICABLE
            exemption_reason = "客户自有码头，经业务确认无需码头作业费"
        else:
            continue

        canonical_name = str(row.get("canonical_name") or "").strip()
        raw_name = str(row.get("port_name") or "").strip()
        formal_rows.append(
            {
                "标准节点ID": node_id,
                "南港名称": canonical_name or raw_name,
                "包装方式": str(row.get("package_type") or ""),
                "贸易类型": str(row.get("trade_type") or ""),
                "费用类型": str(row.get("fee_type") or ""),
                "单价": "0" if applicability == W5_FORMAL_APPLICABILITY_NOT_APPLICABLE else raw_price,
                "费用单位": str(row.get("fee_unit") or ""),
                "适用状态": applicability,
                "不适用原因": exemption_reason,
                "来源类型": "real_data",
                "适用品种": str(row.get("commodity_scope") or ""),
                "别名": raw_name if canonical_name and raw_name != canonical_name else "",
                "维护日期": maintained_at,
                "作业费区域编码": "",
                "是否地域代理参考码头": "否",
                "数据来源": f"{row.get('source') or ''}；{confirmation_source}",
            }
        )
    return tuple(formal_rows)


def match_port_label_name(
    port_name: str,
    *,
    registry: NodeRegistry | None,
    dictionary_entries: Iterable[NameDictionaryEntry] = (),
) -> PortLabelNameMatch:
    """Resolve a label locally without registering an alias or writing master data.

    Direct registry matches remain first. A dictionary-assisted match is accepted
    only when removing one maintained port suffix produces the same normalized
    text and every resolvable dictionary candidate points to one existing node.
    Broader containment matches are query hints only.
    """
    raw_name = _required_text(port_name, "portName")
    if registry is not None:
        direct_node = registry.lookup(raw_name)
        if direct_node is not None:
            return PortLabelNameMatch(
                node=direct_node,
                match_status="direct",
                dictionary_status="not_needed",
                dictionary_rows=(),
                dictionary_candidates=(),
                tencent_query_names=(),
            )

    related_entries = _related_dictionary_entries(raw_name, dictionary_entries)
    related_rows = tuple(sorted({entry.row_number for entry in related_entries}))
    related_names = tuple(
        sorted(
            {
                name
                for entry in related_entries
                for name in (entry.full_name, entry.short_name)
                if name
            },
            key=lambda value: (len(value), value),
        )
    )
    query_names = tuple(dict.fromkeys((raw_name, *related_names)))

    suffix_entries = tuple(
        entry
        for entry in related_entries
        if any(
            candidate
            and _normalized_port_name(candidate) == _normalized_port_name(raw_name)
            for candidate in (entry.full_name, entry.short_name)
        )
    )
    suffix_nodes: dict[str, StandardNode] = {}
    if registry is not None:
        for entry in suffix_entries:
            for candidate in (entry.full_name, entry.short_name):
                node = registry.lookup(candidate) if candidate else None
                if node is not None:
                    suffix_nodes[node.node_id] = node

    suffix_rows = tuple(sorted({entry.row_number for entry in suffix_entries}))
    suffix_names = tuple(
        sorted(
            {
                name
                for entry in suffix_entries
                for name in (entry.full_name, entry.short_name)
                if name
            },
            key=lambda value: (len(value), value),
        )
    )
    if len(suffix_nodes) == 1:
        return PortLabelNameMatch(
            node=next(iter(suffix_nodes.values())),
            match_status="dictionary_suffix_unique",
            dictionary_status="unique_suffix_match",
            dictionary_rows=suffix_rows,
            dictionary_candidates=suffix_names,
            tencent_query_names=(),
        )
    if len(suffix_nodes) > 1:
        return PortLabelNameMatch(
            node=None,
            match_status="unmatched",
            dictionary_status="ambiguous_suffix_match",
            dictionary_rows=suffix_rows,
            dictionary_candidates=suffix_names,
            tencent_query_names=query_names,
        )

    return PortLabelNameMatch(
        node=None,
        match_status="unmatched",
        dictionary_status="candidate_only" if related_entries else "not_found",
        dictionary_rows=related_rows,
        dictionary_candidates=related_names,
        tencent_query_names=query_names,
    )


def collect_port_label_tencent_locations(
    audit_rows: Iterable[dict[str, str]],
) -> tuple[PortLabelTencentLocation, ...]:
    """Deduplicate only the labels that remain unbound after local matching."""
    locations: dict[str, PortLabelTencentLocation] = {}
    for row in audit_rows:
        if row.get("node_id"):
            continue
        port_name = row["port_name"]
        query_names = _split_joined_text(row.get("tencent_query_names", "")) or (port_name,)
        locations.setdefault(
            port_name,
            PortLabelTencentLocation(
                port_name=port_name,
                query_names=query_names,
                dictionary_status=row.get("dictionary_status", ""),
                dictionary_rows=tuple(
                    int(value)
                    for value in _split_joined_text(row.get("dictionary_rows", ""))
                ),
                dictionary_candidates=_split_joined_text(row.get("dictionary_candidates", "")),
            ),
        )
    return tuple(sorted(locations.values(), key=lambda location: location.port_name))


def query_port_label_tencent_candidates(
    locations: Iterable[PortLabelTencentLocation],
    provider: CoordinateProvider,
) -> tuple[PortLabelTencentReview, ...]:
    """Query candidates once per unique query name without changing local data."""
    cache: dict[str, CoordinateResolution] = {}
    reviews: list[PortLabelTencentReview] = []
    for location in locations:
        resolutions: list[CoordinateResolution] = []
        for query_name in location.query_names:
            if query_name not in cache:
                cache[query_name] = provider.resolve(query_name)
            resolutions.append(cache[query_name])
        reviews.append(PortLabelTencentReview(location, tuple(resolutions)))
    return tuple(reviews)


def port_label_tencent_review_to_row(review: PortLabelTencentReview) -> dict[str, Any]:
    return {
        "port_name": review.location.port_name,
        "query_names": list(review.location.query_names),
        "dictionary_status": review.location.dictionary_status,
        "dictionary_rows": list(review.location.dictionary_rows),
        "dictionary_candidates": list(review.location.dictionary_candidates),
        "coordinate_resolutions": [
            {
                "status": resolution.status,
                "query_name": resolution.query_name,
                "canonical_name": resolution.canonical_name,
                "longitude": resolution.longitude,
                "latitude": resolution.latitude,
                "source": resolution.source,
                "source_confidence": resolution.source_confidence,
                "message": resolution.message,
                "candidates": [
                    {
                        "rank": candidate.rank,
                        "title": candidate.title,
                        "address": candidate.address,
                        "category": candidate.category,
                        "longitude": candidate.longitude,
                        "latitude": candidate.latitude,
                        "province": candidate.province,
                        "city": candidate.city,
                        "district": candidate.district,
                        "source_id": candidate.source_id,
                    }
                    for candidate in resolution.candidates
                ],
            }
            for resolution in review.resolutions
        ],
        "review_action": (
            "人工确认标准节点及适用费率后，才可手工写入港口能力表.csv或南港码头作业费.csv；"
            "本清单不自动注册别名，不写正式表。"
        ),
    }


def _related_dictionary_entries(
    raw_name: str,
    entries: Iterable[NameDictionaryEntry],
) -> tuple[NameDictionaryEntry, ...]:
    raw_text = normalize_lookup_name(raw_name)
    related: list[NameDictionaryEntry] = []
    for entry in entries:
        if "铁路" in entry.node_type:
            continue
        names = tuple(
            normalize_lookup_name(value)
            for value in (entry.full_name, entry.short_name)
            if value
        )
        if any(
            raw_text == name
            or raw_text in name
            or name in raw_text
            or _normalized_port_name(raw_text) == _normalized_port_name(name)
            for name in names
        ):
            related.append(entry)
    return tuple(related)


def _normalized_port_name(value: str) -> str:
    text = normalize_lookup_name(value)
    for suffix in PORT_NAME_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            return text[: -len(suffix)]
    return text


def _split_joined_text(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split("；") if item.strip())


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PortLabelRuleError(f"无法读取 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PortLabelRuleError(f"{path.name} 不是有效 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise PortLabelRuleError(f"{path.name} 顶层必须是 JSON 对象。")
    return data


def _text_list(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, list):
        items = tuple(_required_text(item, field_name) for item in value)
    else:
        items = (_required_text(value, field_name),)
    if not items:
        raise PortLabelRuleError(f"{field_name}不能为空。")
    return tuple(dict.fromkeys(items))


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise PortLabelRuleError(f"{field_name}不能为空。")
    return text


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise PortLabelRuleError(f"{field_name}必须是大于 0 的有限数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise PortLabelRuleError(f"{field_name}必须是大于 0 的有限数值。") from None
    if not number.is_finite() or number <= 0:
        raise PortLabelRuleError(f"{field_name}必须是大于 0 的有限数值。")
    return number
