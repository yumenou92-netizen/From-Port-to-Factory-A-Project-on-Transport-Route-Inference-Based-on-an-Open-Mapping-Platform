# CHANGELOG.md

This changelog records actual engineering changes. It is not a leader-facing daily report.

## 2026-09-02

### Changed

- Added a read-only adapter for the first local railway-container test workbook.
  It consumes the confirmed `测试路线/敞顶箱-8.28查询` source as railway-only
  freight in yuan per two-container group, converts it to yuan per box, and
  emits typed `real_data` records only for uniquely registered standard
  north-station/south-station OD pairs.
- Added the confirmed first-batch railway cost components: station handling is
  195 yuan per box for stations in Shaoguan and 136.5 yuan per box elsewhere;
  open-top tarpaulin is 250 yuan per box. Storage and detention are excluded
  from the current order model rather than defaulted to zero.
- Kept `站转专用线` compound endpoints out of normal south-station trunk
  records and retained missing north stations as review-only outcomes.

### Verification

- The local source was read without mutation: 101 confirmed-price rows yielded
  66 typed normal-station records, 34 dedicated-siding outcomes, and one
  unregistered-north-station outcome.

## 2026-08-31

### Changed

- Added a UI-neutral railway-container planning service and a sanitized
  platform-style CLI fixture.  The service filters exact order-applicable
  north-station/south-station records, requires a complete terminal delivery
  record, builds registered `MultiDiGraph` edges, and independently searches
  cost and time.  It is intentionally isolated from real railway data,
  full-flow, and the Web route API.
- Updated the isolated railway-container interactive demo so its direct
  terminal-truck option reuses local-first coordinates, Tencent place/ordinary
  driving providers, and the confirmed rail-terminal truck rule.  Railway
  trunk inputs, station fees, and dedicated-siding inputs remain explicit
  `demo_placeholder` test data; unavailable coordinate or road data returns
  `manual_review` without fabricating a delivery edge.
- Prevented an incomplete railway demo from printing a trunk-only subtotal as
  a full-chain total; it now prints the terminal `manual_review` reason and
  labels the available trunk values as a subtotal.
- Added a narrow railway-demo station shorthand fallback: an unresolved south
  station name without `站` retries the same name with that suffix before any
  external-result failure is surfaced; this does not alter generic port or
  customer name resolution.
- Added a separate Web railway quotation calculator at
  `/rail_calculator.html`, linked from the route-planning page. It mirrors the
  supplied calculator workbook's auditable cost columns and accepts its core
  quotation inputs plus explicitly manual-maintained line items.
- Added a Decimal-backed `/api/rail-freight-calculator` endpoint and an
  isolated domain calculator. Neither reads nor writes the formal railway OD
  rate source, creates a `TransportEdge`, or changes candidates, graph edges,
  costs, times, or Dijkstra results.
- Corrected local freight 2 per business confirmation to
  `adjusted_base × (1 - discount_ratio)`. The original fixed 60-tonne display
  remains visible only as a comparison against the current input load tonnes.

### Verification

- Calculator/domain and Web-adapter focused tests passed; a local Web pass
  loaded the calculator, completed the workbook default calculation, displayed
  the corrected local-freight rule, and reported no browser console errors.

## 2026-08-12

### Changed

- Added the confirmed same-latest-date source priority to the shared freight
  selector: a unique `成交` rate now precedes conflicting `询价` rates, while
  multiple different transaction rates and all other source conflicts remain
  `manual_review`.
- Kept the rule source-text scoped and auditable; it does not alter raw
  workbook rows or silently select a lowest price.
- Added optional local `FREIGHT_WORKBOOK_PATH` configuration.  When set, the
  loader consumes only that explicitly named `.xlsx` freight workbook; when
  absent, the prior `DATA_DIR/运费数据.xlsx` discovery behaviour is unchanged.
- Restored the confirmed display-only `万元/吨` conversion for route unit cost;
  it remains outside edge costs, candidate selection, and both Dijkstra goals.

### Verification

- Added selector regressions for inquiry-versus-transaction selection and for
  the remaining multiple-transaction conflict boundary.
- Added a loader regression for the explicit local freight-workbook override.

## 2026-08-06

### Changed

- The leadership CLI now shows each resolved ton-based route's derived `折合运价` in `万元/吨` (`total cost in yuan / order tons / 10,000`). This is presentation-only, keeps four decimal places to avoid rounding a usable value to zero, and does not affect candidate selection, edge costs, or either Dijkstra search.
- Added a strict `集装箱船运价时效.csv` contract for future north-to-south container-vessel rates and complete-segment times. It accepts only `集装箱/箱`, preserves exact OD, commodity, trade type, price type and source trace, and rejects any implicit `柜` conversion.
- Added a standalone container-vessel Provider boundary. It can create a formal `north_to_south/trunk` `TransportEdge` once confirmed source records exist, but has no fallback to bulk shipping, bulk barge, rail or truck rules.
- Added a read-only container-trunk admission audit and CLI. It uses maintained node tags to distinguish sea/sea-river container ports from pure inland ports and customer/non-port nodes; it does not call Tencent, write real data, or alter the existing bulk full-flow.
- Added a sanitized CSV template and maintenance documentation for the future container-vessel source.

### Verification

- Container contract, provider, node-master and freight-rate focused suites passed: `24 passed in 0.47s`.
- The real-data read-only audit found no connected `集装箱船运价时效.csv` source, zero loaded container-vessel records, and 28 sea or sea-river container-capable south-port candidates pending formal rate/time data. No container graph edge was generated.
- The required developer smoke passed: `468 passed in 4.37s`; real-data smoke passed with 492 freight rates, 972 standard nodes, 302 graph-ready candidates for its representative bulk order, and zero missing node IDs. The restricted Tencent probe returned `manual_review` on `ConnectionError` rather than claiming live API success.

## 2026-07-31

### Changed

- Added a strict Web-only loader for `航线控制点_全点版.json`. The current local GCJ-02 dataset exposes five corridors and 298 control points; invalid coordinate systems, duplicated route IDs, malformed points, or unknown route-mode mappings fail explicitly.
- Bulk-shipping and barge map segments now connect each actual endpoint to its nearest point in one applicable connected control-point network, then follow the maintained corridor subpath. The serialized geometry preserves source schema, route IDs, and endpoint connector distances.
- Kept route-control geometry outside `TransportEdge`, graph construction, cost/time calculation, candidate selection, and Dijkstra. Missing optional control-point data retains the earlier explicit schematic fallback; Tencent truck geometry remains the same measured-route polyline.
- Added a strict `运费数据.xlsx/运价表` adapter and made it the preferred formal freight source. The legacy `运价表.json` remains a compatibility fallback only when the workbook is absent; an invalid present workbook fails closed instead of silently reverting to stale JSON.
- South-port identity screening now treats maintained node tags as primary evidence. `节点信息维护0731.xlsx` is authoritative when present, while `码头信息维护0729版.xlsx` supplies the compatible port-nature fallback; name heuristics are used only when maintained identity tags are unavailable. Port identity requires maintained `节点性质=港口码头`; waterway attributes alone no longer promote a warehouse or company node to a south port.
- Preserved workbook row numbers in every `FreightRate` source trace. Commodity-specific wheat versus corn/soybean records now form distinct business keys, reducing the former ten same-day exact-OD barge conflicts to zero.
- Added two bounded, traceable rate-evidence capability overrides for endpoints absent from `节点信息维护0731.xlsx`: `东莞粤储粮港务有限公司/东莞粤储粮` as a Pearl River Delta sea-river origin and `南宁港牛湾作业区` as a Nanning inland transfer destination. The override applies only to the package and commodity scopes evidenced by exact OD records and does not generalize port identity.
- Added a strict adapter for `节点信息维护0731.xlsx`. It validates the maintained worksheet schema, ignores alias placeholders `24` and `/`, prefers the latest coordinates, preserves source rows, and collapses duplicate names without merging separately named port facilities.
- Added source-backed barge capability construction. An exact barge OD record proves only the two endpoints' ability to handle that record's package/commodity scope; customer endpoints remain customer nodes, transfer ports require an inland-waterway logistics role, and south ports still require sea access.
- Added traceable inland-waterway region assignment for exact barge endpoints. Maintained mappings are preferred; the remaining endpoints may use the nearest already mapped region anchor, retaining the anchor node and distance rather than presenting the proxy as an exact mapping.
- Added `ExactOdInlandWaterwayBargeProvider`. Applicable latest exact OD rates from the typed formal freight source now take precedence over the independent regional freight table, calculate total freight as unit rate times order quantity, and combine with the maintained complete-segment inland-waterway time. Regional freight is used only when no exact OD exists.
- Kept same-day, same-scope conflicting exact OD quotations in `manual_review`; an exact conflict is never hidden by a regional fallback. The former ten groups are no longer conflicts after the maintained workbook split their commodity scopes.
- Extended south-port selection with a small multimodal quota so nearest direct-truck candidates remain available while exact-OD barge origins can also enter the candidate set. For each selected south port, full-flow expands at most the three transfer ports nearest to the customer; the limit is a current search-width policy, not a business connectivity rule.
- Allowed a customer node to be an exact-OD barge receiver without reclassifying it as a port or transfer port. Customer/factory/logistics roles remain properties of one registered node for current routing; no database migration was introduced.

### Verification

- Route-control-point loading, nearest-corridor selection, bulk/barge geometry, Web serialization, and frontend contract tests passed with `19 passed in 0.41s`. The real local file loaded as five routes and 298 points; representative bulk, West River, and Min River paths selected the expected corridor sets. A local browser visual pass loaded the Tencent base map with no console errors.
- Node-master, loader, capability, exact-OD Provider, south-port selection, and full-flow focused suites passed.
- The exhaustive workbook-backed exact-OD audit found 193 selected barge rates and zero latest-price conflict groups. It generated all 163 corn-applicable and all 133 wheat-applicable exact OD edges after scope filtering.
- The representative offline full-flow for `北良港 -> 广西富丰集团有限公司` built direct-truck and barge alternatives in one graph after candidate-width control: 24 transport edges, including 9 barge and 9 truck edges. The winning route remains determined independently by cost and time rather than by the presence of a barge option.
- Final independent full pytest passed with `459 passed in 2.02s`; real-data smoke passed with 492 freight rates, 972 standard nodes, 302 billed/graph-ready validation candidates, and zero missing node IDs. The authorized Tencent probe and full-flow case both resolved successfully. The unified smoke wrapper's fixed pytest temp directory was locked by Windows, so its pytest substep was replaced by the independent unique-`basetemp` run rather than deleting the locked directory.
- Review hardening prevents proximity-only node aliasing, keeps role inference on the authoritative classifier, reserves an alternative-transport candidate even when the initial shortlist is all direct-road preferred, continues past unusable nearby transfer ports until three complete transfer paths are found, and only reports exact-OD origins whose freight, capability and time inputs can actually form an edge. Direct exact-OD customer barge delivery is now covered by full-flow tests and included in the barge-edge count.

## 2026-07-30

### Changed

- Added `src/application/route_planning.py` as the first UI-independent application boundary. `RoutePlanningRequest` now owns the shared north-port, customer, optional south-port, region, and order input; `RoutePlanningResponse` owns the structured result already consumed by the leadership CLI and local Web adapter.
- Added `RoutePlanningService` as the common application entry point and routed both CLI and Web calculations through it. The existing `build_full_flow_demo` engine remains behavior-compatible behind `plan_full_flow`; `FullFlowDemoResult` remains as a compatibility alias.
- Kept freight, shipping-time, port-candidate, graph-construction, cost/time Dijkstra, and Web serialization behavior unchanged. Full orchestration still resides in `leader_full_flow.py` and will migrate incrementally rather than through a broad refactor.
- Changed north-to-south bulk south-port admission so an otherwise unclassified registered port/wharf may use an applicable bulk-grain freight-origin record as business evidence. Evidence is package- and commodity-aware and may come from a truck or barge record.
- Kept confirmed inland ports, railway stations, customer facilities, and explicit bulk-capability exclusions blocked even when freight records exist. Container-only port origins remain outside the bulk south-port pool and are reported separately as potential transfer ports pending a future explicit node functional role.
- Updated the read-only order/port audit to inspect all freight-origin transport modes for bulk identity evidence while retaining maintained truck-rate availability as a separate status. Ports admitted through barge-origin evidence may still use the confirmed unknown-truck rule when Tencent road distance is available.
- Added tri-state `is_transfer_port` to the W3 port-capability contract, CSV aliases, audit row output, and synthetic data template. The value is independent from waterway role and graph-edge role.
- Required a `south_to_customer/transfer` barge destination to have an explicit transfer-port role. Blank role data remains unknown: destination discovery omits it and explicit formal edge construction returns manual review rather than guessing.
- Added structured `SouthPortCandidateDecision` records to the application response. Full-flow now traces identity exclusions, candidate-limit decisions, trunk/operation-fee/second-stage blockers, and final graph inclusion per relevant origin node.
- Exposed the same candidate decisions in the leadership CLI and Web JSON/UI run log. The presentation adapters only format the application result and do not recalculate eligibility.
- Moved automatic/explicit south-port selection, bulk freight-origin evidence, ranking, and distance pre-sort into `src/application/south_port_selection.py`. `leader_full_flow.py` now consumes `SouthPortSelection` and preserves its existing error/output compatibility.
- Added direct application-layer tests for barge-origin bulk evidence, confirmed inland exclusions, customer-facility exclusions, and container-only explicit selection.
- Kept explicit CSV schemas in the data-foundation audit even when a formal source currently has zero rows. The empty W3 capability audit now still exposes `is_transfer_port` and the remaining contract fields for safe data-platform/manual handoff.

### Verification

- The new application-contract, leader full-flow integration, and Web adapter suite passed with `38 passed in 0.95s`.
- The CLI `full-flow --help` entry loaded successfully without accessing Tencent or real-data APIs.
- The affected node-role, order/port audit, and leader full-flow suite passed with `54 passed in 0.59s`.
- The refreshed no-Tencent real-data audit covered 108 order scenarios and 120 relevant/registered nodes. It identified 17 automatic bulk south-port origins, 5 confirmed inland exclusions, 4 explicit capability exclusions, 10 container-only potential transfer ports, and 65 registered manual-only ports.
- The combined W3 loader/template/audit, inland-waterway Provider, full-flow, node-role, and admission-audit suite passed with `79 passed in 0.73s`.
- The application-contract, full-flow, Web serialization, frontend behavior, and geometry suite passed with `42 passed in 0.51s`.
- The new south-port application selector plus full-flow, shared application-contract, and Web regression suite passed with `41 passed in 0.98s`.
- The unified developer smoke passed with `434 passed in 2.61s`; real-data smoke passed with 492 freight rates, 367 standard nodes, 312 billed/graph-ready validation candidates, and zero missing node IDs. The restricted Tencent probe returned traceable `manual_review` on `ConnectionError`, not live-API success.
- The final affected audit/application/full-flow regression passed with `37 passed in 0.47s`. The refreshed read-only data-foundation audit reports zero unregistered freight locations, two unresolved railway-style AdditionalFee nodes, zero formal port-capability rows, eight region mappings, 69 operation-fee rates, two explicit exemptions, and eight inland-waterway time records.
- The W3 loader now distinguishes a missing optional source from a header-only source; both remain nonfatal, but the latter emits an explicit empty-source warning. Its focused reference/audit/template regression passed with `10 passed in 0.20s`.
- Revised the Web bulk-shipping schematic corridor to stay materially closer to mainland China's coast. Guangxi-bound routes now pass through the Qiongzhou Strait into the Beibu Gulf instead of detouring south of Hainan; the source version is `china_coastal_waters_schematic/1.1`.
- This is display-only geometry and does not alter costs, times, candidates, graph edges, or Dijkstra. Web geometry/serialization regression passed with `12 passed in 0.42s`; a local coarse-coast visual review confirmed the new corridor and strait passage.

## 2026-07-29

### Changed

- Re-established the long-term route architecture as exactly two business stages: north port to south port, then south port to customer. A business stage may contain multiple graph edges and multiple transport modes; the current Min River route remains one Demo/data instance rather than a third stage or a fixed topology.
- Replaced mode-shaped `TransportStage` values with `north_to_south` and `south_to_customer`, and added an independent `TransportEdgeRole` (`trunk`, `transfer`, or `delivery`). Edge IDs, graph attributes, `RouteSegment`, row export, and Web JSON now preserve both dimensions separately from `transport_mode`.
- Marked current bulk-shipping edges as `north_to_south/trunk`, barge-to-transfer-port edges as `south_to_customer/transfer`, and road-to-customer edges as `south_to_customer/delivery`.
- Removed the full-flow orchestration's hard-coded Nanping transfer-port list. Inland-waterway Providers now expose capability-backed destination candidates, which full-flow resolves through `NodeRegistry` before requesting an applicable edge.
- Preserved `time_scope` together with stage and edge role in `RouteSegment`, row exports, and Web JSON. Full-flow now also merges repeated shared downstream edges by `edge_id` before graph construction, preventing multiple south ports that share one transfer-port delivery leg from creating duplicate-edge build issues.
- Changed the Web map styling boundary to use explicit `transportStage` instead of assuming segment number one is always the only north-to-south edge.
- Added D-050 and reconciled older long-term wording about three-edge Demo paths, customer terminals, mode-shaped stages, and the current Min River example.
- Added D-051 to preserve leadership-confirmed CLI/Web inputs and outputs as a stable product contract while keeping candidate generation, Provider composition, graph topology, and search algorithms independent from Demo presentation needs.
- Added a strict Loader for the 99-row `码头信息维护0729版.xlsx` node master. The latest workbook names, aliases, and coordinates now overlay the older coordinate JSON while preserving existing canonical names and stable node IDs; ambiguous identity matches fail for manual review and older/newer coordinate differences remain auditable.
- Registered the workbook-only 南平港 node and refreshed the coordinates/aliases for 军航码头、福州马尾港、福州松下码头、秀屿港. The real registry now contains 367 standard nodes and retains 15 coordinate-source conflicts for review.
- Narrowed the Fujian inland-waterway capability scope to the sole maintained route `南平港↔军航码头`. 南平港 supports bulk/container corn and wheat plus barge/rail modes, but cannot receive the sea-going north-south bulk trunk. The confirmed bulk barge rule is 50 yuan/ton and 15 complete-segment hours in either direction.
- Added explicit bulk-trunk capability exclusions so container-only Mawei and capability-unconfirmed Songxia do not enter automatic or manually selected bulk-grain trunk routing. Registered-only ports are kept in manual-selection audit scope rather than being promoted to automatic candidates.
- Removed 福州马尾港 from the currently maintained Min River route while retaining its sea/inland identity and container-only corn/wheat capability. Current customer factories remain non-terminal nodes.
- Required an explicit sea-port or sea/inland marker for every north-south bulk-trunk destination. Inland and unmarked ports are rejected from automatic and explicit south-port selection; the prior unclassified-origin fallback is no longer used for this stage.
- Resolved waterway markers across the canonical name and explicit aliases of the same standard node, while retaining conflicting alias roles as unknown instead of choosing one silently.
- Removed the direct south-port-to-customer barge assumption from `leader_full_flow`. Current customer factories remain non-terminal nodes.
- Added the confirmed Min River transfer alternative: bulk shipping to 军航码头, barge to 南平港, then truck to the customer. The direct military-port truck route remains parallel in the same `MultiDiGraph`; the barge branch is added only when the Nanping-to-customer road result also resolves.
- Added intermediate-port coordinates to the full-flow/Web result so barge geometry remains explicitly schematic while the inland-port truck segment retains its Tencent road polyline.
- Generated a 77-row waterway-role confirmation table and a dual-track data-confirmation/development SOP. Previously ignored 百达码头 and 红东码头 are excluded without asking for duplicate confirmation.
- Added explicit customer and port-waterway role compatibility records for the first business-confirmed node set. 东莞深粮 and 平和县储备粮 are customer factories; 清远清新码头, 苏湾港, 贵港白沙码头, and 韶关北江国际港（白土码头） are inland ports excluded from the north-south bulk trunk.
- Confirmed 军航码头 as a Fujian Min River sea/inland dual-use port and mapped it to the 马尾 freight group and 福建 time region. Confirmed 洋浦港 as a sea port and mapped it to the 马村/海口 freight group and 海南 time region.
- Applied the same waterway-role boundary to automatic candidate selection, explicit `--south-port` validation, and the read-only order/port admission audit. Inland ports remain available for future routes inside the second business stage when their route-specific data is complete.
- Updated the audit wording and long-term project files so excluded inland/customer nodes are not described as unresolved freight candidates.

### Verification

- The final affected transport-contract, graph/result, inland-waterway Provider, full-flow, and Web suite passed with `60 passed in 0.45s`.
- Developer smoke passed with `418 passed in 1.57s`; real-data smoke passed with 492 freight rates, 367 standard nodes, 312 graph-ready billed candidates, and zero missing node IDs. The restricted Tencent probe returned traceable `manual_review` on `ConnectionError` and is not live-API success evidence.
- The focused node-master, data-loader, role, inland-waterway, admission-audit, full-flow, and Web API suite passed with `81 passed in 1.12s`.
- The refreshed read-only audit covered 108 order scenarios and 117 registered/relevant nodes: 9 explicitly sea-marked automatic bulk candidates and 108 nonautomatic or confirmed-excluded nodes, with 116 deduplicated manual-review items. The separate sea-marker table contains 77 nodes; 南平港 is explicitly excluded as an inland port.
- The affected role, Min River, admission-audit, full-flow, and Web tests passed with `67 passed in 0.54s`.
- Developer smoke passed with `413 passed in 1.64s`; real-data smoke passed with 312 graph-ready billed candidates and zero missing node IDs. The Tencent probe remained `manual_review` on restricted-process `ConnectionError`.
- Min River transfer, full-flow and Web affected tests passed with `36 passed in 0.45s`. Final developer smoke passed with `413 passed in 1.75s`; real-data smoke passed, and the restricted Tencent probe remained `manual_review`.
- Developer smoke passed with `409 passed in 1.73s`; real-data smoke passed with 492 freight rates, 367 standard nodes, 312 graph-ready billed candidates, and zero missing node IDs. The restricted Tencent probe returned `manual_review` on `ConnectionError` and is not API-success evidence.
- Affected node-role, bulk-shipping, admission-audit, leader full-flow, and local Web API tests passed with `52 passed in 0.63s`.
- The refreshed read-only real-data audit covered 108 order scenarios and 64 related nodes: 42 north-south candidate-style nodes, 22 nonautomatic or confirmed-excluded nodes, and 126 deduplicated manual-review items.
- For representative 500-ton bulk corn and wheat orders under domestic and external trade, all four scenarios produced 13 automatic candidates, 13 offline-ready candidates, and zero pre-Tencent bulk-trunk blockers. Soybean and container scope remain unresolved as documented.

## 2026-07-28

### Changed

- Extended W5 operation-fee matching with an approved third-priority fallback: after exact and explicitly maintained region rules, the Provider may select the geographically nearest applicable formal rate in the same traceably resolved business region. The result remains `regional_proxy` and retains reference port, distance, region, mapping basis, rule ID/version, and the statement that it is not the target port's exact rate.
- Added a safe nearest-regional bulk-shipping time resolver. It requires a unique confirmed sea-capability record before proxying complete-segment time and never supplies a freight destination group or physical connectivity.
- Added a formal inland-waterway freight CSV Loader and Provider, plus a storage-independent barge-edge Provider that combines endpoint region/capability, fare, and complete-segment time.
- Added the confirmed Fujian Min River business rule to ignored local data: 15 hours each direction and 50 yuan per ton for bulk grain of any commodity. Added a sanitized freight-table template and Loader test.
- Extended `leader_full_flow` so truck and barge can enter the `MultiDiGraph` as parallel second-stage alternatives, remaining placeholder capability is explicitly counted/disclosed, and a registered south port may be supplied with `--south-port`.
- Added a loopback-only local route presentation service and static Tencent-map page. It accepts transport/order inputs, reuses the full-flow orchestration, and displays both objectives, cost components, warnings/errors, candidates and node overlays.
- Upgraded map overlays to per-segment geometry. Tencent driving `routes[0].polyline` is decoded and retained from the same response used for distance/time, while bulk shipping uses an explicitly schematic dashed China-offshore control-point line. Missing road geometry remains unavailable rather than being replaced with a misleading straight line; barge geometry remains explicitly schematic.
- Kept map geometry outside `TransportEdge` and Dijkstra through an edge-ID side table, and changed route responses to `Cache-Control: no-store`.
- Fixed the result-state visibility rule so the initial “等待测算” panel is removed after a successful calculation instead of remaining underneath the route result.
- Cleared prior route overlays and the prior graph-edge badge after a failed calculation, and made a late-loading Tencent map render an already-resolved result instead of remaining blank.
- Added a read-only order/port admission audit. It derives current commodities, legal package/unit pairs, trade types and bulk-vessel capacity boundaries, then checks every order scenario against the last-mile candidate source, bulk-shipping match and south-port operation-fee Provider without calling Tencent or writing business data.
- The audit emits scenario summaries, scenario-by-port stage results, unaggregated issues and a deduplicated manual-review CSV under ignored `output/`. It distinguishes automatic-candidate gaps, manually selectable registered ports, current implementation scope, vessel-capacity limits and the remaining Tencent road dependency.
- Aligned the audit with the full-flow candidate fallback when fewer than two port-like rate origins exist, added registered port-like nodes to the explicit-south-port review scope, retained CSV schemas for empty result sets, and made the unsupported `柜` operation-fee unit explicit without converting it to `箱`.
- Added a shared conservative node-role classifier from confirmed naming rules. Railway-station names and customer facility/company names are now excluded from automatic fallback and explicit south-port selection; customer-owned terminals must use separately maintained port/terminal nodes.
- Updated long-term project state, architecture, decisions, plan, README, and W3/W5 data-template documentation for the new boundaries.

### Verification

- Affected operation-fee, time-proxy, inland-waterway, full-flow, Web API, and template tests passed before the final full run.
- The new order/port admission audit and affected bulk-shipping, operation-fee, data-audit, full-flow and request-contract tests passed `64 passed in 0.62s`.
- After the geometry upgrade, developer smoke passed with `372 passed in 1.95s`; the real-data chain still passed with 312 graph-ready billed candidates and zero missing node IDs.
- The same smoke run's real-data chain passed with 492 freight rates, 303 nodes, 18 AdditionalFee records, 312 graph-ready billed candidates, and zero missing node IDs.
- Final developer smoke after the exhaustive order/port audit passed with `377 passed in 1.77s`; real-data smoke passed with 312 graph-ready billed candidates and zero missing node IDs. The Tencent probe safely returned `manual_review` because the current process could not reach the API, so it is not live-API success evidence.
- Node-role classification, admission audit, full-flow, and local Web API affected tests passed `36 passed in 0.95s`. The refreshed read-only audit reduced the reviewed scope from 77 to 64 relevant nodes and deduplicated manual-confirmation items from 249 to 146.
- End-of-day developer smoke passed with `391 passed in 1.98s`; real-data smoke passed with 312 graph-ready billed candidates and zero missing node IDs. The current-process Tencent probe again returned `manual_review` on connection failure and is not API-success evidence.
- The user confirmed the same Key has both JavaScript API and WebService API permissions. An allowed-network in-browser rehearsal rendered the Tencent base map, returned the resolved 379,750-yuan route, preserved 531 Tencent points for the selected truck segment, and rendered the bulk route as an offshore dashed schematic. The restricted smoke-process Tencent probe fell back safely to `manual_review` on network denial and is not counted as separate live-API evidence.

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
