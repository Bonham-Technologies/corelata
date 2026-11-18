# M6 follow-ups

## Divergences from Coglossa

- None: M6 adds no copied module. The bench is Corelata's own (Coglossa's bench scores
  translations with FLORES; the shapes differ).

## Spec deviations

- §13: scenario files moved into the package (`corelata/bench/scenarios/`) so `corelata bench`
  works in the image; recorded in the spec.
- §6.8 / §14: recorded in the spec (flags, exit codes, the manual half of the exit test).
- §4.4 says the profiler "reads example reports"; the implementation also shows it the base
  pack's rule ids, template and lexicon so it proposes only valid overrides.
- `profile extract` defaults its example budget to
  `min(pipeline.writer_unit_budget_tokens, profiler context_window // 2)` so a small-context
  model is not overrun; `--budget-tokens` overrides it.
- `DraftRuleOverride.severity` is a `Literal` rather than the `Severity` enum, because importing
  `corelata.standards.schema` from `corelata.schema` makes an import cycle (ruling R-M6-1).

## Should fix soon

- `profile extract` cuts each report to an even share of the token budget; a team whose
  reports differ greatly in length loses the tail of the long ones. A per-report budget flag or
  a digest pass (as the pipeline does for long sources) would help. — **closed in M7** (BORG-43)
- The profiler proposes `severity` overrides only; `checkability`, `route_to` and added rules
  are left to the reviewer by design (a model inventing rules is worse than none).
- `bench` runs scenarios one at a time; a `--concurrency` flag would speed up a server with
  spare capacity (the backend's `max_concurrency` already bounds load). — **closed in M7** (BORG-42)
- `bench` traces are written with `store_llm_io` off to keep them small; a `--store-io` flag
  would help when diagnosing a disagreement. — **closed in M7** (BORG-42)
- The web app's profile select shows drafts like any profile (M4b); the API's `GET /packs`
  carries `draft`, so the select could mark or hide them. — **already done in M4b**: the select disables drafts and labels them "(draft)"
- `deploy/tests/check-app-image.sh` checks one shipped scenario file; the air-gap test does not
  run `corelata bench` (it would add minutes against the fake model for little proof).
- `Rate.ratio` is a computed field, so it is absent from the exported validation-mode
  `schema/bench-report.schema.json`; a consumer of the schema does not see it. — **closed in M7** (BORG-42)
- The bench text table's header reads as one merged "agree outcome" label instead of two
  columns. — **closed in M7** (BORG-42)

- `bench` writes no partial `bench.json` on Ctrl-C; an interrupted bench loses its report. — **closed in M7** (BORG-42)
- `profile extract` does not warn when `--name` collides with a profile already in the extends
  chain (the loader lets a later file shadow an earlier one). — **closed in M7** (BORG-43)

## Later

- ~~Scenarios written for real models (today's ten pin the synthetic responder's markers).~~ — CRL-28
- `corelata pack diff` (§6.8) — **closed in M7** (BORG-36).
