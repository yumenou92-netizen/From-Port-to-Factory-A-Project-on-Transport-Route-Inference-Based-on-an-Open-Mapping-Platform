# CHANGELOG.md

This changelog records actual engineering changes. It is not a leader-facing daily report.

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
- Integrated known truck-route policy into `data_loaders.py` candidate generation for freight-rate records whose transport mode is `汽运`.
- Updated unknown bulk truck-route rule to revised `draft-2` piecewise yuan-per-ton parameters from `docs/最后一公里汽运计费规则算法设计_修订版.md`; rule remains disabled.
- Added durable input-completeness rule: user-provided files, formulas, paths, and requirements must be checked for missing or conflicting implementation details before coding.
- Added `src/coordinate_provider.py` and tests for global local-first coordinate confirmation:
  - known coordinates resolve from `NodeRegistry`;
  - unknown coordinates fall back to a disabled Tencent Maps placeholder;
  - missing external provider returns `manual_review`.
- Added Tencent Maps provider spike:
  - `src/distance_provider.py` defines road route request/result interfaces;
  - `src/tencent_map_provider.py` implements Tencent place search and normal driving-route adapters;
  - `src/demo_tencent_map_probe.py` provides an optional local API smoke test;
  - API key is read only from `TENCENT_MAP_API_KEY`;
  - truck-route adapter remains optional future enhancement, while normal driving route is the current default for road distance/time.

### Notes

- `README_Codex_移交说明.md` deletion was confirmed by the user as intentional.
- Real business data remains local-only and must not be committed.
- Tencent Maps API key must never be written to Git-tracked files or printed in logs.

## 2026-07-15

### Added

- Centralized traceable freight calculations in `src/cost_rules.py`.
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

- `src/freight_rate.py` formalized the `FreightRate` model.
- `src/route_request.py` formalized order request and packaging/unit validation.
- `src/unit_conversion.py` implemented exact matching for `吨`, `箱`, and `柜`.
- `src/node_registry.py` implemented standard node ids, aliases, and coordinate conflict reporting.
- Leader demo files were added for node registry, route request, freight rate, real data, and cost rules.

### Changed

- `src/data_loaders.py` now reads local real JSON data into typed intermediate records and candidate edge records.
- `src/demo_run.py` evolved into a mutable development integration script.
- `src/demo_leader.py` became the leader-facing demo menu.

### Verification

- Unit tests were added for data loaders, node registry, route request, unit conversion, freight rate, data audit, and cost rules.

## Earlier Baseline

### Added

- Initial prototype used CSV/sample data, `networkx.DiGraph`, and basic shortest-path logic.
- Initial docs described project background, module architecture, algorithm design, cost rules, data structures, and technical boundaries.

### Known Drift

- Early documents still mention CSV-first sample-data design. Current development has moved toward local JSON data via `DATA_DIR`, formal `FreightRate`, `RouteRequest`, `NodeRegistry`, and `CostRuleEngine`.
