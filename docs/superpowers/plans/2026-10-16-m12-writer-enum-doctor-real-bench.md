# M12 Writer Evidence Enum, Doctor Probes, Real-Model Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-29, CRL-27 and CRL-28, all found in the CRL-1 deployment rehearsal on 2026-10-16 (local Ollama `phi4-mini`, then OpenRouter `gpt-4.1-mini` and `gemini-2.5-flash`). (1) The writer's and conveyor's JSON schema restricts `Claim.evidence` to the run's unit ids, so a `json_schema` server cannot let a model cite `src1` as a unit (CRL-29); the auditor's id enums are hoisted into one `$def` each. (2) `corelata doctor` prints a model count instead of 468 ids, says whether each configured model is served, and probes structured output with the real `GateVerdict` schema through the request builder the stages use, so it fails exactly when a run would (CRL-27). (3) `corelata bench --scenarios real` plays eight scenarios written for real models, with expectations stated as ranges and rule sets; the table shows the gate's verdict and a degraded audit scores as "no audit ran" (CRL-28).

**Architecture:** Engine only. A new `stages/report_schema.py` builds a per-call `ReportBody` subclass (same name, fields and descriptions) whose `Claim.evidence` items are a dynamic `StrEnum` `UnitRef` of `ctx.index.refs()`; `run_writer` and `run_conveyor` send it and convert the reply back to the canonical `ReportBody` before the existing validators run. `audit_schema.enum_list` is the shared builder (one enum in `$defs`, plain strings above `ENUM_LIMIT`, `maxItems: 0` when empty), and the auditor's `cited_units` / `claim_ids` use it too. `llm/agent.py` gains `request_messages` and `build_request`, which `AgentRunner.run` and the doctor's probe both call. `scenarios.ScenarioExpect` gains range and set fields, `scenarios.audited_iterations` recognises a degraded audit, `bench/score.py` scores both forms, `bench/schema.RunResult` keeps the gate verdict (the one exported-schema change: `schema/bench-report.schema.json`, Task 5), and `bench/text.py` prints a gate column. A second scenario directory `bench/scenarios-real/` ships in the wheel; `--scenarios` takes `synthetic`, `real` or a path.

**Tech Stack:** Python 3.12, pydantic 2.14 (`create_model` with `__base__`, functional `StrEnum`), httpx (`MockTransport`), PyYAML; Markdown docs. No web or API change.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §4.4 (roles), §7.3 (routing), §7.4 (context budgets: digested sources, the writer's units), §7.5 (error handling and the M11 degradation), §8.1 (report schema: "every `evidence` unit id exists among the run's units"), §8.4 (trace invariants), §10.2 (CLI, `doctor`), §13 (synthetic responder, scenario fixtures, `corelata bench`). Ticket texts are Jira CRL-27, CRL-28, CRL-29.

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`.
- **No new API route and no API response-model change** (R-M12-7). `api/tests/test_openapi.py::test_every_screen_has_its_routes` lists exactly 22 paths and stays as it is. `RunResult.gate` (Task 5) changes `BenchReport`, which `make schema` exports as `schema/bench-report.schema.json` (not part of the OpenAPI document; nothing in `web/` reads it), so `make schema` runs once, in Task 5, and that task commits the file it rewrites. `schema/openapi.json`, `web/src/api/schema.d.ts` and every other `schema/*.json` must come out unchanged; `test_committed_schema_matches_models`, `test_committed_openapi_matches_the_app` and the `web` CI job enforce it. No other task changes an exported model (`ScenarioExpect` is not exported).
- The trace format does not change (R-M12-1): the writer's and conveyor's replies are converted to the canonical `ReportBody` (`to_report_body`) before validation and storage, so `RunRecord.drafts`, `report.json`, every export and the API read what they read at a625e18. `bench.json` gains `scenarios[].runs[].gate` (default `null`, so an older `bench.json` still loads).
- `api/tests/test_reports.py::test_re_render_failures` monkeypatches `reports._render`; that name stays.
- Web tests mock every request with msw (`web/src/test/setup.ts` fails an unmocked one); poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts`. A loading state is held open by a deferred msw response the test resolves (`web/src/test/deferred.ts`), never by a real delay. (M12 changes nothing in `web/`.)
- Commit messages end with the two attribution lines the session uses; write them to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12, R-M10-1 to R-M10-10 and R-M11-1 to R-M11-8 (`docs/superpowers/plans/2026-10-15-m9-efficiency-and-review-state.md`, `docs/m9-followups.md`, `docs/superpowers/plans/2026-10-15-m10-review-column-pack-index-cache-budget.md`, `docs/m10-followups.md`, `docs/superpowers/plans/2026-10-16-m11-audit-robustness.md`, `docs/m11-followups.md`) stay in force.
  - **R-M12-1 (CRL-29, writer/conveyor schema).** New module `engine/corelata/stages/report_schema.py` with `report_output_type(unit_refs: Sequence[str]) -> type[BaseModel]` and `to_report_body(obj) -> ReportBody`. The per-call type is a `ReportBody` variant (same field names and descriptions; schema name sent to the server stays `ReportBody`) whose `Claim.evidence` is `list[Literal[<unit refs>]]` when `0 < len(unit_refs) <= ENUM_LIMIT` (reuse `audit_schema.ENUM_LIMIT`, 200), `list[str]` above the limit, and a list with `maxItems: 0` when there are no refs (same rule as R-M11-8). "The unit refs" are exactly the refs `StageContext.check_refs` would accept for that call (read `context.py` to name them precisely). Both `run_writer` and `run_conveyor` send it and convert back with `to_report_body` before validation, so `ReportBody`, the trace, exports and the API do not change. `report_validator` and `conveyor_validator` stay as the backstop. The per-call `Claim`/`Section`/whatever models the variant needs are built once per call; keep `$defs` small (one enum def, hoisted, not repeated per field: this is also the M11 follow-up "The unit-ref enum is emitted twice; hoist it into one $def"; apply the same hoisting to `audit_schema.py` in this milestone).
  - **R-M12-2 (CRL-27, doctor backend check).** `_backend` prints `serves N models` plus, per configured model on that backend, `found` or `missing`, e.g. `serves 468 models; writer-model → openai/gpt-4.1-mini found; auditor-model → google/gemini-2.5-flash found`. The full served list is never printed. The `model <key>` FAIL fix line for a missing model names at most 5 served ids that share the configured name's prefix (before the first `/` or `:`), else `see the server's model list`.
  - **R-M12-3 (CRL-27, doctor structured-output probe).** `_structured` sends the real `GateVerdict` schema through the same code path the stages use (`llm/agent.py`'s request builder, so `strict_json_schema` is applied exactly as in a run), with a two-line system prompt asking for a verdict on a one-sentence statement and one-sentence source, `max_tokens` enough for a GateVerdict (read the model to size it), and passes only if the reply parses as `GateVerdict`. The PING probe stays for the plain "test completion" step. The message on pass: `json_schema output works (GateVerdict)`. On a provider schema rejection the FAIL message carries the server's error text, cut to 200 chars, and the fix stays "set models.<key>.structured_output to json_object or none".
  - **R-M12-4 (CRL-28, real-model scenario set).** A second directory `engine/corelata/bench/scenarios-real/` with 8 scenarios: genuine short source texts (2–3 paragraphs each, with dates, named actors and numbers; invented but plausible, no real persons), value statements the sources support, and expectations in the new range form. `corelata bench --scenarios` accepts a directory path as today **and** the names `synthetic` and `real` (resolving to the two shipped sets); default stays `synthetic`. CI runs only the synthetic set (unchanged). Each real scenario's description says what a good model should do and what a weak one typically does.
  - **R-M12-5 (CRL-28, range expectations).** `Expectation` gains optional set/range fields alongside the exact ones: `gate_supported_in: list[bool]`, `substance_in: list[Substance]`, `status_in: list[ReportStatus]`, `state_in: list[RunState]`, `iterations_max: int`, `rules_must_pass: list[str]` (never FAIL in the final audited iteration), `rules_may_fail: list[str]` (FAIL tolerated; anything else failing is a mismatch), `rules_must_fail: list[str]` (at least once). An exact field and its `_in` counterpart cannot both be set (validation error naming both). `compare` and `score_run` honour both forms; `RuleTally` counts `rules_must_fail` as expected. A degraded iteration (`metadata.degradations` non-empty, or an iteration whose only findings are engine-only) is recognised as "no audit ran" in both `scenarios.compare` and `bench/score.py` (closes the m11-followups "treat an iteration as audited when any finding carries it" item).
  - **R-M12-6 (CRL-28, bench table).** `format_bench` adds a `gate` column with `supported/rejected · <substance>` and, on disagreement, the gate's first reason cut to 60 chars, and prints the model ids under the header. `bench.json` gains `gate: {supported, substance, reasons}` per run (`RunResult`); `BenchReport` is otherwise unchanged. Exit codes unchanged.
  - **R-M12-7 (scope).** Nothing else from `docs/m11-followups.md` moves except the three named here (writer enum, hoisted `$def`, degraded-iteration scoring). No change to prompts' versions unless the writer prompt must mention that evidence refs are an enumerated set (if so, bump `writer` to v2 and update `tests/prompts/test_library.py`; decide by reading the v1 writer prompt, and say which you chose). No API/web changes.
  - How the plan applies them (from reading the code at a625e18):
    - R-M12-1: `check_refs` accepts `self.index.has(r)`, so "the unit refs" are `ctx.index.refs()`: every unit of every source, digested or not (the writer sees a digested source through its digest's `unit_refs` and may cite them), in index order. The enum is a functional `StrEnum` named `UnitRef` rather than a `Literal`, because pydantic emits an Enum once in `$defs` and every field that uses it as a `$ref` (a `Literal` is inlined per field); the per-call `Claim` and `ReportBody` are `create_model(..., __base__=Claim/ReportBody, __doc__=...)` subclasses, so the field order, descriptions, the class docstring and `ReportBody`'s claim-id validator carry over unchanged and the only schema difference from `ReportBody.model_json_schema()` is `Claim.evidence.items` plus the `UnitRef` def (pinned by a test). The shared builder is `audit_schema.enum_list`, which reads `ENUM_LIMIT` at call time (the M11 backstop tests lower it with `monkeypatch`). The auditor's `cited_units` and `claim_ids` become `UnitRef` and `ClaimId` defs shared by `VerifiableFinding` and `AdvisoryFinding`. Parsed values are enum members, so both conversions use `model_dump(mode="json")`. A hoisted enum fails with pydantic error type `enum`, not `literal_error`, so `agent._describe` collapses both (R-M11-7 keeps working for long enums). **Writer prompt: no bump.** `writer/v1.j2` already says the units each carry a "ref" and that `evidence` is "the refs that support it"; the enum enforces what v1 asks, and a `json_object`/`none` server sees the enum in the schema appended to the system prompt. `tests/prompts/test_library.py` is unchanged.
    - R-M12-2: the count is pluralised (`serves 1 model`); the arrow is U+2192; a served id "shares the prefix" when its own prefix (before its first `/` or `:`) equals the configured name's, so `phi4-mini` suggests `phi4-mini:3.8b` and `openai/gpt-4.1-mni` suggests `openai/…` ids; suggestions are deduplicated and sorted. The fix reads `set models.<key>.name to a served id, such as: a, b` or `set models.<key>.name to a served id; see the server's model list`.
    - R-M12-3: `llm/agent.py` has no separate builder at a625e18 (the `ChatRequest` is built inline in `AgentRunner.run`), so Task 3 extracts `request_messages` and `build_request` and `run` calls them; `OpenAICompatBackend._payload` applies `strict_json_schema` to every `json_schema` request, so the probe and a run send the same schema. The probe's input is gate-shaped (`task: "gate"`, one unit), so the synthetic responder (the fake server, the demo stack) answers it. `max_tokens` is the model's `max_output_tokens` when set (as in a run), else 512: a `GateVerdict` is a flag, an enum word, a few one-sentence reasons and refs, about 150 tokens, and 512 leaves room for a verbose or reasoning model. A reply cut at `max_tokens` FAILs with a fix to raise `max_output_tokens` (the schema fix would be wrong there). A JSON reply that is not a `GateVerdict` FAILs naming the first pydantic error.
    - R-M12-5: the class is `scenarios.ScenarioExpect` (the brief's "Expectation"). `state` becomes optional and exactly one of `state`/`state_in` is required. `iterations_max` is the counterpart of `iterations`; `failing_rules` (exact, per iteration) and the `rules_*` sets cannot be mixed. `rules_may_fail` is `list[str] | None`: `None` (the default) leaves rules outside the sets unconstrained, a list (even empty) makes any other failure in the final audited iteration a mismatch. A rule in both `rules_must_pass` and `rules_may_fail` is a validation error; a rule in both `rules_must_pass` and `rules_must_fail` means "fails at least once, passes at the end". `status_in` is read only when the run delivered a report (a gate-rejected run has no status). "Degraded" reads `metadata.degradations` lines that start with `audit incomplete` (they mark the run's last iteration, `record.iterations`); a `conveyance skipped` line does not, because that iteration's audit ran. "Engine-only" means every finding of that iteration has evidence starting with `stages.audit.ENGINE_CHECK` (`"engine check: "`). With no audited iteration, a completed run disagrees ("rules: no audit ran") and a run that ended earlier (gate rejected, failed) leaves the rule sets unscored (`rules_agree` is `None`; its state is scored).
    - R-M12-6: the column reads `supported · <substance>` when `gate.supported` and `rejected · <substance>` otherwise, `-` with no verdict; the cut reason goes at the end of the row so the columns stay aligned. "Prints the model ids under the header": the single `models: gate=… writer=…` line becomes a `models:` line followed by one line per model id with the roles it serves (OpenRouter ids are long and four roles usually share two models).
    - R-M12-4: the eight scenarios use invented places and organisations (Tarvos, Kelmar, Dorran, Calvadia; Calrail Cargo, Halden Line) and no persons. Their names are disjoint from the synthetic set's, so one `--out` directory can hold both. A real scenario that may end `gate_rejected` still states the rules a delivered report must pass.

## Review Focus

1. **A `json_schema` server must not let the writer or the conveyor cite a source id (`src1`) or an invented ref as a unit, and every unit the validator accepts, a digested source's included, must stay citable.** Pinned in Task 2 (`test_a_source_id_or_an_invented_ref_is_not_a_unit`, `test_the_writer_schema_rejects_a_source_id_cited_as_a_unit`, `test_run_writer_enumerates_every_indexed_unit_including_digested_sources`).
2. **The drafts the trace stores must still be the canonical `ReportBody` with plain-string refs, so exports, the API and the conveyor's evidence comparison see what they saw before.** Pinned in Task 2 (`test_to_report_body_returns_the_canonical_model_with_plain_strings`, `test_run_conveyor_sends_the_unit_enum_and_returns_a_report_body`).
3. **Against a server that enforces OpenAI strict mode, `doctor`'s structured probe must fail exactly when a gate call through the same backend fails, and carry the server's error.** Pinned in Task 3 (`test_against_a_strict_server_the_probe_passes_exactly_when_a_gate_call_does`).
4. **A server that lists hundreds of models must produce one short backend line, and a mistyped model id must get a short fix that helps.** Pinned in Task 3 (`test_the_backend_check_counts_the_served_models_and_names_only_the_configured`, `test_a_missing_model_suggests_at_most_five_served_ids_with_its_prefix`).
5. **A run whose audit degraded must score as "no audit ran", never as rule hits or rule disagreements, while an iteration whose conveyance was skipped still counts as audited.** Pinned in Task 4 (`test_a_degraded_audit_counts_as_no_audit_ran`, `test_audited_iterations_read_only_audit_incomplete_degradations`, `test_a_degraded_audit_scores_as_missed_not_hit`).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/stages/audit_schema.py` | `enum_list` (shared, hoisted enum); the audit schema uses it. |
| `engine/corelata/stages/report_schema.py` (new) | `report_output_type`, `to_report_body`. |
| `engine/corelata/stages/write.py`, `stages/convey.py` | send the per-call type, convert back. |
| `engine/corelata/stages/audit.py` | `ENGINE_CHECK` constant. |
| `engine/corelata/pipeline.py` | `AUDIT_INCOMPLETE` constant. |
| `engine/corelata/llm/agent.py` | `request_messages`, `build_request`; `_describe` collapses `enum` errors. |
| `engine/corelata/doctor.py` | the backend count, the missing-model fix, the GateVerdict probe. |
| `engine/corelata/scenarios.py` | range and set expectations, `audited_iterations`, `failed_rules`, `meets`. |
| `engine/corelata/bench/__init__.py` | `REAL_SCENARIOS_DIR`, `SCENARIO_SETS`, `scenarios_path`. |
| `engine/corelata/bench/schema.py`, `bench/score.py`, `bench/text.py` | `GateResult`, scoring both forms, the gate column and model lines. |
| `engine/corelata/bench/scenarios-real/*.yaml` (new, 8) | the real-model set. |
| `engine/corelata/cli.py`, `engine/pyproject.toml`, `deploy/tests/check-app-image.sh` | `--scenarios synthetic|real|DIR`; ship the set. |
| `schema/bench-report.schema.json` | regenerated by `make schema` (Task 5). |
| tests: `engine/tests/stages/{test_audit_schema,test_audit,test_report_schema (new),test_write,test_convey}.py`, `engine/tests/llm/{test_agent,test_schema}.py`, `engine/tests/test_doctor.py`, `engine/tests/test_scenarios.py`, `engine/tests/bench/{test_score,test_text,test_package_data}.py`, `engine/tests/test_cli_bench.py` | the tickets' tests. |
| `README.md`, spec, `docs/operator-guide.md`, `docs/m11-followups.md`, `docs/m7-followups.md`, `docs/m12-followups.md` (new) | docs. |

Order: Task 2 needs Task 1's `enum_list`; Task 5 edits the `score.py` Task 4 writes; Task 6's YAML needs Task 4's fields and its CLI test reads Task 5's `gate`. Task 3 is independent.

---

### Task 1: One enum per id list in the audit schema (M11 follow-up, groundwork for CRL-29)

`audit_output_type` builds `cited_units` and `claim_ids` as `list[Literal[...]]`, and pydantic inlines a `Literal` into every field that uses it, so the unit refs appear once in `VerifiableFinding` and again in `AdvisoryFinding`. A functional `StrEnum` is emitted once in `$defs` and referenced. The same builder serves the writer's schema in Task 2.

**Files:**
- Modify: `engine/corelata/stages/audit_schema.py` (whole file), `engine/corelata/llm/agent.py` (`_describe`, lines 233-241)
- Test: `engine/tests/stages/test_audit_schema.py` (imports lines 1-8; `test_cited_units_and_claim_ids_are_enumerated_up_to_the_limit` lines 50-62; after line 93), `engine/tests/stages/test_audit.py` (lines 70-73), `engine/tests/llm/test_schema.py` (lines 66-67), `engine/tests/llm/test_agent.py` (append)

**Interfaces:**
- Produces: `audit_schema.enum_list(name: str, values: Sequence[str], *, description: str | None = None) -> tuple[Any, Any]` (a `create_model` field definition: `(list[<StrEnum name>] | list[str], FieldInfo)`); `audit_schema.ENUM_LIMIT = 200` (unchanged, read at call time). The audit schema's `$defs` gain `UnitRef` and `ClaimId`; `audit_output_type` and `to_audit_output` keep their signatures. `agent._describe` collapses `literal_error` and `enum` errors alike.

- [ ] **Step 1: Failing tests**

In `engine/tests/stages/test_audit_schema.py`, replace the imports (lines 1-8) with:

```python
import json
from enum import StrEnum

import pytest
from pydantic import ValidationError

from corelata.schema import AuditOutput, Verdict
from corelata.stages import audit_schema
from corelata.stages.audit_schema import ENUM_LIMIT, audit_output_type, enum_list, to_audit_output
from corelata.standards.schema import Checkability
```

Replace `test_cited_units_and_claim_ids_are_enumerated_up_to_the_limit` (lines 50-62) with:

```python
def test_cited_units_and_claim_ids_are_one_enum_each_up_to_the_limit(pack):
    def shape(refs, claims):
        defs = audit_output_type(pack, refs, claims).model_json_schema()["$defs"]
        return (
            defs,
            defs["VerifiableFinding"]["properties"],
            defs["AdvisoryFinding"]["properties"],
        )

    defs, verifiable, advisory = shape(REFS, CLAIMS)
    for props in (verifiable, advisory):  # both finding models point at the same two defs
        assert props["cited_units"]["items"] == {"$ref": "#/$defs/UnitRef"}
        assert props["claim_ids"]["items"] == {"$ref": "#/$defs/ClaimId"}
    assert defs["UnitRef"] == {"enum": REFS, "title": "UnitRef", "type": "string"}
    assert defs["ClaimId"] == {"enum": CLAIMS, "title": "ClaimId", "type": "string"}
    assert json.dumps(defs).count('"src1/u2"') == 1  # emitted once, not once per finding model
    many = [f"src1/u{i}" for i in range(1, ENUM_LIMIT + 2)]
    defs, _, _ = shape(many[:ENUM_LIMIT], CLAIMS)
    assert len(defs["UnitRef"]["enum"]) == ENUM_LIMIT
    defs, verifiable, _ = shape(many, [])  # too many refs; no claims
    assert verifiable["cited_units"]["items"] == {"type": "string"} and "UnitRef" not in defs
    assert verifiable["claim_ids"]["maxItems"] == 0 and "ClaimId" not in defs


def test_enum_list_reads_the_limit_when_called(monkeypatch):
    item, field = enum_list("UnitRef", REFS, description="d")
    assert field.description == "d" and issubclass(item.__args__[0], StrEnum)
    assert [m.value for m in item.__args__[0]] == REFS
    monkeypatch.setattr(audit_schema, "ENUM_LIMIT", 0)
    assert enum_list("UnitRef", REFS)[0] == list[str]
```

In `test_a_reply_keyed_by_rule_id_converts_to_audit_output_in_pack_order`, after line 93 (`assert (head.cited_units, head.claim_ids, head.recommendation) == (["src1/u2"], ["c1"], "r")`), add:

```python
    assert type(head.cited_units[0]) is str and type(head.claim_ids[0]) is str  # not enum members
```

In `engine/tests/stages/test_audit.py`, replace lines 70-73:

```python
    cited = sorted({r for c in draft.claims for r in c.evidence})
    assert defs["VerifiableFinding"]["properties"]["cited_units"]["items"]["enum"] == cited
    claim_ids = defs["VerifiableFinding"]["properties"]["claim_ids"]["items"]["enum"]
    assert claim_ids == [c.id for c in draft.claims]
```

with:

```python
    cited = sorted({r for c in draft.claims for r in c.evidence})
    assert defs["UnitRef"]["enum"] == cited
    assert defs["ClaimId"]["enum"] == [c.id for c in draft.claims]
    cited_units = defs["VerifiableFinding"]["properties"]["cited_units"]
    assert cited_units["items"] == {"$ref": "#/$defs/UnitRef"}
```

In `engine/tests/llm/test_schema.py`, replace lines 66-67:

```python
    cited_full = strict["$defs"]["VerifiableFinding"]["properties"]["cited_units"]
    assert cited_full["items"]["enum"] == REFS
```

with:

```python
    assert strict["$defs"]["UnitRef"] == {"enum": REFS, "title": "UnitRef", "type": "string"}
    cited_full = strict["$defs"]["VerifiableFinding"]["properties"]["cited_units"]
    assert cited_full["items"] == {"$ref": "#/$defs/UnitRef"}
```

Append to `engine/tests/llm/test_agent.py`:

```python
def test_a_long_str_enum_error_is_collapsed_like_a_literal():
    from enum import StrEnum

    from corelata.llm.agent import _parse

    Ref = StrEnum("Ref", [(f"v{i}", f"src1/u{i}") for i in range(50)])

    class Cite(BaseModel):
        refs: list[Ref]

    _, errors = _parse('{"refs": ["src1"]}', Cite, None)
    assert errors == [
        "refs.0: use one of the values given in the input (such as 'src1/u0', 'src1/u1', 'src1/u2')"
    ]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/stages/test_audit_schema.py tests/stages/test_audit.py tests/llm/test_schema.py tests/llm/test_agent.py --no-cov -q`
Expected: `test_audit_schema.py` fails to import `enum_list`; `test_run_auditor_sends_the_by_rule_schema_and_returns_the_same_outcome` and `test_defs_refs_enums_and_max_items_are_preserved` fail with `KeyError: 'UnitRef'`; `test_a_long_str_enum_error_is_collapsed_like_a_literal` fails because the `enum` error is listed in full.

- [ ] **Step 3: The shared enum builder**

Replace `engine/corelata/stages/audit_schema.py` with:

```python
"""The auditor's output schema, built per call (R-M11-1): `findings` is an object with one
required property per rule id, each allowing only the verdicts its checkability permits and,
while the lists are short enough to enumerate, only the unit refs and claim ids in scope. A
server configured `json_schema` enforces it while generating, so an advisory rule cannot be
passed, an invented rule id means nothing and a source id cannot be cited as a unit.
Pydantic parsing enforces the shape on every server (required rule keys, verdict literals);
`audit_validator` stays as the backstop on the converted output, adding the unit-ref check and
defending the `AuditOutput` contract.

The unit refs and the claim ids are each one `StrEnum` in `$defs` that every field citing them
refers to (R-M12-1). `enum_list` builds those fields; the writer's schema (`report_schema.py`)
uses it too."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from corelata.schema import AuditOutput, FindingOut, Verdict
from corelata.standards.schema import Checkability, ResolvedPack

# Above this many refs or claim ids the lists stay plain strings: an enum that long slows
# constrained decoding more than it helps, and the validator still checks every ref.
ENUM_LIMIT = 200

_VERDICTS = {
    Checkability.VERIFIABLE: (Verdict.PASS.value, Verdict.FAIL.value, Verdict.NOT_APPLICABLE.value),
    Checkability.ADVISORY: (Verdict.ATTESTED.value, Verdict.NOT_APPLICABLE.value),
}
_NAMES = {Checkability.VERIFIABLE: "VerifiableFinding", Checkability.ADVISORY: "AdvisoryFinding"}


def enum_list(
    name: str, values: Sequence[str], *, description: str | None = None
) -> tuple[Any, Any]:
    """A `create_model` field definition for a list of `values`. Up to ENUM_LIMIT values the
    items are a `StrEnum` called `name`, which the JSON schema emits once in `$defs` however many
    fields use it; above the limit they are plain strings; with no values the list must be empty
    (R-M11-8). ENUM_LIMIT is read on every call, so a test can lower it."""
    if not values:
        return (list[str], Field(default_factory=list, max_length=0, description=description))
    if len(values) > ENUM_LIMIT:
        return (list[str], Field(default_factory=list, description=description))
    item = StrEnum(name, [(f"v{i}", value) for i, value in enumerate(values)])
    return (list[item], Field(default_factory=list, description=description))


def _finding_model(kind: Checkability, unit: Any, claim: Any) -> type[BaseModel]:
    """`unit` and `claim` are `enum_list` fields, shared by both finding models."""
    return create_model(
        _NAMES[kind],
        verdict=(Literal[_VERDICTS[kind]], ...),
        evidence=(str, ...),
        cited_units=unit,
        claim_ids=claim,
        recommendation=(str, ""),
    )


def audit_output_type(
    pack: ResolvedPack, unit_refs: list[str], claim_ids: list[str]
) -> type[BaseModel]:
    unit, claim = enum_list("UnitRef", unit_refs), enum_list("ClaimId", claim_ids)
    models = {kind: _finding_model(kind, unit, claim) for kind in Checkability}
    fields: dict[str, Any] = {
        f"r{i}": (models[r.checkability], Field(alias=r.id)) for i, r in enumerate(pack.rules)
    }
    findings = create_model(
        "AuditFindings",
        __config__=ConfigDict(
            populate_by_name=True, json_schema_extra={"additionalProperties": False}
        ),
        **fields,
    )
    return create_model("AuditByRule", findings=(findings, ...), summary=(str, ...))


def to_audit_output(parsed: BaseModel, pack: ResolvedPack) -> AuditOutput:
    """The list form everything downstream reads: one `FindingOut` per rule, in pack order, with
    plain-string refs and claim ids (`mode="json"` turns the enum members into their values)."""
    by_rule = parsed.findings  # an AuditFindings built by audit_output_type for this pack
    return AuditOutput(
        findings=[
            FindingOut(rule_id=r.id, **getattr(by_rule, f"r{i}").model_dump(mode="json"))
            for i, r in enumerate(pack.rules)
        ],
        summary=parsed.summary,
    )
```

- [ ] **Step 4: Collapse a long `enum` error like a long `Literal`**

In `engine/corelata/llm/agent.py`, replace `_describe` (lines 233-241) with:

```python
def _describe(err: Any) -> str:
    """One pydantic error as a repair line; a long enum is never listed in full (R-M11-7),
    whether it is a `Literal` (`literal_error`) or a hoisted `StrEnum` (`enum`, R-M12-1)."""
    where = ".".join(str(p) for p in err["loc"]) or "<root>"
    if err["type"] in ("literal_error", "enum"):
        values = re.findall(r"'([^']*)'", err["ctx"]["expected"])
        if len(values) > MAX_LISTED_VALUES:
            some = ", ".join(f"'{v}'" for v in values[:3])
            return f"{where}: use one of the values given in the input (such as {some})"
    return f"{where}: {err['msg']}"
```

- [ ] **Step 5: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/stages tests/llm tests/testing tests/test_pipeline.py --no-cov -q`
Expected: PASS (the backstop test `test_the_backstop_validator_still_checks_unit_refs` still lowers `ENUM_LIMIT` to 0 and still passes, because `enum_list` reads it at call time).

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m12-task1-commit.txt <<'EOF'
refactor: one $def per id enum in the audit schema (M11 follow-up)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/stages/audit_schema.py engine/corelata/llm/agent.py engine/tests/stages/test_audit_schema.py engine/tests/stages/test_audit.py engine/tests/llm/test_schema.py engine/tests/llm/test_agent.py
git commit -F <scratchpad>/m12-task1-commit.txt
```

---

### Task 2: The writer's and conveyor's schema enumerates the unit ids (CRL-29)

`run_writer` and `run_conveyor` send `ReportBody.model_json_schema()`, whose `Claim.evidence` is any list of strings, so only the validator catches `src1` cited as a unit, after the model has spent its first attempt. The per-call variant makes it ungeneratable on a `json_schema` server; the validators stay for `json_object` and `none` servers and for runs above `ENUM_LIMIT` units.

**Files:**
- Create: `engine/corelata/stages/report_schema.py`, `engine/tests/stages/test_report_schema.py`
- Modify: `engine/corelata/stages/write.py` (imports lines 1-6, `run_writer` lines 77-107), `engine/corelata/stages/convey.py` (imports lines 1-7, `run_conveyor` lines 36-59)
- Test: `engine/tests/stages/test_write.py` (imports lines 1-10; `test_writer_validator_rejects_unknown_ref_then_fails` lines 65-73; append), `engine/tests/stages/test_convey.py` (imports lines 1-7; append), `engine/tests/llm/test_schema.py` (imports line 7; `_schemas` lines 24-29)

**Interfaces:**
- Consumes: `audit_schema.enum_list` (Task 1).
- Produces: `report_schema.report_output_type(unit_refs: Sequence[str]) -> type[ReportBody]` (a subclass named `ReportBody`; `$defs` gain `UnitRef`); `report_schema.to_report_body(parsed: BaseModel) -> ReportBody`. `run_writer` and `run_conveyor` keep their signatures and return exactly `ReportBody`.

- [ ] **Step 1: Failing tests**

Create `engine/tests/stages/test_report_schema.py`:

```python
import json

import pytest
from pydantic import ValidationError

from corelata.schema import ReportBody
from corelata.stages.audit_schema import ENUM_LIMIT
from corelata.stages.report_schema import report_output_type, to_report_body

REFS = ["src1/u1", "src1/u2", "src2/u1"]


def _body(evidence: list[str]) -> dict:
    return {
        "title": "t",
        "handling_marking": "UNCLASSIFIED",
        "key_judgments": [{"text": "k", "confidence": "moderate", "claim_ids": ["c1"]}],
        "scope_note": "s",
        "sources": [{"source_id": "src1", "descriptor": "open-source report"}],
        "analysis": [{"heading": "h", "paragraphs": [{"text": "p", "claim_ids": ["c1"]}]}],
        "alternatives": [],
        "gaps_and_indicators": [],
        "claims": [{"id": "c1", "text": "t", "kind": "fact", "evidence": evidence}],
    }


def test_the_schema_is_report_body_with_one_unit_ref_enum_for_evidence():
    model = report_output_type(REFS)
    assert model.__name__ == "ReportBody"  # the schema name the server sees
    want = ReportBody.model_json_schema()
    want["$defs"]["Claim"]["properties"]["evidence"]["items"] = {"$ref": "#/$defs/UnitRef"}
    want["$defs"]["UnitRef"] = {"enum": REFS, "title": "UnitRef", "type": "string"}
    assert model.model_json_schema() == want  # same fields, order, descriptions; one new def


def test_evidence_is_plain_strings_above_the_limit_and_empty_without_refs():
    many = [f"src1/u{i}" for i in range(1, ENUM_LIMIT + 2)]
    above = report_output_type(many).model_json_schema()
    assert above["$defs"]["Claim"]["properties"]["evidence"]["items"] == {"type": "string"}
    assert "UnitRef" not in above["$defs"]
    at_limit = report_output_type(many[:ENUM_LIMIT]).model_json_schema()
    assert len(at_limit["$defs"]["UnitRef"]["enum"]) == ENUM_LIMIT
    none = report_output_type([])
    claim = none.model_json_schema()["$defs"]["Claim"]["properties"]["evidence"]
    assert claim["maxItems"] == 0
    none.model_validate(_body([]))
    with pytest.raises(ValidationError, match="too_long|at most 0"):
        none.model_validate(_body(["src1/u1"]))


def test_a_source_id_or_an_invented_ref_is_not_a_unit():
    model = report_output_type(REFS)
    for bad in ("src1", "src9/u1"):
        with pytest.raises(ValidationError) as e:
            model.model_validate_json(json.dumps(_body([bad])))
        [err] = e.value.errors()
        assert err["loc"] == ("claims", 0, "evidence", 0) and err["type"] == "enum", bad


def test_to_report_body_returns_the_canonical_model_with_plain_strings():
    parsed = report_output_type(REFS).model_validate_json(json.dumps(_body(["src1/u2"])))
    body = to_report_body(parsed)
    canonical = ReportBody.model_validate(_body(["src1/u2"]))
    assert type(body) is ReportBody and type(body.claims[0]).__name__ == "Claim"
    assert type(body.claims[0]) is type(canonical.claims[0])
    assert type(body.claims[0].evidence[0]) is str
    assert body == canonical and body.model_dump_json() == canonical.model_dump_json()


def test_the_claim_id_validator_still_runs_on_the_per_call_type():
    data = _body(["src1/u1"])
    data["key_judgments"][0]["claim_ids"] = ["c9"]
    with pytest.raises(ValidationError, match="unknown claim id 'c9'"):
        report_output_type(REFS).model_validate(data)
```

In `engine/tests/stages/test_write.py`, replace the imports (lines 1-10) with:

```python
import json
import re

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Finding, FindingOut, ReportBody, Verdict
from corelata.stages import audit_schema
from corelata.stages.write import run_writer, select_writer_units
from corelata.testing.sources import text_source
from corelata.testing.synthetic import synthetic_response
from tests.stages.conftest import PORT
```

Replace `test_writer_validator_rejects_unknown_ref_then_fails` (lines 65-73) with:

```python
async def test_the_writer_schema_rejects_a_source_id_cited_as_a_unit(make_ctx, fake_backend):
    ctx = make_ctx()
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    good["claims"][0]["evidence"] = ["src1"]  # the CRL-1 failure: a source id where a unit goes
    bad = json.dumps(good)
    fake_backend.script("writer", bad, bad)
    expected = "claims.0.evidence.0: Input should be 'src1/u1', 'src1/u2' or 'src1/u3'"
    with pytest.raises(StructuredOutputError, match=re.escape(expected)):
        await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert expected in fake_backend.requests[1].messages[3].content  # the repair turn names them
    assert [r.ok for r in ctx.runner.log.records] == [False, False]


async def test_the_backstop_validator_still_checks_writer_refs(make_ctx, fake_backend, monkeypatch):
    monkeypatch.setattr(audit_schema, "ENUM_LIMIT", 0)  # every ref list is "too long": strings
    ctx = make_ctx()
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    good["claims"][0]["evidence"] = ["src9/u1"]
    bad = json.dumps(good)
    fake_backend.script("writer", bad, bad)
    with pytest.raises(StructuredOutputError, match="'src9/u1' is not a unit id"):
        await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert [r.ok for r in ctx.runner.log.records] == [False, False]
```

Append to `engine/tests/stages/test_write.py`:

```python
async def test_run_writer_enumerates_every_indexed_unit_including_digested_sources(
    make_ctx, make_config, fake_backend
):
    from corelata.stages.digest import run_digests

    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    long = text_source("src2", *[f"Paragraph {i} about Varna port finance." for i in range(40)])
    ctx = make_ctx(text_source("src1", *PORT), long, cfg=cfg)
    ctx.digests = await run_digests(ctx)
    assert "src2" in ctx.digests  # the writer sees src2 only through its digest
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    request = fake_backend.requests[-1]
    assert request.schema_name == "ReportBody"
    enum = request.json_schema["$defs"]["UnitRef"]["enum"]
    assert enum == ctx.index.refs() and "src2/u40" in enum  # what check_refs accepts
    assert type(body) is ReportBody
```

In `engine/tests/stages/test_convey.py`, replace the imports (lines 1-7) with:

```python
import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import ReportBody
from corelata.stages.convey import run_conveyor
from corelata.stages.write import run_writer
```

Append to `engine/tests/stages/test_convey.py`:

```python
async def test_run_conveyor_sends_the_unit_enum_and_returns_a_report_body(make_ctx, fake_backend):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    request = fake_backend.requests[-1]
    assert request.schema_name == "ReportBody"
    assert request.json_schema["$defs"]["UnitRef"]["enum"] == ctx.index.refs()
    assert type(out) is ReportBody and out.claims == draft.claims
    assert all(type(r) is str for c in out.claims for r in c.evidence)
```

In `engine/tests/llm/test_schema.py`, after line 7 (`from corelata.stages.audit_schema import audit_output_type`) add:

```python
from corelata.stages.report_schema import report_output_type
```

and replace `_schemas` (lines 24-29) with:

```python
def _schemas():
    out = [m.model_json_schema() for m in STATIC]
    pack = load_pack("icd203-base")
    out.append(audit_output_type(pack, REFS, ["c0"]).model_json_schema())
    out.append(audit_output_type(pack, [], []).model_json_schema())
    out.append(report_output_type(REFS).model_json_schema())
    out.append(report_output_type([]).model_json_schema())
    return out
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/stages/test_report_schema.py tests/stages/test_write.py tests/stages/test_convey.py tests/llm/test_schema.py --no-cov -q`
Expected: `test_report_schema.py` and `test_schema.py` fail to import `corelata.stages.report_schema`; `test_the_writer_schema_rejects_a_source_id_cited_as_a_unit` fails (the message is the validator's "'src1' is not a unit id"); the two `*_enumerates_*`/`*_sends_the_unit_enum_*` tests fail with `KeyError: '$defs'` or `'UnitRef'`.

- [ ] **Step 3: The per-call report schema**

Create `engine/corelata/stages/report_schema.py`:

```python
"""The writer's and conveyor's output schema, built per call (R-M12-1): `ReportBody` with
`Claim.evidence` restricted to the run's unit ids, so a server configured `json_schema` cannot
let a model cite a source id (`src1`) or an invented ref as a unit. The variant keeps the field
names, order and descriptions and the schema name (`ReportBody`); only the evidence items
differ, as one `UnitRef` enum in `$defs` (plain strings above `audit_schema.ENUM_LIMIT` refs, an
empty list when there are none). The reply is converted back with `to_report_body` before
anything reads it, so the trace, the exports and the API see the canonical `ReportBody`;
`report_validator` and `conveyor_validator` stay as the backstop for `json_object` and `none`
servers."""

from collections.abc import Sequence

from pydantic import BaseModel, create_model

from corelata.schema.report import Claim, ReportBody
from corelata.stages.audit_schema import enum_list


def report_output_type(unit_refs: Sequence[str]) -> type[ReportBody]:
    """`unit_refs` are the refs `StageContext.check_refs` accepts: `ctx.index.refs()`, every
    unit of every source, digested or not. Subclassing keeps `ReportBody`'s claim-id validator."""
    claim = create_model(
        "Claim",
        __base__=Claim,
        __doc__=Claim.__doc__,
        evidence=enum_list(
            "UnitRef", unit_refs, description=Claim.model_fields["evidence"].description
        ),
    )
    return create_model(
        "ReportBody", __base__=ReportBody, __doc__=ReportBody.__doc__, claims=(list[claim], ...)
    )


def to_report_body(parsed: BaseModel) -> ReportBody:
    """The canonical `ReportBody` for a reply parsed with `report_output_type`: plain-string refs
    (`mode="json"` turns the enum members into their values) and the canonical `Claim`."""
    return ReportBody.model_validate(parsed.model_dump(mode="json"))
```

- [ ] **Step 4: The writer sends it**

In `engine/corelata/stages/write.py`, replace the imports (lines 3-6) with:

```python
from collections.abc import Callable

from corelata.schema import Finding, ReportBody
from corelata.stages.context import StageContext, estimate_tokens
from corelata.stages.report_schema import report_output_type, to_report_body
```

Replace `run_writer` (lines 77-107) with:

```python
async def run_writer(
    ctx: StageContext, *, iteration: int, prior: ReportBody | None, findings: list[Finding]
) -> ReportBody:
    check = report_validator(ctx)
    parsed = await ctx.runner.run(
        role="writer",
        model_key=ctx.model_key("writer"),
        prompt_id="writer",
        prompt_vars={
            "tone": ctx.pack.tone,
            "section_order": ctx.pack.template.section_order,
            "iteration": iteration,
            "extra_guidance": ctx.extra_guidance,
        },
        payload={
            "task": "writer",
            "value_statement": ctx.value_statement,
            "template": ctx.pack.template.model_dump(),
            "rules": [r.model_dump() for r in ctx.pack.rules_for("writer")],
            "lexicon": ctx.pack.lexicon.model_dump(),
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(select_writer_units(ctx)),
            "gate_evidence": list(ctx.gate_evidence),
            "sources": ctx.source_payload(),
            "prior_draft": None if prior is None else prior.model_dump(),
            "findings": [f.model_dump() for f in findings],
            "extra_guidance": ctx.extra_guidance,
            "iteration": iteration,
        },
        output_type=report_output_type(ctx.index.refs()),
        validate=lambda body: check(to_report_body(body)),
    )
    return to_report_body(parsed)
```

- [ ] **Step 5: The conveyor sends it**

In `engine/corelata/stages/convey.py`, replace the imports (lines 3-7) with:

```python
from collections.abc import Callable

from corelata.schema import Finding, ReportBody
from corelata.stages.context import StageContext
from corelata.stages.report_schema import report_output_type, to_report_body
from corelata.stages.write import report_validator
```

Replace `run_conveyor` (lines 36-59) with:

```python
async def run_conveyor(
    ctx: StageContext, *, iteration: int, draft: ReportBody, findings: list[Finding]
) -> ReportBody:
    check = conveyor_validator(ctx, draft)
    parsed = await ctx.runner.run(
        role="conveyor",
        model_key=ctx.model_key("conveyor"),
        prompt_id="conveyor",
        prompt_vars={
            "tone": ctx.pack.tone,
            "heading_style": ctx.pack.format.heading_style,
            "findings": [f.model_dump() for f in findings],
        },
        payload={
            "task": "conveyor",
            "draft": draft.model_dump(),
            "template": ctx.pack.template.model_dump(),
            "rules": [r.model_dump() for r in ctx.pack.rules_for("conveyor")],
            "tone": ctx.pack.tone,
            "findings": [f.model_dump() for f in findings],
            "iteration": iteration,
        },
        output_type=report_output_type(ctx.index.refs()),
        validate=lambda body: check(to_report_body(body)),
    )
    return to_report_body(parsed)
```

- [ ] **Step 6: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/stages tests/llm tests/test_pipeline.py tests/test_scenarios.py tests/test_invariants.py tests/test_trace.py --no-cov -q`
Expected: PASS (the synthetic writer cites only refs from `units`, so every synthetic scenario still agrees).

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m12-task2-commit.txt <<'EOF'
feat: writer and conveyor schema enumerates the run's unit ids (CRL-29)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/stages/report_schema.py engine/corelata/stages/write.py engine/corelata/stages/convey.py engine/tests/stages/test_report_schema.py engine/tests/stages/test_write.py engine/tests/stages/test_convey.py engine/tests/llm/test_schema.py
git commit -F <scratchpad>/m12-task2-commit.txt
```

---

### Task 3: `doctor` counts served models and probes the real schema (CRL-27)

Two failures from the rehearsal. The backend check printed all 468 ids OpenRouter lists in one line. The `model <key>` check passed ("json_schema output works") while every real request was rejected with `invalid_json_schema`, because the ping schema has no optional field and so happened to be strict-compatible. The probe now builds its request with the function the stages use.

**Files:**
- Modify: `engine/corelata/llm/agent.py` (import line 18; new functions after `_repair_message`, line 63; `AgentRunner.run` lines 119-153), `engine/corelata/doctor.py` (imports lines 5-28; constants after line 35; `_backend` lines 221-229; `_model` lines 247-280; `_structured` lines 283-303)
- Test: `engine/tests/llm/test_agent.py` (imports lines 1-7; append), `engine/tests/test_doctor.py` (imports lines 1-15; lines 57-59; line 75; append)

**Interfaces:**
- Produces: `agent.request_messages(system: str, payload: dict[str, Any], model: ModelConfig, schema: dict[str, Any]) -> list[ChatMessage]`; `agent.build_request(model_key: str, model: ModelConfig, output_type: type[BaseModel], schema: dict[str, Any], messages: list[ChatMessage], *, max_tokens: int | None = None) -> ChatRequest`. `doctor.PROBE_SYSTEM: str`, `doctor.PROBE_PAYLOAD: dict[str, Any]`, `doctor.PROBE_MAX_TOKENS = 512`, `doctor.ERROR_CHARS = 200`, `doctor.SIMILAR_MAX = 5`. `run_doctor`'s signature is unchanged; `PING_SCHEMA` and `_ping` stay.

- [ ] **Step 1: Failing tests**

In `engine/tests/llm/test_agent.py`, replace the imports (lines 1-7) with:

```python
import json

import pytest
from pydantic import BaseModel

from corelata.config import StructuredOutput
from corelata.llm.agent import (
    StructuredOutputError,
    _repair_message,
    build_request,
    extract_json,
    request_messages,
)
from corelata.llm.payload import render_input
from corelata.llm.types import PermanentBackendError, TransientBackendError
```

Append to `engine/tests/llm/test_agent.py`:

```python
def test_request_messages_spell_out_the_schema_only_when_the_server_does_not_enforce_it(
    make_config,
):
    model = make_config().models["model-a"]  # json_schema by default
    schema = Ping.model_json_schema()
    enforced = request_messages("sys", PAYLOAD, model, schema)
    assert [(m.role, m.content) for m in enforced] == [
        ("system", "sys"),
        ("user", render_input(PAYLOAD)),
    ]
    loose = model.model_copy(update={"structured_output": StructuredOutput.JSON_OBJECT})
    assert request_messages("sys", PAYLOAD, loose, schema)[0].content == (
        "sys\n\nRespond with one JSON object that matches this JSON Schema:\n"
        + json.dumps(schema, ensure_ascii=False)
    )


async def test_run_sends_the_request_build_request_makes(make_runner, fake_backend):
    runner = make_runner()
    await _run(runner)
    sent = fake_backend.requests[0]
    model = runner.cfg.models["model-a"]
    schema = Ping.model_json_schema()
    assert sent == build_request("model-a", model, Ping, schema, sent.messages)
    assert sent.messages == request_messages(sent.messages[0].content, PAYLOAD, model, schema)
    capped = build_request("model-a", model, Ping, schema, sent.messages, max_tokens=7)
    assert (capped.max_tokens, capped.schema_name, capped.json_schema) == (7, "Ping", schema)
```

In `engine/tests/test_doctor.py`, replace the imports (lines 1-15) with:

```python
import json

import httpx
import pytest
import yaml
from sqlalchemy.engine import make_url

from corelata.cli import main
from corelata.config import load_config
from corelata.doctor import (
    ERROR_CHARS,
    PING_SCHEMA,
    PROBE_MAX_TOKENS,
    PROBE_PAYLOAD,
    PROBE_SYSTEM,
    run_doctor,
)
from corelata.llm.agent import AgentRunner, CallLog
from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.payload import parse_input, render_input
from corelata.llm.schema import strict_json_schema
from corelata.llm.types import ChatResponse, PermanentBackendError
from corelata.prompts.library import PromptLibrary
from corelata.schema import CheckStatus, GateVerdict
from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.fake_openai import FakeOpenAIServer
from corelata.testing.postgres import create_test_database, drop_test_database
from corelata.testing.synthetic import chat_completion, synthetic_response
```

In `test_a_healthy_installation`, replace lines 57-59:

```python
    assert "fake-model" in checks["backend local"].message
    assert "icd203-base" in checks["pack"].message
    assert "json_schema output works" in checks["model fake-model"].message
```

with:

```python
    assert checks["backend local"].message == "serves 1 model; fake-model → fake-model found"
    assert "icd203-base" in checks["pack"].message
    assert checks["model fake-model"].message == (
        "test completion succeeded; json_schema output works (GateVerdict)"
    )
```

In `test_model_not_served`, replace line 75 (`assert check.fix == "set models.big.name to one of: fake-model"`) with:

```python
    assert check.fix == "set models.big.name to a served id; see the server's model list"
```

Append to `engine/tests/test_doctor.py`:

```python
ROLES = ("gate", "writer", "conveyor", "auditor")


def _one_model(tmp_path, server, name, **model):
    return _config(
        tmp_path,
        server.base_url,
        models={"m": {"backend": "local", "name": name, "context_window": 4096, **model}},
        roles={r: {"model": "m"} for r in ROLES},
    )


async def test_the_backend_check_counts_the_served_models_and_names_only_the_configured(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    served = [f"vendor{i}/model-{i}" for i in range(466)]
    served += ["openai/gpt-4.1-mini", "google/gemini-2.5-flash"]
    path = _config(
        tmp_path,
        server.base_url,
        models={
            "writer-model": {
                "backend": "local",
                "name": "openai/gpt-4.1-mini",
                "context_window": 4096,
            },
            "auditor-model": {
                "backend": "local",
                "name": "google/gemini-2.5-flash",
                "context_window": 4096,
            },
        },
        roles={
            "gate": {"model": "writer-model"},
            "writer": {"model": "writer-model"},
            "conveyor": {"model": "auditor-model"},
            "auditor": {"model": "auditor-model"},
        },
    )
    report = await run_doctor(
        path, probe=False, backends_factory=lambda cfg: {"local": FakeBackend(models=tuple(served))}
    )
    check = _by_name(report)["backend local"]
    assert check.status is CheckStatus.PASS
    assert check.message == (
        "serves 468 models; auditor-model → google/gemini-2.5-flash found; "
        "writer-model → openai/gpt-4.1-mini found"  # config order (the test's YAML sorts keys)
    )
    assert "vendor" not in check.message  # the served list is never printed


async def test_a_missing_model_suggests_at_most_five_served_ids_with_its_prefix(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    served = (
        "openai/o3",
        "openai/gpt-4.1-mini",
        "openai/gpt-4o",
        "openai/gpt-5",
        "openai/gpt-4.1",
        "openai/o4-mini",
        "google/gemini-2.5-flash",
        "phi4-mini:3.8b",
    )

    async def fix_for(name):
        report = await run_doctor(
            _one_model(tmp_path, server, name),
            probe=False,
            backends_factory=lambda cfg: {"local": FakeBackend(models=served)},
        )
        assert _by_name(report)["backend local"].message == f"serves 8 models; m → {name} missing"
        check = _by_name(report)["model m"]
        assert check.status is CheckStatus.FAIL
        assert check.message == f"'{name}' is not served by backend local"
        return check.fix

    assert await fix_for("openai/gpt-4.1-mni") == (
        "set models.m.name to a served id, such as: openai/gpt-4.1, openai/gpt-4.1-mini, "
        "openai/gpt-4o, openai/gpt-5, openai/o3"
    )
    assert await fix_for("phi4-mini") == "set models.m.name to a served id, such as: phi4-mini:3.8b"
    assert await fix_for("mistral-small") == (
        "set models.m.name to a served id; see the server's model list"
    )


async def test_the_structured_probe_sends_the_gate_verdict_schema_a_run_sends(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    report = await run_doctor(_config(tmp_path, server.base_url))
    assert _by_name(report)["model fake-model"].status is CheckStatus.PASS
    probe = server.requests[-1]  # the ping first, then the structured probe
    response_format = probe["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "GateVerdict"
    assert response_format["json_schema"]["schema"] == strict_json_schema(
        GateVerdict.model_json_schema()
    )
    assert probe["max_tokens"] == PROBE_MAX_TOKENS
    assert [m["content"] for m in probe["messages"]] == [PROBE_SYSTEM, render_input(PROBE_PAYLOAD)]
    assert len(PROBE_SYSTEM.splitlines()) == 2


def _is_strict(node) -> bool:
    """OpenAI's strict subset: every object lists every property as required and forbids extra
    properties, and no node carries a default."""
    if isinstance(node, list):
        return all(_is_strict(n) for n in node)
    if not isinstance(node, dict):
        return True
    if "default" in node:
        return False
    props = node.get("properties")
    if isinstance(props, dict) and (
        node.get("additionalProperties") is not False
        or node.get("required") != list(props)
        or not all(_is_strict(p) for p in props.values())
    ):
        return False
    return all(_is_strict(v) for k, v in node.items() if k != "properties")


def _strict_openai(request: httpx.Request) -> httpx.Response:
    """A server that validates `json_schema` response formats as OpenAI does (CRL-27)."""
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"object": "list", "data": [{"id": "fake-model"}]})
    body = json.loads(request.content)
    response_format = body.get("response_format") or {}
    if response_format.get("type") == "json_schema":
        spec = response_format["json_schema"]
        if not _is_strict(spec["schema"]):
            message = (
                f"Invalid schema for response_format '{spec['name']}': In context=(), "
                "'required' is required to be supplied and to be an array including every key "
                "in properties. " + "Missing a key. " * 30
            )
            error = {"error": {"code": "invalid_json_schema", "message": message}}
            return httpx.Response(400, json=error)
    content = json.dumps(synthetic_response(parse_input(body["messages"])))
    return httpx.Response(200, json=chat_completion(content))


def _strict_backend() -> OpenAICompatBackend:
    return OpenAICompatBackend(
        "local", "http://strict.test/v1", transport=httpx.MockTransport(_strict_openai)
    )


async def test_against_a_strict_server_the_probe_passes_exactly_when_a_gate_call_does(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url)
    cfg, _ = load_config(path)

    async def gate_call() -> GateVerdict:
        backend = _strict_backend()
        runner = AgentRunner(cfg, {"local": backend}, PromptLibrary(), CallLog())
        try:
            return await runner.run(
                role="gate",
                model_key="fake-model",
                prompt_id="gate",
                prompt_vars={"mode": "verify", "tone": ""},
                payload=PROBE_PAYLOAD,
                output_type=GateVerdict,
            )
        finally:
            await backend.aclose()

    def doctor():
        return run_doctor(path, backends_factory=lambda c: {"local": _strict_backend()})

    assert isinstance(await gate_call(), GateVerdict)
    check = _by_name(await doctor())["model fake-model"]
    assert check.status is CheckStatus.PASS, check

    # CRL-27: when the stages sent a schema the server rejects, the ping probe still passed
    # (its schema has no optional field); the GateVerdict probe fails together with the run.
    monkeypatch.setattr("corelata.llm.openai_compat.strict_json_schema", lambda schema: schema)
    assert _is_strict(PING_SCHEMA)
    with pytest.raises(PermanentBackendError, match="invalid_json_schema"):
        await gate_call()
    check = _by_name(await doctor())["model fake-model"]
    assert check.status is CheckStatus.FAIL
    head = "test completion succeeded; json_schema request failed: "
    assert check.message.startswith(head + "local: HTTP 400: ")
    assert "invalid_json_schema" in check.message and check.message.endswith("…")
    assert len(check.message) == len(head) + ERROR_CHARS  # the server's text, cut to 200
    assert check.fix == "set models.fake-model.structured_output to json_object or none"


async def test_json_that_is_not_a_gate_verdict_fails_the_probe(tmp_path, server):
    class OkOnly(FakeBackend):
        async def chat(self, request):
            self.requests.append(request)
            return ChatResponse(content='{"ok": true}')

    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": OkOnly()}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL
    assert check.message.endswith(
        "the server did not return the requested JSON (json_schema): "
        "not a GateVerdict: supported: Field required"
    )
    assert check.fix == "set models.fake-model.structured_output to json_object or none"


async def test_a_probe_cut_at_max_tokens_says_to_raise_the_limit(tmp_path, server):
    path = _config(
        tmp_path,
        server.base_url,
        models={"fake-model": {"backend": "local", "context_window": 4096, "max_output_tokens": 1}},
    )
    check = _by_name(await run_doctor(path))["model fake-model"]  # the fake cuts max_tokens=1
    assert check.status is CheckStatus.FAIL
    assert check.message == (
        "test completion succeeded; the GateVerdict reply was cut at max_tokens=1"
    )
    assert check.fix == (
        "set models.fake-model.max_output_tokens above 1: a reasoning model spends output "
        "tokens before it answers"
    )
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/llm/test_agent.py tests/test_doctor.py --no-cov -q`
Expected: both files fail to import (`build_request`, `request_messages`, `ERROR_CHARS`, `PROBE_*` do not exist).

- [ ] **Step 3: One request builder for the stages and the probe**

In `engine/corelata/llm/agent.py`, replace line 18 (`from corelata.config import CorelataConfig, StructuredOutput`) with:

```python
from corelata.config import CorelataConfig, ModelConfig, StructuredOutput
```

Between `_repair_message` (ends line 63) and `@dataclass` / `class CallLog` (line 66), add, keeping two blank lines on each side:

```python
def request_messages(
    system: str, payload: dict[str, Any], model: ModelConfig, schema: dict[str, Any]
) -> list[ChatMessage]:
    """The first turn of a structured call: the system prompt and the input. A server that does
    not enforce the schema (`json_object`, `none`) gets it spelled out in the system prompt."""
    if model.structured_output is not StructuredOutput.JSON_SCHEMA:
        spelled = json.dumps(schema, ensure_ascii=False)
        system += f"\n\nRespond with one JSON object that matches this JSON Schema:\n{spelled}"
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=render_input(payload)),
    ]


def build_request(
    model_key: str,
    model: ModelConfig,
    output_type: type[BaseModel],
    schema: dict[str, Any],
    messages: list[ChatMessage],
    *,
    max_tokens: int | None = None,
) -> ChatRequest:
    """The request every structured call sends: each stage through `AgentRunner.run`, and
    `corelata doctor`'s probe (R-M12-3). The backend turns `json_schema` into the strict response
    format (`llm/schema.py`), so the probe and a run send the same schema. `max_tokens`
    overrides the model's `max_output_tokens`."""
    return ChatRequest(
        model=model.name or model_key,
        messages=messages,
        schema_name=output_type.__name__,
        json_schema=schema,
        structured_output=model.structured_output,
        temperature=model.temperature,
        max_tokens=model.max_output_tokens if max_tokens is None else max_tokens,
    )
```

In `AgentRunner.run`, replace lines 119-153 (from `model = self.cfg.models[model_key]` through `result, errors = _parse(content, output_type, validate)`) with:

```python
        model = self.cfg.models[model_key]
        backend = self._backends[model.backend]
        prompt = self.prompts.render(prompt_id, **prompt_vars)
        schema = output_type.model_json_schema()
        messages = request_messages(prompt.text, payload, model, schema)
        content = ""
        errors: list[str] = []
        attempts = itertools.count(1)  # numbers every backend call of this run, repair included
        for _ in range(2):  # first attempt + one repair turn
            if errors:
                messages = [
                    *messages,
                    ChatMessage(role="assistant", content=content),
                    ChatMessage(role="user", content=_repair_message(errors)),
                ]
            request = build_request(model_key, model, output_type, schema, messages)
            content, record = await self._call(role, backend, request, prompt, attempts)
            result, errors = _parse(content, output_type, validate)
```

(The lines after it, from `if result is not None and not errors:` to the `raise StructuredOutputError(...)`, are unchanged.)

- [ ] **Step 4: The doctor's backend line, missing-model fix and probe**

In `engine/corelata/doctor.py`, replace the imports (lines 5-28) with:

```python
import asyncio
import contextlib
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from corelata.config import ConfigError, CorelataConfig, ModelConfig, StructuredOutput, load_config
from corelata.integrations.coglossa import CoglossaClient
from corelata.llm.agent import build_request, extract_json, request_messages
from corelata.llm.payload import render_input
from corelata.llm.registry import build_backends
from corelata.llm.types import Backend, BackendError, ChatMessage, ChatRequest, OutputTruncatedError
from corelata.pipeline import load_run_pack
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.schema import CheckStatus, DoctorCheck, DoctorReport, GateVerdict
from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN, PackError, list_packs
from corelata.storage import StorageError, build_storage
from corelata.store.db import redact
from corelata.store.migrate import connect_error, migration_state
from corelata.worker.execute import DB_ERRORS
```

After `PING_SCHEMA` (ends line 35), add:

```python
# The structured-output probe (R-M12-3) asks for the gate's real output type through the request
# builder every stage uses, so the server sees the same strict schema a run sends. The input is
# gate-shaped, so the synthetic responder (the fake server, the demo stack) answers it.
PROBE_SYSTEM = (
    "You judge whether a source passage supports an analyst's statement.\n"
    "Return your verdict on INPUT_JSON.value_statement against INPUT_JSON.units as one JSON object."
)
PROBE_PAYLOAD: dict[str, Any] = {
    "task": "gate",
    "value_statement": "The port of Tarvos expanded its container capacity in 2026.",
    "digests": [],
    "units": [
        {
            "ref": "probe/u1",
            "text": "Tarvos opened a second container terminal in May 2026, adding 70 percent "
            "to its container capacity.",
            "locator": "para 1",
            "source": "probe.txt",
        }
    ],
}
# A GateVerdict is a flag, an enum word, a few one-sentence reasons and refs: about 150 tokens.
# 512 leaves room for a verbose model; a model's own max_output_tokens wins, as in a run.
PROBE_MAX_TOKENS = 512
ERROR_CHARS = 200  # a server's error text in a check message is cut to this
SIMILAR_MAX = 5  # served ids a missing model's fix suggests
```

Between `_crashed` (ends line 46) and `def _guard` (line 49), add, keeping two blank lines on each side:

```python
def _cut(text: str, limit: int = ERROR_CHARS) -> str:
    """One line of at most `limit` characters: a server's error body can be long."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _prefix(model_id: str) -> str:
    """The part before the first `/` or `:` (`openai` of `openai/gpt-4.1`, `phi4-mini` of
    `phi4-mini:3.8b`)."""
    return re.split(r"[/:]", model_id, maxsplit=1)[0]


def _similar(model_id: str, served: list[str]) -> list[str]:
    """Up to SIMILAR_MAX served ids with the same prefix as `model_id`, sorted (R-M12-2)."""
    prefix = _prefix(model_id)
    return sorted({s for s in served if _prefix(s) == prefix})[:SIMILAR_MAX]
```

In `_backend`, replace line 221 (`checks = [_check(label, CheckStatus.PASS, f"serves {', '.join(served) or 'no models'}")]`) with:

```python
    # R-M12-2: a count and the configured models' state, never the served list (468 ids on
    # OpenRouter)
    have = set(served)
    state = [
        f"{key} → {m.name or key} {'found' if (m.name or key) in have else 'missing'}"
        for key, m in cfg.models.items()
        if m.backend == name
    ]
    noun = "model" if len(served) == 1 else "models"
    summary = "; ".join([f"serves {len(served)} {noun}", *state])
    checks = [_check(label, CheckStatus.PASS, summary)]
```

Replace `_model` (lines 247-280) with:

```python
async def _model(
    key: str, model: ModelConfig, backend: Backend, served: list[str], probe: bool
) -> DoctorCheck:
    label = f"model {key}"
    model_id = model.name or key
    if model_id not in served:
        similar = _similar(model_id, served)
        fix = (
            f"set models.{key}.name to a served id, such as: {', '.join(similar)}"
            if similar
            else f"set models.{key}.name to a served id; see the server's model list"
        )
        return _check(
            label, CheckStatus.FAIL, f"'{model_id}' is not served by backend {model.backend}", fix
        )
    if not probe:
        return _check(label, CheckStatus.PASS, "served")
    parts: list[DoctorCheck] = []
    try:
        await backend.chat(_ping(model_id, StructuredOutput.NONE))
        parts.append(_check(label, CheckStatus.PASS, "test completion succeeded"))
    except OutputTruncatedError:  # cut at max_tokens: the model answered
        parts.append(_check(label, CheckStatus.PASS, "test completion succeeded"))
    except BackendError as e:
        parts.append(
            _check(
                label,
                CheckStatus.FAIL,
                f"test completion failed: {e}",
                "check the model id and server logs",
            )
        )
    if model.structured_output is not StructuredOutput.NONE and parts[0].status is CheckStatus.PASS:
        parts.append(await _structured(label, key, model, backend))
    worst = max(parts, key=lambda c: _ORDER[c.status])
    fix = next((c.fix for c in parts if c.status is not CheckStatus.PASS), "")
    return _check(label, worst.status, "; ".join(c.message for c in parts), fix)
```

Replace `_structured` (lines 283-303) with:

```python
async def _structured(label: str, key: str, model: ModelConfig, backend: Backend) -> DoctorCheck:
    """R-M12-3: the real GateVerdict schema through the stages' request builder, so the backend
    applies `strict_json_schema` exactly as in a run; passes only on a reply that parses as a
    GateVerdict."""
    mode = model.structured_output.value
    fix = f"set models.{key}.structured_output to json_object or none"
    schema = GateVerdict.model_json_schema()
    request = build_request(
        key,
        model,
        GateVerdict,
        schema,
        request_messages(PROBE_SYSTEM, PROBE_PAYLOAD, model, schema),
        max_tokens=model.max_output_tokens or PROBE_MAX_TOKENS,
    )
    try:
        reply = await backend.chat(request)
    except OutputTruncatedError:
        return _check(
            label,
            CheckStatus.FAIL,
            f"the GateVerdict reply was cut at max_tokens={request.max_tokens}",
            f"set models.{key}.max_output_tokens above {request.max_tokens}: a reasoning model "
            "spends output tokens before it answers",
        )
    except BackendError as e:
        return _check(label, CheckStatus.FAIL, f"{mode} request failed: {_cut(str(e))}", fix)
    try:
        GateVerdict.model_validate_json(extract_json(reply.content))
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "<root>"
        return _check(
            label,
            CheckStatus.FAIL,
            f"the server did not return the requested JSON ({mode}): "
            + _cut(f"not a GateVerdict: {where}: {first['msg']}"),
            fix,
        )
    return _check(label, CheckStatus.PASS, f"{mode} output works (GateVerdict)")
```

(`json` is no longer used in `doctor.py`; the import list above drops it.)

- [ ] **Step 5: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/llm tests/test_doctor.py tests/test_cli_ops.py tests/stages tests/test_profiler.py --no-cov -q`
Expected: PASS (`test_structured_output_not_honoured` still finds "did not return the requested JSON"; the `api` doctor route reuses `run_doctor` unchanged).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest -k doctor --no-cov -q`
Expected: PASS.

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m12-task3-commit.txt <<'EOF'
fix: doctor counts served models and probes the real GateVerdict schema (CRL-27)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/llm/agent.py engine/corelata/doctor.py engine/tests/llm/test_agent.py engine/tests/test_doctor.py
git commit -F <scratchpad>/m12-task3-commit.txt
```

---

### Task 4: Range expectations and degraded audits in scenarios and scoring (CRL-28, R-M12-5)

The synthetic set's exact expectations ("clean at iteration 0, these rules fail") are right for the synthetic responder and wrong for a real model, which may take another acceptable path. `ScenarioExpect` gains ranges and rule sets. Separately, `compare` and `score.py` count an iteration as audited when any finding carries it, so a degraded audit (only the engine's `icd203.tc.8` finding) reports rule disagreements instead of "no audit ran".

**Files:**
- Modify: `engine/corelata/scenarios.py` (whole file), `engine/corelata/bench/score.py` (whole file), `engine/corelata/stages/audit.py` (after line 11; line 79), `engine/corelata/pipeline.py` (after line 48; line 325)
- Test: `engine/tests/test_scenarios.py` (imports lines 1-17; append), `engine/tests/bench/test_score.py` (imports lines 1-7; append)

**Interfaces:**
- Produces: `stages.audit.ENGINE_CHECK = "engine check: "`; `pipeline.AUDIT_INCOMPLETE = "audit incomplete"`. In `corelata.scenarios`: `ScenarioExpect` (fields below; `state` now `RunState | None`), `ScenarioExpect.rule_sets() -> list[str]`, `ScenarioExpect.expects_gate() -> bool`, `meets(exact: object, allowed: list[Any] | None, actual: object) -> bool`, `audited_iterations(record: RunRecord) -> set[int]`, `failed_rules(record: RunRecord, iteration: int) -> set[str]`; `compare` keeps its signature. `bench.score.score_run` keeps its signature.

- [ ] **Step 1: Failing tests**

In `engine/tests/test_scenarios.py`, replace the imports (lines 1-17) with:

```python
import pytest
import yaml

from corelata.bench import SCENARIOS_DIR
from corelata.llm.agent import CallLog
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import (
    Scenario,
    ScenarioError,
    audited_iterations,
    compare,
    load_scenario,
    load_scenarios,
    run_scenario,
    scenario_sources,
)
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.sources import text_source
```

Append to `engine/tests/test_scenarios.py`:

```python
BAD = "this is not JSON"  # four of them: two stage attempts, each a first try and a repair


async def _played(name: str, make_config, backend: FakeBackend | None = None):
    scenario = load_scenario(FIXTURES / f"{name}.yaml")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": backend or FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    return scenario, record


def _expecting(base: Scenario, **expect) -> Scenario:
    """`base`'s sources and statement with another expectation, validated as a file would be."""
    data = base.model_dump(mode="json", exclude={"expect"})
    return Scenario.model_validate({**data, "expect": expect})


@pytest.mark.parametrize(
    ("expect", "message"),
    [
        ("{state: completed, state_in: [completed]}", "set state or state_in, not both"),
        ("{state: completed, status: clean, status_in: [clean]}", "set status or status_in"),
        (
            "{state: completed, iterations: 0, iterations_max: 1}",
            "set iterations or iterations_max",
        ),
        (
            "{state: completed, gate_supported: true, gate_supported_in: [true]}",
            "set gate_supported or gate_supported_in, not both",
        ),
        (
            "{state: completed, substance: thin, substance_in: [thin]}",
            "set substance or substance_in",
        ),
        ("{status: clean}", "set state or state_in"),
        (
            "{state: completed, failing_rules: {0: []}, rules_may_fail: []}",
            "set failing_rules or rules_may_fail, not both",
        ),
        (
            "{state: completed, rules_must_pass: [icd203.tc.8], rules_may_fail: [icd203.tc.8]}",
            "icd203.tc.8 in both rules_must_pass and rules_may_fail",
        ),
        ("{state_in: []}", "expect.state_in: List should have at least 1 item"),
    ],
)
def test_expectation_forms_are_validated(tmp_path, expect, message):
    path = tmp_path / "bad.yaml"
    path.write_text(
        f"name: x\nstatement: s\nsources: [{{id: src1, paragraphs: [a]}}]\nexpect: {expect}\n"
    )
    with pytest.raises(ScenarioError) as e:
        load_scenario(path)
    assert str(e.value).startswith("bad.yaml: expect") and message in str(e.value)


async def test_range_expectations_accept_any_listed_outcome(make_config):
    clean, record = await _played("clean-single-source", make_config)
    ranged = _expecting(
        clean,
        state_in=["completed", "gate_rejected"],
        status_in=["clean", "findings_open"],
        iterations_max=0,
        gate_supported_in=[True],
        substance_in=["sufficient", "thin"],
        rules_must_pass=["icd203.tc.8", "icd206.src.2"],
        rules_may_fail=[],
    )
    assert compare(ranged, record) == []
    rejected, rec = await _played("gate-rejected", make_config)
    # no report, so status_in is not read; the run ended before an audit, so the rule sets are
    # not read either
    loose = _expecting(
        rejected,
        state_in=["completed", "gate_rejected"],
        status_in=["clean"],
        rules_must_pass=["icd203.tc.8"],
    )
    assert compare(loose, rec) == []


async def test_range_expectations_report_every_way_they_disagree(make_config):
    clean, record = await _played("clean-single-source", make_config)
    wrong = _expecting(
        clean,
        state_in=["gate_rejected"],
        status_in=["findings_open"],
        gate_supported_in=[False],
        substance_in=["thin", "insufficient"],
        rules_must_fail=["icd203.tc.2", "nope.rule.1"],
    )
    assert compare(wrong, record) == [
        "state: expected one of ['gate_rejected'], got 'completed'",
        "status: expected one of ['findings_open'], got 'clean'",
        "gate.supported: expected one of [False], got True",
        "gate.substance: expected one of ['thin', 'insufficient'], got 'sufficient'",
        "rules_must_fail: not in pack: nope.rule.1",
        "rules_must_fail: never failed: icd203.tc.2, nope.rule.1",
    ]
    unfixable, rec = await _played("unsourced-unfixable", make_config)
    strict = _expecting(
        unfixable,
        state="completed",
        iterations_max=1,
        rules_must_pass=["icd203.tc.8"],
        rules_may_fail=[],
    )
    assert compare(strict, rec) == [
        "iterations: expected at most 1, got 2",
        "rules_must_pass: failed in iteration 2: icd203.tc.8",
        "rules: unexpected failure in iteration 2: icd203.as.5, icd206.src.2",
    ]


async def test_a_degraded_audit_counts_as_no_audit_ran(make_config):
    backend = FakeBackend(name="fake")
    backend.script("auditor", *[BAD] * 4)
    scenario, record = await _played("max-iterations-zero", make_config, backend)
    [note] = record.report.metadata.degradations
    assert note.startswith("audit incomplete")
    assert [f.rule_id for f in record.findings] == ["icd203.tc.8"]  # the engine's own check
    assert audited_iterations(record) == set()
    mismatches = compare(scenario, record)
    assert "failing_rules[0]: no audit ran for iteration 0" in mismatches
    assert not any(m.startswith("failing_rules[0]: expected") for m in mismatches)
    ranged = _expecting(scenario, state="completed", rules_must_pass=["icd203.tc.8"])
    assert compare(ranged, record) == ["rules: no audit ran"]


async def test_audited_iterations_read_only_audit_incomplete_degradations(make_config):
    _, record = await _played("clean-single-source", make_config)
    assert audited_iterations(record) == {0}

    def with_note(note: str):
        meta = record.report.metadata.model_copy(update={"degradations": [note]})
        report = record.report.model_copy(update={"metadata": meta})
        return record.model_copy(update={"report": report})

    assert audited_iterations(with_note("audit incomplete after 2 attempts: x")) == set()
    assert audited_iterations(with_note("conveyance skipped after 2 attempts: x")) == {0}
```

In `engine/tests/bench/test_score.py`, replace the imports (lines 1-7) with:

```python
from corelata.bench import SCENARIOS_DIR
from corelata.bench.schema import Rate, RuleTally, RunResult, ScenarioResult
from corelata.bench.score import error_result, score_run, summarize
from corelata.llm.agent import CallLog
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import Scenario, load_scenario, run_scenario
from corelata.testing.fake_backend import FakeBackend
```

Append to `engine/tests/bench/test_score.py`:

```python
def _expecting(base: Scenario, **expect) -> Scenario:
    data = base.model_dump(mode="json", exclude={"expect"})
    return Scenario.model_validate({**data, "expect": expect})


def _score(scenario, record, tallies=None):
    tallies = {} if tallies is None else tallies
    return score_run(scenario, record, repeat=1, duration_s=0, tallies=tallies)


async def test_gate_and_state_ranges_are_scored(make_config):
    rejected, record = await _record("gate-rejected", make_config)
    ok = _expecting(
        rejected,
        state="gate_rejected",
        gate_supported_in=[False],
        substance_in=["insufficient", "thin"],
    )
    assert _score(ok, record).gate_agree is True
    thin_only = _expecting(rejected, state="gate_rejected", substance_in=["thin"])
    assert _score(thin_only, record).gate_agree is False
    # no report: status_in is not read
    loose = _expecting(
        rejected, state_in=["completed", "gate_rejected"], status_in=["clean"], iterations_max=0
    )
    assert _score(loose, record).state_agree is True
    assert _score(_expecting(rejected, state_in=["completed"]), record).state_agree is False
    unfixable, rec = await _record("unsourced-unfixable", make_config)

    def state_agree(**expect):
        return _score(_expecting(unfixable, state="completed", **expect), rec).state_agree

    assert state_agree(iterations_max=1) is False
    assert state_agree(status_in=["clean"]) is False
    assert state_agree(iterations_max=2) is True


async def test_rule_sets_tally_must_fail_as_expected_and_untolerated_failures_as_unexpected(
    make_config,
):
    unfixable, record = await _record("unsourced-unfixable", make_config)
    scenario = _expecting(
        unfixable,
        state="completed",
        rules_must_fail=["icd203.tc.8", "icd203.tc.2"],
        rules_may_fail=["icd203.as.5"],
    )
    tallies: dict[str, RuleTally] = {}
    assert _score(scenario, record, tallies).rules_agree is False
    assert tallies == {
        "icd203.tc.8": RuleTally(expected=1, hit=1),
        "icd203.tc.2": RuleTally(expected=1, missed=1),
        "icd206.src.2": RuleTally(unexpected=1),  # failed at the end, not tolerated
    }
    open_set = _expecting(unfixable, state="completed", rules_must_pass=["icd206.src.2"])
    tallies = {}
    assert _score(open_set, record, tallies).rules_agree is False  # a must-pass rule failed
    assert tallies == {"icd206.src.2": RuleTally(unexpected=1)}  # others are left free


async def test_a_rule_fixed_in_a_revision_meets_must_fail_and_must_pass(make_config):
    fixed, record = await _record("unsourced-fixed-one-loop", make_config)
    scenario = _expecting(
        fixed,
        state="completed",
        rules_must_fail=["icd203.tc.8"],
        rules_must_pass=["icd203.tc.8", "icd206.src.2"],
        rules_may_fail=[],
    )
    tallies: dict[str, RuleTally] = {}
    result = _score(scenario, record, tallies)
    assert result.rules_agree is True and result.agree
    assert tallies == {"icd203.tc.8": RuleTally(expected=1, hit=1)}


async def test_a_degraded_audit_scores_as_missed_not_hit(make_config):
    backend = FakeBackend(name="fake")
    backend.script("auditor", *["this is not JSON"] * 4)
    scenario = load_scenario(SCENARIOS_DIR / "max-iterations-zero.yaml")
    record = await run_scenario(
        scenario, make_config(), backends={"fake": backend}, prompts=PromptLibrary(), log=CallLog()
    )
    tallies: dict[str, RuleTally] = {}
    assert _score(scenario, record, tallies).rules_agree is False
    # before M12 the engine's own icd203.tc.8 finding counted as a hit for an audit that never ran
    assert tallies == {
        "icd203.as.5": RuleTally(expected=1, missed=1),
        "icd203.tc.8": RuleTally(expected=1, missed=1),
        "icd206.src.2": RuleTally(expected=1, missed=1),
    }


async def test_rule_sets_are_not_scored_when_the_run_stopped_before_an_audit(make_config):
    rejected, record = await _record("gate-rejected", make_config)
    scenario = _expecting(rejected, state="gate_rejected", rules_must_pass=["icd203.tc.8"])
    result = _score(scenario, record)
    assert result.rules_agree is None and result.agree
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_scenarios.py tests/bench/test_score.py --no-cov -q`
Expected: `test_scenarios.py` fails to import `audited_iterations`; in `test_score.py` the new tests fail with `ValidationError` (`state_in`, `rules_must_pass` … are extra inputs).

- [ ] **Step 3: Name the two markers the scorer reads**

In `engine/corelata/stages/audit.py`, after the last import (line 11, `from corelata.standards.schema import Checkability, ResolvedPack, Severity`), add (the blank line already at line 12 then separates it from `LOOPING`):

```python

# How an engine-owned finding's evidence starts (R-M11-6); the bench reads it to recognise an
# iteration whose only findings are the engine's, a degraded audit (R-M12-5).
ENGINE_CHECK = "engine check: "
```

and change line 79 from

```python
                    "evidence": f"engine check: claims without evidence: {', '.join(ids)}",
```

to

```python
                    "evidence": f"{ENGINE_CHECK}claims without evidence: {', '.join(ids)}",
```

In `engine/corelata/pipeline.py`, after `DEGRADATION_CHARS = 200` (line 48), add:

```python
# The degradation line for an audit the run was delivered without; `scenarios` reads it.
AUDIT_INCOMPLETE = "audit incomplete"
```

and change line 325 from

```python
                        self._degradation("audit incomplete", RunState.AUDITING, iteration, e)
```

to

```python
                        self._degradation(AUDIT_INCOMPLETE, RunState.AUDITING, iteration, e)
```

- [ ] **Step 4: Range expectations and audited iterations**

Replace `engine/corelata/scenarios.py` with:

```python
"""Scenario fixtures (spec §13): sources plus a statement plus what the run must do. CI runs the
synthetic set against the synthetic model; `corelata bench` (M6) runs a set against real models
and reports agreement. The synthetic set states exact outcomes; the real-model set (M12) states
ranges and rule sets, because a real model may take more than one acceptable path. Loading,
running and comparing live here so both callers share one truth."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from corelata.config import CorelataConfig, PipelineConfig
from corelata.ingest.units import source_from_paragraphs
from corelata.llm.agent import CallLog
from corelata.llm.types import Backend
from corelata.pipeline import AUDIT_INCOMPLETE, RunOptions, run_report, utcnow
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    Finding,
    ReportStatus,
    RunRecord,
    RunState,
    Source,
    Substance,
    Verdict,
)
from corelata.stages.audit import ENGINE_CHECK


class ScenarioError(ValueError):
    """A scenario file is unusable; the message names the file and the problem."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioSource(_Strict):
    id: str
    name: str | None = None
    paragraphs: list[str] = Field(min_length=1)


# An exact expectation and its range form (R-M12-5): a scenario sets one or the other.
_PAIRS = (
    ("state", "state_in"),
    ("status", "status_in"),
    ("iterations", "iterations_max"),
    ("gate_supported", "gate_supported_in"),
    ("substance", "substance_in"),
)


class ScenarioExpect(_Strict):
    """What the run must do (R-M12-5). Exact fields and range fields can be mixed, never a field
    and its range form. `status_in` is read only when the run delivered a report. Rules are
    stated either per iteration (`failing_rules`, exact) or as sets: `rules_must_pass` never
    fail in the last audited iteration, `rules_must_fail` fail in at least one audited
    iteration, and `rules_may_fail` lists what else may fail at the end; with
    `rules_may_fail: null` (the default) other rules are free, with a list (even empty) any
    other failure at the end is a mismatch."""

    state: RunState | None = None
    state_in: list[RunState] | None = Field(None, min_length=1)
    status: ReportStatus | None = None
    status_in: list[ReportStatus] | None = Field(None, min_length=1)
    iterations: int | None = None
    iterations_max: int | None = Field(None, ge=0, le=10)
    gate_supported: bool | None = None
    gate_supported_in: list[bool] | None = Field(None, min_length=1)
    substance: Substance | None = None
    substance_in: list[Substance] | None = Field(None, min_length=1)
    failing_rules: dict[int, list[str]] = Field(default_factory=dict)
    rules_must_pass: list[str] = Field(default_factory=list)
    rules_may_fail: list[str] | None = None
    rules_must_fail: list[str] = Field(default_factory=list)
    open_findings: list[str] | None = None
    digested: list[str] | None = None

    @model_validator(mode="after")
    def _one_form_each(self) -> "ScenarioExpect":
        for exact, ranged in _PAIRS:
            if getattr(self, exact) is not None and getattr(self, ranged) is not None:
                raise ValueError(f"set {exact} or {ranged}, not both")
        if self.state is None and self.state_in is None:
            raise ValueError("set state or state_in")
        sets = self.rule_sets()
        if self.failing_rules and sets:
            raise ValueError(f"set failing_rules or {', '.join(sets)}, not both")
        clash = sorted(set(self.rules_must_pass) & set(self.rules_may_fail or []))
        if clash:
            raise ValueError(f"{', '.join(clash)} in both rules_must_pass and rules_may_fail")
        return self

    def rule_sets(self) -> list[str]:
        """The `rules_*` fields this scenario sets (an empty `rules_may_fail` list is set)."""
        named = []
        if self.rules_must_pass:
            named.append("rules_must_pass")
        if self.rules_may_fail is not None:
            named.append("rules_may_fail")
        if self.rules_must_fail:
            named.append("rules_must_fail")
        return named

    def expects_gate(self) -> bool:
        ranged = (self.gate_supported, self.gate_supported_in, self.substance, self.substance_in)
        return any(v is not None for v in ranged)


class Scenario(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""
    statement: str = Field(min_length=1)
    sources: list[ScenarioSource] = Field(min_length=1)
    max_iterations: int | None = Field(None, ge=0, le=10)
    profile: str | None = None
    pipeline: dict[str, Any] = Field(default_factory=dict)
    expect: ScenarioExpect


def load_scenario(path: Path) -> Scenario:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScenarioError(f"{path.name}: invalid YAML: {' '.join(str(e).split())}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ScenarioError(f"{path.name}: cannot read: {e}") from e
    if not isinstance(data, dict):
        raise ScenarioError(f"{path.name}: expected a mapping at the top level")
    try:
        scenario = Scenario.model_validate(data)
    except ValidationError as e:
        raise ScenarioError(f"{path.name}: {_first_error(e)}") from e
    try:  # an unknown key or a bad value fails here, not when the scenario runs
        PipelineConfig.model_validate({**PipelineConfig().model_dump(), **scenario.pipeline})
    except ValidationError as e:
        raise ScenarioError(f"{path.name}: pipeline.{_first_error(e)}") from e
    return scenario


def _first_error(e: ValidationError) -> str:
    first = e.errors()[0]
    where = ".".join(str(p) for p in first["loc"]) or "(top level)"
    return f"{where}: {first['msg']}"


def load_scenarios(directory: Path) -> list[Scenario]:
    if not directory.is_dir():
        return []
    return [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]


def scenario_sources(scenario: Scenario) -> list[Source]:
    return [source_from_paragraphs(s.id, s.paragraphs, name=s.name) for s in scenario.sources]


async def run_scenario(
    scenario: Scenario,
    cfg: CorelataConfig,
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    now: Callable[[], datetime] = utcnow,
) -> RunRecord:
    if scenario.pipeline:
        pipeline = PipelineConfig.model_validate({**cfg.pipeline.model_dump(), **scenario.pipeline})
        cfg = cfg.model_copy(update={"pipeline": pipeline})
    return await run_report(
        cfg,
        scenario_sources(scenario),
        RunOptions(
            value_statement=scenario.statement,
            profile=scenario.profile,
            max_iterations=scenario.max_iterations,
            run_id=scenario.name,
        ),
        backends=backends,
        prompts=prompts,
        log=log,
        now=now,
    )


def meets(exact: object, allowed: list[Any] | None, actual: object) -> bool:
    """`actual` satisfies an exact expectation and its range form (either may be unset)."""
    return (exact is None or exact == actual) and (allowed is None or actual in allowed)


def audited_iterations(record: RunRecord) -> set[int]:
    """The iterations whose audit completed (R-M12-5). A finding carries its iteration, but a
    degraded audit (R-M11-2) leaves only the engine's own findings for it (R-M11-6), or none,
    and the report says "audit incomplete" for the run's last iteration; neither counts. A
    skipped conveyance does not touch the audit, so its iteration counts."""
    by_iteration: dict[int, list[Finding]] = {}
    for f in record.findings:
        by_iteration.setdefault(f.iteration, []).append(f)
    incomplete = record.report is not None and any(
        line.startswith(AUDIT_INCOMPLETE) for line in record.report.metadata.degradations
    )
    return {
        iteration
        for iteration, found in by_iteration.items()
        if not all(f.evidence.startswith(ENGINE_CHECK) for f in found)
        and not (incomplete and iteration == record.iterations)
    }


def failed_rules(record: RunRecord, iteration: int) -> set[str]:
    return {
        f.rule_id for f in record.findings if f.iteration == iteration and f.verdict is Verdict.FAIL
    }


def compare(scenario: Scenario, record: RunRecord) -> list[str]:
    """Every way the record disagrees with the scenario's expectations; empty means it passed."""
    e = scenario.expect
    out: list[str] = []

    def check(label: str, expected: object, actual: object) -> None:
        if expected is not None and expected != actual:
            out.append(f"{label}: expected {_show(expected)}, got {_show(actual)}")

    def within(label: str, allowed: list[Any] | None, actual: object) -> None:
        if allowed is not None and actual not in allowed:
            out.append(f"{label}: expected one of {_show_all(allowed)}, got {_show(actual)}")

    check("state", e.state, record.state)
    within("state", e.state_in, record.state)
    check("status", e.status, record.status)
    if record.report is not None:  # status_in speaks only of a delivered report
        within("status", e.status_in, record.status)
    check("iterations", e.iterations, record.iterations)
    if e.iterations_max is not None and record.iterations > e.iterations_max:
        out.append(f"iterations: expected at most {e.iterations_max}, got {record.iterations}")
    if record.gate is None:
        if e.expects_gate():
            out.append("gate: expected a verdict, got none")
    else:
        check("gate.supported", e.gate_supported, record.gate.supported)
        within("gate.supported", e.gate_supported_in, record.gate.supported)
        check("gate.substance", e.substance, record.gate.substance)
        within("gate.substance", e.substance_in, record.gate.substance)
    pack_rules = {r["id"] for r in record.pack_snapshot.get("rules", [])}
    audited = audited_iterations(record)
    for it, rules in sorted(e.failing_rules.items()):
        unknown = sorted(set(rules) - pack_rules)
        if unknown:
            out.append(f"failing_rules[{it}]: not in pack: {', '.join(unknown)}")
        if it not in audited:
            out.append(f"failing_rules[{it}]: no audit ran for iteration {it}")
            continue
        check(f"failing_rules[{it}]", sorted(rules), sorted(failed_rules(record, it)))
    out += _compare_rule_sets(e, record, pack_rules, audited)
    if e.open_findings is not None:
        actual_open = sorted(record.report.metadata.open_findings) if record.report else []
        check("open_findings", sorted(e.open_findings), actual_open)
    if e.digested is not None:
        check("digested", sorted(e.digested), sorted(d.source_id for d in record.digests))
    return out


def _compare_rule_sets(
    e: ScenarioExpect, record: RunRecord, pack_rules: set[str], audited: set[int]
) -> list[str]:
    if not e.rule_sets():
        return []
    out: list[str] = []
    named = (
        ("rules_must_pass", e.rules_must_pass),
        ("rules_may_fail", e.rules_may_fail or []),
        ("rules_must_fail", e.rules_must_fail),
    )
    for label, rules in named:
        unknown = sorted(set(rules) - pack_rules)
        if unknown:
            out.append(f"{label}: not in pack: {', '.join(unknown)}")
    if not audited:
        if record.state is RunState.COMPLETED:  # an earlier end is the state check's business
            out.append("rules: no audit ran")
        return out
    final = max(audited)
    last = failed_rules(record, final)
    ever = set().union(*(failed_rules(record, it) for it in audited))
    must_have_passed = sorted(set(e.rules_must_pass) & last)
    if must_have_passed:
        out.append(f"rules_must_pass: failed in iteration {final}: {', '.join(must_have_passed)}")
    never = sorted(set(e.rules_must_fail) - ever)
    if never:
        out.append(f"rules_must_fail: never failed: {', '.join(never)}")
    if e.rules_may_fail is not None:
        allowed = set(e.rules_may_fail) | set(e.rules_must_fail) | set(e.rules_must_pass)
        extra = sorted(last - allowed)
        if extra:
            out.append(f"rules: unexpected failure in iteration {final}: {', '.join(extra)}")
    return out


def _show(value: object) -> str:
    if hasattr(value, "value"):  # enums print as their wire value
        return repr(value.value)
    return repr(value)


def _show_all(values: list[Any]) -> str:
    return "[" + ", ".join(_show(v) for v in values) + "]"
```

- [ ] **Step 5: Scoring both forms**

Replace `engine/corelata/bench/score.py` with:

```python
"""From a scenario and the record a real model produced to a `RunResult` (pure functions)."""

from corelata.bench.schema import BenchSummary, Rate, RuleTally, RunResult, ScenarioResult
from corelata.scenarios import (
    Scenario,
    ScenarioExpect,
    audited_iterations,
    compare,
    failed_rules,
    meets,
)
from corelata.schema import RunRecord, RunState


def _gate_agree(scenario: Scenario, record: RunRecord) -> bool | None:
    e = scenario.expect
    if not e.expects_gate():
        return None
    if record.gate is None:
        return False
    return meets(e.gate_supported, e.gate_supported_in, record.gate.supported) and meets(
        e.substance, e.substance_in, record.gate.substance
    )


def _tally(tallies: dict[str, RuleTally], rule_id: str) -> RuleTally:
    return tallies.setdefault(rule_id, RuleTally())


def _per_iteration_agree(
    expected_by_iteration: dict[int, list[str]], record: RunRecord, tallies: dict[str, RuleTally]
) -> bool:
    audited = audited_iterations(record)
    agree = True
    for iteration, expected in sorted(expected_by_iteration.items()):
        if iteration not in audited:
            agree = False
            for rule_id in expected:
                tally = _tally(tallies, rule_id)
                tally.expected += 1
                tally.missed += 1
            continue
        actual = failed_rules(record, iteration)
        if actual != set(expected):
            agree = False
        for rule_id in expected:
            tally = _tally(tallies, rule_id)
            tally.expected += 1
            if rule_id in actual:
                tally.hit += 1
            else:
                tally.missed += 1
        for rule_id in sorted(actual - set(expected)):
            _tally(tallies, rule_id).unexpected += 1
    return agree


def _rule_sets_agree(
    e: ScenarioExpect, record: RunRecord, tallies: dict[str, RuleTally]
) -> bool | None:
    """R-M12-5. Each `rules_must_fail` rule is expected once per run, a hit when it failed in
    any audited iteration. A failure in the last audited iteration is unexpected when the rule
    must pass, or when `rules_may_fail` closes the set and does not list it. A run that ended
    before any audit (gate rejected, failed) is not scored here; its state is."""
    audited = audited_iterations(record)
    if not audited and record.state is not RunState.COMPLETED:
        return None
    last = failed_rules(record, max(audited)) if audited else set()
    ever = set().union(*(failed_rules(record, it) for it in audited))
    agree = bool(audited)
    for rule_id in e.rules_must_fail:
        tally = _tally(tallies, rule_id)
        tally.expected += 1
        if rule_id in ever:
            tally.hit += 1
        else:
            tally.missed += 1
            agree = False
    tolerated = (set(e.rules_must_fail) | set(e.rules_may_fail or [])) - set(e.rules_must_pass)
    for rule_id in sorted(last - tolerated):
        if rule_id in e.rules_must_pass or e.rules_may_fail is not None:
            _tally(tallies, rule_id).unexpected += 1
            agree = False
    return agree


def _rules_agree(
    scenario: Scenario, record: RunRecord, tallies: dict[str, RuleTally]
) -> bool | None:
    e = scenario.expect
    if e.failing_rules:
        return _per_iteration_agree(e.failing_rules, record, tallies)
    if e.rule_sets():
        return _rule_sets_agree(e, record, tallies)
    return None


def _state_agree(scenario: Scenario, record: RunRecord) -> bool:
    e = scenario.expect
    delivered = record.report is not None
    return (
        meets(e.state, e.state_in, record.state)
        and (e.status is None or record.status == e.status)
        and (e.status_in is None or not delivered or record.status in e.status_in)
        and (e.iterations is None or record.iterations == e.iterations)
        and (e.iterations_max is None or record.iterations <= e.iterations_max)
    )


def score_run(
    scenario: Scenario,
    record: RunRecord,
    *,
    repeat: int,
    duration_s: float,
    tallies: dict[str, RuleTally],
) -> RunResult:
    """Score one record; `tallies` is updated in place with this run's rule outcomes."""
    return RunResult(
        repeat=repeat,
        ok=True,
        state=record.state,
        status=record.status,
        iterations=record.iterations,
        duration_s=duration_s,
        calls=record.usage.calls,
        tokens_in=record.usage.tokens_in,
        tokens_out=record.usage.tokens_out,
        mismatches=compare(scenario, record),
        gate_agree=_gate_agree(scenario, record),
        rules_agree=_rules_agree(scenario, record, tallies),
        state_agree=_state_agree(scenario, record),
    )


def error_result(*, repeat: int, error: str, duration_s: float) -> RunResult:
    """A run that raised before producing a record (a missing profile, a broken pack)."""
    return RunResult(repeat=repeat, ok=False, error=error, duration_s=duration_s)


def summarize(results: list[ScenarioResult], *, duration_s: float) -> BenchSummary:
    full, gate, rules, state = Rate(), Rate(), Rate(), Rate()
    runs = errors = tokens_in = tokens_out = 0
    for scenario in results:
        for run in scenario.runs:
            runs += 1
            tokens_in += run.tokens_in
            tokens_out += run.tokens_out
            full.add(run.agree)  # an errored run is a disagreement here, and counted below
            if not run.ok:
                errors += 1
                continue
            gate.add(run.gate_agree)
            rules.add(run.rules_agree)
            state.add(run.state_agree)
    return BenchSummary(
        scenarios=len(results),
        runs=runs,
        errors=errors,
        full_agreement=full,
        gate_agreement=gate,
        rule_agreement=rules,
        state_agreement=state,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_s=duration_s,
    )
```

- [ ] **Step 6: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_scenarios.py tests/bench tests/test_cli_bench.py tests/test_pipeline.py tests/stages/test_audit.py --no-cov -q`
Expected: PASS (every synthetic scenario still agrees: none of them degrades, so `audited_iterations` equals the old set).

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m12-task4-commit.txt <<'EOF'
feat: range and rule-set scenario expectations; a degraded audit is no audit (CRL-28)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/scenarios.py engine/corelata/bench/score.py engine/corelata/stages/audit.py engine/corelata/pipeline.py engine/tests/test_scenarios.py engine/tests/bench/test_score.py
git commit -F <scratchpad>/m12-task4-commit.txt
```

---

### Task 5: The bench table shows the gate, and `bench.json` keeps it (CRL-28, R-M12-6)

In the rehearsal six of ten runs ended `gate_rejected` and the table said only that; the reader had to open each trace to learn the gate judged the marker text insufficient.

**Files:**
- Modify: `engine/corelata/bench/schema.py` (import line 8; new class before `RunResult`, line 38; `RunResult` after line 44), `engine/corelata/bench/score.py` (import line 3; `score_run`), `engine/corelata/bench/text.py` (whole file), `schema/bench-report.schema.json` (regenerated)
- Test: `engine/tests/bench/test_text.py` (whole file), `engine/tests/bench/test_score.py` (import line 2; append)

**Interfaces:**
- Consumes: `score.py` as Task 4 wrote it.
- Produces: `bench.schema.GateResult(supported: bool, substance: Substance, reasons: list[str] = [])`; `RunResult.gate: GateResult | None = None`. `bench.text.GATE_WIDTH = 23`, `bench.text.GATE_REASON_CHARS = 60`; `format_bench(report) -> str` keeps its signature.

- [ ] **Step 1: Failing tests**

Replace `engine/tests/bench/test_text.py` with:

```python
from datetime import UTC, datetime

from corelata.bench.schema import (
    BenchReport,
    BenchSummary,
    GateResult,
    Rate,
    RuleTally,
    RunResult,
    ScenarioResult,
)
from corelata.bench.text import GATE_REASON_CHARS, format_bench

REASON = (
    "The terminal log shows July arrivals below June, so growth since the shuttle began is "
    "not established."
)


def _report() -> BenchReport:
    t = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    good = RunResult(
        repeat=1,
        ok=True,
        state="completed",
        status="clean",
        iterations=0,
        gate=GateResult(supported=True, substance="sufficient", reasons=["Three passages."]),
        duration_s=12.3,
        calls=4,
        tokens_in=1200,
        tokens_out=400,
        gate_agree=True,
        rules_agree=None,
        state_agree=True,
    )
    bad = RunResult(
        repeat=1,
        ok=True,
        state="completed",
        status="findings_open",
        iterations=2,
        gate=GateResult(supported=True, substance="thin", reasons=[REASON, "second reason"]),
        duration_s=40.0,
        calls=9,
        tokens_in=5000,
        tokens_out=900,
        mismatches=[
            "status: expected 'clean', got 'findings_open'",
            "failing_rules[1]: expected [], got ['icd203.tc.8']",
        ],
        gate_agree=False,
        rules_agree=False,
        state_agree=False,
    )
    err = RunResult(repeat=1, ok=False, error="RuntimeError: boom", duration_s=0.1)
    results = [
        ScenarioResult(name="clean-single-source", description="", runs=[good]),
        ScenarioResult(name="unsourced-fixed-one-loop", description="", runs=[bad]),
        ScenarioResult(name="broken", description="", runs=[err]),
    ]
    summary = BenchSummary(
        scenarios=3,
        runs=3,
        errors=1,
        full_agreement=Rate(agree=1, total=3),
        gate_agreement=Rate(agree=1, total=2),
        rule_agreement=Rate(agree=0, total=1),
        state_agreement=Rate(agree=1, total=2),
        tokens_in=6200,
        tokens_out=1300,
        duration_s=52.4,
    )
    return BenchReport(
        corelata_version="0.1.0",
        started_at=t,
        finished_at=t,
        config_hash="abc",
        repeat=1,
        models={
            "gate": "openai/gpt-4.1-mini",
            "writer": "openai/gpt-4.1-mini",
            "conveyor": "google/gemini-2.5-flash",
            "auditor": "google/gemini-2.5-flash",
        },
        scenarios_dir="/x",
        scenarios=results,
        rules={
            "icd203.tc.8": RuleTally(expected=1, hit=0, missed=0, unexpected=1),
            "icd203.tc.2": RuleTally(expected=2, hit=2),
        },
        summary=summary,
    )


def _rows(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    header = next(ln for ln in lines if ln.startswith("scenario "))
    names = ("clean-single-source", "unsourced-fixed", "broken")
    return header, [next(ln for ln in lines if ln.startswith(n)) for n in names]


def test_format_bench_lists_scenarios_summary_rules_and_mismatches():
    text = format_bench(_report())
    lines = text.splitlines()
    assert lines[0].startswith("corelata bench 0.1.0")
    assert lines[1:4] == [  # one line per model id, with the roles it serves
        "models:",
        "  openai/gpt-4.1-mini      gate, writer",
        "  google/gemini-2.5-flash  conveyor, auditor",
    ]
    header, table = _rows(text)
    assert "  agree  outcome" in header and "agree outcome" not in header
    assert table[0].split()[2] == "yes" and table[1].split()[2] == "no"
    assert table[2].split()[2] == "err" and "RuntimeError: boom" in table[2]
    assert "completed clean" in table[0] and "12.3s" in table[0]
    assert "findings_open" in table[1]
    assert "full agreement 1/3 (33%)" in text
    assert "gate agreement 1/2 (50%)" in text
    assert "rule-failure agreement 0/1 (0%)" in text
    assert "state agreement 1/2 (50%)" in text
    assert "errors 1" in text and "tokens in 6200, out 1300" in text
    assert "icd203.tc.8" in text and "unexpected 1" in text
    assert "icd203.tc.2" not in text.split("rules with misses or unexpected failures")[1]
    assert "  unsourced-fixed-one-loop run 1:" in text
    assert "    status: expected 'clean', got 'findings_open'" in text


def test_the_gate_column_shows_the_verdict_and_a_disagreeing_gates_first_reason():
    header, (good, bad, err) = _rows(format_bench(_report()))
    column = header.index("gate")
    assert good[column:].startswith("supported · sufficient")
    assert "Three passages" not in good  # the gate agreed: no reason
    assert bad[column:].startswith("supported · thin")
    assert bad.endswith("  " + REASON[: GATE_REASON_CHARS - 1] + "…")
    assert "second reason" not in bad
    assert err[column:].startswith("-")
    rejected = _report()
    run = rejected.scenarios[0].runs[0]
    run.gate = GateResult(supported=False, substance="insufficient", reasons=["short"])
    run.gate_agree = False
    _, (row, _, _) = _rows(format_bench(rejected))
    assert row[column:].startswith("rejected · insufficient") and row.endswith("  short")


def test_format_bench_when_everything_agrees_has_no_rule_or_mismatch_sections():
    report = _report()
    report.scenarios = report.scenarios[:1]
    report.rules = {"icd203.tc.2": RuleTally(expected=2, hit=2)}
    report.summary = BenchSummary(
        scenarios=1,
        runs=1,
        errors=0,
        full_agreement=Rate(agree=1, total=1),
        gate_agreement=Rate(agree=1, total=1),
        rule_agreement=Rate(),
        state_agreement=Rate(agree=1, total=1),
        tokens_in=1,
        tokens_out=1,
        duration_s=1,
    )
    text = format_bench(report)
    assert "rule-failure agreement n/a" in text
    assert "rules with misses" not in text and "mismatches" not in text
```

In `engine/tests/bench/test_score.py`, replace line 2 (`from corelata.bench.schema import Rate, RuleTally, RunResult, ScenarioResult`) with:

```python
from corelata.bench.schema import GateResult, Rate, RuleTally, RunResult, ScenarioResult
```

and append:

```python
async def test_score_run_keeps_the_gate_verdict(make_config):
    scenario, record = await _record("gate-rejected", make_config)
    result = score_run(scenario, record, repeat=1, duration_s=0, tallies={})
    assert result.gate == GateResult(
        supported=False, substance="insufficient", reasons=record.gate.reasons
    )
    assert RunResult.model_validate_json(result.model_dump_json()).gate == result.gate
    no_gate = record.model_copy(update={"gate": None})
    assert score_run(scenario, no_gate, repeat=1, duration_s=0, tallies={}).gate is None
    assert RunResult.model_validate({"repeat": 1, "ok": True}).gate is None  # older bench.json
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/bench --no-cov -q`
Expected: both files fail to import `GateResult` (and `GATE_REASON_CHARS`).

- [ ] **Step 3: `RunResult.gate`**

In `engine/corelata/bench/schema.py`, replace line 8 (`from corelata.schema import ReportStatus, RunState`) with:

```python
from corelata.schema import ReportStatus, RunState, Substance
```

Before `class RunResult(BaseModel):` (line 38), add:

```python
class GateResult(BaseModel):
    """The gate's verdict in one run (R-M12-6), so a reader sees why a run stopped there."""

    supported: bool
    substance: Substance
    reasons: list[str] = Field(default_factory=list)


```

In `RunResult`, after `iterations: int | None = None` (line 44), add:

```python
    gate: GateResult | None = None  # None: the run errored, or ended before the gate answered
```

In `engine/corelata/bench/score.py`, replace the first import line with:

```python
from corelata.bench.schema import (
    BenchSummary,
    GateResult,
    Rate,
    RuleTally,
    RunResult,
    ScenarioResult,
)
```

and in `score_run`, after `iterations=record.iterations,` add:

```python
        gate=None
        if record.gate is None
        else GateResult(
            supported=record.gate.supported,
            substance=record.gate.substance,
            reasons=list(record.gate.reasons),
        ),
```

- [ ] **Step 4: The gate column and the model lines**

Replace `engine/corelata/bench/text.py` with:

```python
"""The terminal rendering of a `BenchReport`."""

from corelata.bench.schema import BenchReport, Rate, RunResult

# The gate column fits "rejected · insufficient"; when the gate disagreed with the scenario its
# first reason follows the row, cut to GATE_REASON_CHARS (R-M12-6).
GATE_WIDTH = 23
GATE_REASON_CHARS = 60


def _pct(rate: Rate) -> str:
    if rate.total == 0:
        return "n/a"
    return f"{rate.agree}/{rate.total} ({round(100 * rate.agree / rate.total)}%)"


def _cut(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _outcome(run: RunResult) -> tuple[str, str]:
    """The `agree` flag and the `outcome` text of a table row."""
    if not run.ok:
        return "err", run.error or ""
    state = run.state.value if run.state is not None else "?"
    status = f" {run.status.value}" if run.status is not None else ""
    return ("yes" if run.agree else "no"), f"{state}{status}"


def _gate(run: RunResult) -> tuple[str, str]:
    """The `gate` column and, when the gate disagreed with the scenario, its first reason."""
    if run.gate is None:
        return "-", ""
    verdict = "supported" if run.gate.supported else "rejected"
    column = f"{verdict} · {run.gate.substance.value}"
    if run.gate_agree is False and run.gate.reasons:
        return column, _cut(run.gate.reasons[0], GATE_REASON_CHARS)
    return column, ""


def _models(models: dict[str, str]) -> list[str]:
    """One line per model id with the roles it serves, in role order."""
    roles: dict[str, list[str]] = {}
    for role, model in models.items():
        roles.setdefault(model, []).append(role)
    width = max((len(m) for m in roles), default=0)
    return ["models:", *(f"  {m:<{width}}  {', '.join(rs)}" for m, rs in roles.items())]


def format_bench(report: BenchReport) -> str:
    s = report.summary
    width = max([len(x.name) for x in report.scenarios] + [8])
    lines = [
        f"corelata bench {report.corelata_version}  config {report.config_hash}  "
        f"{report.started_at:%Y-%m-%d %H:%M} UTC",
        *_models(report.models),
        f"scenarios: {report.scenarios_dir} (repeat {report.repeat})",
        "",
        f"{'scenario':<{width}}  {'run':>3}  {'agree':<5}  {'outcome':<24} "
        f"{'gate':<{GATE_WIDTH}}  {'time':>7}  {'calls':>5}  {'tokens':>6}",
    ]
    for scenario in report.scenarios:
        for run in scenario.runs:
            agree, outcome = _outcome(run)
            gate, reason = _gate(run)
            row = (
                f"{scenario.name:<{width}}  {run.repeat:>3}  {agree:<5}  {outcome:<24} "
                f"{gate:<{GATE_WIDTH}}  {run.duration_s:>6.1f}s  {run.calls:>5}  "
                f"{run.tokens_in + run.tokens_out:>6}"
            )
            lines.append(f"{row}  {reason}" if reason else row)
    lines += [
        "",
        f"full agreement {_pct(s.full_agreement)}",
        f"gate agreement {_pct(s.gate_agreement)}",
        f"rule-failure agreement {_pct(s.rule_agreement)}",
        f"state agreement {_pct(s.state_agreement)}",
        f"runs {s.runs}, errors {s.errors}, tokens in {s.tokens_in}, out {s.tokens_out}, "
        f"{s.duration_s:.1f}s",
    ]
    noisy = {rid: t for rid, t in report.rules.items() if t.missed or t.unexpected}
    if noisy:
        lines += ["", "rules with misses or unexpected failures"]
        for rid, t in noisy.items():
            lines.append(
                f"  {rid}: expected {t.expected}, hit {t.hit}, missed {t.missed}, "
                f"unexpected {t.unexpected}"
            )
    mismatched = [
        (sc.name, run) for sc in report.scenarios for run in sc.runs if run.ok and run.mismatches
    ]
    if mismatched:
        lines += ["", "mismatches"]
        for name, run in mismatched:
            lines.append(f"  {name} run {run.repeat}:")
            lines += [f"    {m}" for m in run.mismatches]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 5: Regenerate the exported schema**

Run: `make schema && git status --short schema web/src/api`
Expected: exactly ` M schema/bench-report.schema.json` (the new `GateResult` def and `RunResult.gate`); nothing else listed (R-M12-7).

- [ ] **Step 6: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/bench tests/test_cli_bench.py tests/schema --no-cov -q`
Expected: PASS (`test_committed_schema_matches_models` reads the regenerated file).

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m12-task5-commit.txt <<'EOF'
feat: bench table and bench.json show the gate's verdict (CRL-28)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/bench/schema.py engine/corelata/bench/score.py engine/corelata/bench/text.py engine/tests/bench/test_text.py engine/tests/bench/test_score.py schema/bench-report.schema.json
git commit -F <scratchpad>/m12-task5-commit.txt
```

---

### Task 6: The real-model scenario set and `--scenarios synthetic|real|DIR` (CRL-28, R-M12-4)

The rehearsal measured agreement with the synthetic responder's markers ("UNSOURCED UNFIXABLE detail on Varna.") rather than model quality: a real gate rightly rejects them. The real set has short, plausible sources (invented places and organisations, no persons) and expectations a good model meets.

**Files:**
- Create: `engine/corelata/bench/scenarios-real/{conflicting-rail-figures,corroborated-port-expansion,mixed-relevance-sources,off-topic-sources,overreaching-statement,quarterly-throughput-figures,thin-harvest-outlook,unverified-social-post}.yaml`
- Modify: `engine/corelata/bench/__init__.py` (whole file), `engine/corelata/cli.py` (import line 18; `--scenarios` lines 179-181), `engine/pyproject.toml` (artifacts, after line 42), `deploy/tests/check-app-image.sh` (line 26)
- Test: `engine/tests/bench/test_package_data.py` (whole file), `engine/tests/test_scenarios.py` (imports; append), `engine/tests/test_cli_bench.py` (import line 10; append)

**Interfaces:**
- Consumes: `ScenarioExpect` range fields (Task 4); `RunResult.gate` (Task 5) in the CLI test.
- Produces: `bench.REAL_SCENARIOS_DIR: Path`, `bench.SCENARIO_SETS: dict[str, Path]` (`{"synthetic": SCENARIOS_DIR, "real": REAL_SCENARIOS_DIR}`), `bench.scenarios_path(value: str) -> Path`. `corelata bench --scenarios` defaults to `synthetic`.

- [ ] **Step 1: Failing tests**

Replace `engine/tests/bench/test_package_data.py` with:

```python
import tomllib
from pathlib import Path

from corelata.bench import REAL_SCENARIOS_DIR, SCENARIO_SETS, SCENARIOS_DIR, scenarios_path
from corelata.scenarios import load_scenarios

REAL_NAMES = [
    "conflicting-rail-figures",
    "corroborated-port-expansion",
    "mixed-relevance-sources",
    "off-topic-sources",
    "overreaching-statement",
    "quarterly-throughput-figures",
    "thin-harvest-outlook",
    "unverified-social-post",
]


def test_shipped_scenarios_load_and_are_the_known_set():
    names = [s.name for s in load_scenarios(SCENARIOS_DIR)]
    assert names == [
        "badterm-fixed-one-loop",
        "clean-single-source",
        "clean-two-sources",
        "gate-rejected",
        "long-source-digested",
        "many-sources-writer-budget",
        "max-iterations-zero",
        "thin-material",
        "unsourced-fixed-one-loop",
        "unsourced-unfixable",
    ]
    assert all(p.suffix == ".yaml" for p in SCENARIOS_DIR.iterdir() if p.is_file())


def test_the_real_set_ships_in_the_wheel_beside_the_synthetic_set():
    names = [s.name for s in load_scenarios(REAL_SCENARIOS_DIR)]
    assert names == REAL_NAMES
    assert set(names).isdisjoint(s.name for s in load_scenarios(SCENARIOS_DIR))
    assert all(p.suffix == ".yaml" for p in REAL_SCENARIOS_DIR.iterdir() if p.is_file())
    assert SCENARIO_SETS == {"synthetic": SCENARIOS_DIR, "real": REAL_SCENARIOS_DIR}
    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    artifacts = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]
    assert "corelata/bench/scenarios-real/*.yaml" in artifacts


def test_scenarios_path_resolves_set_names_before_paths():
    assert scenarios_path("synthetic") == SCENARIOS_DIR
    assert scenarios_path("real") == REAL_SCENARIOS_DIR
    assert scenarios_path("./real") == Path("./real")  # a directory that is called real
    assert scenarios_path("/srv/scenarios") == Path("/srv/scenarios")
```

In `engine/tests/test_scenarios.py`, replace the import block (lines 1-18 as Task 4 left it) with:

```python
import pytest
import yaml

from corelata.bench import REAL_SCENARIOS_DIR, SCENARIOS_DIR
from corelata.llm.agent import CallLog
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import (
    Scenario,
    ScenarioError,
    audited_iterations,
    compare,
    load_scenario,
    load_scenarios,
    run_scenario,
    scenario_sources,
)
from corelata.schema import RunState
from corelata.standards.loader import load_pack
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.sources import text_source
```

and append:

```python
REAL = load_scenarios(REAL_SCENARIOS_DIR)


def test_the_real_set_is_written_for_real_models():
    assert len(REAL) == 8
    rule_ids = set(load_pack("icd203-base").rule_ids())
    for s in REAL:
        e = s.expect
        assert "A good model" in s.description and "A weak model" in s.description, s.name
        assert all(2 <= len(src.paragraphs) <= 3 for src in s.sources), s.name
        assert not e.failing_rules, s.name  # rule expectations are sets, never exact per iteration
        named = set(e.rules_must_pass) | set(e.rules_may_fail or []) | set(e.rules_must_fail)
        assert named <= rule_ids, s.name
        if e.state is not RunState.GATE_REJECTED:  # a run that may deliver names what must pass
            assert e.rules_must_pass, s.name
        assert e.expects_gate() or e.state_in, s.name


@pytest.mark.parametrize("scenario", REAL, ids=[s.name for s in REAL])
async def test_every_real_scenario_runs_to_an_outcome_on_the_synthetic_model(scenario, make_config):
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert record.state in (RunState.COMPLETED, RunState.GATE_REJECTED), record.error
    assert record.gate is not None
    assert isinstance(compare(scenario, record), list)  # scoring never raises on these records
```

In `engine/tests/test_cli_bench.py`, replace line 10 (`from corelata.bench import SCENARIOS_DIR`) with:

```python
from corelata.bench import REAL_SCENARIOS_DIR, SCENARIOS_DIR
```

and append:

```python
def test_bench_plays_a_shipped_set_by_name(config_path, capsys):
    argv = ["bench", "--config", str(config_path), "--json"]
    rc = main([*argv, "--scenarios", "real", "--only", "off-topic-sources"])
    data = json.loads(capsys.readouterr().out)
    # the synthetic gate supports any statement whose words appear in the sources, so it
    # disagrees with a set written for real models: exit 3, not an error
    assert rc == 3
    assert data["scenarios_dir"] == str(REAL_SCENARIOS_DIR)
    [scenario] = data["scenarios"]
    [run] = scenario["runs"]
    assert scenario["name"] == "off-topic-sources"
    assert "state: expected 'gate_rejected', got 'completed'" in run["mismatches"]
    assert run["gate"]["supported"] is True and run["gate"]["reasons"]
    assert main([*argv, "--scenarios", "synthetic", "--only", "gate-rejected"]) == 0
    assert json.loads(capsys.readouterr().out)["scenarios_dir"] == str(SCENARIOS_DIR)


def test_bench_help_names_the_sets(capsys):
    with pytest.raises(SystemExit):
        main(["bench", "--help"])
    out = capsys.readouterr().out
    assert "'synthetic'" in out and "'real'" in out
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/bench/test_package_data.py tests/test_scenarios.py tests/test_cli_bench.py --no-cov -q`
Expected: the three files fail to import `REAL_SCENARIOS_DIR`.

- [ ] **Step 3: The set names**

Replace `engine/corelata/bench/__init__.py` with:

```python
"""`corelata bench` (spec §13, §14 M6): the shipped scenario sets and the runner that plays them
against real models. Only the data paths live here; the runner is `corelata.bench.run`, the
result schema `corelata.bench.schema`, so importing the package never imports the pipeline.
Two sets ship (R-M12-4): `synthetic`, written for the synthetic model's markers and the one CI
runs, and `real`, written for real models."""

from pathlib import Path

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
REAL_SCENARIOS_DIR = Path(__file__).parent / "scenarios-real"
SCENARIO_SETS: dict[str, Path] = {"synthetic": SCENARIOS_DIR, "real": REAL_SCENARIOS_DIR}


def scenarios_path(value: str) -> Path:
    """`--scenarios`: a shipped set by name, else a directory path (write `./real` for a
    directory that happens to be called `real`)."""
    return SCENARIO_SETS.get(value, Path(value))
```

In `engine/corelata/cli.py`, replace line 18 (`from corelata.bench import SCENARIOS_DIR`) with:

```python
from corelata.bench import scenarios_path
```

and replace the `--scenarios` argument (lines 179-181) with:

```python
    bench.add_argument(
        "--scenarios",
        type=scenarios_path,
        default="synthetic",
        help="'synthetic' (the default; the set CI runs), 'real' (written for real models) or a "
        "directory of scenario YAML files",
    )
```

(argparse applies `type` to a string default, so `args.scenarios` is always a `Path`.)

In `engine/pyproject.toml`, after line 42 (`  "corelata/bench/scenarios/*.yaml",`) add:

```toml
  "corelata/bench/scenarios-real/*.yaml",
```

In `deploy/tests/check-app-image.sh`, replace line 26:

```sh
  ingest/vendor/coglossa-report-1.schema.json bench/scenarios/clean-single-source.yaml; do
```

with:

```sh
  ingest/vendor/coglossa-report-1.schema.json bench/scenarios/clean-single-source.yaml \
  bench/scenarios-real/corroborated-port-expansion.yaml; do
```

- [ ] **Step 4: The eight scenarios**

Create `engine/corelata/bench/scenarios-real/corroborated-port-expansion.yaml`:

```yaml
name: corroborated-port-expansion
description: >-
  Three independent sources that agree (the Tarvos port authority, Kelmar's chamber of commerce
  and a forwarders' survey), with dates and figures, support the statement. A good model passes
  the gate as sufficient, cites a unit for every fact and judgment, weighs Kelmar's planned 2027
  dredging as the alternative and delivers a clean report within one revision. A weak model
  leaves its analytic judgments uncited (icd203.tc.8, icd206.src.2), drops the alternative
  (icd203.tc.4) or spends every revision.
statement: The expansion of Tarvos container port is drawing regional shipping away from Kelmar
sources:
  - id: src1
    name: tarvos-port-authority-bulletin.txt
    paragraphs:
      - >-
        Tarvos Port Authority, quarterly bulletin, 3 July 2026. The second container terminal at
        Tarvos (Terminal B) entered full service on 12 May 2026, raising the port's annual
        handling capacity from 1.1 million to 1.9 million TEU.
      - >-
        Container throughput in April to June 2026 reached 352,000 TEU, 38 percent more than in
        the same quarter of 2025. The authority attributes most of the rise to three Asia-Europe
        services that moved their regional call from Kelmar to Tarvos in May.
      - >-
        Average waiting time for container ships at anchor fell from 31 hours in the first
        quarter to 9 hours in the second.
  - id: src2
    name: kelmar-chamber-statement.txt
    paragraphs:
      - >-
        Kelmar Chamber of Commerce, press statement, 18 July 2026. Container volumes at Kelmar in
        June 2026 were 61,000 TEU, 22 percent below June 2025 and the steepest monthly fall since
        the port opened its deep-water berth in 2019.
      - >-
        The Chamber names the move of the Orion Line and Marisco services to Tarvos as the main
        cause, and warns that a third service, the Halden Express, is reviewing its Kelmar call
        for the winter schedule.
  - id: src3
    name: forwarders-survey.md
    paragraphs:
      - >-
        Northern Freight Forwarders Association, member survey published 25 July 2026; 142 firms
        responded. 61 percent said they had moved at least some regional import volume from
        Kelmar to Tarvos since May.
      - >-
        The reasons most often given were shorter waiting times (74 percent of those who moved)
        and the new rail shuttle from Tarvos to the inland terminal at Dorran (52 percent). 19
        percent expect to move volume back if Kelmar completes its planned berth dredging in 2027.
expect:
  state: completed
  status_in: [clean]
  iterations_max: 1
  gate_supported_in: [true]
  substance_in: [sufficient]
  rules_must_pass: [icd203.tc.8, icd206.src.2, icd206.src.1, icd203.tc.4]
```

Create `engine/corelata/bench/scenarios-real/thin-harvest-outlook.yaml`:

```yaml
name: thin-harvest-outlook
description: >-
  One ministry outlook says the harvest and July's export licences are down but says nothing
  about Tarvos or any port. A good model passes the gate as thin (or rejects it as
  insufficient), and if it writes, carries the gate's scope sentence, keeps confidence low or
  moderate, expresses the uncertainty (icd203.tc.2) and cites both paragraphs. A weak model
  calls the material sufficient and states a port-level fall the source never gives.
statement: Calvadian grain exports through Tarvos will fall sharply this harvest season
sources:
  - id: src1
    name: agriculture-ministry-outlook.txt
    paragraphs:
      - >-
        Calvadia Ministry of Agriculture, crop outlook, 2 August 2026. The wheat harvest is
        forecast at 4.2 million tonnes, 15 percent below 2025, after a dry June in the eastern
        provinces.
      - >-
        The ministry does not forecast exports by port. Grain export licences issued in July 2026
        were 9 percent below July 2025.
expect:
  state_in: [completed, gate_rejected]
  substance_in: [thin, insufficient]
  rules_must_pass: [icd203.tc.8, icd206.src.2, icd203.tc.2]
```

Create `engine/corelata/bench/scenarios-real/off-topic-sources.yaml`:

```yaml
name: off-topic-sources
description: >-
  Both sources are about the Tarvos port authority and the harbour, but neither mentions
  ownership, a sale or privatisation. A good model rejects at the gate (supported false) and its
  reasons say the sources do not address the statement. A weak model accepts because the names
  match and writes a report that speculates about a sale.
statement: The Tarvos Port Authority plans to privatise its container terminals
sources:
  - id: src1
    name: tarvos-cruise-season.txt
    paragraphs:
      - >-
        Tarvos Port Authority, press release, 14 June 2026. The cruise season opened with 41 calls
        scheduled between June and September, eight more than in 2025.
      - >-
        A new canopy for the passenger terminal, paid for by the city of Tarvos, will be finished
        in August. The authority expects 96,000 cruise passengers this year.
  - id: src2
    name: harbour-master-notice.txt
    paragraphs:
      - >-
        Notice to fishing vessels, Tarvos harbour master, 20 June 2026. The inner fishing basin
        will be closed for dredging from 1 to 19 September 2026.
      - >-
        Vessels under 12 metres may use the temporary pontoons at the north mole during the
        closure.
expect:
  state: gate_rejected
  gate_supported: false
```

Create `engine/corelata/bench/scenarios-real/conflicting-rail-figures.yaml`:

```yaml
name: conflicting-rail-figures
description: >-
  The rail operator reports steady growth on the new Tarvos-Dorran shuttle; the inland
  terminal's log shows July below June, with cancelled trains and more road traffic. A good
  model passes the gate, judges growth since May with moderate or low confidence, cites both
  sources and offers the alternative that growth stalled in July (icd203.tc.4). A weak model
  repeats the operator's claim with high confidence and ignores the terminal log (icd203.as.4,
  icd203.tc.2).
statement: >-
  Rail freight between Tarvos and the Dorran inland terminal has grown since the shuttle
  service began
sources:
  - id: src1
    name: calrail-press-release.txt
    paragraphs:
      - >-
        Calrail Cargo, press release, 10 August 2026. Since the Tarvos-Dorran container shuttle
        began on 2 May 2026 it has run 168 trains carrying 14,800 containers.
      - >-
        Calrail says weekly trains rose from 9 in May to 16 in late July, and it will add a third
        daily path in October.
  - id: src2
    name: dorran-terminal-log.txt
    paragraphs:
      - >-
        Dorran Inland Terminal, monthly operations summary, July 2026. Rail arrivals from Tarvos:
        41 trains and 2,950 containers in July, against 44 trains and 3,300 containers in June.
      - >-
        Six scheduled July trains were cancelled for lack of locomotives. Road arrivals from
        Tarvos rose 11 percent over the same month.
expect:
  state: completed
  gate_supported_in: [true]
  substance_in: [thin, sufficient]
  rules_must_pass: [icd203.tc.8, icd206.src.2, icd203.tc.4]
  rules_may_fail: [icd203.as.5, icd203.tc.1, icd203.tc.3, icd203.tc.5, icd203.tc.6]
```

Create `engine/corelata/bench/scenarios-real/overreaching-statement.yaml`:

```yaml
name: overreaching-statement
description: >-
  The statement asserts a decision the sources only say is under review, and the operator's own
  advisory says every call stays in place for now. A good model rejects at the gate or passes it
  as thin, and if it writes, scopes the report to the review and uses a likelihood term no
  stronger than "roughly even chance" (icd203.tc.2). A weak model calls the material sufficient
  and reports the withdrawal as fact.
statement: The Halden Express will stop calling at Kelmar from this winter
sources:
  - id: src1
    name: kelmar-chamber-statement.txt
    paragraphs:
      - >-
        Kelmar Chamber of Commerce, press statement, 18 July 2026. The Chamber warns that the
        Halden Express, a weekly feeder service, is reviewing its Kelmar call for the winter
        schedule.
      - >-
        The Chamber has asked the port company to cut berth fees by 10 percent for services that
        commit to Kelmar until March 2027.
  - id: src2
    name: halden-line-advisory.txt
    paragraphs:
      - >-
        Halden Line, customer advisory, 1 August 2026. The winter 2026-27 schedule will be
        published on 15 September. All current port calls remain in place until further notice.
      - >-
        Customers should book October sailings through the usual channels; no surcharge changes
        are planned.
expect:
  state_in: [completed, gate_rejected]
  substance_in: [thin, insufficient]
  rules_must_pass: [icd203.tc.8, icd206.src.2, icd203.tc.2]
```

Create `engine/corelata/bench/scenarios-real/unverified-social-post.yaml`:

```yaml
name: unverified-social-post
description: >-
  An unverified social media post predicts a strike; the union's own notice only calls a
  meeting on shift patterns. A good model passes the gate as thin (or rejects it), describes the
  post as unverified (icd203.tc.1) and keeps the scheduled meeting (a fact) apart from a strike
  (an assumption or a low-confidence judgment, icd203.tc.3). A weak model treats the post as
  confirmation and reports a planned strike with high confidence.
statement: Dockworkers at Tarvos are preparing a strike over the Terminal B shift system
sources:
  - id: src1
    name: social-post-translation.txt
    paragraphs:
      - >-
        Translated social media post by the account tarvos_docks_news (unverified, about 2,300
        followers), 21 July 2026: "Terminal B crews are fed up with the 12-hour rotation.
        Thursday's union meeting will vote on action. Expect trouble before September."
      - >-
        The post links to no union statement. One reply shows a photo of a meeting notice whose
        date cannot be read.
  - id: src2
    name: union-branch-notice.txt
    paragraphs:
      - >-
        Port and Harbour Workers' Union, Tarvos branch, notice dated 19 July 2026. Members are
        invited to a branch meeting on 24 July to discuss shift patterns at Terminal B.
      - >-
        The notice does not mention industrial action. The branch's last strike ballot was held
        in 2023.
expect:
  state_in: [completed, gate_rejected]
  substance_in: [thin, insufficient]
  rules_must_pass: [icd203.tc.8, icd206.src.2, icd203.tc.1, icd203.tc.3]
```

Create `engine/corelata/bench/scenarios-real/mixed-relevance-sources.yaml`:

```yaml
name: mixed-relevance-sources
description: >-
  One source backs the statement with before-and-after figures; the other, a city budget
  extract, is beside the point. A good model passes the gate, cites the port bulletin for every
  figure, still lists the budget extract under sources and says in the scope note why it was set
  aside (icd206.src.1, icd203.as.4), and weighs another cause for the shorter waits as an
  alternative. A weak model cites the budget for claims it does not support or leaves it out of
  the sources.
statement: Terminal B has cut vessel waiting times at Tarvos
sources:
  - id: src1
    name: tarvos-port-authority-bulletin.txt
    paragraphs:
      - >-
        Tarvos Port Authority, quarterly bulletin, 3 July 2026. Terminal B entered full service
        on 12 May 2026 with four ship-to-shore cranes.
      - >-
        Average waiting time for container ships at anchor fell from 31 hours in January to
        March 2026 to 9 hours in April to June. Berth productivity rose from 24 to 29 crane moves
        per hour over the same period.
  - id: src2
    name: city-budget-extract.txt
    paragraphs:
      - >-
        City of Tarvos, draft budget for 2027, published 30 July 2026. Capital spending on roads
        near the port rises to 18 million.
      - >-
        The budget also funds a library in the old customs house and a cycle lane along the
        harbour front.
expect:
  state: completed
  iterations_max: 1
  gate_supported_in: [true]
  substance_in: [thin, sufficient]
  rules_must_pass: [icd203.tc.8, icd206.src.2, icd206.src.1, icd203.as.4]
```

Create `engine/corelata/bench/scenarios-real/quarterly-throughput-figures.yaml`:

```yaml
name: quarterly-throughput-figures
description: >-
  Two official releases give each port's second-quarter throughput. A good model passes the
  gate as sufficient, writes one fact claim per figure citing its own unit, labels any
  comparison it computes as a judgment (icd203.tc.3) and delivers a clean report within one
  revision. A weak model mixes up the two ports' figures, cites the wrong unit or presents a
  computed ratio as a sourced fact.
statement: Tarvos handled more containers than Kelmar in the second quarter of 2026
sources:
  - id: src1
    name: tarvos-quarterly-bulletin.txt
    paragraphs:
      - >-
        Tarvos Port Authority, quarterly bulletin, 3 July 2026. Container throughput in April to
        June 2026 was 352,000 TEU: 104,000 in April, 118,000 in May and 130,000 in June.
      - >-
        Transshipment made up 41 percent of the quarter's volume, against 33 percent a year
        earlier.
  - id: src2
    name: kelmar-statistics-release.txt
    paragraphs:
      - >-
        Kelmar Port Company, statistics release, 9 July 2026. Container throughput in April to
        June 2026 was 198,000 TEU, 17 percent less than a year earlier.
      - >-
        June alone was 61,000 TEU. Bulk cargo rose 4 percent over the quarter to 2.3 million
        tonnes.
expect:
  state: completed
  status_in: [clean]
  iterations_max: 1
  gate_supported_in: [true]
  substance_in: [sufficient]
  rules_must_pass: [icd203.tc.8, icd206.src.2, icd206.src.1, icd203.tc.3]
```

- [ ] **Step 5: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/bench tests/test_scenarios.py tests/test_cli_bench.py --no-cov -q`
Expected: PASS. On the synthetic model every real scenario completes (its gate finds the statement's words in the sources); that is expected and is why CI does not score this set.

Run: `cd engine && uv build --wheel --out-dir <scratchpad>/m12-wheel && unzip -l <scratchpad>/m12-wheel/corelata-*.whl | grep -c scenarios-real/`
Expected: `8`.

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m12-task6-commit.txt <<'EOF'
feat: bench scenarios for real models, --scenarios synthetic|real|DIR (CRL-28)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/bench/__init__.py engine/corelata/bench/scenarios-real engine/corelata/cli.py engine/pyproject.toml deploy/tests/check-app-image.sh engine/tests/bench/test_package_data.py engine/tests/test_scenarios.py engine/tests/test_cli_bench.py
git commit -F <scratchpad>/m12-task6-commit.txt
```

---

### Task 7: Docs

**Files:**
- Modify: `README.md` (new `## M12` section before `## Development`, line 217; M6 paragraph lines 142-150; Development paragraph lines 224-227), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (after lines 321, 426, 529), `docs/operator-guide.md` (step 4, lines 90-92; the bench paragraphs, lines 452-468; section 11 row, line 596), `docs/m11-followups.md` (three bullets), `docs/m7-followups.md` (line 42)
- Create: `docs/m12-followups.md`

- [ ] **Step 1: README**

Insert before `## Development` (line 217):

```markdown
## M12: writer evidence enum, doctor probes, bench scenarios for real models

The rehearsal against OpenRouter (CRL-1) found three gaps. The writer's and conveyor's schema now
restricts `Claim.evidence` to the run's unit ids (one `UnitRef` enum built per call; plain strings
above 200 units), so a `json_schema` server cannot let a model cite `src1` as a unit (CRL-29); the
auditor's unit and claim enums are emitted once each. `corelata doctor` prints how many models a
server serves and whether each configured model is among them, never the whole list, and its
structured-output probe asks for a real gate verdict with the request a run sends, so it fails
when a run's schema would be rejected (CRL-27). `corelata bench --scenarios real` plays eight
scenarios written for real models: short sources with dates, actors and figures, and
expectations stated as ranges and rule sets (`state_in`, `substance_in`, `rules_must_pass`, …);
the synthetic set stays the default and the one CI runs. The bench table shows the gate's verdict
and, when it disagrees, its first reason; `bench.json` keeps the verdict per run, and a run whose
audit degraded scores as "no audit ran" (CRL-28).

```

Replace the M6 paragraph that begins "`bench` plays the shipped scenario set" (lines 142-150) with:

```markdown
`bench` plays a scenario set against the configured models and reports agreement with each
scenario's expectations: full agreement (nothing to object to), gate agreement, rule-failure
agreement, state agreement, and a per-rule tally of misses and unexpected failures.
`--scenarios synthetic` (the default; `engine/corelata/bench/scenarios/`) is the set written for
the synthetic model's markers, `--scenarios real` (`engine/corelata/bench/scenarios-real/`, M12)
the set written for real models, and `--scenarios DIR` any directory. `--only NAME` (repeatable)
picks scenarios, `--repeat N` plays each scenario N times; `--out DIR` keeps `bench.json` and
every run's `trace.json` (a re-run into the same directory replaces the traces of the scenarios it
runs); `--json` prints the report. `--concurrency N` runs up to N scenario runs at once (the
backend's `max_concurrency` still caps the server), `--store-io` keeps the model requests and
responses in the traces for diagnosing a disagreement, and `bench.json` is rewritten after every
finished run, so Ctrl-C keeps what finished. Exit 0 means full agreement, 3 some disagreement, 1 a
run that errored, 2 a usage error. A real model disagrees with the synthetic set often, which says
little about it; the real set is how you measure a model or a prompt change. Neither is a
pass/fail gate.
```

Replace the Development paragraph that begins "Scenario fixtures" (lines 224-227) with:

```markdown
Scenario fixtures (`engine/corelata/bench/scenarios/*.yaml`) pin the pipeline's behaviour
against the synthetic model: sources, statement, expected gate verdict, failing rules per
iteration. They ship inside the package so `corelata bench` can play them against real models
(see M6). Add one when you change what a run does. The real-model set
(`engine/corelata/bench/scenarios-real/*.yaml`) states ranges and rule sets instead; CI only checks
that it loads and runs to an outcome on the synthetic model.
```

- [ ] **Step 2: Spec amendments**

§8.1, after line 321 ("Validation at the schema level: …"):

```markdown

M12 amendment (CRL-29): the writer and the conveyor send a per-call variant of `ReportBody`
(`stages/report_schema.py`) whose `Claim.evidence` items are an enum of the run's unit ids (every
unit of every source, as the validator accepts; plain strings above 200 units, an empty list when
there are none), so a `json_schema` server enforces the unit-id rule while generating. The reply
is converted to `ReportBody` before validation and storage; the validators still check it for
`json_object` and `none` servers.
```

§10.2, after line 426:

```markdown

M12 amendment (CRL-27): `doctor`'s backend check reports how many models the server serves and,
for each configured model on that backend, whether it is served; a missing model's fix names up
to five served ids with the same prefix. Its structured-output probe sends the gate's
`GateVerdict` schema through the request builder the stages use and passes only on a reply that
parses as one.
```

§13, after line 529 (the M6 amendment to the scenario-fixtures bullet):

```markdown

  *M12 amendment (CRL-28):* a second set, `engine/corelata/bench/scenarios-real/`, is written for
  real models: short invented sources with dates, actors and figures, and expectations stated as
  ranges and rule sets (`state_in`, `status_in`, `iterations_max`, `gate_supported_in`,
  `substance_in`, `rules_must_pass`, `rules_may_fail`, `rules_must_fail`). `corelata bench
  --scenarios synthetic|real|DIR` picks the set (default `synthetic`; CI scores only that one).
  An iteration whose audit degraded (M11) counts as not audited. Each run in `bench.json` keeps
  the gate's verdict.
```

- [ ] **Step 3: Operator guide**

Replace step 4's paragraph (lines 90-92):

```markdown
   `doctor` checks the configuration, the database, the files volume, the standards pack and each
   model server (it sends each one a small test completion). Every check must pass; a failing
   check says what to fix. Add `--no-probe` to skip the test completions.
```

with:

```markdown
   `doctor` checks the configuration, the database, the files volume, the standards pack and each
   model server. For a server it reports how many models it serves and whether each model you
   configured is among them (a missing one's fix suggests up to five ids with the same prefix);
   then it sends each model a small test completion and, for a model set to `json_schema` or
   `json_object`, asks for a real gate verdict with the same request a run sends, so a server
   that would reject a run's schema fails here, with the server's own error. Every check must
   pass; a failing check says what to fix. Add `--no-probe` to skip the test completions.
```

Replace the two bench paragraphs and their command block (lines 452-468, from "**Checking a model with the bench.**" to "…several dozen model calls."):

````markdown
**Checking a model with the bench.** `corelata bench` plays a set of scenario files against the
configured models and reports how often the run did what the scenario expects: gate verdict,
failing rules, final state. Two sets ship with the engine. `synthetic` (the default, ten
scenarios) was written for the synthetic model and steers it with markers in the source text; a
real model disagrees with it often, and that says little about the model. `real` (eight
scenarios) has short, plausible sources and expectations a good model meets, stated as ranges
("thin or sufficient", "these rules must pass"); use it when you change a model, a prompt
override or the pack, and compare the numbers with the previous run:

```sh
docker compose exec api corelata bench --scenarios real --out /data/files/bench-real-$(date +%F)
docker compose exec api corelata bench --scenarios real --only conflicting-rail-figures --repeat 3
docker compose exec api corelata bench --concurrency 4 --store-io --out /data/files/bench-$(date +%F)
```

The table's `gate` column shows the gate's verdict (`supported · thin`, `rejected ·
insufficient`) and, when it disagrees with the scenario, the gate's first reason. An interrupted
bench leaves a `bench.json` with the runs that finished. `--scenarios DIR` plays a directory of
your own (for a directory called `real` or `synthetic`, write `./real`).

Exit 0 means every run matched, 3 that some disagreed (listed at the end of the report), 1 that a
run could not execute (the scenario's profile is missing, for example). The bench is a
measurement, not a gate. A run of either set makes several dozen model calls.
````

In section 11, replace the row `| \`doctor\` fails on a backend | … |` (line 596) with:

```markdown
| `doctor` fails on a backend or a model | The URL (ends in `/v1`; reachable from a container), the model id (the fix suggests up to five ids the server serves with the same prefix; the whole list is `curl <base_url>/models`) or `api_key_env` (the variable must be in `.env`; recreate the services). "json_schema request failed: … invalid_json_schema" means the server rejects the schema a run sends: set that model's `structured_output` to `json_object`. "the GateVerdict reply was cut at max_tokens=N" means the model ran out of output tokens (reasoning models spend some before they answer): raise its `max_output_tokens`. |
```

- [ ] **Step 4: Follow-ups**

In `docs/m11-followups.md`, "Should fix soon": the bullet ending "…as the auditor's schema now does." becomes "…as the auditor's schema now does. — **closed in M12** (CRL-29, `stages/report_schema.py`)", and the bullet ending "…recognise a degraded iteration from `metadata.degradations`." becomes "…recognise a degraded iteration from `metadata.degradations`. — **closed in M12** (CRL-28, `scenarios.audited_iterations`)". "Later": the bullet "The unit-ref enum is emitted twice in the schema; hoist it into one `$def` with a dynamic Enum." becomes "… with a dynamic Enum. — **closed in M12** (`audit_schema.enum_list`)". Nothing else in the file changes (R-M12-7).

In `docs/m7-followups.md`, line 42 becomes:

```markdown
- Scenarios written for real models (needs its own ticket, after the deployment dry run BORG-34). — **closed in M12** (CRL-28: `engine/corelata/bench/scenarios-real/`, `corelata bench --scenarios real`)
```

Create `docs/m12-followups.md`:

```markdown
# M12 follow-ups

## Divergences from Coglossa

- `corelata doctor`'s backend check prints a count and the configured models' found/missing state
  instead of the served list, and a missing model's fix names up to five same-prefix ids —
  **backport**: Coglossa's doctor prints the whole list too (one 468-id line on OpenRouter).
- The structured-output probe sends a real output schema (`GateVerdict`) through the request
  builder the stages use (`llm/agent.py` `request_messages`, `build_request`, extracted from the
  copied `AgentRunner.run`) — **backport**: Coglossa's probe schema has no optional field either,
  so it passes against a strict server that rejects its real schemas.
- The per-call `ReportBody` (`stages/report_schema.py`), the range expectations and the real-model
  scenario set — Corelata only.

## Spec deviations

- None. §8.1, §10.2 and §13 carry M12 amendments.

## Rulings during execution

- None yet; number new ones from R-M12-8. How the plan applied R-M12-1 to R-M12-7 is in its
  Global Constraints ("How the plan applies them").

## Should fix soon

- The doctor probes only the gate's schema, the smallest. A server limit on schema size or enum
  length (the writer's `UnitRef` enum, up to 200 values; the auditor's one required property per
  rule) shows only in a run. Probe the auditor's schema for a small fixed pack as well.
- `SourceEntry.source_id` is a free string in the writer's schema; an enum of the run's source
  ids (the validator already requires one entry per source) would stop an invented source id the
  same way `UnitRef` stops an invented unit.

## Later

- The conveyor may not add or remove claims, so its schema could enumerate the draft's claim ids
  in `key_judgments`, `analysis` and `alternatives` as well.
- `rules_must_fail` is unused by the shipped real set: no real-model scenario has a failure a good
  writer cannot avoid. Add one if the customer's pack gains a rule their material always trips.
- The real set is English, short and port-and-logistics themed. The customer's own material, when
  they give any, would make a better set, played with `--scenarios DIR`.
- `--scenarios real` shadows a directory named `real` in the working directory (write `./real`).
- `ENUM_LIMIT` (200) now also caps the writer's enum: a run with more units sends plain strings
  and relies on the validator. Measure constrained decoding with a 500-unit run before raising it.
- `bench.json` keeps the gate's reasons whole; the table cuts the first to 60 characters.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint && git diff --stat main -- docs/m10-followups.md web api`
Expected: lint clean; the diff prints nothing.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m12-task7-commit.txt <<'EOF'
docs: M12 README section, spec amendments, operator notes, follow-ups

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/operator-guide.md docs/m11-followups.md docs/m7-followups.md docs/m12-followups.md
git commit -F <scratchpad>/m12-task7-commit.txt
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine
make test-api
make test-web       # unchanged; proves nothing in web/ moved
make e2e            # the Playwright journey runs on the synthetic model through the new writer schema
make deploy-check   # the image must carry bench/scenarios-real/ (check-app-image.sh)
git diff --stat main -- schema web/src/api/schema.d.ts   # only schema/bench-report.schema.json (R-M12-7)
```

CI must be green on all six jobs (engine, api, web, e2e, deploy-check, airgap) before the merge.

## Live rehearsal (the controller runs this after the merge; not a task)

Against the CRL-1 OpenRouter configuration (`gate`/`writer` on `openai/gpt-4.1-mini`, `conveyor`/`auditor` on `google/gemini-2.5-flash`, every model `structured_output: json_schema`; use the same file as the rehearsal on 2026-10-16). `corelata doctor` probes by default; there is no `--probe` flag (`--no-probe` skips the probes).

- [ ] `corelata doctor --config <openrouter.yaml>`. Expect the backend line to read `serves <N> models; <key> → openai/gpt-4.1-mini found; <key> → google/gemini-2.5-flash found` (one line, no served ids), and each model check `test completion succeeded; json_schema output works (GateVerdict)`. Record N and the line's length.
- [ ] Set one model's `name` to `openai/gpt-4.1-mni`, run `corelata doctor --no-probe`, and check the fix lists at most five `openai/…` ids; restore the name.
- [ ] `corelata bench --config <openrouter.yaml> --scenarios synthetic --out bench-m12-synthetic/`. Expect roughly the baseline below (the synthetic set is unchanged); check that each `gate_rejected` row's `gate` column reads `rejected · insufficient` or `supported · …` with the gate's first reason.
- [ ] `corelata bench --config <openrouter.yaml> --scenarios real --store-io --out bench-m12-real/`. Record the numbers below. In a trace, `grep -c "is not a unit id" bench-m12-real/*/run-1/trace.json` should be 0 for writer and conveyor calls (the schema now stops a source id cited as a unit).
- [ ] Fill in the table and add it to Jira CRL-28 (and close CRL-27 and CRL-29 with the doctor and trace evidence).

| Measure | Baseline (CRL-28, synthetic set, 2026-10-16) | M12 synthetic set | M12 real set |
|---|---|---|---|
| Scenarios / runs / errors | 10 / 10 / 0 | | 8 / 8 / |
| Duration | 76 s | | |
| Full agreement | 2/10 | | |
| Gate agreement | 4/6 | | |
| Rule-failure agreement | 1/9 | | |
| State agreement | not recorded | | |
| Runs ended `gate_rejected` | 6 | | |
| Rules with misses or unexpected failures | `icd203.as.5`, `icd203.tc.8` unexpected on `clean-two-sources`, `thin-material` | | |
