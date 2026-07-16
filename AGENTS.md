# AGENTS.md

This file defines durable development rules for the port-to-customer route inference prototype. It is intended for Codex or any future coding agent working in this repository.

## Project Positioning

Project name:

```text
北港至客户工厂全链路运输路径推断原型
```

This repository is a Python prototype for business-rule validation and explainable route inference. It is not a production dispatching, quotation, database, backend, or frontend system.

The current development goal is to build a maintainable prototype that can:

- read local business JSON data without committing the data;
- standardize transport nodes;
- validate order quantity units against freight price units;
- calculate transport-segment total cost in yuan;
- keep cost and time as independent weights;
- later build a multi-edge graph and output explainable route results.

## Repository Structure

Current important paths:

```text
src/
  data_audit.py          # JSON data quality audit and sanitized report generation
  data_loaders.py        # local JSON loading and candidate edge preparation
  node_registry.py       # standard node ids, aliases, coordinate conflict checks
  coordinate_provider.py # local-first coordinate confirmation and API fallback
  distance_provider.py   # road distance/time provider interfaces
  tencent_map_provider.py # Tencent Maps WebService adapter
  route_request.py       # order request model and packaging/unit validation
  unit_conversion.py     # exact unit matching and segment total cost conversion
  freight_rate.py        # formal FreightRate model and evaluation entry point
  cost_rules.py          # CostRuleEngine and traceable calculation results
  graph_builder.py       # legacy DiGraph builder, pending MultiDiGraph upgrade
  route_planner.py       # legacy shortest path baseline, pending strategy upgrade
  demo_run.py            # mutable development integration script
  demo_leader.py         # leader-facing demo menu

tests/
  test_*.py              # pytest unit tests

docs/
  PROJECT_STATE.md       # current verified engineering state
  ARCHITECTURE.md        # current and target architecture
  DECISIONS.md           # durable business and technical decisions
```

## Data And Privacy Rules

Real business data may be read locally for development and validation, but must not be uploaded to GitHub.

Never commit:

- `data_REAL/`;
- `output/`;
- `.env` or `.env.*` files containing API keys;
- raw JSON business files such as freight rates, coordinates, or additional fees;
- Excel workbooks containing business data;
- customer names, route details, coordinate details, or raw price records unless explicitly sanitized.

Data directory access must use `DATA_DIR` or local runtime configuration. Do not hardcode an absolute D drive business-data path in source code.

Tencent Maps API access must use `TENCENT_MAP_API_KEY` from the local environment. Do not hardcode the key in source code, tests, docs, demos, shell scripts, committed config, or output files. Do not print the full key.

The `.gitignore` must continue to ignore local business data folders and generated output folders.

## Git Rules

After each completed module, remind the user to commit. If the user authorizes it, commit and push to GitHub only after a sensitive-data check.

Before every commit or push, run at least:

```powershell
git status --short --branch
git status --short --ignored data_REAL output
git diff --cached --name-only
git diff --cached --name-only | Select-String -Pattern "data_REAL|output|\.json$|\.xlsx$|\.xls$|\.csv$"
git ls-files data_REAL output
```

Before push, also check the committed tree:

```powershell
git ls-tree -r --name-only HEAD | Select-String -Pattern "data_REAL|output|\.xlsx$|\.xls$|运价表\.json$|地点经纬度\.json$|其他费用表\.json$"
```

If any sensitive match appears, stop and resolve the issue before committing or pushing.

## Run And Test Commands

Primary test command:

```powershell
python -m pytest
```

If the default Python environment does not contain `pytest`, use the configured project/PyCharm virtual environment. Do not install dependencies into the repository without confirming the environment plan.

Data audit requires `DATA_DIR`:

```powershell
$env:DATA_DIR=(Resolve-Path ".\data_REAL").Path
python -m src.data_audit
```

Development demo:

```powershell
python src/demo_run.py
```

Leader-facing demo:

```powershell
python src/demo_leader.py
```

## Development Workflow

Use this order for feature work:

1. Read `docs/PROJECT_STATE.md`.
2. Check `PLAN.md`.
3. Check `docs/DECISIONS.md` for durable business rules.
4. Inspect current code before editing.
5. Make narrowly scoped changes.
6. Add or update pytest coverage for behavior changes.
7. Run tests.
8. Update `docs/PROJECT_STATE.md` and `CHANGELOG.md` when the project state changes.
9. Run Git sensitive-data checks before commit or push.

Do not treat chat history as the only project memory. Durable decisions and status must be reflected in the Markdown files above.

## Input Completeness Check

Before implementing or assisting with development work based on user-provided files, prompts, business rules, or requirements:

1. Locate and read the referenced file instead of assuming the path or content.
2. Check whether the provided material is internally complete enough for the requested change.
3. Check for conflicts with current code, tests, `PLAN.md`, `docs/PROJECT_STATE.md`, and `docs/DECISIONS.md`.
4. Check whether key inputs are missing, such as business formulas, units, data source, effective date, directionality, API contract, test expectation, or enable/disable status.
5. If any missing or conflicting item affects implementation safety, stop and ask the user for confirmation before continuing.
6. If there are only non-blocking assumptions, state them clearly and proceed conservatively.

Do not silently fill material business gaps with guesses.

## Engineering Rules

- Keep modules small and focused.
- Prefer existing patterns over new abstractions.
- Use type annotations for new Python code.
- Use structured parsing and dataclasses where appropriate.
- Do not silently coerce unsupported business units.
- Do not mix raw unit prices such as `元/吨`, `元/箱`, and `元/柜`.
- Convert every usable freight price to current-order segment total cost in yuan before route search.
- Keep original price, unit, source, and maintenance date for explanation.
- Keep `cost` and `time` independent; do not create a synthetic combined weight without a confirmed business coefficient.
- Missing cost or time must not default to zero.
- Placeholder providers must fail clearly when called.

## Current Business Rules

- The first-stage destination "南方港口" and second-stage origin "南方港口" are the same physical node and must use the same `node_id` and coordinates.
- Coordinate confirmation is global and local-first: standard node registry and known coordinate tables must be checked before any external map API fallback.
- Tencent Maps coordinate lookup and driving-route lookup are provider modules, not direct business logic.
- Road distance/time lookup should use normal driving route first. Truck route is optional future enhancement for vehicle-specific restrictions, not a current hard dependency.
- If the local coordinate table has no match and the provider is not configured or returns ambiguous results, return manual review instead of guessing.
- Transport mode comes from freight-rate data; it must not be inferred from packaging.
- Packaging is an auxiliary billing validation field.
- Quantity and price units must match exactly:
  - `吨` matches `元/吨`;
  - `箱` matches `元/箱`;
  - `柜` matches `元/柜`;
  - `箱` and `柜` are not interchangeable.
- Unit mismatch means `manual_review`, not automatic calculation.
- Current real data covers South Port to customer/factory routes. North Port to South Port data is not yet provided.
- Known truck routes should use maintained freight rates.
- Unknown bulk truck-route rule is recorded as `draft-2` using the revised piecewise yuan-per-ton function, but remains disabled until distance provider, latest-rate selection, business acceptance, and boundary tests are complete.
- Unknown container truck-route rule remains disabled and needs further business confirmation.
- Shipping time currently comes from manual input only; JSON, database, and API providers are future placeholders.

## Reporting Boundary

Leader-facing reports are communication deliverables. Engineering state must be derived from current code, tests, Git status, `PLAN.md`, `docs/PROJECT_STATE.md`, and verified module behavior.

Do not use leader-facing progress documents as the source of truth for actual development completion.

## Stakeholder And Demand Management

The project has two separate communication tracks:

```text
engineering track = actual code, tests, data status, blockers, and Git state
reporting track   = conservative leader-facing progress, risks, and next-step framing
```

Rules for the engineering track:

- Keep `docs/PROJECT_STATE.md`, `PLAN.md`, `CHANGELOG.md`, and `docs/DECISIONS.md` technically accurate.
- Record real blockers, unimplemented modules, failed tests, and missing data sources.
- Do not mark a module complete unless the completion standard in this file is met.

Rules for the reporting track:

- Use verified facts, but present progress conservatively.
- Prefer staged language such as "梳理", "复核", "初步验证", "形成设计口径", and "为后续开发做准备" when the work is exploratory or foundational.
- Do not over-promise delivery dates, automation ability, API readiness, or production reliability.
- Do not expose unnecessary internal implementation speed or tool-assisted acceleration as a management headline.
- Do not claim that unimplemented modules are complete.
- Do not fabricate work, test results, data sources, or business confirmations.

When a user asks for a leader-facing report, derive the content from the real engineering state, then translate it into conservative business-facing language. Keep actual engineering status and leader-facing narrative separate.

## Completion Standard

A module is complete only when:

- the code implements the agreed behavior;
- normal, error, and boundary cases have pytest coverage;
- the demo or development script can show the behavior when useful;
- sensitive data is not committed;
- relevant status, decision, or changelog docs are updated;
- tests pass or the failure reason is explicitly recorded.
