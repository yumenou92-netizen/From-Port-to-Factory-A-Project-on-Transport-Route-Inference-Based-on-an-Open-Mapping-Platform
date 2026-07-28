# DECISIONS.md

This document records durable business and technical decisions. Add new decisions when rules change.

Updated: 2026-07-24

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

## D-029: Phase 18 Uses Explicit Transport Contracts Without Silent Defaults

Date: 2026-07-22

Decision:

Phase 18 introduces source-backed node profiles, transport stages, time scopes, cost components, and manual-review outcomes before connecting real bulk-shipping rates. Missing scope or unconfirmed business inputs remain unknown or `manual_review`; they are not converted into usable defaults.

Reason:

Bulk-shipping trunk, barge last-mile, road last-mile, and future rail segments may share physical nodes while representing different business stages. Their time and cost meanings cannot be recovered safely from a generic transport-mode string or a single total. The graph also needs stable edge keys that distinguish these semantics.

Implications:

- `NodeRegistry` continues to identify one physical node; `NodeProfile` separately records infrastructure type, standard location, time region, capabilities, source, and maintenance date.
- `bulk_shipping_trunk` and `barge_last_mile` are different transport stages and must not share pricing assumptions.
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

Decision:

For the current prototype, inland-waterway transport is considered in two business corridors:

1. Fujian inland waterway centered on 马尾港 and the 闽江 channel;
2. Pearl Delta–West River inland waterway centered on Pearl Delta sea-river integrated ports and extending through the maintained Wuzhou, Pingnan, Yulin-region, Guigang, Nanning, and Baise mappings.

The Pearl Delta time region includes Guangzhou, Shenzhen, Dongguan, Foshan, Zhaoqing, Jiangmen, Zhongshan, and Zhuhai. Ports mapped to the Yulin region use the Yulin regional rule. Other corridors must not automatically generate inland-waterway barge edges.

Port-to-port connectivity is graph connectivity: a transport edge may exist only when the two endpoint nodes have compatible transport stage, cargo handling capability, packaging, and commodity capability. Geography alone is not enough to connect two ports by sea or inland waterway.

North-port-to-south-port bulk-shipping freight and complete-segment shipping time continue to use confirmed mapping logic: map a south-port node to a destination freight group and time region by its city/nearby regional label, using the nearest reasonable business mapping when the port itself is not a direct workbook column. This mapping must be traceable and must not silently classify unmatched inland ports, rail stations, factories, or warehouses as sea-going bulk-shipping destinations.

Inland-waterway barge freight and time remain separate sources. Regional complete-segment time may be loaded from a local real table, but formal freight and port capabilities are not yet sufficient for real graph edges. Until those edge prerequisites exist, a demo Provider may generate barge edges only in the supported regions above, and every demo fee/time component must be marked `demo_placeholder`.

For this model version, customer factory and customer terminal are treated as the same delivery endpoint unless a later formal customer-terminal table provides a distinct node.

The previously discussed "within 300 km use truck" idea is not a project rule and must not be implemented as a hard pre-filter. If truck is cheaper or faster, the independent cost/time search should select it from available edges.

Reason:

Leadership clarified that inland-waterway capability is region-specific and cargo-form-specific. A last-mile origin that appears in a maintained truck rate may be a valid inland port or terminal, but that does not prove it can receive north-port sea-going bulk cargo or connect by barge to a customer. The model therefore needs explicit port capabilities, regional mappings, and barge fee/time records before inland-waterway edges can be safely generalized.

Implications:

- Add and maintain explicit data interfaces for port capabilities, regional mappings, inland-waterway barge freight, and inland-waterway complete-segment time.
- Port capability records must express supported stages and supported cargo/packaging capability before they create graph connectivity.
- Regional mapping records must keep the source and destination group/time-region trace used for bulk-shipping or inland-waterway lookup.
- Inland-waterway fee/time records must preserve cost unit, time scope, rule id/version, and source type.
- Demo barge edges remain limited to the existing Fujian/闽江 and Pearl Delta same-region examples and must use `transport_stage=barge_last_mile`, explicit `demo_placeholder` fee/time sources, and non-zero positive cost/time. Extending real graph edges along the Pearl Delta–West River corridor still requires applicable formal freight and confirmed endpoint capabilities.
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
