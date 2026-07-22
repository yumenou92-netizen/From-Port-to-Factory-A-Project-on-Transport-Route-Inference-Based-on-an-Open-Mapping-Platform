# DECISIONS.md

This document records durable business and technical decisions. Add new decisions when rules change.

Updated: 2026-07-21

## D-001: Prototype Scope

Date: 2026-07-09

Decision:

This project is a Python prototype for explainable route inference, not a production route-planning or quotation system.

Reason:

The current goal is to validate data structure, business rules, cost logic, time logic, and graph-search feasibility before investing in production infrastructure.

Implications:

- Prefer clear Python modules and pytest over production services.
- Do not add database, backend, or frontend infrastructure unless explicitly requested.

## D-002: Real Business Data Stays Local

Date: 2026-07-14

Decision:

Real business data may be read locally but must not be committed or pushed.

Reason:

Data includes business routes, customer/location information, coordinates, and freight-rate records.

Implications:

- Use `DATA_DIR`.
- Keep `data_REAL/` and `output/` ignored.
- Commit only sanitized or aggregated outputs.

## D-003: South Port Is One Physical Node

Date: 2026-07-10

Decision:

The first-stage destination "南方港口" and second-stage origin "南方港口" are the same physical node.

Reason:

Creating duplicate nodes would break graph continuity and route explanation.

Implications:

- Use the same `node_id` and coordinates.
- Handle aliases through `NodeRegistry`, not duplicate graph nodes.

## D-004: Cost And Time Are Independent Weights

Date: 2026-07-10

Decision:

Store and search `cost` and `time` as separate weights.

Reason:

No confirmed business coefficient exists for combining money and time into a single score.

Implications:

- Output cost-minimum and time-minimum routes separately.
- Do not implement a combined "best" path unless the business supplies coefficients.

## D-005: Raw Unit Prices Must Not Enter Route Search

Date: 2026-07-13

Decision:

Route-search `cost` must be current-order segment total cost in yuan.

Reason:

Raw values such as `元/吨`, `元/箱`, and `元/柜` are not directly additive.

Implications:

- Validate quantity unit against price unit.
- Convert to total yuan before graph construction.
- Keep raw price and unit only as explanation fields.

## D-006: Packaging Does Not Determine Transport Mode

Date: 2026-07-15

Decision:

Transport mode must be read from freight-rate data. Packaging is only auxiliary validation.

Reason:

Packaging and transport mode are different business dimensions.

Implications:

- Do not infer `汽运`, `驳船`, or other transport modes from `散粮` or `集装箱`.
- Use packaging to decide whether the order unit is plausible.

## D-007: Box And Container-Load Units Are Not Interchangeable

Date: 2026-07-15

Decision:

`箱` and `柜` are both container-related billing units, but they are not the same unit.

Reason:

Business feedback clarified that one "柜" may correspond to multiple containers or boxes depending on context.

Implications:

- `500箱` can match `元/箱`.
- `500柜` can match `元/柜`.
- `500柜` must not automatically match `元/箱`.
- `500箱` must not automatically match `元/柜`.

## D-008: FreightRate Delegates Calculation To CostRuleEngine

Date: 2026-07-15

Decision:

`FreightRate.evaluate_for_request()` remains a compatibility entry point but delegates to `CostRuleEngine`.

Reason:

Cost rules need rule ids, versions, traces, and a single calculation result shape.

Implications:

- New cost logic should be added to `domain/cost_rules.py`.
- `FreightRate` should remain a data model, not a rule container.

## D-009: Unknown Truck Rules Are Disabled Until Confirmed

Date: 2026-07-15

Decision:

Unknown-route truck rules are registered but disabled.

Reason:

They depend on a distance provider and have unresolved business formula questions, especially the long-distance container formula.

Implications:

- Known routes use maintained freight rates.
- Unknown routes must not enter automatic recommendation yet.
- Calling disabled rules should fail clearly.

## D-010: Latest Maintained Rate Is Required Before Formal Edge Building

Date: 2026-07-16

Decision:

Same business route with multiple maintained rates must be resolved before formal `TransportEdge` construction.

Reason:

Otherwise stale freight rates may enter the graph and distort route cost.

Implications:

- Use `FreightRate.business_route_key` as the starting route identity.
- A missing raw maintenance date remains `None` for audit and source traceability.
- Latest-rate comparison treats a missing date as the internal baseline `1970-01-01`; this baseline does not overwrite the source record.
- A normally dated record therefore supersedes an undated historical record for the same business route.
- If multiple records conflict on the same effective date, including multiple conflicting undated records sharing the 1970 baseline, the route requires manual review.
- If the latest effective date contains different rate ids, the whole latest-date set requires manual review and that business route produces no automatic candidate.
- Exact duplicates with the same rate id and latest date are reduced to one deterministic source record for candidate generation.
- Older dated records are superseded for candidate generation but remain available in the loaded bundle.
- Data audit should still preserve full raw history.

## D-011: Shipping Time Uses Provider Interface

Date: 2026-07-10

Decision:

Use a `ShippingTimeProvider` interface. The first enabled implementation is `ManualShippingTimeProvider`; JSON, database, and API implementations remain unconfigured placeholders until a reliable source is confirmed.

Reason:

Time may later come from JSON, a database, or an API, but current data does not contain reliable time fields.

Implications:

- Internal time unit should be hours.
- Missing time must not become zero.
- Manual input may be normalized from hours, days, or minutes into hours.
- Missing, zero, negative, non-numeric, or unsupported-unit manual input requires manual review.
- JSON/database/API providers are placeholders until a source is confirmed.
- Placeholder providers must explain that they are unconfigured and must not return a usable time.
- Tencent ordinary driving duration is road-route reference data and must not automatically replace manually confirmed shipping or operational time.

## D-012: Tencent Maps Must Be Behind DistanceProvider

Date: 2026-07-10

Decision:

Do not call Tencent Maps directly from cost rules or graph construction.

Reason:

Distance lookup is an external dependency with credentials, quota, error handling, and caching concerns.

Implications:

- Implement `DistanceProvider` before enabling unknown-route truck pricing.
- Stop and ask for API details if implementation requires external credentials or contract assumptions.

## D-013: Leader Reports Are Not Engineering State

Date: 2026-07-15

Decision:

Leader-facing reports are communication artifacts. Actual project state comes from code, tests, Git, and project memory Markdown files.

Reason:

Reporting cadence and engineering completion have different purposes.

Implications:

- Update `PROJECT_STATE.md` from verified code behavior.
- Do not infer module completion from daily reports.

## D-014: Stakeholder Reporting Uses Conservative Demand Management

Date: 2026-07-16

Decision:

Maintain separate engineering and reporting tracks. Engineering state must be accurate and internal-facing. Leader-facing reports should be factual but conservative, staged, and focused on expectation management.

Reason:

The prototype is evolving quickly, while business stakeholders need stable, non-overstated progress updates. Reporting too aggressively can create unrealistic expectations about delivery speed, production readiness, or data completeness.

Implications:

- Engineering files must record actual completion, blockers, tests, and missing modules.
- Leader-facing plans and reports should use restrained language and avoid over-promising.
- Do not present unimplemented features as complete.
- Do not fabricate results or confirmations.
- Do not make tool-assisted development speed the headline of stakeholder communication.

## D-015: Last-Mile Truck Cost Uses Known-Route First Policy

Date: 2026-07-16

Decision:

Last-mile truck cost must first check whether a maintained truck freight rate exists. If a known route rate exists, calculate through the maintained `FreightRate`. If no maintained rate exists, unknown bulk-truck routes may calculate only when a traceable road distance is supplied by the geo layer.

Reason:

Business feedback indicated the earlier generic truck-cost design was not reliable. Last-mile truck cost depends on maintained familiar-route rates, distance source, packaging, vehicle assumptions, and formula confirmation.

Implications:

- `known_truck_maintained_rate` is the enabled policy for known truck routes.
- `unknown_truck_bulk_distance_tier` is enabled for prototype use only when both `distance_km` and `distance_source` are present.
- `unknown_truck_container_distance` is enabled for prototype use only when both `distance_km` and `distance_source` are present.
- Unknown truck routes without traceable distance remain `manual_review`.
- The old simple idea `truck cost = distance × rate` is not a formal project rule.

## D-016: User-Provided Materials Must Be Checked Before Implementation

Date: 2026-07-16

Decision:

Before implementing work based on user-provided files, rules, or prompts, first locate and read the referenced materials, check for missing or conflicting information, and ask for confirmation when the gap affects implementation safety.

Reason:

Business rules in this project are evolving. Implementing from an incomplete prompt or a path typo can lock wrong assumptions into code, tests, and documents.

Implications:

- Do not assume a referenced file path is correct; locate and verify it.
- Do not silently resolve material ambiguity in formulas, units, directions, data sources, validity dates, provider status, or enablement state.
- If the ambiguity is blocking, ask the user before coding.
- If the assumption is non-blocking, state it and proceed conservatively.

## D-017: Coordinate Resolution Is Local-First With Tencent Maps Fallback

Date: 2026-07-16

Decision:

Coordinate confirmation is a global project rule. The system must first check the standard node registry and known coordinate tables. Only when no local coordinate is available may it use a map geocoding provider such as Tencent Maps.

Reason:

Known internal coordinate tables are more controllable and auditable than external geocoding. External API results may be ambiguous, require credentials, and need cache and manual confirmation policies.

Implications:

- Use `LocalFirstCoordinateProvider` for coordinate confirmation.
- Keep `NodeRegistry` as the source of known node ids, aliases, and coordinates.
- Tencent Maps geocoding must be implemented behind a provider, not called directly from cost rules, graph construction, or path search.
- Tencent Maps fallback may resolve a coordinate only when the provider is configured and the API result is unique or uniquely exact; ambiguous results return `manual_review`.
- New coordinates fetched from an API should be cached locally and manually reviewed before merging into the formal coordinate table.

## D-018: Tencent Maps Uses Normal Driving Route First

Date: 2026-07-16

Decision:

For road distance and estimated time, use Tencent Maps normal driving route as the current default provider. Keep Tencent truck route as an optional future enhancement, not a current hard dependency.

Reason:

Current business need is to obtain road driving distance and estimated time for unknown last-mile routes. Truck route planning is marked by Tencent as an advanced paid service and may not be enabled for a personal key. The prototype should validate the API connection and distance/time contract without depending on vehicle-specific truck restrictions.

Implications:

- Use `TencentMapDrivingRouteProvider` as the current Tencent road-route adapter.
- `TencentMapTruckingRouteProvider` may remain in code for future vehicle-restriction use.
- Convert Tencent route `distance` from meters to kilometers.
- Convert Tencent route `duration` from minutes to hours.
- Read Tencent API key only from `TENCENT_MAP_API_KEY`.
- Do not store or print API keys.
- API failures, no-permission responses, empty routes, and malformed route fields return `manual_review`.
- Prototype unknown bulk-truck cost may consume `tencent_map_driving_route` distance through the geo provider interface; cost rules must not call Tencent Maps directly.

## D-019: Customer Private Terminal Determines The Second-Stage Chain

Date: 2026-07-16

Decision:

The second-stage route structure is determined by whether the customer has a private terminal.

Reason:

A customer with a private terminal can receive the waterway segment directly, while a customer without one requires a transfer terminal and short-distance truck delivery. Sending both cases through the same chain would create physically incorrect routes.

Implications:

- With a private terminal: South Port -> customer private terminal -> delivery complete.
- Without a private terminal: South Port -> candidate transfer terminal -> short-distance truck -> customer factory.
- A private-terminal customer must not be routed through a transfer terminal.
- `CustomerProfile` must contain a traceable source for the private-terminal flag and terminal node.
- Until that data source exists, the system must not guess the route branch.
- `routing/customer_profile.py` implements the branch as `private_terminal` or `transfer_terminal`; unknown, missing-source, or contradictory profile data returns `manual_review` with no executable branch.

## D-020: Candidate Transfer Ports Use Distance Only For Pre-Filtering

Date: 2026-07-16

Decision:

Distance may be used to select the nearest K candidate transfer ports, but it cannot determine the final recommendation by itself.

Reason:

The geographically nearest port may not have the lowest maintained freight cost or the shortest total transport time.

Implications:

- Candidate generation may pre-filter the nearest K ports using a confirmed distance source.
- Each retained candidate chain must calculate total cost and total time.
- Cost-minimum and time-minimum routes are returned separately.
- Straight-line distance must not be presented as final route optimality.
- `prefilter_transfer_ports()` records K, confirmed distance source, deterministic ordering, and the requirement for downstream total-cost/total-time comparison.

## D-021: Formal Graph Uses MultiDiGraph And Returns Edge Keys

Date: 2026-07-16

Decision:

The formal transport graph must use `nx.MultiDiGraph` or an equivalent multi-edge directed structure. Route results must identify the selected edge key for every segment.

Reason:

The same origin and destination may have different transport modes, packaging, prices, sources, maintenance dates, costs, and times. A simple `DiGraph` overwrites parallel choices and loses the evidence needed for explanation.

Implications:

- The old `graph_builder.py`, `route_planner.py`, and `models.py` files have been removed from `src`; do not revive them as a parallel route engine.
- `TransportEdge` must exist before real candidates enter the formal graph.
- Missing cost or time must block or flag an edge; it must not default to zero.
- Route output must include node sequence, edge keys, segment cost, segment time, transport mode, price source, rule trace, total cost, and total time.
- Cost and time searches remain independent under D-004.
- The formal implementation is split across `routing/transport_edge.py`, `routing/transport_graph.py`, `routing/route_search.py`, and `routing/route_result.py`.
- `routing/transport_graph.py` excludes unavailable, duplicate-ID, and unknown-node edges with traceable issue records.
- Formal graph construction requires `NodeRegistry` by default; only sanitized demos and unit tests may explicitly opt into unregistered nodes.
- Any graph-build exclusion blocks a resolved recommendation because the omitted edge may change reachability or optimality.
- `routing/route_search.py` treats missing/invalid weights and same-node requests as `manual_review` rather than using NetworkX defaults or assuming zero transport.
- Search outcomes carry a deterministic objective-weight graph signature, and `routing/route_result.py` requires a new search when graph state changes before verifying edge keys and segment totals.

## D-022: Bulk Shipping Supports Index And Explicit Manual Quote Modes

Date: 2026-07-16

Decision:

North-to-South bulk shipping cost supports index calculation and manual quotation as separate, explicit modes.

Reason:

The two modes have different inputs and audit requirements. Treating an entered number ambiguously as either a unit price or a total price would make the segment cost unreliable.

Implications:

- Index unit price is `coal index * 1.12 + 2 yuan harbor sailing fee + 5 yuan profit` and total cost is the matched order quantity times that unit price.
- Manual quotation must explicitly declare `unit_price` or `total_price` and record the original fee unit.
- Manual unit price follows the same exact quantity-unit matching rules as other maintained rates.
- Manual total price must use a total-amount yuan unit and is not multiplied by quantity again.
- Shipping time remains a separate input under D-011 and is not derived from the cost mode.

## D-023: Source Code Is Organized By Functional Package

Date: 2026-07-17

Decision:

Project source code is organized under functional packages: `src/data`, `src/domain`, `src/geo`, `src/routing`, and `src/demos`.

Reason:

The earlier flat `src` layout mixed model code, provider code, route search, and demos. That made it easy to reuse obsolete prototype files or confuse demo entry points with core modules.

Implications:

- Core model code must live in `data`, `domain`, `geo`, or `routing` according to responsibility.
- Demo and local development scripts must live under `src/demos`.
- New imports should use package paths such as `src.domain.cost_rules` and `src.routing.route_search`.
- Do not add new top-level `src/demo_*.py` files.
- Do not reintroduce the removed CSV/DiGraph prototype chain.

## D-024: Real EdgeCandidate Bridge Requires Explicit Time

Date: 2026-07-17

Decision:

Real-data `EdgeCandidate` rows may enter the formal graph only through `routing/real_data_bridge.py`, and only when they have both endpoint node IDs and an explicit shipping-time input.

Reason:

The current real data already supports order-segment cost calculation, but it does not provide complete transport time. Letting cost-only candidates enter graph search would create misleading fastest-time results.

Implications:

- Missing shipping time keeps the converted `TransportEdge` in `manual_review`.
- Missing endpoint node IDs also keep the converted edge in `manual_review`.
- `src/demos/real_data_run.py` may use `REAL_DATA_DEMO_MANUAL_TIME_HOURS` for local chain validation, but this is not a real business-time source.
- Formal route recommendations based on that variable must be presented as integration validation only.
- A future production path must replace the demo time variable with a confirmed manual, JSON, database, or API shipping-time source.

## D-025: Prototype Unknown Bulk Truck Uses Confirmed Normal Driving Distance

Date: 2026-07-17

Decision:

For prototype-stage last-mile unknown bulk-truck pricing, Tencent Maps normal driving distance is an accepted formal distance input after it has been obtained through the geo provider layer. `domain/cost_rules.py` only consumes `distance_km` and `distance_source`.

Reason:

The prototype must produce usable route-cost behavior before truck-specific driving data is available. Tencent truck routing may require paid or advanced permissions, while normal driving distance can validate the route-distance contract now. API keys and external calls must stay outside the domain cost layer.

Implications:

- Known maintained truck rates still take priority over unknown-route formulas.
- `unknown_truck_bulk_distance_tier` can return a valid cost when `distance_km` is positive and `distance_source` is traceable.
- Missing distance, missing source, non-positive distance, malformed distance, and unsupported packaging remain `manual_review`.
- Unknown container truck pricing uses its own confirmed yuan-per-box formula and does not convert to yuan per ton.
- Future production providers may replace normal driving distance with truck distance without changing the cost-rule interface.

## D-026: Unknown Container Truck Uses Yuan-Per-Box Formula

Date: 2026-07-17

Decision:

For prototype-stage unknown container last-mile truck pricing, keep the unit as `元/箱`. Do not convert the result to `元/吨`. Let `X` be confirmed road distance in kilometers:

- if `X <= 20`, unit price is `500 元/箱`;
- if `X > 20`, unit price is `500 + (X - 20) * 30 * 0.55 元/箱`;
- total cost is unit price times the order quantity in boxes.

Reason:

Business confirmation clarified that the earlier minus sign was incorrect and that the cost should remain a box-based freight amount. The `30` factor is part of the confirmed business formula, not a reason for the system to convert the order to tons.

Implications:

- `unknown_truck_container_distance` is enabled when a positive `distance_km` and traceable `distance_source` are available.
- Orders measured in `箱` can use this rule.
- Orders measured in `柜` must not be silently treated as `箱`; they remain `manual_review` unless a separate unit policy is confirmed.
- Known maintained truck rates still take priority.
- Cost rules continue to consume geo-layer distance only and must not call Tencent Maps directly.

## D-027: Leader Full-Flow Demo Uses Real-First Minimal Placeholders

Date: 2026-07-21

Decision:

The first full-flow leader demo accepts a north port A and customer factory B, then returns independent lowest-cost and fastest-time recommendations through the formal `TransportEdge`, `MultiDiGraph`, search, and result chain. Real data and confirmed providers take priority. Demo placeholders are allowed only where the current project lacks confirmed business inputs.

Reason:

The presentation must demonstrate the target end-to-end workflow without presenting incomplete data as production truth. A narrow, visible placeholder layer lets the complete model run while preserving the boundary between verified data and assumptions.

Implications:

- Local registered coordinates, maintained freight rates, Tencent road distance/time, and confirmed cost rules are used before any placeholder.
- Only north-port-to-south-port shipping cost/time and the explicitly displayed no-private-terminal customer profile may be placeholders in this version.
- Existing A/B last-mile maintained rates take selection priority over closer unknown-route candidates.
- AdditionalFee is excluded until segment attribution is confirmed; it is neither assigned arbitrarily nor defaulted to zero.
- Every selected segment exposes source categories such as `real_business_data`, `tencent_map`, `confirmed_cost_rule`, and `demo_placeholder`.
- Tencent API keys remain in local runtime configuration. Real API rehearsal is performed in the user's PyCharm environment and is not a repository secret or Codex-network requirement.

## D-028: Prototype Multi-Candidate Place Search Defaults To Traceable Top1

Date: 2026-07-20

Decision:

When Tencent place search returns multiple candidates in the prototype, the geo provider resolves to the first-ranked result instead of blocking the route chain. It must retain a confidence label and up to five structured candidates for traceability.

Reason:

For bulk-freight route comparison, small coordinate differences among nearby results have negligible cost impact, while blocking every ambiguous result creates disproportionate manual work. The project accepts Tencent ranking as the prototype default but preserves evidence so the policy can be audited against real samples.

Implications:

- Name-aligned candidates use `auto_top1_name_match`.
- Candidates clustered near top1 use `auto_top1_nearby_cluster`.
- Other multiple results use `auto_top1_unclustered`; this is resolved but lower confidence, not proof of exact identity.
- Zero candidates and provider/API failures remain `manual_review` and cannot produce route-search coordinates.
- The domain and routing layers do not implement GUI prompts; future review UI, sampling, cache, and write-back consume the structured geo result.
- Tightening or relaxing this policy requires real-sample evidence and user confirmation.
