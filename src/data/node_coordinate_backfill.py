from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from src.data.loaders import EdgeCandidate
from src.data.name_dictionary import NameDictionaryEntry
from src.geo.coordinate_provider import CoordinateProvider, CoordinateResolution


@dataclass(frozen=True)
class MissingNodeLocation:
    """One raw location requiring coordinate registration or alias review."""

    raw_name: str
    query_names: tuple[str, ...]
    node_types: tuple[str, ...]
    missing_sides: tuple[str, ...]
    candidate_count: int
    transport_modes: tuple[str, ...]
    sample_rate_ids: tuple[str, ...]
    dictionary_status: str
    dictionary_rows: tuple[int, ...]


@dataclass(frozen=True)
class CoordinateBackfillReview:
    location: MissingNodeLocation
    resolutions: tuple[CoordinateResolution, ...]


def collect_missing_node_locations(
    candidates: Iterable[EdgeCandidate],
    dictionary_entries: Iterable[NameDictionaryEntry] = (),
) -> tuple[MissingNodeLocation, ...]:
    """Deduplicate unresolved candidate endpoints without changing business data.

    A complete dictionary pair may provide additional Tencent query names, but
    it never proves an alias or creates a node. Those decisions remain review-only.
    """
    dictionary_by_name = _dictionary_entries_by_name(dictionary_entries)
    aggregates: dict[str, dict[str, set[str] | int]] = defaultdict(
        lambda: {
            "missing_sides": set(),
            "transport_modes": set(),
            "rate_ids": set(),
        }
    )
    for candidate in candidates:
        if candidate.from_node_id is None:
            _add_candidate_side(aggregates, candidate.origin, "origin", candidate)
        if candidate.to_node_id is None:
            _add_candidate_side(aggregates, candidate.destination, "destination", candidate)

    locations: list[MissingNodeLocation] = []
    for raw_name, aggregate in aggregates.items():
        entries = dictionary_by_name.get(raw_name, ())
        explicit_entries = tuple(entry for entry in entries if entry.has_explicit_alias_mapping)
        query_names = _coordinate_query_names(raw_name, explicit_entries)
        dictionary_status = _dictionary_status(entries, explicit_entries)
        locations.append(
            MissingNodeLocation(
                raw_name=raw_name,
                query_names=query_names,
                node_types=tuple(sorted({entry.node_type for entry in entries})),
                missing_sides=tuple(sorted(aggregate["missing_sides"])),
                candidate_count=len(aggregate["rate_ids"]),
                transport_modes=tuple(sorted(aggregate["transport_modes"])),
                sample_rate_ids=tuple(sorted(aggregate["rate_ids"]))[:5],
                dictionary_status=dictionary_status,
                dictionary_rows=tuple(entry.row_number for entry in entries),
            )
        )
    return tuple(sorted(locations, key=lambda item: (-item.candidate_count, item.raw_name)))


def query_coordinate_candidates(
    locations: Iterable[MissingNodeLocation],
    provider: CoordinateProvider,
) -> tuple[CoordinateBackfillReview, ...]:
    """Fetch candidate coordinates only; never write the coordinate registry."""
    return tuple(
        CoordinateBackfillReview(
            location=location,
            resolutions=tuple(provider.resolve(query_name) for query_name in location.query_names),
        )
        for location in locations
    )


def backfill_review_to_row(review: CoordinateBackfillReview) -> dict[str, object]:
    location = review.location
    return {
        "raw_name": location.raw_name,
        "query_names": list(location.query_names),
        "node_types": list(location.node_types),
        "missing_sides": list(location.missing_sides),
        "candidate_count": location.candidate_count,
        "transport_modes": list(location.transport_modes),
        "sample_rate_ids": list(location.sample_rate_ids),
        "dictionary_status": location.dictionary_status,
        "dictionary_rows": list(location.dictionary_rows),
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
        "review_action": "人工确认后再写入地点经纬度.json；本清单不自动注册节点或别名。",
    }


def _add_candidate_side(
    aggregates: dict[str, dict[str, set[str] | int]],
    raw_name: str,
    side: str,
    candidate: EdgeCandidate,
) -> None:
    aggregate = aggregates[raw_name]
    aggregate["missing_sides"].add(side)  # type: ignore[union-attr]
    aggregate["transport_modes"].add(candidate.transport_mode)  # type: ignore[union-attr]
    aggregate["rate_ids"].add(candidate.rate_id)  # type: ignore[union-attr]


def _dictionary_entries_by_name(
    entries: Iterable[NameDictionaryEntry],
) -> dict[str, tuple[NameDictionaryEntry, ...]]:
    index: dict[str, list[NameDictionaryEntry]] = defaultdict(list)
    for entry in entries:
        for value in (entry.full_name, entry.short_name):
            if value:
                index[value].append(entry)
    return {name: tuple(values) for name, values in index.items()}


def _coordinate_query_names(
    raw_name: str,
    entries: tuple[NameDictionaryEntry, ...],
) -> tuple[str, ...]:
    full_names = sorted(
        {
            entry.full_name
            for entry in entries
            if entry.short_name == raw_name and entry.full_name
        }
    )
    return tuple(dict.fromkeys((raw_name, *full_names)))


def _dictionary_status(
    entries: tuple[NameDictionaryEntry, ...],
    explicit_entries: tuple[NameDictionaryEntry, ...],
) -> str:
    if not entries:
        return "not_in_dictionary"
    full_names = {
        entry.full_name
        for entry in explicit_entries
        if entry.full_name is not None
    }
    if len(full_names) > 1:
        return "ambiguous_dictionary_mapping_review_required"
    if explicit_entries:
        return "explicit_full_short_pair_review_required"
    return "dictionary_name_without_explicit_pair"
