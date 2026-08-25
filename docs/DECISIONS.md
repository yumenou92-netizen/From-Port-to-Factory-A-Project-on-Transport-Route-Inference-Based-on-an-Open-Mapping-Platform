# DECISIONS.md

This document records durable business and technical decisions. Add new decisions when rules change.

Updated: 2026-07-31

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

Status: Superseded for the current customer baseline and generalized by D-050. The current model treats all customer factories as having no private terminal; a future private terminal must be a separate source-backed node and does not reduce the second business stage to one fixed chain.

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

## D-029: Phase 18 Uses Explicit Transport Contracts Without Silent Defaults

Date: 2026-07-22

Status: Transport-stage naming is superseded by D-050. The cost, time-scope, source-trace, and manual-review requirements remain valid.

Decision:

Phase 18 introduces source-backed node profiles, transport stages, time scopes, cost components, and manual-review outcomes before connecting real bulk-shipping rates. Missing scope or unconfirmed business inputs remain unknown or `manual_review`; they are not converted into usable defaults.

Reason:

Bulk-shipping trunk, barge last-mile, road last-mile, and future rail segments may share physical nodes while representing different business stages. Their time and cost meanings cannot be recovered safely from a generic transport-mode string or a single total. The graph also needs stable edge keys that distinguish these semantics.

Implications:

- `NodeRegistry` continues to identify one physical node; `NodeProfile` separately records infrastructure type, standard location, time region, capabilities, source, and maintenance date.
- North-to-south bulk shipping and south-to-customer barge transport are different edges with different transport modes, roles, and pricing assumptions. Their business-stage values are governed by D-050.
- Time scope is explicit. `pure_sailing`, `road_driving`, and `complete_segment` are distinct; an omitted scope stays `None` rather than becoming `complete_segment`.
- Cost components are positive yuan amounts with source type, rule ID/version, and calculation detail; when supplied, their sum must equal the edge cost.
- `demo_placeholder` is a source type, not a formal-data fallback.
- `ManualReviewOutcome` carries a stable reason code, source reference, explanation, and owning work package; any such result keeps the edge out of the searchable graph.
- `TransportEdge.edge_id` includes stage, time scope, cost-component trace, and manual-review trace so semantically different parallel candidates do not collide.

## D-030: Phase 18 Bulk Shipping B1 Business Baseline

Date: 2026-07-23

Decision:

For Phase 18, `data_REAL/fee_switch/散船运价表.xlsx` is the confirmed source for north-port-to-south-port bulk grain shipping unit freight. Its prices are yuan per ton. The formal bulk shipping segment cost is `quoted_rate_yuan_per_ton * order_weight_tons`.

The workbook represents freight only: it does not include south-port operation fees, and tax handling is out of scope for this project version. The rates apply to all project north ports; for this project, other north ports have the same applicability as 北良港. Destination columns outside Guangdong, Guangxi, Fujian, and Hainan are not part of the current project scope and must not be read into the route engine or modified.

South-port operation fees are a separate cost component. The first implementation uses one aggregate fee type, `码头作业费`, with unit yuan per ton. The provider interface must allow later CSV-backed breakdowns such as unloading fees, storage fees, and short-transfer fees, but unprovided or unattributed operation fees still must not default to zero.

Reason:

These confirmations remove the blocking ambiguity around rate unit, cost formula, north-port scope, freight-vs-operation-fee boundary, and tax handling. They also expand the implementation target from a small pilot set to full real-business coverage for all relevant south ports in the project test range.

Implications:

- W2 can implement a real bulk-shipping XLSX loader using yuan-per-ton rates and order tonnage without additional tax logic.
- W2 must preserve the latest-date, destination-group, and vessel-type source trace, while skipping out-of-scope destination columns.
- W3 must audit and maintain mappings for all relevant south ports in the project scope, not only a 3-to-5-port pilot.
- W5 must model `码头作业费` as a separate `CostComponent` through a provider; it is not part of the bulk shipping freight quote.
- `AdditionalFee` raw records remain excluded until they can be mapped to stage, fee type, unit, applicability, and duplicate rules. B1 confirms the target operation-fee shape, not automatic use of the existing 18 raw records.
- Formal mode must return `manual_review` for missing rate, missing mapping, unknown vessel eligibility, or missing operation-fee attribution. Demo placeholders remain allowed only when explicitly marked `demo_placeholder`.

## D-031: Bulk Shipping Candidate Eligibility and Manual South-Port Mode

Date: 2026-07-23

Decision:

In automatic recommendation mode, a candidate south-port node can receive a north-to-south bulk-shipping trunk edge only when it is eligible for sea-going bulk grain shipping and can be mapped to a confirmed bulk-rate destination group and complete-segment shipping-time region. Inland ports, rail stations, factories, warehouses, or unmatched nodes must not receive synthetic north-to-south sea-shipping edges merely because they appear as origins in maintained last-mile truck rates.

If the user explicitly specifies a south port, the north-port-to-south-port trunk segment is treated as a fixed user-selected segment: calculate its freight and complete-segment shipping time directly, then reduce the graph search problem to south-port-to-customer routing. The fixed trunk segment is added back into the final total and explanation, but it does not compete against other south ports inside the graph.

Reason:

Some maintained south-port-to-customer truck-rate origins are inland ports or non-seaport facilities. They are valid for last-mile or regional transfer, but they cannot receive sea-going cargo from a north port. Separating automatic eligibility from manual south-port selection prevents physically invalid candidates while preserving a leader-facing workflow where a known business south port can be evaluated directly.

Implications:

- Automatic full-flow must exclude candidates that lack confirmed bulk-shipping destination/time mapping and report the exclusion reason.
- Node profiles remain the target long-term source for infrastructure type, capabilities, standard location, rate destination group, and complete-segment shipping-time region.
- Name-based rules in interim code are only a transition mechanism until node profiles are fully maintained; missing or ambiguous mapping must not be silently guessed.
- Manual south-port mode is a separate implementation path and should not be emulated by adding zero-cost or forced edges into the north-to-south candidate graph.

## D-032: Vessel-Time Data Boundary Warning

Date: 2026-07-23

Decision:

This decision's description of bulk-shipping time as `pure_sailing` and its requirement to decompose missing vessel-time components are superseded by D-039. The remaining rule is still valid: an unconfigured transport segment has no usable time and must not be defaulted to zero.

Any route output that includes a vessel segment whose complete-segment time is not configured must warn about that missing time. A configured business “航行时效” is treated according to D-039.

Reason:

Without this warning, users may incorrectly interpret a route containing an unconfigured transport segment as complete. A route whose every segment has a confirmed `complete_segment` or road-driving time can be compared under the current simplified model, but production dispatch accuracy remains dependent on the quality and maintenance of those source rules.

Implications:

- `leader_full_flow` must display a warning when a recommended or attempted vessel segment has no configured complete-segment time.
- Future barge/rail time providers must preserve `time_scope` and source trace separately from road driving.
- Missing vessel or operation time must remain missing/manual-review; it must not be defaulted to zero or hidden inside another segment.

## D-033: Inland Waterway Scope, Port Capability, And Regional Mapping

Date: 2026-07-23

Status: Capability, mapping, fee/time, and no-300-km-filter rules remain valid. Current Fujian endpoint details are superseded by D-047; the fixed second-stage route wording and customer-terminal equivalence are superseded by D-047 and D-050.

Decision:

For the current prototype, inland-waterway transport is considered in two business corridors:

1. Fujian inland waterway centered on 马尾港 and the 闽江 channel;
2. Pearl Delta–West River inland waterway centered on Pearl Delta sea-river integrated ports and extending through the maintained Wuzhou, Pingnan, Yulin-region, Guigang, Nanning, and Baise mappings.

The Pearl Delta time region includes Guangzhou, Shenzhen, Dongguan, Foshan, Zhaoqing, Jiangmen, Zhongshan, and Zhuhai. Ports mapped to the Yulin region use the Yulin regional rule. Other corridors must not automatically generate inland-waterway barge edges.

Port-to-port connectivity is graph connectivity: a transport edge may exist only when the two endpoint nodes have compatible transport stage, cargo handling capability, packaging, and commodity capability. Geography alone is not enough to connect two ports by sea or inland waterway.

North-port-to-south-port bulk-shipping freight and complete-segment shipping time continue to use confirmed mapping logic: map a south-port node to a destination freight group and time region by its city/nearby regional label, using the nearest reasonable business mapping when the port itself is not a direct workbook column. This mapping must be traceable and must not silently classify unmatched inland ports, rail stations, factories, or warehouses as sea-going bulk-shipping destinations.

Inland-waterway barge freight and time remain separate sources. Regional complete-segment time may be loaded from a local real table, but formal freight and port capabilities are not yet sufficient for real graph edges. Until those edge prerequisites exist, a demo Provider may generate barge edges only in the supported regions above, and every demo fee/time component must be marked `demo_placeholder`.

For the current model version, customer factories have no customer-owned terminal. A later formal customer-terminal relation must provide a distinct terminal node before a waterway delivery edge can terminate there.

The previously discussed "within 300 km use truck" idea is not a project rule and must not be implemented as a hard pre-filter. If truck is cheaper or faster, the independent cost/time search should select it from available edges.

Reason:

Leadership clarified that inland-waterway capability is region-specific and cargo-form-specific. A last-mile origin that appears in a maintained truck rate may be a valid inland port or terminal, but that does not prove it can receive north-port sea-going bulk cargo or connect by barge to a customer. The model therefore needs explicit port capabilities, regional mappings, and barge fee/time records before inland-waterway edges can be safely generalized.

Implications:

- Add and maintain explicit data interfaces for port capabilities, regional mappings, inland-waterway barge freight, and inland-waterway complete-segment time.
- Port capability records must express supported stages and supported cargo/packaging capability before they create graph connectivity.
- Regional mapping records must keep the source and destination group/time-region trace used for bulk-shipping or inland-waterway lookup.
- Inland-waterway fee/time records must preserve cost unit, time scope, rule id/version, and source type.
- Demo barge edges remain limited to the existing Fujian/闽江 and Pearl Delta examples and must use `transport_stage=south_to_customer`, an explicit transfer or delivery edge role, disclosed `demo_placeholder` sources where applicable, and non-zero positive cost/time. Extending real graph edges along the Pearl Delta–West River corridor still requires applicable formal freight and confirmed endpoint capabilities.
- Missing inland-waterway capability, unmatched region, cross-region endpoints, unsupported package/commodity, or absent fee/time record means no barge edge is generated; the system must not create a zero-cost or guessed edge.

## D-034: W3/W5 Tables Are Source Interfaces, Not Default Rules

Date: 2026-07-24

Decision:

`秀屿` is confirmed as an in-scope Fujian bulk-shipping destination label. `秀屿港` refers to the port at 福建省莆田市秀屿区东庄镇莆头村, with confirmed coordinate source text `25.216168,118.988634` where the project should store longitude `118.988634` and latitude `25.216168`.

W3 port capability and regional mapping data are loaded only from explicit source tables such as `港口能力表.csv` and `区域映射表.csv`. Missing W3 records mean missing capability or missing mapping; the system must audit the gap and must not infer eligibility merely from a freight-rate origin name.

W5 south-port operation fees are loaded through a separate Provider as one aggregate `码头作业费` component for the first version. The current bulk-grain path uses `元/吨`; containerized operation-fee records may be preserved as `元/箱` for future use. Missing, duplicated, trade-type-mismatched, commodity-mismatched, unit-mismatched, or order-mismatched operation-fee records return `manual_review` without a usable amount; they are not interpreted as zero and are not silently included in graph-search cost.

D-040 refines the treatment of a source-backed zero row: a confirmed customer-owned-terminal exemption is an explicit `not_applicable` rule, not a missing fee and not a normal zero-priced rate.

Reason:

The project needs full real-data coverage without expanding placeholder behavior. Confirming `秀屿` removes one known mapping blocker, while W3/W5 tables create explicit data contracts for future business maintenance. Keeping missing operation fees out of totals prevents under-quoting and preserves the minimum-fabrication principle.

Implications:

- Bulk-shipping classification may map `秀屿港` to destination group `秀屿` and complete-segment shipping-time region `福建`.
- `data_foundation_audit` must show W3/W5 table paths, record counts, unresolved node bindings, and missing-table warnings.
- Operation-fee totals may enter route cost only after a matching positive record exists for the current south port, package type, trade type, commodity scope, and exact order unit (`元/吨` for `吨`, `元/箱` for `箱`). No `吨`/`箱`/`柜` conversion is allowed.
- When a formal operation-fee provider is connected to `leader_full_flow`, a candidate south port with missing or unsafe operation-fee data must be excluded from the searchable graph with a warning, not retained as an implicit zero-fee candidate.
- W3/W5 source tables should be maintained from tested templates under `docs/data_templates/`; the committed templates must use synthetic examples rather than real business rows.
- A `demo_placeholder` operation-fee Provider may be used only when explicitly selected for presentation or experimentation; it is not the default formal-data fallback.
- `AdditionalFee` raw records remain separate until their stage attribution and duplicate rules are confirmed.

## D-035: Port-Label JSON Is A Candidate Source For Operation-Fee Audit

Date: 2026-07-24

Decision:

The leader-provided `部分码头标签.json` may assist W3/W5 data construction, but it is not the formal operation-fee table. In the current prototype, only `serviceFees.入库` is mapped to a candidate aggregate `码头作业费` unit rate. For `散粮`, the unit is `元/吨`; for future containerized records, the reserved unit is `元/箱`.

Every operation-fee rule must preserve `tradeType` as a matching dimension. The project mainly studies domestic trade (`内贸`) now, but the data model and Provider must also support `外贸`. The same port may have different operation-fee rates by commodity, trade type, and packaging mode; route calculation may only use a rate that exactly matches the current order dimensions.

Alias handling must follow a conservative sequence: first check the maintained name dictionary, then use Tencent Maps API candidate search, then require human confirmation. The audit converter may report direct node matches and unmatched names, but it must not automatically register aliases or write coordinates. Formal W5 output is written only after explicit user approval and an explicit apply command; ordinary audit remains read-only.

For the dictionary-first audit pass, a label may bind to an existing node only when removing one maintained port suffix (`港`, `码头`, `港区`, or `作业区`) makes the texts exactly equal and every resolvable dictionary candidate points to one node ID. This binding is audit-local evidence, not a new alias registration. Broader containment matches may only expand Tencent query terms.

Reason:

The JSON file is useful business signal, but it mixes port labels, factory labels, aliases, trade type, commodity scope, and service-fee rules. Treating it as a candidate source preserves momentum while preventing silent fee attribution, duplicate node creation, or under-specified alias acceptance.

Implications:

- `RouteRequest` must carry a `trade_type` dimension; the default can be `内贸`, but unsupported values must be rejected.
- W5 operation-fee matching must include south-port node/name, package type, trade type, commodity scope, fee type, and exact fee unit.
- Zero rows remain manual review unless D-040's customer-owned-terminal non-applicability has been explicitly confirmed. Missing, invalid, duplicated, unmatched, or ambiguous rows do not create usable cost.
- `部分码头标签.json` audit output belongs in ignored local `output/`; reviewed rows may later be copied manually into formal W3/W5 CSV tables.
- Railway dictionary rows are excluded from W5 port-operation-fee query expansion.
- Tencent API is part of alias/candidate investigation only; cost rules and Providers still must not call Tencent directly.

## D-036: Factory-Bound Terminal Labels Represent Customer-Owned Ports

Date: 2026-07-24

Decision:

When a reviewed terminal label is explicitly bound to a customer factory or customer company node, the terminal is classified as that customer's own port (`客户自有码头`). The factory/company name remains the canonical node identity and the terminal label is retained as a source-backed alias; the system must not create a second unrelated public-port node for the same confirmed location.

This identity decision does not prove port operating capability, inland-waterway connectivity, packaging support, commodity support, or an applicable operation-fee amount. Those dimensions still require explicit W3/W5 source records. D-040 now confirms a narrow exception for the reviewed current batch: the two business-confirmed customer-owned-terminal zero rows are explicit operation-fee non-applicability rules.

Reason:

Customer factories may use their own wharf names in business data. Treating the wharf and factory as unrelated nodes would duplicate one physical delivery destination and could incorrectly add a final truck segment. At the same time, node identity alone is insufficient evidence for transport capability or pricing.

Implications:

- `肇庆福加德码头` is an alias of `广东加福加德食品有限公司` and is classified as a customer-owned port.
- Future human-confirmed factory/terminal bindings follow the same rule.
- Customer-owned-port delivery may terminate at the customer node, but the full-flow branch still requires a formal customer profile/capability source before it replaces the current default “无自有码头” presentation profile.
- Partial W5 data must not be activated under the formal file name until its intended coverage and missing-fee behavior are accepted; otherwise the strict Provider would exclude uncovered south-port candidates.

## D-037: W5 Operation-Fee Regional Proxy Uses Explicit Maintained Node Mapping

Date: 2026-07-24

Status: Partially superseded by D-041 for the standalone leader-demo fallback. Exact rates and explicit maintained region assignments still have priority.

Decision:

South-port operation-fee matching follows one strict order:

1. an applicable exact rate for the target port's standard `node_id`;
2. one applicable reference-port rate from the target port's uniquely confirmed `operation_fee_region_code`;
3. `manual_review` without a usable amount.

The machine definition of "nearby" for this rule is not same-city text and is not the geographically nearest coordinate. It is membership in one manually maintained `operation_fee_region_code`. The mapping must explicitly list standard port `node_id` values and preserve its source, mapping basis, rule ID, rule version, confirmation status, and maintenance date. City keywords, port-name containment, and coordinates must not create an operation-fee regional assignment.

A regional result uses the formal cost source type `regional_proxy`. It must preserve the reference port node ID and mapping trace and must state that the rate is not the target port's exact real rate. Missing node ID, missing or unconfirmed mapping, multiple confirmed mappings, missing reference rate, or multiple applicable reference rates returns `manual_review`; none of these cases is zero cost.

Reason:

Business users may temporarily apply a known port's operation fee to nearby ports with similar conditions, but geographic proximity alone does not prove fee equivalence. Explicit maintained membership provides a deterministic and auditable prototype rule while preventing inferred fees from being presented as target-port real data.

Implications:

- `区域映射表.csv` carries explicit operation-fee node assignments and mapping trace; keyword matching remains available for other audited region uses but is not used to create W5 fee assignments.
- `南港码头作业费.csv` may mark a real rate as the reference rate for one `operation_fee_region_code`; the reference row requires its own standard node ID.
- Exact applicable target-port data always wins over regional proxy data.
- `regional_proxy` is a non-placeholder derived source. It is neither `real_data` for the target port nor `demo_placeholder`.
- Formal W5 data remains local business data and must not be committed.

## D-038: Route-Relevant Port And Customer Tags Preserve Unknown State

Date: 2026-07-24

Decision:

Route-planning profiles retain only fields that affect route feasibility or cost selection: stable node/customer IDs, infrastructure type, supported packaging, commodities and transport modes, region/city/time-region labels, customer-to-private-terminal relation, source, maintenance date, and confirmation status.

Port capability values are three-state. `True` and `False` are allowed only for confirmed support and confirmed non-support; an unmaintained capability is `None`/blank and remains an audit gap. The formal port capability table is not activated as a `leader_full_flow` route filter in this phase.

A customer profile or customer-owned-terminal relation must be explicitly confirmed before it can produce an executable route branch. An unconfirmed profile remains `manual_review` even when some individual fields are present.

Reason:

Treating unknown capability as false would silently remove feasible routes, while treating it as true would create physically unsupported edges. Stable, source-backed relations also reduce future file/database adapter changes without turning the current route-planning task into a database project.

Implications:

- W3 loaders and audit output preserve blank capability values instead of coercing them to false.
- Customer-owned-terminal identity remains separate from evidence of port capability, packaging support, waterway connectivity, or fee applicability.
- Database, ORM, API, and administration UI work remain outside Phase 18; future adapters should return the same domain contracts.

## D-039: Business Sailing Duration Equals Complete Shipping-Segment Time

Date: 2026-07-27

Decision:

In the current simplified route-planning model, the business field called “航行时效” is the total time of the corresponding shipping segment. The model does not split that time into waiting, loading, physical sailing, unloading, or other operational components.

This rule applies consistently to north-port-to-south-port bulk shipping and inland-waterway barge transport. Their `TransportEdge.time_scope` is `complete_segment`; `pure_sailing` remains a generic interface value only and is not the active scope for these two modeled shipping stages.

An absent regional time rule remains missing and must return exclusion or manual review. It must not be replaced with zero, a road duration, or a guessed component sum. A time rule by itself does not authorize a graph edge: applicable freight, endpoint capability, packaging/commodity compatibility, and source trace are still required.

Reason:

Leadership time standards are maintained as complete business transport durations. Decomposing them would introduce unsupported assumptions and could double-count future operational items. Treating the supplied value as the whole shipping segment keeps the prototype simple and auditable.

Implications:

- Bulk-shipping and barge time Providers convert maintained days directly to hours and emit `time_scope=complete_segment`.
- Display text may retain the familiar term “航行时效”, but must explain that it represents the complete shipping-segment time in this model.
- The project does not add separate waiting/loading/sailing/unloading time placeholders while a complete-segment rule is present.
- Regional barge time may be loaded independently from barge freight, but no searchable barge edge is created until an applicable positive fare and confirmed endpoint capability are also available.
- Real regional time rows remain local business data; committed templates and tests use synthetic records only.

## D-040: Approved W5 Rates And Customer-Owned-Terminal Exemptions Enter Costing

Date: 2026-07-27

Decision:

The current W5 batch classified as eligible for admission is approved to enter formal route costing. Positive records require a standard node ID and retain package type, commodity scope, trade type, fee unit, source, and maintenance trace. Other positive records without a standard node binding are ignored for this batch.

The two reviewed zero `入库` rows are confirmed to mean that the delivery node is a customer-owned terminal and no separate terminal operation fee applies. They enter the formal W5 table as `applicability=not_applicable`, with unit price 0 and a required source-backed exemption reason. They are not ordinary zero-priced rates and are not missing values defaulted to zero.

Provider results distinguish:

- `resolved`: a positive applicable rate creates a `south_port_operation_fee` cost component;
- `not_applicable`: an approved exemption allows the route with an explicit 0 amount and reason, but creates no artificial zero-valued cost component;
- `manual_review`: missing, conflicting, duplicated, or dimension-mismatched data still blocks the candidate when formal W5 is active.

Reason:

The user explicitly approved the eligible positive rows and clarified the business meaning of the two zero rows. A separate non-applicability state preserves the global rule that missing cost is never silently zero while allowing confirmed customer-owned-terminal behavior to participate in measurement.

Implications:

- The local formal `南港码头作业费.csv` may contain both `chargeable` and `not_applicable` rows.
- A `not_applicable` row must have unit price 0 and a non-empty reason; a `chargeable` row must remain positive.
- If one request matches both a positive rate and an exemption, the Provider returns `manual_review`.
- Explicit W5 application refuses to overwrite an existing formal table.
- Real W5 rows remain local business data and are ignored by Git.

## D-041: Leader Demo May Use Nearest Applicable Operation Fee In The Same Business Region

Date: 2026-07-28

Decision:

For the standalone leader demo, south-port operation-fee matching now follows:

1. an applicable exact rate for the target port;
2. an applicable reference rate from a uniquely confirmed maintained `operation_fee_region_code`;
3. the geographically nearest applicable formal rate whose reference port is in the same traceably resolved business region;
4. `manual_review`.

The third step is an approved temporary data-completion rule while the company data platform is not connected. Business-region resolution must come from the formal regional mapping table when available, with the already confirmed bulk-shipping destination/time mapping as a compatibility fallback. Both target and reference ports must have registered coordinates. The result is `regional_proxy`, retains the reference port, distance, region, mapping basis, rule ID/version, and must state that it is not the target port's exact real rate.

Exact and maintained explicit mappings always win. Missing coordinates, ambiguous region resolution, no same-region applicable rate, duplicate applicable rates, unsupported order dimensions, or unsafe source data remains `manual_review`; none is zero cost.

Reason:

Leadership currently needs a smooth standalone demonstration before all authoritative south-port fees are available from the data platform. Nearest distance within a confirmed business region gives a deterministic and inspectable proxy without weakening exact-data priority or presenting derived values as exact business data.

Implications:

- D-037's coordinate prohibition no longer applies to this narrow third-priority demo fallback; its exact-rate priority, explicit-assignment priority, trace requirements, and missing-is-not-zero rule remain valid.
- The operation-fee Provider remains storage-independent. A future data-platform adapter may replace CSV loading without changing the quote contract.
- A proxy fee may allow a candidate into the demo graph, but it does not prove sea or inland-waterway connectivity and does not grant port capability.

## D-042: Nearest Shipping-Time Proxy Cannot Create Port Connectivity

Date: 2026-07-28

Decision:

When a north-to-south bulk-shipping destination lacks a direct time mapping, the model may borrow the shipping-segment duration of the geographically nearest reference port in the same traceably resolved business region only after the formal port-capability source uniquely confirms that the target port can receive north-port bulk shipping.

This proxy supplies only complete-segment time. It does not supply a bulk-freight destination group, a freight rate, sea/river connectivity, package compatibility, or port capability. If those independent prerequisites are absent, the target still does not form a bulk-shipping trunk edge.

Reason:

Time similarity between nearby ports is a useful approximation, but geographic proximity alone can incorrectly promote an inland terminal, railway station, warehouse, or factory into a sea-shipping endpoint. Capability must therefore precede the proxy.

Implications:

- Exact confirmed time mappings remain first priority.
- Proxy results are marked `regional_proxy` and retain the reference port and distance.
- Current ports lacking both destination-group eligibility and formal sea capability remain manual-confirmation items rather than being silently admitted.

## D-043: Fujian Min River Barge Uses Confirmed Complete-Segment Time And Bulk Rate

Date: 2026-07-28

Status: The fare/time rule remains valid. Any wording that treats barge as a fixed "last-mile stage" is superseded by D-050; it is a transport mode used by an edge within the second business stage.

Decision:

The maintained Fujian Min River barge route uses a complete shipping-segment duration of 15 hours one way, with the same duration in reverse. For bulk grain, all grain commodities use 50 yuan per ton in either direction. The current formal rate applies to `散粮`, `吨`, and the maintained trade-type dimension; it does not authorize container-unit conversion.

The rate and time are independent source records. A searchable barge edge is generated only when both endpoints resolve to the maintained Min River region and both endpoint capability records support the order. While formal capability rows are incomplete, the leader demo may use an explicitly disclosed `demo_placeholder` capability record; the rate and time themselves remain confirmed real business inputs.

Reason:

The business supplied a real rate/time rule but the endpoint capability master is not yet complete. Separating these facts preserves the usable data while keeping the remaining assumption visible.

Implications:

- Barge time uses `time_scope=complete_segment`; no waiting/loading/sailing/unloading components are added.
- Barge freight is a separate `barge_freight` cost component and can coexist with truck and future modes inside the `south_to_customer` subgraph.
- Outside maintained Fujian/Min River or Pearl-Delta/West-River scope, no barge edge is generated.
- Missing rate, time, region, or endpoint capability is never interpreted as zero.

## D-044: Local Map Frontend Reuses The Full-Flow Application Boundary

Date: 2026-07-28

Decision:

The first frontend is a loopback-only local demonstration service. It accepts north port, customer factory, optional south port, region, commodity, package type, quantity, billing unit, and trade type, then calls the same `leader_full_flow` orchestration used by the command-line demo. An entered south port fixes the candidate to that registered port; an empty field keeps automatic candidate selection.

The browser displays independent lowest-cost and fastest-time results, segment cost components, run warnings/errors, candidate nodes, and a Tencent base map. Geometry is rendered by transport segment. A bulk-shipping segment uses a dashed, explicitly schematic China-offshore control-point line; it is not navigable waterway geometry or proof of physical routing. A truck segment uses the decoded `routes[0].polyline` from the same Tencent driving response that supplied its measured distance and duration. A barge segment remains explicitly schematic until an authoritative maintained waterway geometry source exists.

Map geometry is associated with an edge ID in a side table rather than stored as a `TransportEdge` search attribute. Missing or malformed Tencent geometry does not invalidate otherwise usable distance/time, but the frontend must mark that geometry unavailable and must not substitute a node-to-node straight line as if it were a real road. Offshore schematic generation exposes a human control-point hook because a broad regional corridor cannot prove land avoidance for every future port pair.

Map credentials are loaded at runtime from ignored local configuration. They are not embedded in tracked HTML/JavaScript, printed to the console, or returned by general route results. The server binds to loopback by default; non-loopback binding requires an explicit option.

Reason:

The user needs an interactive leadership surface now, while database, production API, authentication, deployment, and authoritative route geometry remain outside the current route-planning milestone.

Implications:

- `src/web/server.py` is a local adapter, not a production backend.
- The user confirmed that the current local Tencent key has both JavaScript API and WebService API permissions. Browser and backend may therefore share `TENCENT_MAP_API_KEY` in the current standalone environment; a separate `TENCENT_MAP_JS_KEY` remains optional for future credential isolation.
- The shared-key path was verified locally on 2026-07-28: the Tencent base map rendered, the route WebService returned a resolved result, and the default truck segment retained 531 decoded road points. The bulk segment rendered as a dashed offshore schematic and the truck segment as a solid Tencent road line.
- Frontend errors must preserve `manual_review` and business warnings rather than smoothing missing values into success.
- Route JSON uses `Cache-Control: no-store`; the service does not write detailed road geometry to logs or local data files.

## D-045: Conservative Name Rules Exclude Railway And Customer Nodes From South-Port Selection

Date: 2026-07-28

Decision:

Until a formal node-role master is connected, south-port selection uses the
following confirmed conservative naming rules:

1. names containing `站`, or names formed as a place name followed by a
   cardinal direction such as 北京西、怀化西、深圳北, are railway stations;
2. names containing `库`, `仓`, or `公司` are customer factory/warehouse
   nodes even when incidental text also contains `港`;
3. a customer-owned terminal must be maintained as a separate port/terminal
   node and linked to the customer, rather than treating the customer-company
   node itself as a south port.

Railway and customer nodes are excluded from automatic south-port fallback and
are rejected by explicit `--south-port` input. When port candidates are below
the display threshold, only currently unclassified freight origins may be used
as a compatibility fallback.

Reason:

The previous name-only port heuristic allowed railway stations, warehouses and
company names containing `港` to enter the audit or fallback candidate set.
That creates physically invalid north-port-to-south-port trunk endpoints.

Implications:

- These rules are conservative compatibility rules, not a replacement for the
  future authoritative node-role and customer-terminal relationship tables.
- A company that operates a terminal still needs a distinct terminal node if
  that terminal is to participate in routing.
- No coordinate, freight rate, or operation-fee record can override a confirmed
  railway/customer role and silently promote that node into a south port.

## D-046: Confirmed Waterway Roles Govern North-South Bulk-Trunk Eligibility

Date: 2026-07-29

Decision:

The first manually confirmed node and waterway roles are:

1. 东莞深粮 and 平和县储备粮 are customer-factory nodes only;
2. 军航码头 is a Fujian Min River sea/inland dual-use port and maps explicitly
   to the `马尾` bulk-freight destination group and `福建` complete-segment time
   region;
3. 洋浦港 is a sea port and maps explicitly to the `马村/海口` bulk-freight
   destination group and `海南` complete-segment time region;
4. 清远清新码头, 苏湾港, 贵港白沙码头, and 韶关北江国际港（白土码头）
   are inland-waterway ports. They cannot be north-port-to-south-port bulk
   shipping trunk destinations, but may participate in a later inland-waterway
   route inside the `south_to_customer` stage when that route has applicable capability, freight, and
   complete-segment time data.

These mappings are explicit business confirmations. They must not be recreated
from name similarity, coordinates, or an operation-fee record. Until the formal
port-capability master is connected, the confirmed roles remain code-level
compatibility records and must be visible in audit output.

Reason:

The six previously blocked names represented two different problems: two
sea-accessible ports lacked explicit bulk-freight/time-region mappings, while
four inland ports were being evaluated in the wrong transport stage. Treating
all six as generic missing data would either hide usable sea ports or construct
physically invalid north-south bulk-shipping edges.

Implications:

- Explicit `--south-port` input rejects a confirmed inland port for the
  north-south bulk trunk and explains that the node is reserved for downstream
  routing inside the second business stage.
- A confirmed sea or dual-use role does not create a rate, handling capability,
  or packaging conversion. The order must still match maintained freight,
  complete-segment time, operation-fee, commodity, package, unit, and trade-type
  rules.
- A customer factory remains separate from any customer-owned terminal. A
  terminal must have its own maintained port node before it may enter routing.
- Missing capability, freight, time, or fee data is never interpreted as zero.

## D-047: The 0729 Port Workbook Is The Latest Local Node-Master Overlay

Date: 2026-07-29

Decision:

`data_REAL/fee_switch/码头信息维护0729版.xlsx` is the latest local source for
port names, aliases, administrative location, address, longitude, and latitude.
It is loaded as a node-master overlay before the older coordinate JSON:

1. an exact full name or alias that resolves to one existing physical node keeps
   the existing canonical name and stable node ID, while the workbook coordinate
   becomes the current coordinate;
2. an unresolved workbook row creates a new standard node using its full name;
3. names that resolve to more than one existing node, duplicate workbook rows,
   invalid headers, missing coordinates, or out-of-range coordinates stop the
   load for manual review;
4. older coordinate JSON records remain available as source evidence. Coordinate
   differences are retained in the registry conflict audit and are not silently
   treated as identical.

The workbook supplies node identity and location only. It does not by itself
prove sea/inland role, bulk or container handling capability, freight
applicability, operation-fee applicability, or route connectivity.

For the currently confirmed Fujian ports:

- 军航码头 is a Min River sea/inland dual-use port supporting bulk corn and
  wheat, and may receive the north-south bulk trunk;
- 福州马尾港 is sea/inland integrated but currently supports only containerized
  corn and wheat, so it is excluded from the current bulk-grain trunk and the
  50-yuan-per-ton bulk barge rule;
- 福州松下码头 remains a sea port, but its bulk-grain handling capability is not
  confirmed and it is not part of the confirmed Min River barge corridor;
- 南平港 is the upstream Min River endpoint. Its node and coordinates are now
  registered. It supports bulk and container cargo for corn and wheat, supports
  barge and railway transport, and cannot receive the north-south sea-going bulk
  trunk;
- the only maintained Min River barge route is 南平港↔军航码头. The confirmed
  bulk-grain rule is 50 yuan/ton and 15 hours for the complete segment in either
  direction. 福州马尾港 is no longer an endpoint in the currently maintained
  Min River routing scope.

Current customer factories are treated as having no customer-owned terminal.
A later authoritative customer-terminal relationship must explicitly introduce
such a terminal; company identity or coordinates cannot imply one.

Reason:

The new workbook materially improves node coverage and coordinates, but mixing
node identity with transport capability would recreate invalid edges. A
stable-ID overlay keeps existing freight bindings intact while allowing the
latest local master data to improve location quality and expose source
conflicts.

## D-048: A South-Port Trunk Endpoint Requires An Explicit Sea-Access Marker

Date: 2026-07-29

Status: Superseded in part by D-052. Confirmed inland and explicit
bulk-capability exclusions remain authoritative, but an otherwise unclassified
port may now use applicable bulk-grain freight-origin evidence as the approved
south-port identity signal.

Decision:

A node may be the destination of the north-port-to-south-port bulk-shipping
trunk only when its maintained waterway role is explicitly `sea_port` or
`sea_inland_dual_use`. The following are not sufficient evidence:

- a name containing `港` or `码头`;
- a coordinate near the coast;
- a freight or operation-fee record;
- a bulk rate/time region mapping;
- successful Tencent place resolution.

An `inland_port` is always excluded from the north-south trunk. An
`unknown_port` without a sea-access marker is also excluded from both automatic
selection and explicit `--south-port` selection until manually confirmed.
There is no fallback that promotes an unclassified freight origin merely
because the automatic candidate count is small.

The current code-level confirmed sea-access set is a compatibility layer until
the formal port-capability/role table is populated. A confirmed marker may be
resolved from any unambiguous name or alias attached to the same standard node;
conflicting alias roles remain unknown. Audit output must list unmarked ports
for manual classification rather than guessing them.

Reason:

North-south bulk shipping is a sea-going stage. Allowing inland or unclassified
terminals into that stage can create physically impossible edges even when
their names, coordinates, fees, or last-mile rates appear usable.

## D-049: Current Barge Routing Uses A Confirmed Inland Transfer Port

Date: 2026-07-29

Status: This is a current Min River implementation instance, not the general route architecture. D-050 governs the two business stages and data-driven second-stage subgraph.

Decision:

Because current customer factories are not customer-owned terminals,
`leader_full_flow` does not generate a barge edge directly from a south port to
a customer-company node. For the maintained Min River scope, the searchable
alternatives are:

1. north port → 军航码头 by bulk shipping → customer by truck;
2. north port → 军航码头 by bulk shipping → 南平港 by barge → customer by
   truck.

The direct-truck and barge-transfer alternatives coexist in the same
`MultiDiGraph`; cost and time Dijkstra searches remain independent. The barge
edge is added only together with a resolved inland-port-to-customer road edge,
so the graph does not retain an orphan transfer branch that cannot reach the
customer.

The south-port operation fee remains attached to the north-to-south bulk trunk.
No additional Nanping operation fee is invented. If such a fee becomes
applicable, it must enter through a separately confirmed cost component.

Intermediate ports and their coordinates are returned to the Web adapter so the
barge segment can be shown as an explicit schematic and the following truck
segment can use the Tencent road polyline from the same calculation response.

Reason:

Treating a customer factory as a barge terminal contradicts the current
customer-node boundary. A confirmed inland transfer node preserves the physical
transport stages while allowing direct truck and barge-plus-truck alternatives
to be compared by the existing route-search model.

## D-050: Two Business Stages Are Independent From Transport Modes And Graph-Edge Count

Date: 2026-07-29

Decision:

The full transport problem contains exactly two business stages:

1. `north_to_south`: north port to south port;
2. `south_to_customer`: south port to the customer delivery node.

A business stage is a route boundary, not a graph-edge template. Either stage may contain one or more directed `TransportEdge` objects and may combine one or more transport modes. Bulk shipping is only the first implemented mode for the first stage. The second stage is a general subpath-search problem and may contain direct truck, barge transfer, rail, additional transfer ports, future customer-terminal delivery, or other confirmed multimodal combinations.

Transport semantics are represented by three independent dimensions:

- `TransportStage`: `north_to_south` or `south_to_customer`;
- `transport_mode`: business mode such as 散船、集装箱船、驳船、汽运、铁路;
- `TransportEdgeRole`: `trunk`, `transfer`, or `delivery`.

The Military Port–Nanping Port–customer route is one current data-supported example. Military Port represents a sea/inland dual-use south-port type; Nanping Port is an inland transfer node in the second stage. Neither node is a mandatory architectural component. Demo route shape, segment count, display ordering, or hard-coded example data must not define the long-term graph.

Full-flow orchestration must obtain possible transfer endpoints from capability-backed Provider data and resolve them through the standard node registry. It must not own a fixed list such as `("南平港",)`. Providers still decide whether each requested edge is applicable by checking region, capability, packaging, commodity, fare, time, and source trace.

Reason:

Earlier contracts encoded mode-shaped names such as `bulk_shipping_trunk`, `barge_last_mile`, and `road_last_mile` as transport stages, and the first Min River full-flow instance directly enumerated Nanping Port. That conflated business boundaries, transport modes, edge roles, and one Demo path. It would prevent the second business stage from growing into a general multimodal subgraph.

Implications:

- `TransportStage` values are limited to the two business stages.
- `TransportEdgeRole` is stored separately and is included in edge identity and route explanation.
- Current bulk-shipping trunk edges use `north_to_south/trunk`.
- Current barge-to-transfer-port edges use `south_to_customer/transfer`.
- Current road-to-customer edges use `south_to_customer/delivery`.
- A future first or second stage may contain multiple graph edges without creating a new business stage.
- `MultiDiGraph`, independent cost/time search, missing-is-not-zero, unit isolation, and source trace rules remain unchanged.
- The leader Demo and local Web page are adapters over the domain model; they may visualize a supported instance but must not infer stage from segment position or prescribe one fixed path topology.

## D-051: Leadership IO Requirements Are Product Contracts, Not Algorithm Specifications

Date: 2026-07-29

Decision:

The input/output behavior already established by `leader_full_flow.py` and the local Web page represents leadership's product-facing requirements and must be preserved when the implementation is reorganized.

The current input contract includes:

- north port;
- customer factory;
- optional south port;
- region;
- commodity;
- package type;
- quantity and billing unit;
- trade type.

The current output contract includes:

- independent lowest-cost and fastest-time recommendations;
- route nodes and transport segments;
- total and component costs;
- segment time, rule, and source explanations;
- candidate and graph information;
- explicit warnings and errors;
- map-ready nodes and segment geometry or an explicit unavailable/schematic status.

Leadership requirements determine what the system accepts, what it communicates, and which business meanings require confirmation. Unless explicitly confirmed as a business rule, they do not determine the internal candidate-generation algorithm, Provider composition, graph topology, route-search implementation, module boundaries, number of graph edges, or fixed route shape.

The required dependency direction is:

```text
data/domain/geo/routing capabilities
-> UI-independent route-planning application request/response service
-> leader CLI Demo and local Web adapters
```

The Demo is an observation and acceptance surface over developed capabilities. It may choose representative inputs and presentation wording, but it must not own a separate pricing formula, fixed transfer-node list, candidate rule, graph builder, or search algorithm. The Web page must consume the same application result rather than reimplement route logic.

`demo_placeholder` behavior must be explicitly injected through a Demo-specific Provider or request context, remain traceable, and never become the formal service's silent default.

Reason:

The current full-flow CLI and Web page correctly capture leadership's IO expectations, but `leader_full_flow.py` also contains application orchestration and presentation formatting. Without an explicit boundary, future work could either lose required IO behavior during refactoring or distort the domain model to make one presentation run smoothly. Treating IO as a stable application contract while preserving engineering independence for inference logic prevents both failures.

Implications:

- New model capabilities are implemented and tested in data/domain/geo/routing or an application-service layer before being exposed in a Demo.
- CLI and Web adapters may format the same structured result differently but may not calculate different routes.
- A display order, example node, current candidate limit, or current map style is not an algorithm requirement unless separately confirmed.
- Refactoring `leader_full_flow.py` into a UI-independent application service is a future architectural cleanup direction, not authorization for an immediate large rewrite.
- Any change to leadership-visible inputs or outputs requires explicit product review; internal algorithm changes remain governed by business correctness, traceability, tests, and existing project decisions.

## D-052: Bulk-Grain Freight-Origin Evidence May Admit An Unclassified South Port

Date: 2026-07-30

Decision:

For the current `运价表.json`, a registered origin whose canonical name or
confirmed alias is a port/wharf may be treated as a north-to-south bulk-shipping
south port when the same standard node has an applicable `散粮` freight-origin
record for the current commodity. The qualifying record may describe truck or
barge transport after the south port; its role here is evidence that the port
can originate onward bulk-grain transport, not proof of one fixed second-stage
route shape.

The evidence rule has the following precedence and limits:

1. a confirmed `inland_port` remains excluded from the north-to-south
   sea-going trunk even when it has bulk-grain rates;
2. an explicit bulk-capability exclusion remains excluded;
3. names classified as railway stations or customer facilities remain
   excluded;
4. a port/wharf with only container freight-origin records is not a bulk
   south port;
5. a container-only origin may be reported as
   `potential_transfer_port_pending_confirmation`, but this does not create a
   graph edge or assign a transfer-port role;
6. a registered port with neither bulk nor container origin evidence remains
   manual-only and is not labelled a potential transfer port automatically;
7. bulk freight-origin evidence admits the port identity only. Applicable
   trunk rate/time, operation fee, coordinates, package/commodity support and
   second-stage edge inputs must still pass their own Providers before a
   searchable route is created.

`中转港` is represented in the W3 capability contract by the tri-state
`is_transfer_port` field. It is distinct from:

- waterway role (`sea_port`, `sea_inland_dual_use`, `inland_port`);
- business stage (`north_to_south`, `south_to_customer`);
- graph-edge role (`trunk`, `transfer`, `delivery`).

No port is automatically assigned the transfer-port role solely because it has
container rates. A `south_to_customer/transfer` barge edge requires its
destination capability row to set `is_transfer_port=true`; blank remains
unknown and blocks that transfer endpoint.

Reason:

The maintained freight table is now confirmed as business evidence about which
port origins can handle onward bulk-grain transport. Ignoring barge-origin
records would incorrectly exclude known ports such as Guangzhou New Port,
Dongguan Machong Port and Shenzhen Shekou Port. At the same time, confirmed
inland ports and container-only origins must remain separated to avoid creating
physically invalid sea-going trunk edges.

Implications:

- D-034 and D-048 remain valid for unqualified names, coordinates, fees and
  mappings, but their blanket rejection of freight-origin evidence is replaced
  by this narrowly scoped, package-aware rule.
- Full-flow automatic and explicit south-port selection use the same evidence
  predicate.
- The read-only order/port audit examines all freight-origin transport modes
  for bulk identity evidence while continuing to report maintained truck rates
  separately from confirmed-rule truck fallback.
- Missing values remain unknown and are never converted to zero.

## D-053: Bulk-Shipping Map Geometry Follows A Mainland-Coastal Schematic

Date: 2026-07-30

Decision:

The Web map's north-to-south bulk-shipping line remains an explicitly
schematic presentation geometry. Its default control-point corridor should
stay near mainland China's coast rather than using a visually distant
deep-sea arc.

For a Guangxi seaport destination, the schematic must pass through the
Qiongzhou Strait between the Leizhou Peninsula and Hainan Island before
entering the Beibu Gulf. It must not route around the south of Hainan.

This geometry:

- remains labelled `bulk_shipping_schematic` and `is_schematic=true`;
- is not a navigational route or authoritative waterway;
- does not provide distance or time;
- does not enter candidate selection, graph construction, cost calculation,
  time calculation, or Dijkstra;
- retains the explicit manual-control-point hook for individual port-pair
  visual corrections.

Reason:

The earlier generic offshore corridor was too far from the mainland and its
Guangxi branch visually detoured south of Hainan. Both reduced leadership
confidence in the presentation even though the line was correctly labelled
as schematic.

Implications:

- The geometry source version is `china_coastal_waters_schematic/1.1`.
- New destination regions require visual review before their control points
  are treated as a stable presentation default.
- A future authoritative shipping-lane dataset should replace this schematic
  through the geometry Provider boundary without changing route-search
  semantics.

## D-054: Exact OD Barge Rates Precede Regional Freight Proxies

Date: 2026-07-31

Decision:

For inland-waterway routes in the second business stage, an applicable latest
exact OD barge quotation from the typed formal freight source is the primary
freight source. The
regional `内河驳船运输费率.csv` interface remains a fallback only when no exact
OD quotation exists for the two standard endpoint node IDs.

The exact OD path must satisfy all of the following:

1. both rate endpoints resolve to standard node IDs;
2. the rate applies to the request's package, commodity and price unit;
3. the request uses the confirmed domestic-trade scope;
4. both endpoints have source-backed barge capability for that same business
   scope;
5. a transfer edge ends at an inland-waterway-capable transfer port, while an
   exact delivery edge may end at a customer barge receiver without changing
   that customer's node identity;
6. the separate inland-waterway time Provider returns one confirmed complete
   transport-segment time;
7. the latest exact OD price is unique.

If the same OD has different prices on the same latest maintenance date, the
result is `manual_review`. A regional rate must not hide that conflict. If an
exact OD exists but does not support the request package or commodity, the
system also does not fall back to a broader regional rate.

An exact barge quotation is evidence that its endpoints can handle the
quotation's recorded package and commodity scope. It does not by itself:

- classify a customer as a port;
- classify an inland port as a north-to-south south port;
- classify a sea-only port as an inland transfer port;
- establish connectivity for another package or commodity.

For endpoints without a direct maintained inland-time-region mapping, the
current independent-development adapter may assign the geographically nearest
already mapped region. The assignment must retain the anchor node, distance,
source, and `nearest_region_proxy` method. It is not an exact region fact.

Reason:

The maintained freight source contains route-specific business quotations that
have been used in real operations. Ignoring those records in favor of one regional rate loses
information and previously prevented otherwise complete barge alternatives
from entering the graph. Strict exact-rate precedence preserves the strongest
available evidence while retaining conservative conflict handling.

Implications:

- Barge freight remains independent from road distance and is calculated as
  unit rate times the request quantity.
- Complete-segment time remains a separate Provider input; freight existence
  never supplies or defaults time.
- Online full-flow may bound candidate expansion for performance, but offline
  audits must verify the complete exact-OD set.
- Candidate-width limits do not become port-connectivity rules.
- The current exact-rate Provider consumes typed records rather than opening
  the JSON itself, preserving a future database-adapter boundary.

## D-055: Maintained Freight Workbook Precedes JSON Compatibility Data

Date: 2026-07-31

Decision:

`运费数据.xlsx` 的 `运价表` 工作表是当前独立开发阶段的优先正式运价数据源。
仅当该工作簿不存在时，才允许回退读取 `运价表.json` 兼容数据；工作簿存在但
工作表、表头、日期或记录格式无效时必须失败并提示修复，不得静默回退到旧
JSON。

工作簿接入必须：

1. 严格校验九列表头；
2. 保留源文件名和 Excel 物理行号；
3. 将包装方式、适用品种和费用单位纳入适用性判断；
4. 将同一 OD、同一日期下适用品种不同的报价保留为业务范围不同的平行记录，
   不误判为价格冲突；
5. 继续通过类型化运价记录向 Provider 提供数据，不让路径规划代码直接读取
   Excel，以保留未来数据库适配边界。

基于 2026-07-31 的业务确认，`东莞粤储粮` 和 `南宁港牛湾作业区` 可在存在
精确 OD 驳船运价证据时，获得与该记录包装方式、粮食品种范围一致的最小能力
补充。该补充必须保留运价源文件和行号，且不得推广为其他节点、其他包装方式
或其他粮食品种的能力事实。未来正式港口能力表或数据平台记录接入后，应替代
此受限适配。

Reason:

新版工作簿通过适用品种拆分解决了旧数据中同日同 OD 不同报价的歧义，并且比
旧 JSON 更接近当前维护口径。优先使用工作簿可以避免正式数据已更新而系统仍
消费旧兼容快照；失败关闭和逐行追溯则避免错误数据在领导演示中被静默掩盖。

Implications:

- `运价表.json` 保留为工作簿缺失时的兼容回退，不再与工作簿并列竞争。
- 数据源选择属于加载层职责，Provider 和图搜索只消费统一的类型化记录。
- 精确运价可以证明对应记录范围内的驳船作业能力，但不能自动证明海港、
  南港、中转港或其他运输方式身份。
- 数据源或能力证据不完整时仍返回不可准入或人工复核，不把缺失值解释为 0。

## D-056: Maintained Node Tags Precede Name Heuristics

Date: 2026-07-31

Decision:

南港身份判断以正式节点维护表的结构化标签为主，节点名称规则仅作为标签缺失
时的补充。当前本地数据源优先级为：

1. `节点信息维护0731.xlsx`；
2. 当新版节点主表缺少对应标签时，使用 `码头信息维护0729版.xlsx`；
3. 两份维护表均无可用身份标签时，才使用“港/码头、站、库、仓、公司”等
   名称启发式。

南港身份要求维护记录的 `节点性质` 明确包含“港口码头”。`码头属性` 用于
判断海港、内河港或河海一体港，不能单独把“租赁库”、客户或其他非港口节点
提升为南港。`包装方式` 用于判断当前订单是否得到散粮或集装箱能力支持。

标签优先只解决节点身份误判，不取消其他准入条件：

- 纯内河港仍不能作为北港至南港散船干线终点；
- 明确不支持散粮的港口仍不得进入散粮订单；
- 水域角色未分类时仍需要适用订单的真实散粮始发运价作为业务证据；
- 同日运价冲突、缺少散船目的区域、航时或作业费等问题仍可在后续阶段阻断
  构边。

Reason:

早期名称规则是在节点标签缺失条件下的保守权衡，但会误排除“东莞新沙”这类
名称不含“港/码头”的正式码头，也会误排除“广西铁山东岸码头有限公司”这类
名称含“公司”的正式码头。维护表已经提供结构化节点性质后，继续让名称覆盖
正式标签会降低数据质量；同时，仅凭码头属性提升租赁库又会产生相反的误纳入
风险。

Implications:

- CLI、Web 和离线审计应共享同一标签优先身份口径。
- 候选决策必须保留维护表来源或 `name_rule_fallback` 证据。
- 未来数据库接入时，可用同一 `node_id` 下的节点身份、码头属性和包装能力表
  替换本地 Excel 适配器，不改变南港选择接口的业务顺序。

## D-057: Maintained Waterway Control Points Are Display Geometry Only

Date: 2026-07-31

Decision:

Web 水运示意优先读取本地 `航线控制点_全点版.json`。控制点坐标系必须为
`GCJ-02`，以便与腾讯地图底图及节点坐标一致。当前散船使用南北沿海、福建—
珠三角和珠三角—粤西—海南—广西走廊组成的控制点网络；驳船在福建闽江或
珠三角—西江控制点网络中选择与当前 OD 端点共同最接近的连通走廊。

对每一条散船或驳船展示段：

1. 实际起点连接到适用连通网络中距离最近的控制点；
2. 实际终点连接到同一网络中距离最近的控制点；
3. 两个控制点之间沿维护走廊的最短控制点子路径绘制；
4. 输出保留控制点文件版本、命中走廊 ID 和两端接入距离；
5. 控制点文件缺失时保留旧的显式示意回退；文件存在但 JSON、坐标系或
   路线结构无效时显式失败，不静默消费错误数据。

Reason:

此前散船使用代码内少量人工点，驳船仅用端点直线，无法稳定反映沿海、闽江
和西江的基本走向。维护型控制点数据可以改善领导展示的线路形态，同时保持
路线计算与地图绘制解耦。

Implications:

- 控制点几何只属于 Web 展示适配层，不写入 `TransportEdge` 或正式搜索图；
- 控制点长度不能作为业务距离，不能用于费用、时效、候选排序或连通性证明；
- 命中某条控制点走廊不证明两个港口具有业务运输能力；
- 腾讯汽运仍使用同次测算返回的真实道路折线，不改用控制点；
- 未来取得权威航道或数据平台接口后，可替换控制点 Provider，而不改变路线
  规划应用契约。

## D-058: Container-Vessel Trunk Starts as a Box-Only Data Contract

Date: 2026-08-06

Decision:

集装箱运输首轮只交付北港—南港集装箱船的类型化数据接口和只读准入审计，不
改变现有散粮主链。订单范围固定为 `集装箱/箱`；`柜` 不得自动换算为 `箱`。
集装箱船边只有在一条已确认记录同时提供精确 OD、包装/品种/贸易类型、报价
及单位、价格类型和完整航运段时效时才能进入 `north_to_south/trunk`。

南港候选必须同时满足：维护标签为物流节点和港口码头、码头属性为海港或海河
一体、支持集装箱，且存在适用的已确认集装箱船记录。纯内河港可在以后作为
第二业务运输段的中转节点，但不得作为集装箱船北港—南港终点。客户、仓库或
非港口节点不得因具备内河属性或集装箱能力而被提升为南港。

Reason:

当前真实数据尚无北港—南港集装箱船运价和时效源。散粮散船、散粮驳船、铁路
和汽运的单位、连通性与报价机制均不能替代集装箱船数据；提前构边会把数据缺
口伪装成可执行路线。

Implications:

- 新接口文件名为 `集装箱船运价时效.csv`，允许 `元/箱` 单价或 `元` 总价，
  但必须显式声明 `price_type`；
- 无源、缺时效、同日冲突或单位不精确匹配时返回 `manual_review`，不补零；
- 当前 CLI/Web full-flow 不自动消费该 Provider，待真实数据接入和独立验收后
  再连接到应用层；
- 南港—客户工厂的集装箱第二业务段沿用多方案图建模原则，但不复用散粮驳船
  或铁路记录，需独立数据准入。

## D-059: Transaction Freight Quotes Precede Inquiry Quotes On The Same Latest Date

Date: 2026-08-12

Decision:

For one business-route key on its latest effective maintenance date, when
business-maintained source labels contain both an inquiry quote (`询价`) and a
transaction quote (`成交`), the transaction quote is preferred for automatic
candidate generation. This applies only when the remaining transaction quote
set resolves to one unique rate id.

Reason:

The business has confirmed that a completed transaction is stronger evidence
than an inquiry when the two sources conflict. It removes a known avoidable
manual-review class without treating every source-label difference as safe.

Implications:

- Two or more different transaction quotes on the same latest date still
  require `manual_review`.
- Conflicts between sources that are not an explicit inquiry-versus-transaction
  pair still require `manual_review`.
- Raw inquiry records and their original maintenance dates remain loaded and
  auditable; the source-priority rule does not delete or rewrite history.

## D-060: Railway-Container Prototype Uses Explicit Placeholder Records Only

Date: 2026-08-20

Decision:

铁路—集装箱首轮保留两个业务运输段。北站至南站为
`north_to_south/铁路/trunk`；南站至客户工厂仍属于
`south_to_customer`，但客户专用线和第三方专用线方案在费用、时效未确认前不构边。

首轮测试记录允许使用 `demo_placeholder`，且必须在边、费用分项和来源中保留该
标记。它们仅用于验证费用组成、时效字段、`TransportEdge` 和并行边契约，不能被
CLI、Web 或真实数据链默认加载。铁路运费、上/下站费、专用线费用与时效取得正式
数据后，才允许使用 `real_data` 进入正式图。

已确认的铁路干线区域时效为东北至福建 168 小时、东北至广东 192 小时、东北至
广西 192 小时；均表示完整铁路运输段总时效。区域无法唯一映射时不得猜测或构边。

铁路末端直达汽运允许使用独立于既有通用集装箱汽运的规则：0—10km 为 450 元/箱，
10—20km 为 500 元/箱，超过 20km 为
`500 + 30 × 0.6 × (X - 20)` 元/箱。该规则尚未接入正式 Provider，且不得覆盖既有
通用集装箱汽运的 `0.55` 系数。

Implications:

- 铁路箱型必须单列为 `顶开门箱` 或 `敞顶箱`，不得与包装方式 `集装箱` 混用；
- 敞顶箱篷布费为 25 元/箱，顶开门箱不计该项；
- 上站费、下站费当前尚未确认统一或站点维护口径，未知不得按 195 元/箱默认计入；
- `箱` 与 `柜` 继续严格区分，铁路首轮只支持 `集装箱/箱`；
- 铁路站是合法铁路端点，不是海港南港，不适用海港准入、散船、港口作业费或水运规则。
- The rule is implemented in `latest_rate_selector`; all consumers, including
  last-mile truck, exact-OD barge, and future container providers, receive the
  same deterministic selection result.
