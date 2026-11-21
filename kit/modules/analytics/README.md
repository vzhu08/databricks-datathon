# Analytics and optimization

## 1. What problem does this solve, and when should I use it?

Turn a small CSV into explicit clean values, summary statistics and chart data, then explore a real constrained allocation. The reference scenario chooses event improvements under budget, item-count, category, dependency and exclusion constraints. Both the API and the what-if interface call the same exact solver.

## 2. What is the smallest working example?

```sh
node --import tsx modules/analytics/examples/demo.ts
```

The authored sample data contains missing/invalid costs. These remain missing rather than becoming zero. The 100-credit allocation selects captions, mentor hours and signage for 127 synthetic benefit points; 50 credits yields 52 points, and a zero-credit budget is infeasible with the sample minimum item count.

## 3. How do I add it to a fresh project or an existing project?

Select `analytics` from the catalog or copy this module. Install exact `papaparse`, `zod` and (for components) `react` versions from [module.json](module.json); TypeScript applications also need `@types/papaparse` and `@types/react`. Call the [pure API](src/index.ts) from existing handlers. Import optional `DataChart` and `ScenarioExplorer` from [components.tsx](src/components.tsx) into a client component. No service, worker or migration is mandatory.

## 4. What does the API accept and return?

`cleanCsv(csv, numericColumns=[], maxRows=10000)` uses comma-separated CSV with quoted-field support, trimmed headers/values, and blank/NA/N/A/null missing values. Explicit numeric columns accept finite decimal/exponent forms only; invalid numeric values become null with row/column issues. Duplicate/empty headers fail. Extra/missing fields generate issues; extra values are ignored, missing fields are null. Nothing is auto-imputed or coerced into a date/currency.

`summarize(values)` returns count, missing, sum, mean, median, min, max and population standard deviation. Empty inputs have null mean/median/extrema/deviation and sum 0. `aggregate(rows, category, metric)` sums finite numeric values, keeps a named missing category, and sorts labels; ISO date strings form ordered time-series buckets. `scoreRow` takes domain-fixed min/max, nonnegative weight and higher/lower direction; missing input contributes zero and contributions sum to the score.

`optimizeAllocation(problem)` takes an integer budget and up to 20 binary items with integer cost, nonnegative value, category and optional requires/excludes IDs. It enforces min/max selected count and required category coverage. It exhaustively searches the bounded feasible space, maximizes value, then minimizes cost, then uses lexical ID ordering. Returns `status:'optimal'|'infeasible'`, selection, cost, benefit, remaining budget and evaluated terminal states. Infeasible is distinct from a feasible empty selection. `compareScenarios(problem, nextBudget)` returns before/after and a null delta if either is infeasible.

## 5. What prerequisites, environment variables, or credentials are needed?

Node.js 22+ for examples and modern React for optional UI. No credentials, environment variables or external requests. Numeric units are caller-defined; sample costs are **credits** and values are **authored benefit points**, not measured financial return.

## 6. What changes must I make to routes, schema, storage, or UI?

`ScenarioExplorer({problem?})` renders the synthetic allocation by default, budget slider, constraints result, selection and before/after chart. Pass your own validated problem to reuse it. `DataChart({data,title,kind:'bar'|'line',unit})` renders an accessible SVG and textual values, handles negative values and empty data. Line charts use evenly spaced categories, not continuous time interpolation. Keep column-to-unit and currency/date parsing decisions in the consuming domain. Use a worker/server for larger synchronous workloads rather than increasing this solver's cap.

## 7. How do I verify it and handle expected failures?

```sh
npx vitest run modules/analytics/tests
```

Checks exercise CSV quoting/missing values, malformed headers, all-missing statistics, charts' source aggregation, scoring agreement, a known exact optimum, scenario equality, infeasibility, dependencies, exclusions and tie handling. Display CSV issues to users. Reject malformed problems before solving, and present infeasible constraints as a valid result with an action to revise the budget or requirements.

Implementation: implemented. Observed local verification: `npx tsc --noEmit` passed on the module checkout; `npx eslint modules` passed; `npx vitest run modules/analytics/tests` passed (7 tests as part of the combined 35-test module run); `node --import tsx modules/analytics/examples/demo.ts` completed without credentials. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Live checks: not applicable; no provider adapter. [events.csv](fixtures/events.csv) and [allocation.json](fixtures/allocation.json) are original synthetic fixtures (MIT).

## 8. What does it depend on, and what are its limits?

[Zod](https://zod.dev/) validates inputs; [PapaParse](https://www.papaparse.com/docs) parses CSV; React renders optional UI. CSV limits: 2 MB, 200 columns, default 10,000 rows, configurable up to 100,000 rows. The solver is exact for at most 20 binary items; its worst case is exponential and it has no continuous quantities or scheduling durations. Benefit numbers are assumptions, so the optimum is only as meaningful as those assumptions. No API charges. Original code/fixtures: MIT; dependencies retain their licenses.
