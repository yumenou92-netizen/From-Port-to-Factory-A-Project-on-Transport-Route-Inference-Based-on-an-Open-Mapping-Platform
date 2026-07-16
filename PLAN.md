# PLAN.md

This plan is the durable engineering plan for the route inference prototype. It supersedes older one-off SOP fragments when they conflict with current code and decisions.

Updated: 2026-07-16

## Current Development Principle

Build the prototype in dependency order:

```text
data audit
-> node registry
-> coordinate provider
-> route request and unit validation
-> freight rate and cost rules
-> latest rate selection
-> shipping time provider
-> customer profile and route rules
-> transport edge
-> MultiDiGraph
-> route search strategy
-> route result explanation
```

Do not jump to full path search until cost, time, node, and edge inputs are explainable.

## Two-Track Operating Model

Development uses two tracks:

| Track | Purpose | Source Of Truth | Output |
|---|---|---|---|
| Engineering track | Build and verify the system | Code, tests, Git, `PROJECT_STATE.md`, `DECISIONS.md` | Modules, tests, demos, changelog |
| Reporting track | Manage stakeholder expectations | Verified engineering facts translated conservatively | Daily plans, work reports, leader demos |

The engineering track can move faster than the reporting track. The reporting track should stay factual, conservative, and staged so the project does not over-promise incomplete capabilities.

Leader-facing plans should emphasize:

- what is being clarified;
- what has been locally verified;
- what remains pending business confirmation;
- what will be prepared for the next stage.

Leader-facing plans should not present unbuilt modules as complete or production-ready.

## Milestones

| Phase | Milestone | Status | Completion Standard |
|---|---|---|---|
| 0 | Durable project memory | Complete | `AGENTS.md`, `PLAN.md`, `CHANGELOG.md`, `docs/PROJECT_STATE.md`, `docs/ARCHITECTURE.md`, and `docs/DECISIONS.md` exist and reflect current scope |
| 1 | Data audit and data-use report | Complete | JSON files audited; sanitized report and local quality output generated; sensitive output isolated |
| 2 | Node registry | Complete | Standard node ids, alias handling, coordinate conflict reporting, and coverage checks implemented |
| 3 | Coordinate and map provider | Complete second version | Local standard node registry resolves known coordinates; Tencent coordinate and driving-route providers exist behind explicit interfaces and read API key from environment only |
| 4 | Route request and unit validation | Complete | Order units and price units match exactly; mismatches return manual review |
| 5 | FreightRate and cost rules | Partially complete | Formal `FreightRate`, `CostRuleEngine`, and corrected truck-rule boundary exist; latest-rate selection still pending |
| 6 | Latest freight-rate selection | Not started | Same business route selects latest maintained valid rate; conflicts and missing dates are explicit |
| 7 | ShippingTimeProvider | Not started | Manual provider enabled; JSON, database, and API providers reserved but disabled |
| 8 | CustomerProfile and route filtering | Not started | Private-terminal and no-private-terminal route logic separated and tested |
| 9 | TransportEdge | Not started | Standard edge contains node ids, cost, time, mode, packaging, source, and availability reason |
| 10 | MultiDiGraph | Not started | Parallel edges are preserved and edge keys are returned in route results |
| 11 | RouteSearchStrategy | Not started | Cost-minimum and time-minimum paths are searched separately |
| 12 | RouteResult and explanation output | Not started | Segment-level and total-level costs, times, sources, and manual-review flags are explainable |

## Immediate Work Queue

### Task 0: Durable Project Memory

Status: complete.

Goal:

- establish persistent project state files before further development;
- reduce drift from chat-only memory and outdated SOP documents.

Deliverables:

- `AGENTS.md`
- `PLAN.md`
- `CHANGELOG.md`
- `docs/PROJECT_STATE.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`

Verification:

- all six files exist;
- no real business data is included;
- Git status shows only intentional docs plus previously confirmed local changes.

### Task 1: Truck Cost Rule Review And Correction

Status: complete.

Goal:

- address the business feedback that the earlier truck-cost rule design was incorrect;
- clarify known-route vs unknown-route truck billing before building `TransportEdge`.

Scope:

- review `src/cost_rules.py`;
- revise rule config names, statuses, disabled reasons, and calculation boundaries if needed;
- keep unknown truck-route rules disabled until formula and distance provider are confirmed;
- add or update tests proving incorrect or disabled truck rules cannot enter automatic recommendation.

Verification:

- `pytest` passes;
- known freight-rate records still calculate through `FreightRate`;
- unknown bulk truck rule records the revised `draft-2` piecewise parameters but is not active;
- unknown container truck rule remains disabled and pending confirmation;
- demo output can explain the boundary.

### Task 1.5: Tencent Maps API Provider Spike

Status: complete first version.

Goal:

- verify that Tencent Maps can be isolated behind provider modules before latest-rate selection continues;
- support local-first coordinate lookup fallback and road distance/time probing without committing API keys.

Scope:

- implement Tencent place-search coordinate provider;
- implement Tencent normal driving-route provider for road distance and estimated time;
- keep truck-route provider as optional future enhancement, not current dependency;
- read `TENCENT_MAP_API_KEY` from local environment only;
- use mocked unit tests rather than consuming live API quota.

Verification:

- provider tests pass with mocked Tencent responses;
- API key is not written to code, docs, tests, Git, or output;
- live API smoke test remains a local optional script.

### Task 2: Latest Freight-Rate Selection

Goal:

- choose the latest maintained freight rate for the same business route.

Scope:

- define route identity using existing `FreightRate.business_route_key`;
- prefer latest `maintained_at`;
- define handling for missing dates and same-day conflicting records;
- integrate selection before candidate edge generation.

Verification:

- tests cover old/new records, missing dates, same-day conflicts, and different route keys;
- data audit remains full-history and is not filtered.

### Task 3: ShippingTimeProvider

Goal:

- define one interface for transport time.

Scope:

- implement `ManualShippingTimeProvider`;
- reserve `JsonShippingTimeProvider`, `DatabaseShippingTimeProvider`, and `ApiShippingTimeProvider`;
- standardize internal time unit as hours.

Verification:

- manual positive time returns valid hours;
- missing or invalid time fails clearly;
- disabled providers fail clearly.

## Deferred Work

- Formal integration of road distance provider into unknown-route truck pricing.
- Customer profile source and private-terminal data.
- Formal `TransportEdge`.
- `nx.MultiDiGraph` upgrade.
- Route search strategy and edge-key path output.
- Production database or API service.
- Frontend UI.

## Stop Conditions

Stop and ask for user/business confirmation if:

- a cost formula is ambiguous or contradicted by business feedback;
- a user-provided file, path, formula, unit, data source, effective date, direction, or enable/disable requirement is missing or conflicts with current project rules;
- a required file or external API contract is missing;
- a rule would require converting between `吨`, `箱`, and `柜`;
- a route depends on unprovided North Port to South Port data;
- a requested algorithm depends on the user's thesis code or paper files.
