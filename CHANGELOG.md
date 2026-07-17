# CHANGELOG.md

This changelog records actual engineering changes. It is not a leader-facing daily report.

## 2026-07-17

### Changed

- Added a developer smoke-test entry:
  - `config/runtime_env.example.csv` documents local-only runtime variables;
  - `src/dev/runtime_env.py` loads `local_env/runtime_env.csv` without committing local paths or API keys;
  - `python -B -m src.dev.smoke_test` runs pytest with a local temp directory and optional real-data/API probes;
  - Windows/Excel CSV encodings are accepted and secret-like notes are redacted in smoke output;
  - project-level `pytest.ini` temp-directory configuration remains intentionally deferred for today's end-of-day report.
- Added a developer feature-demo entry:
  - `python -B -m src.dev.feature_demo` shows the current model behavior for code understanding and daily review;
  - it displays runtime-env status, last-mile truck cost rules, latest-rate selection, formal graph/search behavior, and an optional real-data snapshot;
  - it is a demonstration surface, not the pass/fail smoke-test gate, and it must be updated when core feature behavior changes.
- Improved Tencent Maps probe diagnostics:
  - `src/demos/tencent_map_probe.py` now loads `local_env/runtime_env.csv` directly for standalone runs;
  - coordinate probe output prints manual-review messages so network, API, permission, and candidate-selection issues are distinguishable;
  - HTTP errors include sanitized error type/status details without printing API keys.
- Enabled prototype unknown bulk truck pricing:
  - known maintained truck rates still take priority;
  - `unknown_truck_bulk_distance_tier` now calculates from positive, traceable `distance_km` and `distance_source`;
  - Tencent Maps normal driving distance is accepted only through the geo provider contract;
  - missing, invalid, or untraceable distance remains `manual_review`.
- Enabled prototype unknown container truck pricing:
  - `unknown_truck_container_distance` uses `500 元/箱` within 20 km;
  - over 20 km it uses `500 + (distance_km - 20) * 30 * 0.55 元/箱`;
  - it keeps the unit as `元/箱`, does not convert to `元/吨`, and does not silently treat `柜` as `箱`.
- Added a conservative real-data bridge:
  - `src/routing/real_data_bridge.py` converts billed `EdgeCandidate` rows into formal `TransportEdge` objects;
  - missing shipping time or missing node IDs remain `manual_review`;
  - explicitly setting `REAL_DATA_DEMO_MANUAL_TIME_HOURS` lets `src/demos/real_data_run.py` validate the formal graph/search chain locally without claiming real business timing.
- Reorganized `src` into functional packages:
  - `src/data` for data audit, real-data loading, and local output helpers;
  - `src/domain` for request, unit, node, freight-rate, latest-rate, and cost-rule models;
  - `src/geo` for coordinate and distance providers;
  - `src/routing` for customer profile, shipping time, transport edge, graph, search, and route result modules;
  - `src/demos` for all leader-facing demos, real-data development runs, and public API probes.
- Updated tests and demo imports to use package paths such as `src.domain.cost_rules` and `src.routing.route_search`.
- Changed the main demo command to `python -m src.demos.leader`.

### Removed

- Removed obsolete CSV/DiGraph prototype files from `src`: `models.py`, `graph_builder.py`, and `route_planner.py`.
- Removed duplicate standalone `demo_cost_rules.py`; cost-rule demonstration remains available through `python -m src.demos.leader cost-rules`.

### Verification

- Full pytest suite passed after the restructuring and real-data bridge.

## 2026-07-16

### Added

- Added durable project memory structure:
  - `AGENTS.md`
  - `PLAN.md`
  - `docs/PROJECT_STATE.md`
  - `docs/ARCHITECTURE.md`
  - `docs/DECISIONS.md`
- Recorded that truck cost-rule correction is now today's first functional task before latest-rate selection.
- Added durable stakeholder reporting rules that separate actual engineering state from conservative leader-facing demand management.
- Corrected last-mile truck cost-rule boundary:
  - known truck routes use maintained `FreightRate` records;
  - unknown truck routes return `manual_review`;
  - draft unknown-route formulas remain disabled until distance and business formulas are confirmed.
- Integrated known truck-route policy into `data/loaders.py` candidate generation for freight-rate records whose transport mode is `汽运`.
- Updated unknown bulk truck-route rule to revised `draft-2` piecewise yuan-per-ton parameters from `docs/最后一公里汽运计费规则算法设计_修订版.md`; at that point it remained disabled until the 2026-07-17 confirmed-distance activation.
- Added durable input-completeness rule: user-provided files, formulas, paths, and requirements must be checked for missing or conflicting implementation details before coding.
- Added `src/geo/coordinate_provider.py` and tests for global local-first coordinate confirmation:
  - known coordinates resolve from `NodeRegistry`;
  - unknown coordinates fall back to a disabled Tencent Maps placeholder;
  - missing external provider returns `manual_review`.
- Added Tencent Maps provider spike:
  - `src/geo/distance_provider.py` defines road route request/result interfaces;
  - `src/geo/tencent_map_provider.py` implements Tencent place search and normal driving-route adapters;
  - `src/demos/tencent_map_probe.py` provides an optional local API smoke test;
  - API key is read only from `TENCENT_MAP_API_KEY`;
  - truck-route adapter remains optional future enhancement, while normal driving route is the current default for road distance/time.
- Added latest freight-rate selection:
  - `src/domain/latest_rate_selector.py` groups records by `FreightRate.business_route_key`;
  - only the latest unambiguous dated record enters candidate billing;
  - raw missing dates remain empty but use `1970-01-01` as a traceable internal comparison baseline;
  - normally dated records supersede undated historical records, while same-effective-date conflicts remain manual-review items;
  - candidate and review exports distinguish raw maintenance date, effective comparison date, and whether the date was defaulted;
  - exact duplicate latest records are deterministically reduced to one candidate record;
  - `data/loaders.py` preserves full loaded history while filtering candidate generation;
  - `demos/leader.py latest-rate` provides a sanitized business-facing demonstration.
- Added first-version shipping-time provider:
  - `src/routing/shipping_time_provider.py` defines `ShippingTimeRequest`, `ShippingTimeResult`, `ManualShippingTimeProvider`, and unconfigured JSON/database/API placeholders;
  - manual inputs in hours, days, and minutes are normalized to internal hours;
  - missing, zero, negative, non-numeric, unsupported-unit, and unconfigured-provider cases return `manual_review` without a usable time;
  - `tests/test_shipping_time_provider.py` covers valid conversion, invalid inputs, result invariants, and placeholder providers;
  - `src/demos/leader_shipping_time.py` and `python -m src.demos.leader shipping-time` show the current source and unconnected future sources.
- Added first-version customer profile and route branching:
  - `src/routing/customer_profile.py` preserves customer/factory/private-terminal fields and traceable sources;
  - private-terminal and transfer-terminal branches are mutually exclusive;
  - unknown, missing-source, and contradictory profile data returns `manual_review` without guessing;
  - transfer-port distance is used only for deterministic nearest-K pre-filtering before cost/time comparison.
- Added traceable formal transport edges:
  - `src/routing/transport_edge.py` combines `FreightRate`, `CostCalculationResult`, and `ShippingTimeResult`;
  - only candidates with nodes, positive order-segment cost/time, and complete trace fields are `available`;
  - missing values remain unavailable with explicit reasons and never default to zero.
- Added the formal multi-edge graph:
  - `src/routing/transport_graph.py` builds `nx.MultiDiGraph` with edge IDs as keys;
  - parallel transport options are preserved;
  - unavailable, duplicate-ID, and unknown-node edges are excluded with issue records.
  - production graph construction requires a `NodeRegistry` by default; sanitized demos/tests must opt in explicitly when using unregistered nodes;
  - graph-build exclusions are retained on the graph and block resolved recommendations.
- Added independent route search strategies:
  - `src/routing/route_search.py` defines the strategy protocol and NetworkX Dijkstra baseline;
  - cost and time are searched separately;
  - results retain each selected MultiDiGraph edge key;
  - missing nodes, same-node requests, missing/invalid weights, and no-path cases have explicit statuses;
  - search outcomes carry deterministic graph-weight signatures so mutated graphs require a new search.
- Added explainable route results:
  - `src/routing/route_result.py` restores complete segments and trace fields from selected edge keys;
  - route totals are checked against segment sums;
  - row export preserves resolved segments plus explicit no-path/manual-review status rows;
  - `demos/leader.py route-search` demonstrates different cost-minimum and time-minimum routes with sanitized objects.

### Verification

- Full pytest suite passed: `213 passed in 1.20s`.
- `demos/leader.py` demos for shipping time, customer profile, transport edge, MultiDiGraph, and route search are runnable without real data or API keys.
- Real business data remains outside the formal graph until customer profile, missing nodes, trunk-shipping inputs, and candidate integration are resolved.

### Notes

- `README_Codex_移交说明.md` deletion was confirmed by the user as intentional.
- Real business data remains local-only and must not be committed.
- Tencent Maps API key must never be written to Git-tracked files or printed in logs.

## 2026-07-15

### Added

- Centralized traceable freight calculations in `src/domain/cost_rules.py`.
- Added `CostRuleConfig`, `CostCalculationResult`, and `CostRuleEngine`.
- Registered freight-rate, bulk-shipping, manual-quote, and draft unknown-truck rules.
- Kept unknown truck rules disabled pending distance provider and business confirmation.
- Added tests for cost-rule ids, versions, traces, manual review, and disabled rules.

### Changed

- `FreightRate.evaluate_for_request()` delegates to the unified cost-rule engine.
- Data audit separates sanitized committed reports from local detailed output.
- Fee outlier checks are isolated by fee unit instead of mixing different billing units.

### Verification

- Full pytest suite passed in the user's PyCharm virtual environment: `107 passed`.
- Changes were committed and pushed to GitHub after sensitive-data checks.

## 2026-07-14 To 2026-07-15

### Added

- `src/domain/freight_rate.py` formalized the `FreightRate` model.
- `src/domain/route_request.py` formalized order request and packaging/unit validation.
- `src/domain/unit_conversion.py` implemented exact matching for `吨`, `箱`, and `柜`.
- `src/domain/node_registry.py` implemented standard node ids, aliases, and coordinate conflict reporting.
- Leader demo files were added for node registry, route request, freight rate, real data, and cost rules.

### Changed

- `src/data/loaders.py` now reads local real JSON data into typed intermediate records and candidate edge records.
- `src/demos/real_data_run.py` evolved into a mutable development integration script.
- `src/demos/leader.py` became the leader-facing demo menu.

### Verification

- Unit tests were added for data loaders, node registry, route request, unit conversion, freight rate, data audit, and cost rules.

## Earlier Baseline

### Added

- Initial prototype used CSV/sample data, `networkx.DiGraph`, and basic shortest-path logic.
- Initial docs described project background, module architecture, algorithm design, cost rules, data structures, and technical boundaries.

### Known Drift

- Early documents still mention CSV-first sample-data design. Current development has moved toward local JSON data via `DATA_DIR`, formal `FreightRate`, `RouteRequest`, `NodeRegistry`, and `CostRuleEngine`.
