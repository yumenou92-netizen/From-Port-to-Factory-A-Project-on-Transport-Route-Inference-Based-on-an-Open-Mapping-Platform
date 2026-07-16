# PROJECT_STATE.md

Updated: 2026-07-16

This file records the current verified engineering state of the project. It is the first file to read before continuing development.

## Current Position

The project has completed the core pre-graph foundation:

```text
local JSON data audit
-> real data loading
-> node standardization
-> local-first coordinate confirmation provider
-> Tencent Maps provider adapter for place search and driving-route distance/time
-> route request validation
-> unit matching
-> FreightRate model
-> traceable CostRuleEngine
```

The project has not yet completed:

```text
latest freight-rate selection
-> shipping time provider
-> customer profile
-> formal TransportEdge
-> MultiDiGraph
-> cost-minimum and time-minimum route search
-> route result explanation
```

## Current Code Modules

| File | Current Role | State |
|---|---|---|
| `src/data_audit.py` | Audits local JSON data quality and writes sanitized/local outputs | Complete first version |
| `src/data_loaders.py` | Loads real JSON data and builds order edge candidates | First version complete |
| `src/node_registry.py` | Standard node ids, aliases, coordinates, coverage checks | Complete first version |
| `src/coordinate_provider.py` | Local-first coordinate confirmation and Tencent Maps fallback hook | Complete first version |
| `src/distance_provider.py` | Road route request/result interfaces and km/hour normalization | Complete first version |
| `src/tencent_map_provider.py` | Tencent Maps place-search and normal driving-route adapter | Complete first version |
| `src/route_request.py` | Order request model and billing validation | Complete first version |
| `src/unit_conversion.py` | Exact quantity/price unit matching and total cost conversion | Complete |
| `src/freight_rate.py` | Formal freight-rate model and evaluation entry point | Mostly complete |
| `src/cost_rules.py` | Central rule engine and traceable calculation result | Truck known-route/unknown-route boundary corrected |
| `src/graph_builder.py` | Legacy `nx.DiGraph` builder | Needs replacement or upgrade |
| `src/route_planner.py` | Legacy shortest-path baseline | Needs strategy and MultiDiGraph upgrade |
| `src/models.py` | Legacy general models | Needs gradual replacement or split |

## Current Data State

Current local real data covers South Port to customer/factory routes. It does not yet provide North Port to South Port trunk-shipping data.

Local real data is allowed for development and validation, but must remain uncommitted. Use `DATA_DIR` rather than hardcoded absolute paths.

Current data can support:

- freight-rate candidate generation;
- node and coordinate lookup;
- endpoint coverage checks;
- unit validation and current-order segment cost calculation;
- known-route freight-rate lookup after latest-rate selection is implemented.

Current data cannot alone support:

- complete North Port to South Port pricing;
- automatic shipping time;
- customer private-terminal rules;
- Tencent Maps road distance;
- complete route recommendation.

## Current Business Rules Implemented

- Quantity units supported: `吨`, `箱`, `柜`.
- Price units supported: `元/吨`, `元/箱`, `元/柜`.
- Quantity and price units must match exactly.
- `箱` and `柜` are not converted automatically.
- Packaging is auxiliary validation, not transport-mode inference.
- Transport mode is copied from freight-rate data.
- Valid calculated cost is current-order segment total cost in yuan.
- Manual review is returned for unit mismatch or invalid price states.
- Known truck routes use maintained `FreightRate` records through `calculate_last_mile_truck(..., known_rate=...)`.
- Unknown bulk truck-route rule is registered as revised `draft-2` parameters but remains disabled; missing known rate returns `manual_review`.
- Unknown container truck-route rule remains disabled and pending business confirmation.
- Coordinate confirmation is local-first: standard node registry and known coordinate table are checked before any Tencent Maps fallback.
- Tencent Maps geocoding is available through `TencentMapCoordinateProvider` but only after `TENCENT_MAP_API_KEY` is configured; ambiguous place-search results return `manual_review`.
- Tencent Maps road distance/time currently uses normal driving route through `TencentMapDrivingRouteProvider`; truck-route support is optional future enhancement.
- Tencent route distance is normalized from meters to kilometers; route duration is normalized from minutes to hours.
- Tencent API key must not be committed, printed, or written to docs/tests/output.

## Current Business Rules Pending

- Latest maintained freight-rate selection.
- Shipping time provider design.
- Customer profile and private-terminal source.
- Formal integration of road distance provider into unknown truck-route pricing.
- Unknown container truck-route formula confirmation.
- Live Tencent Maps smoke test result against the user's local key.
- Whether and how to convert container cost to ton-based comparison.

## Current Test State

Last verified full test result:

```text
125 passed
```

The default Python installation may not have `pytest`; use the configured project/PyCharm virtual environment when needed.

## Current Git State Notes

- `README_Codex_移交说明.md` deletion was confirmed by the user as intentional.
- Several local leader-facing report files are untracked and should normally remain local unless explicitly selected and sanitized.
- `data_REAL/` and `output/` must remain ignored.

## Next Work

Immediate order:

1. Implement latest freight-rate selection.
2. Implement `ShippingTimeProvider` with manual provider first.
3. Move into `TransportEdge` only after cost and time inputs are stable.

## Source Of Truth

Use these in order:

1. Current code and tests.
2. `AGENTS.md`.
3. `PLAN.md`.
4. `docs/DECISIONS.md`.
5. This file.
6. Git history.

Leader-facing daily reports are not the engineering source of truth.
