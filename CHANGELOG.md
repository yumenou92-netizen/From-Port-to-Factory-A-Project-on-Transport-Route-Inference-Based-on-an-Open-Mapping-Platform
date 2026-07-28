# CHANGELOG.md

This changelog records actual engineering changes. It is not a leader-facing daily report.

## 2026-07-27

### Changed

- Unified the current shipping-time business scope: maintained “航行时效” now represents the complete corresponding shipping segment for both north-to-south bulk shipping and inland-waterway barge transport; the model does not decompose waiting, loading, physical sailing, or unloading.
- Changed bulk-shipping and barge edges to require `time_scope=complete_segment`; missing segment time remains unavailable and is never defaulted to zero.
- Added a source-backed `内河驳船运输时效.csv` interface with day/hour conversion, bidirectional regional matching, explicit source/rule trace, and duplicate or missing-rule manual review.
- Added the inland-waterway time table to the read-only data-foundation audit, including file status, record count, normalized hour output, and the warning that time alone cannot authorize a graph edge without applicable freight and endpoint capability.
- Added W5 formal-data admission review output that separates rows eligible for manual admission review from unresolved-node rows and fee-meaning review rows; the audit still never writes the formal W5 source table automatically.
- Added explicit W5 application after user approval: 69 bound positive rules enter the local formal table as `chargeable`, two confirmed customer-owned-terminal rules enter as `not_applicable`, and other unbound positive rows are ignored.
- Extended the operation-fee Provider with a source-backed `not_applicable` result. It carries an explicit 0 amount and exemption reason, creates no artificial zero-valued cost component, and remains distinct from missing-data `manual_review`.
- Extended `leader_full_flow` and data-foundation audit output to distinguish charged operation fees, approved non-applicability, and missing or unsafe fee data.

### Verification

- Affected inland-waterway time, barge capability, bulk-shipping, transport-edge, data-foundation audit, template, full-flow, and W5 admission tests passed: `57 passed in 0.73s`.
- Required developer smoke passed after the final W5 admission changes: `350 passed in 1.70s`; real-data smoke passed with 312 graph-ready edges and zero missing node IDs. The Tencent probe completed safely with network failures represented as `manual_review`, not as successful live API evidence.
- Read-only local audits loaded 7 regional inland-waterway time rules and generated W5 admission review groups of 69 eligible-for-review, 7 pending-node, and 2 pending-fee-meaning rows. No Tencent call or formal-table write was performed.
- After explicit approval, the local formal W5 table loaded 69 chargeable rates and 2 non-applicability rules; the final affected W5, full-flow, audit, and template suite passed `41 passed in 0.78s`.

## 2026-07-24

### Changed

- Confirmed `秀屿` as an in-scope Fujian bulk-shipping destination label and mapped `秀屿港` to the `福建` pure-sailing time region for bulk-shipping classification.
- Added W3 CSV loaders for `港口能力表.csv` and `区域映射表.csv`; missing tables are audited as missing interfaces rather than guessed defaults.
- Extended the data-foundation audit to report W3/W5 table paths, record counts, node-binding gaps, warnings, and row-level CSV outputs for port capabilities, region mappings, and south-port operation fees.
- Added a W5 south-port operation-fee Provider contract for one aggregate `码头作业费` component in `元/吨`.
- Added a CSV-backed operation-fee Provider and an explicit `demo_placeholder` operation-fee Provider; missing or unmatched operation-fee data returns `manual_review` without a usable amount and is not interpreted as zero.
- Extended `RouteRequest` and the W5 operation-fee Provider with `trade_type`: current demo defaults to `内贸`, while `外贸` is preserved as an explicit future matching dimension.
- Extended W5 operation-fee matching to require exact package, commodity scope, trade type, and fee unit alignment; `散粮` uses `元/吨`, containerized orders may use `元/箱`, and `吨/箱/柜` are still never converted automatically.
- Added a read-only `部分码头标签.json` audit converter: `serviceFees.入库` is treated as a candidate `码头作业费` unit rate for `散粮`, retaining `tradeType` and commodity scope while leaving unmatched aliases or invalid fee rows for manual review.
- Added dictionary-first label resolution to the port-label audit: only unique exact matches after conservative port-suffix normalization may bind an audit candidate, without registering aliases or writing formal data; unresolved names are deduplicated into a Tencent-pending JSONL, while API results are written to a separate review file only when explicitly requested.
- Added tested W3/W5 data templates under `docs/data_templates/` so business-maintained CSV files can be created without guessing headers.
- Connected the W5 operation-fee Provider to `leader_full_flow` as an optional formal input: when a fee table is present, resolved fees are included as trunk-edge cost components, while candidates with missing or unsafe operation-fee data are excluded with a warning instead of participating as implicit zero-cost fees.
- Extended `RouteSegment` to preserve and validate `CostComponent` entries, allowing leader output to show sub-costs such as bulk-shipping freight and south-port operation fees.
- Applied the first human-reviewed port-label identity batch and the already-unambiguous candidate write-back to local real-data masters: ten new coordinate nodes and fourteen explicit alias relationships now bind the reviewed raw labels to standard nodes; `肇庆福加德码头` is bound to the customer company node and classified as customer-owned, while `汇东`, `百达`, and `红东` remain explicit ignores rather than aliases.
- Kept the partial operation-fee source out of the active formal filename because strict W5 loading would exclude every uncovered south-port candidate; W3 capability booleans also remain unfilled until business confirmation rather than being inferred from identity.
- Added the confirmed W5 operation-fee priority `exact node rate -> confirmed operation_fee_region_code proxy -> manual_review`; region assignments use explicit standard node IDs and never city/name/coordinate inference.
- Added `regional_proxy` as a formal traceable cost source. Proxy components retain the reference port, mapping basis, rule ID/version, and an explicit statement that the value is not the target port's exact real rate.
- Extended W3/W5 templates and the data-foundation audit with operation-fee region assignments and reference-port fields; unconfirmed or duplicate mappings and reference rates remain manual-review evidence.
- Extended route-relevant node and customer contracts with supported transport modes, confirmation status, maintenance fields, and a stable customer-owned-terminal relation; unknown port capabilities are preserved as blank/`None` instead of false, and capability filtering remains disabled.

### Verification

- W3/W5 and affected bulk/audit tests passed: `19 passed in 0.25s`.
- Affected inland-waterway/full-flow/cost-component regression tests passed: `20 passed in 0.59s`.
- W3/W5 templates, full-flow operation-fee integration, route-result cost components, Provider, and audit tests passed: `32 passed in 0.54s`.
- Trade-type, W5 exact-unit matching, tag-JSON conversion, full-flow, and data-foundation affected tests passed: `44 passed in 0.43s`.
- Read-only data-foundation audit completed without Tencent calls or real-data write-back; current real data shows 0 unresolved freight locations, 2 unresolved AdditionalFee station nodes, 18 bulk-workbook columns, and 0 currently loaded W3/W5 records.
- Read-only `部分码头标签.json` audit completed without Tencent calls or real-data write-back: 76 expanded candidate fee records, 2 manual-review rows, 13 direct node matches, and 65 unmatched rule rows covering 27 deduplicated names requiring alias/Tencent/manual confirmation before formal table use.
- Dictionary-first and Tencent-review workflow tests passed: `13 passed in 0.48s`; the refreshed read-only audit found 13 direct matches, 9 dictionary-assisted rule-row matches covering 4 names, and 56 still-unmatched rows covering 23 deduplicated Tencent-review names.
- After the human-confirmed and unambiguous alias/coordinate write-back, all 24 checked lookup names resolve to the intended standard nodes. The refreshed no-Tencent audit found 60 direct matches, 9 dictionary-assisted rule-row matches, and 9 still-unmatched rows covering 7 deduplicated names.
- Final alias, node-registry, and port-label audit tests passed: `16 passed in 0.45s`; the real-data registry loads 303 standard nodes with zero coordinate conflicts, and its two remaining alias-review groups are pre-existing railway-name groups.
- W5 regional proxy, route-label contracts, customer-owned-terminal relation, cost-component, formal-graph/search, full-flow, template, and audit tests passed: `123 passed in 0.75s`. Full pytest, Tencent calls, and the real-data smoke were intentionally not repeated because the user requested affected-scope verification only.

## 2026-07-23

### Changed

- Recorded the latest user PyCharm full-flow acceptance for Phase 17 and marked the phase as completed in project planning state.
- Recorded the Phase 18 B1 business baseline: bulk shipping rates are yuan per ton, apply to all project north ports, calculate as rate times order tons, exclude port operation fees, and ignore tax handling.
- Clarified that non-Guangdong/Guangxi/Fujian/Hainan destination columns in the bulk shipping workbook stay out of the current route engine scope.
- Clarified the first south-port operation-fee integration target as one aggregate `码头作业费` component in yuan per ton, with Provider/CSV structure reserved for later fee breakdowns.
- Added a real bulk-shipping workbook provider that reads the latest row from `散船运价表.xlsx`, preserves parallel destination/vessel columns, selects the smallest vessel that can cover the order tonnage, and calculates trunk freight as yuan-per-ton times order tons.
- Replaced `leader_full_flow` north-to-south trunk cost/time placeholders with real bulk-shipping freight and confirmed pure-sailing regional time; candidates without confirmed sea-shipping destination/time mapping are excluded with an explicit warning.
- Recorded the automatic-candidate boundary and future manual south-port mode: auto mode must not treat inland ports as north-to-south sea-shipping destinations; user-specified south ports will become fixed trunk segments outside the north-to-south candidate graph.
- Recorded the vessel-time data gap as a durable project constraint and added a route warning when recommendations contain vessel segments: current bulk-shipping time is pure sailing only, while barge, operation, waiting, loading, unloading, storage, and short-transfer times remain unavailable.
- Recorded the inland-waterway business boundary: only Fujian/Minjiang and Pearl Delta inland-waterway scenarios are considered; 300 km truck pre-filtering is not a project rule.
- Added data interface records for port capabilities, regional mappings, and inland-waterway barge fee/time sources.
- Added `DemoInlandWaterwayBargeProvider`, which generates explicit `demo_placeholder` barge edges only for same-region Fujian/Minjiang or Pearl Delta bulk-grain scenarios and otherwise produces no edge.

### Verification

- Focused bulk-shipping and full-flow tests passed: `11 passed in 0.30s`.
- Real-data smoke was intentionally skipped for this increment; a no-network read-only probe confirmed the real workbook loads and distinguishes confirmed sea-shipping destinations from unmatched inland candidates.
- Focused full-flow warning regression passed after the vessel-time boundary update.
- Focused inland-waterway Provider tests passed: `6 passed in 0.07s`.
- Pre-commit affected-suite tests passed: `47 passed in 0.65s`.
- End-of-day full pytest passed: `300 passed in 1.78s`.
- End-of-day read-only data-foundation audit completed without Tencent calls or real-data write-back; current audit shows 0 unresolved freight-rate locations, 2 unresolved AdditionalFee station nodes, and 18 bulk-workbook columns.

## 2026-07-22

### Changed

- Changed missing-node coordinate review to query the raw business name first and each explicit dictionary full name separately, preserving every result for human comparison instead of replacing the raw query.
- Tencent resolved-coordinate results now retain structured candidate trace fields, including address, category, administrative area, and POI ID, even when place search returns only one candidate.
- The JSONL review schema now exposes `query_names` and parallel `coordinate_resolutions`; it still does not write the coordinate registry or approve aliases automatically.
- Applied the second local-only batch of human-confirmed coordinates and explicit aliases: 10 standard coordinate records and 7 alias groups were verified without adding business names or coordinates to Git-tracked files.
- Applied the final reviewed local batch: 17 additional coordinate records and 9 alias groups now cover every distinct location name in the current freight-rate dataset; the user-confirmed company coordinate supersedes the rejected Tencent candidate for that review item.
- Added the first Phase 18 contract slice: source-backed node profiles, explicit transport stages and time scopes, traceable cost components, and structured manual-review outcomes.
- Extended shipping-time results and transport edges without changing existing cost/time search weights; missing time scope remains unknown instead of being silently labeled as a complete segment.
- Required supplied cost components to equal the transport-edge total and included the new transport semantics in stable edge IDs so parallel options cannot collide.
- Created a sanitized public GitHub issue for Phase 18 while keeping the detailed internal execution plan local.

### Verification

- Targeted coordinate-review and Tencent-provider tests passed: `15 passed in 0.19s`.
- After the confirmed local-data update, the no-network audit reduced the deduplicated missing locations from 29 to 17, with 19 planned queries; targeted dictionary/data/backfill tests passed with `24 passed in 0.80s`.
- Confirmed-node validation passed for all 10 coordinate records and 7 alias groups; the current real-data chain reports 275 standard coordinates, 312 billed candidates, 192 graph-ready candidates, 120 missing-node candidates, and 29 manual-review records.
- Final confirmed-node validation passed for all 17 remaining locations with zero coordinate conflicts. The current chain reports 292 standard coordinates, all 295 distinct freight-rate location names matched, 312 billed and graph-ready candidates, zero missing-node candidates, and zero deduplicated coordinate-backfill locations.
- Final local-data targeted tests passed with `24 passed in 0.79s`; full smoke was not repeated because no pricing behavior, graph construction, or route-search behavior changed in this batch.
- Full smoke was intentionally not repeated because pricing, graph construction, and route search were unchanged.
- After the Phase 18 W1 contract change, focused contract and affected-chain tests passed with `78 passed in 0.42s`.
- The required developer smoke passed with `284 passed in 1.39s`; real-data smoke passed. The Tencent diagnostic command completed with API connection failures represented as `manual_review`, so it is not evidence of a successful live Tencent query.

## 2026-07-21

### Added

- Added `python -B -m src.demos.leader full-flow`, an interactive leader demo that accepts north port A and customer factory B and returns independent lowest-cost and fastest-time recommendations through the formal graph/search chain.
- Added real-first candidate composition: local coordinates and maintained last-mile rates take priority, Tencent Maps supplies unresolved coordinates and road distance/time, and confirmed unknown-route cost rules handle unmaintained last-mile routes.
- Added an isolated `demo_placeholder` layer for the currently missing north-to-south shipping cost/time and the displayed no-private-terminal customer profile; AdditionalFee remains explicitly excluded pending attribution.
- Added per-edge source trace categories and a final minimal-placeholder disclosure in the leader output.
- Added coordinate `source_confidence` to the full-flow leader output so Tencent top1 results can be audited during rehearsal.
- Added local `名称字典.xlsx` parsing: only explicit full-name/short-name pairs may extend an already registered coordinate node's aliases; blank pairs and conflicts stay in manual review.
- Added `src.demos.node_coordinate_backfill`, which deduplicates missing-node candidate endpoints into a JSONL review list and can query Tencent candidate coordinates only when explicitly requested; it never writes `地点经纬度.json` or auto-registers an alias.
- Made the name-dictionary reader tolerate sparse Excel rows that contain fewer than three physical cells after a standards-compliant workbook save.
- Completed the first local-only batch of three human-confirmed node mappings; no business names or coordinates were added to Git-tracked files.
- Added integration coverage for dual recommendations, real-rate priority, placeholder confinement, source labels, and unresolved-coordinate failure.
- Updated the developer feature demo with the full-flow command and source boundary.

### Verification

- After the sparse-row compatibility fix and local node updates, targeted tests passed with `20 passed in 0.55s`; the real-data chain improved to `492 / 314 / 152 / 162 / 27`, with 29 deduplicated missing locations remaining.
- Full developer smoke passed after the name-dictionary and coordinate-review additions: `259 passed in 1.06s`; real-data smoke retained `492 / 314 / 144 / 170 / 27`.
- Full developer smoke passed with `251 passed` after the coordinate-confidence display update.
- Real-data smoke retained the verified `492 / 314 / 144 / 170 / 27` counts and completed successfully.
- Tencent API integration remains local-only and is ready for the user to rehearse in PyCharm with `local_env/runtime_env.csv`.

## 2026-07-20

### Changed

- Updated `src/demos/leader.py` to load `local_env/runtime_env.csv` before importing leader demo modules, so direct commands such as `python -B -m src.demos.leader cost-rules` can find project-local dependencies without manual `PYTHONPATH` setup.
- Kept leader demo modules lazy-loaded by key, preserving the existing demo menu while avoiding unnecessary imports before the runtime environment is ready.
- Recorded the user-confirmed demonstration schedule: enter demo-freeze/convergence on 2026-07-23 and prepare the first formal demo for the 2026-07-24 10:30 model presentation.
- Added interactive manual candidate selection to `src/demos/tencent_map_probe.py`: when Tencent place search returns structured manual-review candidates, a local interactive console can accept a candidate rank and continue to the driving-route distance probe.
- Added `TENCENT_MAP_PROBE_INTERACTIVE` to the runtime env template and smoke-test environment snapshot; non-interactive smoke runs skip the prompt so automated validation does not hang.
- Updated the formal Tencent coordinate provider so multi-candidate place-search results no longer block by default in the prototype: top 1 is auto-selected, `source_confidence` records `auto_top1_name_match`, `auto_top1_nearby_cluster`, or `auto_top1_unclustered`, and the top 5 candidates remain attached for review.
- Local demo display text is now leader-friendly Chinese in the Tencent Maps probe, real-data demo, and node-registry demo; internal status codes, environment variables, and output file names remain unchanged for traceability.
- Recorded the main-chain real-data smoke acceptance in `docs/PROJECT_STATE.md`, including candidate counts, missing-node counts, manual-review counts, formal graph edge counts, CSV output checks, and remaining automation blockers.
- Added `docs/2026-07-20_ACCEPTANCE_LOG.md` as the fourth-stage module acceptance log with a fixed record format for command, result, pass/fail, questions, and business-confirmation needs.

### Verification

- Direct leader demo commands for `cost-rules` and `route-search` run without manually setting `PYTHONPATH`.
- Tencent probe manual-selection helper is covered by tests for accepted rank input and disabled non-interactive behavior.
- Tencent coordinate-provider tests cover top1 name-match, nearby-cluster, and unclustered multi-candidate outcomes.
- Full developer smoke passed with `248 passed`; real-data smoke and Tencent diagnostic probe both completed successfully.

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
- Implemented Tencent Maps multi-candidate coordinate selection in the formal geo layer:
  - `CoordinateResolution` can now carry `source_confidence` and structured manual-review candidates;
  - unique candidates resolve normally, highly similar top candidates can auto-select top 1 with `source_confidence=auto_similar_top1`;
  - ambiguous place-search results return top 5 candidate records for manual selection instead of requiring a GUI popup;
  - `src/demos/tencent_map_probe.py` prints candidate rank, title, address, category, area, and coordinates for local review;
  - Tencent probe region/origin/destination can be overridden with local-only runtime env entries while the committed default remains public Beijing points.
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
