# M13 Auditor Schema Probe, Source-Id Enum, Bench Table and Test Debt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-31, CRL-32 and CRL-33, the "Should fix soon" list of `docs/m12-followups.md` (M12 whole-branch review, 2026-10-17). (1) `corelata doctor` probes the auditor's by-rule `AuditByRule` schema for the configured pack on its own check line, so a server limit on schema size shows in doctor instead of in a run, and the `unreachable: …` and `test completion failed: …` messages are cut to `ERROR_CHARS` (CRL-31). (2) The writer's and conveyor's per-call schema restricts `SourceEntry.source_id` to the run's source ids with one hoisted `SourceId` enum (CRL-32). (3) The bench table cuts an errored run's error to the outcome column so the row stays aligned, and a test pins the `ENGINE_CHECK` clause of `scenarios.audited_iterations` on its own (CRL-33).

**Architecture:** Engine only. `doctor._structured`'s body becomes a shared `_probe` (request through `llm.agent.build_request`/`request_messages`, the same fixes and messages); the gate probe calls it unchanged and a new `_auditor_schema` calls it with `audit_output_type(pack, 2 refs, 2 claim ids)` and an auditor-shaped payload built by `stages.audit.auditor_payload`, which `run_auditor` now uses too. `_backend` appends a `model <key> auditor schema` line after the auditor model's own line once its test completion passed. `audit_schema.enum_item` builds one id's type (a `StrEnum` up to `ENUM_LIMIT`, else `str`); `enum_list` is built on it, and `report_output_type(unit_refs, source_ids)` uses it for `SourceEntry.source_id`. `bench/text.py` gains `OUTCOME_WIDTH` and an `errors` section. No exported model changes, so `make schema` is a no-op.

**Tech Stack:** Python 3.12, pydantic 2.14 (`create_model` with `__base__`, functional `StrEnum`), httpx; Markdown docs. No web or API change.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §8.1 (report schema and its M12 amendment), §8.2 (audit schema, M11 amendment), §8.4 (trace invariants, M11 amendment), §10.2 (CLI, `doctor`, M12 amendment), §13 (scenario fixtures and `corelata bench`, M6 and M12 amendments). Ticket texts are Jira CRL-31, CRL-32, CRL-33. The previous plan, `docs/superpowers/plans/2026-10-16-m12-writer-enum-doctor-real-bench.md`, specified `stages/report_schema.py` and the doctor's GateVerdict probe.

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`, the Makefile's `DB_URL`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`.
- **No new API route and no API response-model change** (R-M13-6). `api/tests/test_openapi.py::test_every_screen_has_its_routes` lists exactly 22 paths and stays as it is. Nothing in M13 changes an exported model: the per-call writer type is not exported, `DoctorCheck` is unchanged (the new line is one more check with a new `name`), `RunResult.error` is unchanged. `make schema` must be a no-op: `schema/*.json`, `schema/openapi.json` and `web/src/api/schema.d.ts` come out unchanged; `test_committed_schema_matches_models`, `test_committed_openapi_matches_the_app` and the `web` CI job enforce it.
- The trace format does not change: the writer's and conveyor's replies are still parsed as the canonical `ReportBody` (R-M12-8), so `RunRecord.drafts`, `report.json`, every export and the API read what they read at d02dd63. `bench.json` does not change.
- `api/tests/test_reports.py::test_re_render_failures` monkeypatches `reports._render`; that name stays. `api/tests/test_system.py::test_doctor_is_healthy_against_the_fake_server` requires every doctor check to pass or warn against the fake server; the new auditor line passes there (the synthetic responder answers the auditor-shaped probe).
- Web tests mock every request with msw (`web/src/test/setup.ts` fails an unmocked one); poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts`. A loading state is held open by a deferred msw response the test resolves (`web/src/test/deferred.ts`), never by a real delay. (M13 changes nothing in `web/`.)
- Commit messages end with exactly these two lines, nothing else after them:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK`
  Write the message to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Version stays `0.1.1` (`engine/pyproject.toml`, `tests/test_version.py`); the controller cuts 0.1.2 after the live rehearsal (R-M13-6).
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12, R-M10-1 to R-M10-10, R-M11-1 to R-M11-8 and R-M12-1 to R-M12-10 (`docs/superpowers/plans/2026-10-16-m12-writer-enum-doctor-real-bench.md`, `docs/m12-followups.md` and the earlier plans and follow-ups they cite) stay in force.
  - **R-M13-1 (CRL-31, auditor probe).** `doctor` gains one more check line per model configured as `auditor`, after the gate probe: label `model <key> auditor schema` (match the existing label style; read `_structured`'s label). It builds the real by-rule schema with `audit_output_type(pack, unit_refs, claim_ids)` for the configured pack and a fixed small list of two unit refs and two claim ids, sends it through `build_request` exactly as `run_auditor` does (same `max_tokens` rule as R-M12-9: `model.max_output_tokens`, omitted when unset), with a short system prompt and a tiny draft payload, and passes only when the reply parses via `to_audit_output`. PASS message `json_schema output works (AuditByRule, N rules)`; the FAIL message and fix follow the gate probe's wording (server error cut to `ERROR_CHARS`; `json_object` parse failure says try `none`). The gate probe stays for every model. On `structured_output: none` the auditor probe runs too (the schema is then in the prompt).
  - **R-M13-2 (CRL-31, bounded messages).** `unreachable: <error>` in `_backend` and `test completion failed: <error>` in `_model` go through `_cut`. Nothing else in doctor changes.
  - **R-M13-3 (CRL-32, source-id enum).** `report_output_type(unit_refs, source_ids)` (second positional parameter, required; update both call sites) emits `SourceEntry.source_id` as a hoisted `SourceId` enum via `enum_list` under the same `ENUM_LIMIT` rule as `UnitRef` (plain string above the limit; a run always has at least one source, so `maxItems 0` does not arise; say so in a comment). The reply is still parsed as the canonical `ReportBody` (R-M12-8); `check_sources`/the existing validator remains the backstop and its message is unchanged. Schema name sent stays `ReportBody`. If the writer or conveyor prompt mentions the evidence enum, add the source-id enum in the same sentence and bump that prompt's version only if its text changes (decide by reading; say which).
  - **R-M13-4 (CRL-33, bench table).** `format_bench` cuts an errored run's error text to the `outcome` column width with the module's `_cut`; `bench.json` keeps the full error. Column offsets are identical on every row; test with a 300-character error.
  - **R-M13-5 (CRL-33, test debt).** A `test_scenarios.py` test constructs a `RunRecord` (or plays a scenario with a scripted backend) where iteration 0's audit completed, iteration 1 carries only `ENGINE_CHECK`-prefixed findings and the report's degradations do **not** name iteration 1 (no `audit incomplete` line), and asserts `audited_iterations` excludes iteration 1 on the `ENGINE_CHECK` clause alone. If no pipeline path can produce that record, build it by hand from a played record and say so in the test's docstring.
  - **R-M13-6 (scope).** Nothing from the "Later" list of `docs/m12-followups.md` moves. No API/web changes. The real scenario set is untouched. Version stays 0.1.1; the controller cuts 0.1.2 after the live rehearsal.
  - How the plan applies them (from reading the code at d02dd63, and applying every task to a scratch copy of `engine/` and `api/`: engine 834 passed, api 138 passed, ruff clean):
    - R-M13-1: there is one auditor model (`cfg.roles.auditor.model`), so at most one auditor line. The line follows that model's `model <key>` line and runs only when that line's message starts with `PING_OK` (`"test completion succeeded"`): with `--no-probe`, for a model that is not served, and after a failed test completion there is no auditor line (the model line already fails or says `served`). The pack is `load_run_pack(cfg, None)`, the pack a run without `--profile` uses. The draft is `doctor.AUDIT_PROBE_DRAFT` (two fact claims `c1`, `c2` citing `probe/u1`, `probe/u2`), so `AUDIT_PROBE_UNITS`' refs and `AUDIT_PROBE_CLAIMS` are exactly the `UnitRef` and `ClaimId` enums `run_auditor` would build for it; the system prompt is `AUDIT_PROBE_SYSTEM`, two lines, not the auditor prompt template. "Parses via `to_audit_output`" means `to_audit_output(output_type.model_validate_json(extract_json(reply)), pack)` raises nothing. The gate probe's messages and fixes are byte-identical to M12 (every existing gate assertion in `tests/test_doctor.py` stands).
    - R-M13-2: `_cut` flattens whitespace and cuts to 200 characters with `…`, as it already does for the probe's error.
    - R-M13-3: `enum_list` builds a list field, and `source_id` is one string, so `audit_schema` gains `enum_item(name, values)`, the item type `enum_list` already built inline; `enum_list` now calls it and is otherwise unchanged. The source ids are `[s.id for s in ctx.sources]` at both call sites, exactly the set `report_validator` accepts (`known_sources`); there is no `index.source_ids()`. **Prompts: no change, no bump.** Neither `writer/v1.j2` nor `conveyor/v1.j2` mentions an enum (the writer says "`evidence`: the refs that support it" and "sources: one entry per source in INPUT_JSON.sources"); `tests/prompts/test_library.py` is unchanged. A `json_object`/`none` server sees the `SourceId` def in the schema spelled into the system prompt.
    - R-M13-4: `OUTCOME_WIDTH = 24` replaces the literal `24` in the header and the rows; the cut is `_cut(run.error or "", OUTCOME_WIDTH)`.
    - R-M13-5: no pipeline path produces that record (a degraded audit always ends the loop and names the run's last iteration, `pipeline.py` lines 323-334), so the test plays `unsourced-unfixable` with `AuditorFailsFromIteration1` (iteration 0 audited; iteration 1 degraded, leaving only the engine's `icd203.tc.8` failure) and removes the note. Dropping the `ENGINE_CHECK` clause from `audited_iterations` fails this test and no other (checked on the scratch copy).
  - Rulings this plan adds:
    - **R-M13-7 (CRL-32).** `audit_schema.enum_item(name: str, values: Sequence[str]) -> Any` returns a `StrEnum` called `name` for `0 < len(values) <= ENUM_LIMIT` and `str` otherwise (reading `ENUM_LIMIT` at call time); `enum_list` keeps its signature and behaviour (an empty list still gets `maxItems: 0`). If wrong: a reviewer who wants `enum_list` itself to serve the scalar field moves ten lines; no behaviour changes.
    - **R-M13-8 (CRL-31).** The gate and auditor probes share `doctor._probe`; the fix for a rejected request and for a reply that is not the requested JSON comes from `_fixes(key, mode)`: `json_schema` → `set models.<key>.structured_output to json_object or none` for both; `json_object` → that, and `set models.<key>.structured_output to none, or pick a model that follows a JSON schema` for a wrong reply (R-M12-9); `none` (reached only by the auditor probe) → `check the model id and server logs` for a rejected request and `pick a model that follows a JSON schema given in the prompt` for a wrong reply. A truncated auditor reply reads `the AuditByRule reply was cut at max_tokens=N`, fix `raise models.<key>.max_output_tokens or unset it: an AuditByRule needs about 60 tokens per rule (N here) plus any reasoning the model emits first`. A pack that does not load fails the line with `cannot build the AuditByRule schema: <error cut to 200>`, fix `fix the pack check first`. The auditor's input shape is shared: `stages.audit.auditor_payload(pack, draft, cited_units, value_statement)`, extracted verbatim from `run_auditor`. If wrong: the 60-tokens-per-rule estimate only shapes a fix line; a `none` auditor model whose replies are not JSON now FAILs doctor, which is what R-M13-1 asks.
    - **R-M13-9 (CRL-33).** Cutting the table cell removed the only copy of an errored run's error from the text output (the CLI prints progress lines on stderr; `tests/test_cli_bench.py::test_bench_profile_missing_is_an_error_exit_1` asserts the error's text on stdout and fails with the cut alone). `format_bench` therefore ends with an `errors` section, one line per errored run, `  <scenario> run <n>: <whole error>`, after `mismatches`. If wrong: one extra section in the text output; `bench.json` and exit codes are unchanged.
    - **R-M13-10 (docs).** The source-id amendment goes in spec §8.1 after the M12 amendment (where the unit-id enum is described), the auditor probe in §10.2, the bench table in §13. The m12 follow-ups are struck in the repository's convention, `— **closed in M13** (CRL-…)` appended to the bullet. If wrong: placement only.

## Review Focus

1. **A server that accepts the gate's small schema but rejects the auditor's larger one must fail doctor on the auditor line, with the server's own error, while the gate line still passes; and `json_object`, the fix doctor gives, must then pass.** Pinned in Task 1 (`test_a_schema_size_limit_fails_the_auditor_probe_and_not_the_gate_probe`).
2. **The auditor probe must send what a run sends: the by-rule schema of the configured pack through the strict-mode transform, no output cap unless the model sets one, and the auditor's input shape, also on a `none` server where the schema goes in the prompt.** Pinned in Task 1 (`test_the_auditor_probe_sends_the_by_rule_schema_a_run_sends`, `test_a_none_model_gets_the_auditor_probe_with_the_schema_in_the_prompt`, `test_run_auditor_sends_the_payload_auditor_payload_builds`).
3. **A `json_schema` server must not let the writer list a source the run does not have, and a `json_object` server's invented source id must still get the validator's existing message in the repair turn.** Pinned in Task 2 (`test_an_invented_source_id_is_not_a_source`, `test_a_json_object_writer_sees_the_source_enum_and_gets_the_validator_message`).
4. **An errored bench run with a long error must not shift the gate, time, calls and tokens columns, and the operator must still be able to read the whole error in the text output and in `bench.json`.** Pinned in Task 3 (`test_an_errored_runs_long_error_keeps_every_column_aligned`).
5. **An iteration whose findings are all the engine's must count as not audited even when no `audit incomplete` note names it, and one auditor-worded finding must make it audited again.** Pinned in Task 4 (`test_engine_only_findings_alone_leave_an_iteration_unaudited`).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/stages/audit.py` | `auditor_payload` (the auditor's input), used by `run_auditor` and the doctor. |
| `engine/corelata/doctor.py` | `AUDIT_PROBE_*`, `PING_OK`, `_fixes`, `_probe`, `_auditor_schema`; cut listing and ping errors. |
| `engine/corelata/stages/audit_schema.py` | `enum_item` (one id), `enum_list` built on it. |
| `engine/corelata/stages/report_schema.py` | `report_output_type(unit_refs, source_ids)` with the `SourceId` enum. |
| `engine/corelata/stages/write.py`, `stages/convey.py` | pass the run's source ids. |
| `engine/corelata/bench/text.py` | `OUTCOME_WIDTH`, the cut cell, the `errors` section. |
| tests: `engine/tests/test_doctor.py`, `engine/tests/stages/{test_audit,test_audit_schema,test_report_schema,test_write,test_convey}.py`, `engine/tests/llm/test_schema.py`, `engine/tests/bench/test_text.py`, `engine/tests/test_scenarios.py` | the tickets' tests. |
| `README.md`, spec, `docs/operator-guide.md`, `docs/m12-followups.md`, `docs/m13-followups.md` (new) | docs (Task 5). |

Order: the four code tasks are independent (Task 1 owns `doctor.py` and `stages/audit.py`, Task 2 the schema modules and the writer/conveyor, Task 3 `bench/text.py`, Task 4 one test). Task 5 documents all four.

---

### Task 1: `doctor` probes the auditor's by-rule schema; listing and ping errors are cut (CRL-31)

**Files:**
- Modify: `engine/corelata/stages/audit.py` (line 6 import; `run_auditor`, lines 124-151), `engine/corelata/doctor.py` (imports lines 14 and 25; after `PROBE_PAYLOAD`, before line 59; `_backend` lines 255-287; `_model` lines 322-336; `_structured` lines 344-387)
- Test: `engine/tests/stages/test_audit.py` (imports lines 8-16; after `test_clean_draft_passes`, line 38), `engine/tests/test_doctor.py` (imports lines 9-24; `test_a_healthy_installation` lines 54-76; `test_no_probe_skips_the_test_completions` lines 103-107; `test_failed_completion_is_reported` line 122; `test_the_structured_probe_sends_the_gate_verdict_schema_a_run_sends` line 487; `test_against_a_strict_server_the_probe_passes_exactly_when_a_gate_call_does` lines 569-580; `test_json_that_is_not_a_gate_verdict_fails_the_probe` after line 603; `test_a_probe_cut_at_max_tokens_says_to_raise_the_limit` lines 612-620; `test_the_probe_sends_no_cap_when_the_model_has_none` lines 630-631; append)

**Interfaces:**
- Consumes: `llm.agent.build_request(model_key, model, output_type, schema, messages, *, max_tokens=None) -> ChatRequest`, `llm.agent.request_messages(system, payload, model, schema) -> list[ChatMessage]`, `llm.agent.extract_json(content) -> str`, `stages.audit_schema.audit_output_type(pack, unit_refs, claim_ids) -> type[BaseModel]` (named `AuditByRule`), `stages.audit_schema.to_audit_output(parsed, pack) -> AuditOutput`, `pipeline.load_run_pack(cfg, profile) -> ResolvedPack` (raises `PackError`).
- Produces: `stages.audit.auditor_payload(pack: ResolvedPack, draft: ReportBody, cited_units: list[dict[str, str]], value_statement: str) -> dict[str, Any]`; `doctor.AUDIT_PROBE_SYSTEM: str`, `doctor.AUDIT_PROBE_UNITS: list[dict[str, str]]` (`ref`, `text`), `doctor.AUDIT_PROBE_CLAIMS: list[str]`, `doctor.AUDIT_PROBE_DRAFT: ReportBody`, `doctor.PING_OK = "test completion succeeded"`. Check name `model <key> auditor schema`; messages `<mode> output works (AuditByRule, <N> rules)`, `<mode> request failed: <error cut to 200>`, `the AuditByRule reply was cut at max_tokens=<n>`, `the server did not return the requested JSON (<mode>): not an AuditByRule: <loc>: <msg>`, `cannot build the AuditByRule schema: <error>`.

- [ ] **Step 1: Failing tests**

In `engine/tests/stages/test_audit.py`, the `from corelata.stages.audit import (…)` block (lines 8-16) becomes:

```python
from corelata.stages.audit import (
    ENGINE_CHECK,
    AuditOutcome,
    apply_engine_checks,
    audit_validator,
    auditor_payload,
    merge_engine_findings,
    open_findings,
    run_auditor,
)
```

After `test_clean_draft_passes` (after line 38) add:

```python


async def test_run_auditor_sends_the_payload_auditor_payload_builds(make_ctx):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    await run_auditor(ctx, iteration=0, draft=draft)
    rec = ctx.runner.log.records[-1]
    sent = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    cited = sorted({r for c in draft.claims for r in c.evidence})
    units = [{"ref": r, "text": ctx.index.text(r)} for r in cited]
    want = auditor_payload(ctx.pack, draft, units, ctx.value_statement)
    assert sent == json.loads(json.dumps(want))  # the doctor's auditor probe sends this shape
```

In `engine/tests/test_doctor.py`, replace the imports from `from corelata.config import load_config` (line 9) through `from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN` (line 24) with:

```python
from corelata.config import StructuredOutput, load_config
from corelata.doctor import (
    AUDIT_PROBE_CLAIMS,
    AUDIT_PROBE_DRAFT,
    AUDIT_PROBE_SYSTEM,
    AUDIT_PROBE_UNITS,
    ERROR_CHARS,
    PING_SCHEMA,
    PROBE_PAYLOAD,
    PROBE_SYSTEM,
    run_doctor,
)
from corelata.llm.agent import AgentRunner, CallLog
from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.payload import parse_input, render_input
from corelata.llm.schema import strict_json_schema
from corelata.llm.types import ChatResponse, PermanentBackendError, TransientBackendError
from corelata.prompts.library import PromptLibrary
from corelata.schema import CheckStatus, GateVerdict
from corelata.stages.audit import auditor_payload
from corelata.stages.audit_schema import audit_output_type
from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN, load_pack
```

In `test_a_healthy_installation`, add `"model fake-model auditor schema",` to the name tuple right after `"model fake-model",`, and after the assertion on `checks["model fake-model"].message` (ends line 74) add:

```python
    assert checks["model fake-model auditor schema"].message == (
        "json_schema output works (AuditByRule, 17 rules)"
    )
    names = [c.name for c in report.checks]
    assert names.index("model fake-model auditor schema") == names.index("model fake-model") + 1
```

In `test_no_probe_skips_the_test_completions`, before `assert server.requests == []` add:

```python
    assert "model fake-model auditor schema" not in _by_name(report)
```

In `test_failed_completion_is_reported`, after the last assertion add:

```python
    assert "model fake-model auditor schema" not in _by_name(report)  # no probe after a failed ping
```

In `test_the_structured_probe_sends_the_gate_verdict_schema_a_run_sends`, line 487 becomes:

```python
    probe = server.requests[1]  # the ping, the gate probe, then the auditor probe
```

In `test_against_a_strict_server_the_probe_passes_exactly_when_a_gate_call_does`, replace

```python
    check = _by_name(await doctor())["model fake-model"]
    assert check.status is CheckStatus.PASS, check
```

with

```python
    checks = _by_name(await doctor())
    check = checks["model fake-model"]
    assert check.status is CheckStatus.PASS, check
    assert checks["model fake-model auditor schema"].status is CheckStatus.PASS  # strict as well
```

and, after `await gate_call()` in the `pytest.raises` block, replace

```python
    check = _by_name(await doctor())["model fake-model"]
    assert check.status is CheckStatus.FAIL
```

with

```python
    checks = _by_name(await doctor())
    assert checks["model fake-model auditor schema"].status is CheckStatus.FAIL
    check = checks["model fake-model"]
    assert check.status is CheckStatus.FAIL
```

At the end of `test_json_that_is_not_a_gate_verdict_fails_the_probe` add:

```python
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == (
        "the server did not return the requested JSON (json_schema): "
        "not an AuditByRule: findings: Field required"
    )
    assert audit.fix == "set models.fake-model.structured_output to json_object or none"
```

In `test_a_probe_cut_at_max_tokens_says_to_raise_the_limit`, replace

```python
    check = _by_name(await run_doctor(path))["model fake-model"]  # the fake cuts max_tokens=1
```

with

```python
    checks = _by_name(await run_doctor(path))  # the fake cuts max_tokens=1
    check = checks["model fake-model"]
```

and at the end of the test add:

```python
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == "the AuditByRule reply was cut at max_tokens=1"
    assert audit.fix == (
        "raise models.fake-model.max_output_tokens or unset it: an AuditByRule needs about 60 "
        "tokens per rule (17 here) plus any reasoning the model emits first"
    )
```

In `test_the_probe_sends_no_cap_when_the_model_has_none`, replace

```python
    probe = backend.requests[-1]
    assert probe.schema_name == "GateVerdict" and probe.max_tokens is None
```

with

```python
    ping, gate, audit = backend.requests
    assert gate.schema_name == "GateVerdict" and gate.max_tokens is None
    assert audit.schema_name == "AuditByRule" and audit.max_tokens is None
```

Append to `engine/tests/test_doctor.py`:

```python


def _most_properties(node) -> int:
    """The largest `properties` object anywhere in a JSON schema."""
    if isinstance(node, list):
        return max((_most_properties(n) for n in node), default=0)
    if not isinstance(node, dict):
        return 0
    own = len(node["properties"]) if isinstance(node.get("properties"), dict) else 0
    return max([own, *(_most_properties(v) for v in node.values())])


class SchemaSizeLimit(FakeBackend):
    """A server that rejects a `json_schema` request whose largest object has more than `limit`
    properties, as some servers limit schema size (CRL-31)."""

    limit = 10

    async def chat(self, request):
        if request.structured_output is StructuredOutput.JSON_SCHEMA:
            size = _most_properties(request.json_schema)
            if size > self.limit:
                self.requests.append(request)
                raise PermanentBackendError(
                    f"local: HTTP 400: response_format schema has an object with {size} "
                    f"properties; at most {self.limit} are supported"
                )
        return await super().chat(request)


async def test_a_schema_size_limit_fails_the_auditor_probe_and_not_the_gate_probe(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    assert len(GateVerdict.model_json_schema()["properties"]) <= SchemaSizeLimit.limit
    path = _config(tmp_path, server.base_url)
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": SchemaSizeLimit()})
    checks = _by_name(report)
    gate = checks["model fake-model"]
    assert gate.status is CheckStatus.PASS
    assert gate.message == "test completion succeeded; json_schema output works (GateVerdict)"
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL and not report.ok
    assert audit.message == (
        "json_schema request failed: local: HTTP 400: response_format schema has an object "
        "with 17 properties; at most 10 are supported"
    )
    assert audit.fix == "set models.fake-model.structured_output to json_object or none"
    path = _config(  # the fix works: json_object sends no schema for the server to reject
        tmp_path,
        server.base_url,
        models={
            "fake-model": {
                "backend": "local",
                "context_window": 4096,
                "structured_output": "json_object",
            }
        },
    )
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": SchemaSizeLimit()})
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.PASS
    assert audit.message == "json_object output works (AuditByRule, 17 rules)"


async def test_long_listing_and_ping_errors_are_cut_to_error_chars(tmp_path, server):
    long = "upstream says: " + "y" * 5000

    class Unlisted(FakeBackend):
        async def list_models(self):
            raise TransientBackendError(long)

    class Unanswering(FakeBackend):
        async def chat(self, request):
            raise PermanentBackendError(long)

    path = _config(tmp_path, server.base_url)
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": Unlisted()})
    check = _by_name(report)["backend local"]
    assert check.message == "unreachable: " + long[: ERROR_CHARS - 1] + "…"
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": Unanswering()})
    check = _by_name(report)["model fake-model"]
    assert check.message == "test completion failed: " + long[: ERROR_CHARS - 1] + "…"
    assert check.fix == "check the model id and server logs"


async def test_the_auditor_probe_sends_the_by_rule_schema_a_run_sends(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    report = await run_doctor(_config(tmp_path, server.base_url))
    assert _by_name(report)["model fake-model auditor schema"].status is CheckStatus.PASS
    ping, gate, audit = server.requests
    assert gate["response_format"]["json_schema"]["name"] == "GateVerdict"
    pack = load_pack("icd203-base")
    refs = [u["ref"] for u in AUDIT_PROBE_UNITS]
    want = audit_output_type(pack, refs, AUDIT_PROBE_CLAIMS).model_json_schema()
    response_format = audit["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "AuditByRule"
    assert response_format["json_schema"]["schema"] == strict_json_schema(want)
    assert len(want["$defs"]["AuditFindings"]["required"]) == 17  # one property per rule
    assert "max_tokens" not in audit  # the model sets none, as in a run
    payload = auditor_payload(
        pack, AUDIT_PROBE_DRAFT, AUDIT_PROBE_UNITS, PROBE_PAYLOAD["value_statement"]
    )
    assert [m["content"] for m in audit["messages"]] == [AUDIT_PROBE_SYSTEM, render_input(payload)]
    assert len(AUDIT_PROBE_SYSTEM.splitlines()) == 2
    cited = sorted({r for c in AUDIT_PROBE_DRAFT.claims for r in c.evidence})
    assert cited == refs and [c.id for c in AUDIT_PROBE_DRAFT.claims] == AUDIT_PROBE_CLAIMS


async def test_only_the_auditors_model_gets_the_auditor_probe(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(
        tmp_path,
        server.base_url,
        models={
            "a": {"backend": "local", "context_window": 4096},
            "b": {"backend": "local", "context_window": 4096},
        },
        roles={
            "gate": {"model": "a"},
            "writer": {"model": "a"},
            "conveyor": {"model": "a"},
            "auditor": {"model": "b"},
        },
    )
    backend = FakeBackend(models=("a", "b"))
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": backend})
    names = [c.name for c in report.checks if c.name.startswith("model ")]
    assert names == ["model a", "model b", "model b auditor schema"]
    assert [r.schema_name for r in backend.requests if r.model == "b"] == [
        "Ping",
        "GateVerdict",
        "AuditByRule",
    ]


async def test_a_none_model_gets_the_auditor_probe_with_the_schema_in_the_prompt(tmp_path):
    backend = FakeBackend()
    path = _config(
        tmp_path,
        "http://unused.test/v1",
        models={
            "fake-model": {"backend": "local", "context_window": 4096, "structured_output": "none"}
        },
    )
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": backend})
    checks = _by_name(report)
    assert checks["model fake-model"].message == "test completion succeeded"  # no gate probe
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.PASS
    assert audit.message == "none output works (AuditByRule, 17 rules)"
    ping, probe = backend.requests
    assert probe.schema_name == "AuditByRule" and probe.structured_output is StructuredOutput.NONE
    assert "matches this JSON Schema" in probe.messages[0].content
    assert '"AuditFindings"' in probe.messages[0].content


async def test_a_none_model_that_returns_the_wrong_json_is_told_to_pick_another(tmp_path):
    class OkOnly(FakeBackend):
        async def chat(self, request):
            self.requests.append(request)
            return ChatResponse(content='{"ok": true}')

    path = _config(
        tmp_path,
        "http://unused.test/v1",
        models={
            "fake-model": {"backend": "local", "context_window": 4096, "structured_output": "none"}
        },
    )
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": OkOnly()})
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == (
        "the server did not return the requested JSON (none): "
        "not an AuditByRule: findings: Field required"
    )
    assert audit.fix == "pick a model that follows a JSON schema given in the prompt"


async def test_a_pack_that_does_not_load_fails_the_auditor_probe(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url, standards={"default_profile": "nope"})
    report = await run_doctor(path)
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message.startswith("cannot build the AuditByRule schema: ")
    assert "profile 'nope' not found" in audit.message
    assert audit.fix == "fix the pack check first"
    assert _by_name(report)["model fake-model"].status is CheckStatus.PASS
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_doctor.py tests/stages/test_audit.py --no-cov -q`
Expected: both files fail at collection, `ImportError: cannot import name 'AUDIT_PROBE_CLAIMS' from 'corelata.doctor'` and `ImportError: cannot import name 'auditor_payload' from 'corelata.stages.audit'`.

- [ ] **Step 3: The shared auditor input**

In `engine/corelata/stages/audit.py`, line 6 becomes `from typing import Any, Literal`, and the head of `run_auditor` (lines 124-151, from `async def run_auditor` through `output_type=output_type,`) is replaced by:

```python
def auditor_payload(
    pack: ResolvedPack, draft: ReportBody, cited_units: list[dict[str, str]], value_statement: str
) -> dict[str, Any]:
    """The auditor's input: the draft, every rule of the pack, the lexicon and the units the
    draft cites (`{"ref", "text"}` each). `corelata doctor`'s auditor probe sends the same shape
    (R-M13-1)."""
    return {
        "task": "auditor",
        "draft": draft.model_dump(),
        "rules": [
            {
                "id": r.id,
                "title": r.title,
                "text": r.text,
                "severity": r.severity.value,
                "checkability": r.checkability.value,
                "evidence_required": r.evidence_required,
            }
            for r in pack.rules
        ],
        "lexicon": pack.lexicon.model_dump(),
        "cited_units": cited_units,
        "value_statement": value_statement,
    }


async def run_auditor(ctx: StageContext, *, iteration: int, draft: ReportBody) -> AuditOutcome:
    cited = sorted({r for c in draft.claims for r in c.evidence if ctx.index.has(r)})
    output_type = audit_output_type(ctx.pack, cited, [c.id for c in draft.claims])
    backstop = audit_validator(ctx)
    parsed = await ctx.runner.run(
        role="auditor",
        model_key=ctx.model_key("auditor"),
        prompt_id="auditor",
        prompt_vars={},
        payload=auditor_payload(
            ctx.pack,
            draft,
            [{"ref": r, "text": ctx.index.text(r)} for r in cited],
            ctx.value_statement,
        ),
        output_type=output_type,
```

The rest of `run_auditor` (from `validate=lambda o: …` on) is unchanged.

- [ ] **Step 4: The auditor probe and the cut messages**

In `engine/corelata/doctor.py`, line 14 becomes `from pydantic import BaseModel, ValidationError`, and line 25 becomes these three lines:

```python
from corelata.schema import CheckStatus, DoctorCheck, DoctorReport, GateVerdict, ReportBody
from corelata.stages.audit import auditor_payload
from corelata.stages.audit_schema import audit_output_type, to_audit_output
```

Insert between the end of `PROBE_PAYLOAD` (line 58) and `ERROR_CHARS = 200 …` (line 59):

```python
# The auditor probe (R-M13-1) sends the auditor's real by-rule schema for the configured pack:
# one required property per rule (17 for icd203-base), with these two units and two claims as
# its `UnitRef` and `ClaimId` enums. The input is auditor-shaped (`stages.audit.auditor_payload`),
# so the synthetic responder answers it.
AUDIT_PROBE_SYSTEM = (
    "You audit a draft intelligence report against every rule in INPUT_JSON.rules.\n"
    "Return one finding per rule, keyed by rule id, and a short summary, as one JSON object."
)
AUDIT_PROBE_UNITS: list[dict[str, str]] = [
    {"ref": "probe/u1", "text": PROBE_PAYLOAD["units"][0]["text"]},
    {
        "ref": "probe/u2",
        "text": "The terminal was financed by a loan from the Kelmar state development bank.",
    },
]
AUDIT_PROBE_CLAIMS = ["c1", "c2"]
AUDIT_PROBE_DRAFT = ReportBody.model_validate(
    {
        "title": "Tarvos container capacity",
        "handling_marking": "UNCLASSIFIED",
        "key_judgments": [
            {
                "text": "Tarvos expanded its container capacity in 2026.",
                "confidence": "high",
                "claim_ids": ["c1", "c2"],
            }
        ],
        "scope_note": "One port notice; nothing set aside.",
        "sources": [{"source_id": "probe", "descriptor": "official government publication"}],
        "analysis": [
            {
                "heading": "Capacity",
                "paragraphs": [
                    {
                        "text": "A second terminal opened in May 2026 with state bank funding.",
                        "claim_ids": ["c1", "c2"],
                    }
                ],
            }
        ],
        "alternatives": [],
        "gaps_and_indicators": ["Throughput figures for the new terminal."],
        "claims": [
            {
                "id": "c1",
                "text": "Tarvos opened a second container terminal in May 2026.",
                "kind": "fact",
                "evidence": ["probe/u1"],
            },
            {
                "id": "c2",
                "text": "A state development bank financed the terminal.",
                "kind": "fact",
                "evidence": ["probe/u2"],
            },
        ],
    }
)
PING_OK = "test completion succeeded"
```

In `_backend`, the `unreachable` message (line 266) becomes:

```python
                f"unreachable: {_cut(str(e))}",
```

and the loop at the end of `_backend` (lines 280-287, from `for key, model in cfg.models.items():` through `return checks`) becomes:

```python
    for key, model in cfg.models.items():
        if model.backend != name:
            continue
        check = await _aguard(
            f"model {key}", lambda k=key, m=model: _model(k, m, backend, served, probe)
        )
        checks.append(check)
        # R-M13-1: the auditor's schema is the largest a run sends; probe it on its own line
        # once the model has answered the test completion
        if key == cfg.roles.auditor.model and check.message.startswith(PING_OK):
            audit = f"model {key} auditor schema"
            checks.append(
                await _aguard(
                    audit, lambda a=audit, k=key, m=model: _auditor_schema(cfg, a, k, m, backend)
                )
            )
    return checks
```

In `_model`, the ping block (lines 322-336) becomes:

```python
    parts: list[DoctorCheck] = []
    try:
        await backend.chat(_ping(model_id, StructuredOutput.NONE))
        parts.append(_check(label, CheckStatus.PASS, PING_OK))
    except OutputTruncatedError:  # cut at max_tokens: the model answered
        parts.append(_check(label, CheckStatus.PASS, PING_OK))
    except BackendError as e:
        parts.append(
            _check(
                label,
                CheckStatus.FAIL,
                f"test completion failed: {_cut(str(e))}",
                "check the model id and server logs",
            )
        )
```

Replace the whole of `_structured` (lines 344-387) with:

```python
def _fixes(key: str, mode: StructuredOutput) -> tuple[str, str]:
    """The fix for a rejected request and for a reply that is not the requested JSON (R-M12-9,
    R-M13-8). A `none` model sends no response format, so its server cannot reject a schema."""
    schema_fix = f"set models.{key}.structured_output to json_object or none"
    if mode is StructuredOutput.JSON_OBJECT:
        return schema_fix, (
            f"set models.{key}.structured_output to none, or pick a model that follows a "
            "JSON schema"
        )
    if mode is StructuredOutput.NONE:
        return "check the model id and server logs", (
            "pick a model that follows a JSON schema given in the prompt"
        )
    return schema_fix, schema_fix


async def _probe(
    label: str,
    key: str,
    model: ModelConfig,
    backend: Backend,
    output_type: type[BaseModel],
    system: str,
    payload: dict[str, Any],
    parse: Callable[[str], object],
    *,
    works: str,
    needs: str,
) -> DoctorCheck:
    """One structured request exactly as a run sends it: the stages' request builder, so the
    backend applies `strict_json_schema` as in a run, and no `max_tokens` of its own (the
    model's cap if it has one, else none). Passes only when `parse` accepts the reply."""
    name = output_type.__name__
    mode = model.structured_output.value
    rejected, wrong_json = _fixes(key, model.structured_output)
    schema = output_type.model_json_schema()
    request = build_request(
        key, model, output_type, schema, request_messages(system, payload, model, schema)
    )
    try:
        reply = await backend.chat(request)
    except OutputTruncatedError:
        return _check(
            label,
            CheckStatus.FAIL,
            f"the {name} reply was cut at max_tokens={request.max_tokens}",
            f"raise models.{key}.max_output_tokens or unset it: {needs}",
        )
    except BackendError as e:
        return _check(label, CheckStatus.FAIL, f"{mode} request failed: {_cut(str(e))}", rejected)
    try:
        parse(extract_json(reply.content))
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "<root>"
        article = "an" if name[0] in "AEIOU" else "a"
        return _check(
            label,
            CheckStatus.FAIL,
            f"the server did not return the requested JSON ({mode}): "
            + _cut(f"not {article} {name}: {where}: {first['msg']}"),
            wrong_json,
        )
    return _check(label, CheckStatus.PASS, f"{mode} output works ({works})")


async def _structured(label: str, key: str, model: ModelConfig, backend: Backend) -> DoctorCheck:
    """R-M12-3: the real GateVerdict schema; passes only on a reply that parses as one."""
    return await _probe(
        label,
        key,
        model,
        backend,
        GateVerdict,
        PROBE_SYSTEM,
        PROBE_PAYLOAD,
        GateVerdict.model_validate_json,
        works="GateVerdict",
        needs="a GateVerdict needs about 150 tokens plus any reasoning the model emits first",
    )


async def _auditor_schema(
    cfg: CorelataConfig, label: str, key: str, model: ModelConfig, backend: Backend
) -> DoctorCheck:
    """R-M13-1: the auditor's by-rule schema for the configured pack, the largest schema a run
    sends (one required property per rule); passes only on a reply that converts to an
    `AuditOutput`. On `none` it runs too: the schema is then spelled in the prompt."""
    try:
        pack = load_run_pack(cfg, None)
    except PackError as e:
        return _check(
            label,
            CheckStatus.FAIL,
            f"cannot build the AuditByRule schema: {_cut(str(e))}",
            "fix the pack check first",
        )
    refs = [u["ref"] for u in AUDIT_PROBE_UNITS]
    output_type = audit_output_type(pack, refs, AUDIT_PROBE_CLAIMS)
    payload = auditor_payload(
        pack, AUDIT_PROBE_DRAFT, AUDIT_PROBE_UNITS, PROBE_PAYLOAD["value_statement"]
    )
    rules = len(pack.rules)
    noun = "rule" if rules == 1 else "rules"
    return await _probe(
        label,
        key,
        model,
        backend,
        output_type,
        AUDIT_PROBE_SYSTEM,
        payload,
        lambda text: to_audit_output(output_type.model_validate_json(text), pack),
        works=f"AuditByRule, {rules} {noun}",
        needs=f"an AuditByRule needs about 60 tokens per rule ({rules} here) plus any reasoning "
        "the model emits first",
    )
```

- [ ] **Step 5: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_doctor.py tests/stages tests/test_pipeline.py --no-cov -q`
Expected: PASS (every M12 gate-probe assertion unchanged; the seven new doctor tests and the new audit test pass).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_system.py --no-cov -q`
Expected: PASS (the API's doctor route reports the new line as a pass against the fake server).

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m13-task1-commit.txt <<'EOF'
feat: doctor probes the auditor's by-rule schema; cut listing and ping errors (CRL-31)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/doctor.py engine/corelata/stages/audit.py engine/tests/test_doctor.py engine/tests/stages/test_audit.py
git commit -F <scratchpad>/m13-task1-commit.txt
```

---

### Task 2: The writer's and conveyor's schema enumerates the source ids (CRL-32)

**Files:**
- Modify: `engine/corelata/stages/audit_schema.py` (module docstring lines 10-12; `enum_list` lines 34-46), `engine/corelata/stages/report_schema.py` (whole file), `engine/corelata/stages/write.py` (line 108), `engine/corelata/stages/convey.py` (line 60)
- Test: `engine/tests/stages/test_report_schema.py` (whole file), `engine/tests/stages/test_audit_schema.py` (imports line 9; after `test_enum_list_reads_the_limit_when_called`), `engine/tests/stages/test_write.py` (after `test_the_backstop_validator_still_checks_writer_refs`, line 102), `engine/tests/stages/test_convey.py` (`test_run_conveyor_sends_the_unit_enum_and_returns_a_report_body`, lines 54-60), `engine/tests/llm/test_schema.py` (lines 30-31)

**Interfaces:**
- Consumes: `audit_schema.ENUM_LIMIT` (200, read at call time), `schema.report.SourceEntry`, `Claim`, `ReportBody`.
- Produces: `audit_schema.enum_item(name: str, values: Sequence[str]) -> Any` (a `StrEnum` named `name`, or `str`); `report_schema.report_output_type(unit_refs: Sequence[str], source_ids: Sequence[str]) -> type[ReportBody]` (schema name `ReportBody`; `$defs` gain `SourceId` next to `UnitRef`; `$defs.SourceEntry.properties.source_id == {"$ref": "#/$defs/SourceId"}`).

- [ ] **Step 1: Failing tests**

Replace `engine/tests/stages/test_report_schema.py` with:

```python
import json

import pytest
from pydantic import ValidationError

from corelata.schema import ReportBody
from corelata.stages.audit_schema import ENUM_LIMIT
from corelata.stages.report_schema import report_output_type

REFS = ["src1/u1", "src1/u2", "src2/u1"]
SOURCES = ["src1", "src2"]


def _body(evidence: list[str], source_id: str = "src1") -> dict:
    return {
        "title": "t",
        "handling_marking": "UNCLASSIFIED",
        "key_judgments": [{"text": "k", "confidence": "moderate", "claim_ids": ["c1"]}],
        "scope_note": "s",
        "sources": [{"source_id": source_id, "descriptor": "open-source report"}],
        "analysis": [{"heading": "h", "paragraphs": [{"text": "p", "claim_ids": ["c1"]}]}],
        "alternatives": [],
        "gaps_and_indicators": [],
        "claims": [{"id": "c1", "text": "t", "kind": "fact", "evidence": evidence}],
    }


def test_the_schema_is_report_body_with_one_enum_each_for_unit_refs_and_source_ids():
    model = report_output_type(REFS, SOURCES)
    assert model.__name__ == "ReportBody"  # the schema name the server sees
    want = ReportBody.model_json_schema()
    want["$defs"]["Claim"]["properties"]["evidence"]["items"] = {"$ref": "#/$defs/UnitRef"}
    want["$defs"]["UnitRef"] = {"enum": REFS, "title": "UnitRef", "type": "string"}
    want["$defs"]["SourceEntry"]["properties"]["source_id"] = {"$ref": "#/$defs/SourceId"}
    want["$defs"]["SourceId"] = {"enum": SOURCES, "title": "SourceId", "type": "string"}
    got = model.model_json_schema()
    assert got == want  # same fields, descriptions and required lists; two new defs
    assert list(got["properties"]) == list(ReportBody.model_fields)  # field order kept
    entry = got["$defs"]["SourceEntry"]["properties"]
    assert list(entry) == ["source_id", "descriptor", "reliability_note"]
    assert json.dumps(got).count('"src2"') == 1  # the source ids are emitted once


def test_evidence_is_plain_strings_above_the_limit_and_empty_without_refs():
    many = [f"src1/u{i}" for i in range(1, ENUM_LIMIT + 2)]
    above = report_output_type(many, SOURCES).model_json_schema()
    assert above["$defs"]["Claim"]["properties"]["evidence"]["items"] == {"type": "string"}
    assert "UnitRef" not in above["$defs"]
    at_limit = report_output_type(many[:ENUM_LIMIT], SOURCES).model_json_schema()
    assert len(at_limit["$defs"]["UnitRef"]["enum"]) == ENUM_LIMIT
    none = report_output_type([], SOURCES)
    claim = none.model_json_schema()["$defs"]["Claim"]["properties"]["evidence"]
    assert claim["maxItems"] == 0
    none.model_validate(_body([]))
    with pytest.raises(ValidationError, match="too_long|at most 0"):
        none.model_validate(_body(["src1/u1"]))


def test_source_ids_are_a_plain_string_above_the_limit():
    many = [f"src{i}" for i in range(1, ENUM_LIMIT + 2)]
    above = report_output_type(REFS, many).model_json_schema()
    source_id = above["$defs"]["SourceEntry"]["properties"]["source_id"]
    assert source_id == {"title": "Source Id", "type": "string"}
    assert "SourceId" not in above["$defs"]
    at_limit = report_output_type(REFS, many[:ENUM_LIMIT]).model_json_schema()
    assert len(at_limit["$defs"]["SourceId"]["enum"]) == ENUM_LIMIT
    report_output_type(REFS, many).model_validate(_body(["src1/u1"], source_id="src9"))


def test_a_source_id_or_an_invented_ref_is_not_a_unit():
    model = report_output_type(REFS, SOURCES)
    for bad in ("src1", "src9/u1"):
        with pytest.raises(ValidationError) as e:
            model.model_validate_json(json.dumps(_body([bad])))
        [err] = e.value.errors()
        assert err["loc"] == ("claims", 0, "evidence", 0) and err["type"] == "enum", bad


def test_an_invented_source_id_is_not_a_source():
    model = report_output_type(REFS, SOURCES)
    for bad in ("src9", "src1/u1"):
        with pytest.raises(ValidationError) as e:
            model.model_validate_json(json.dumps(_body(["src1/u1"], source_id=bad)))
        [err] = e.value.errors()
        assert err["loc"] == ("sources", 0, "source_id") and err["type"] == "enum", bad


def test_the_claim_id_validator_still_runs_on_the_per_call_type():
    data = _body(["src1/u1"])
    data["key_judgments"][0]["claim_ids"] = ["c9"]
    with pytest.raises(ValidationError, match="unknown claim id 'c9'"):
        report_output_type(REFS, SOURCES).model_validate(data)
```

In `engine/tests/stages/test_audit_schema.py`, line 9 becomes:

```python
from corelata.stages.audit_schema import (
    ENUM_LIMIT,
    audit_output_type,
    enum_item,
    enum_list,
    to_audit_output,
)
```

and after `test_enum_list_reads_the_limit_when_called` add:

```python


def test_enum_item_is_one_str_enum_or_a_plain_string(monkeypatch):
    item = enum_item("SourceId", ["src1", "src2"])
    assert issubclass(item, StrEnum) and item.__name__ == "SourceId"
    assert [m.value for m in item] == ["src1", "src2"]
    assert enum_item("SourceId", []) is str
    monkeypatch.setattr(audit_schema, "ENUM_LIMIT", 1)  # read when called
    assert enum_item("SourceId", ["src1", "src2"]) is str
```

In `engine/tests/stages/test_write.py`, at the end of `test_the_backstop_validator_still_checks_writer_refs` (after line 102) add one line, and then a new test:

```python
    assert "SourceId" not in fake_backend.requests[0].json_schema["$defs"]  # a plain string too


async def test_a_json_object_writer_sees_the_source_enum_and_gets_the_validator_message(
    make_ctx, make_config, fake_backend
):
    models = {
        key: {"backend": "fake", "context_window": 32768, "structured_output": "json_object"}
        for key in ("model-a", "model-b")
    }
    cfg = make_config(models=models)
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link."), cfg=cfg)
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    bad = json.loads(json.dumps(good))
    bad["sources"][1]["source_id"] = "src9"  # an invented source id where src2 belongs
    fake_backend.script("writer", json.dumps(bad), json.dumps(good))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    first, second = fake_backend.requests
    assert first.json_schema["$defs"]["SourceId"]["enum"] == ["src1", "src2"]
    assert '"SourceId": {"enum": ["src1", "src2"]' in first.messages[0].content  # in the prompt
    repair = second.messages[3].content
    assert "unknown source id 'src9' in sources" in repair  # the validator's message, unchanged
    assert "source 'src2' has no entry in sources" in repair
    assert [s.source_id for s in body.sources] == ["src1", "src2"] and type(body) is ReportBody
```

In `engine/tests/stages/test_convey.py`, replace the head of the last test (lines 54-60, from `async def test_run_conveyor_sends_the_unit_enum_and_returns_a_report_body` through the `UnitRef` assertion) with:

```python
async def test_run_conveyor_sends_the_unit_and_source_enums_and_returns_a_report_body(
    make_ctx, fake_backend
):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    request = fake_backend.requests[-1]
    assert request.schema_name == "ReportBody"
    assert request.json_schema["$defs"]["UnitRef"]["enum"] == ctx.index.refs()
    assert request.json_schema["$defs"]["SourceId"]["enum"] == ["src1"]
    assert all(type(s.source_id) is str for s in out.sources)
```

(the test's last two lines, `assert type(out) is ReportBody …` and `assert all(type(r) is str …)`, stay).

In `engine/tests/llm/test_schema.py`, lines 30-31 become:

```python
    out.append(report_output_type(REFS, ["src1", "src2"]).model_json_schema())
    out.append(report_output_type([], ["src1"]).model_json_schema())
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/stages tests/llm --no-cov -q`
Expected: `test_audit_schema.py` fails to import `enum_item`; `test_report_schema.py` and `tests/llm/test_schema.py` fail with `TypeError: report_output_type() takes 1 positional argument but 2 were given`; the writer and conveyor tests fail with `KeyError: 'SourceId'`.

- [ ] **Step 3: One id's enum, and the source-id field**

In `engine/corelata/stages/audit_schema.py`, the docstring's last sentence (lines 11-12) becomes:

```python
refers to (R-M12-1). `enum_list` builds those fields and `enum_item` a single id; the writer's
schema (`report_schema.py`) uses both."""
```

and `enum_list` (lines 34-46) is replaced by:

```python
def enum_item(name: str, values: Sequence[str]) -> Any:
    """The type of one id drawn from `values`: a `StrEnum` called `name` up to ENUM_LIMIT values,
    which the JSON schema emits once in `$defs` however many fields use it, else `str` (above the
    limit, or with no values; `enum_list` makes an empty list's field empty instead). ENUM_LIMIT is
    read on every call, so a test can lower it."""
    if not values or len(values) > ENUM_LIMIT:
        return str
    return StrEnum(name, [(f"v{i}", value) for i, value in enumerate(values)])


def enum_list(
    name: str, values: Sequence[str], *, description: str | None = None
) -> tuple[Any, Any]:
    """A `create_model` field definition for a list of `values`: items of `enum_item(name,
    values)`; with no values the list must be empty (R-M11-8)."""
    if not values:
        return (list[str], Field(default_factory=list, max_length=0, description=description))
    return (list[enum_item(name, values)], Field(default_factory=list, description=description))
```

Replace `engine/corelata/stages/report_schema.py` with:

```python
"""The writer's and conveyor's schema source, built per call (R-M12-1, R-M13-3): `ReportBody`
with `Claim.evidence` restricted to the run's unit ids and `SourceEntry.source_id` to its source
ids, so a server configured `json_schema` cannot let a model cite a source id (`src1`) or an
invented ref as a unit, or list a source the run does not have. The variant keeps the field
names, order and descriptions and the schema name (`ReportBody`); only those two fields differ,
each as one enum in `$defs` (`UnitRef`, `SourceId`; plain strings above
`audit_schema.ENUM_LIMIT` ids, and an empty evidence list when there are no units). The per-call
type is only a schema source: replies are parsed as the canonical `ReportBody`, so `check_refs`
and the sources check report a bad id in the same repair message as every other validator error
(R-M12-8); a `json_schema` server still cannot generate one."""

from collections.abc import Sequence

from pydantic import create_model

from corelata.schema.report import Claim, ReportBody, SourceEntry
from corelata.stages.audit_schema import enum_item, enum_list


def report_output_type(unit_refs: Sequence[str], source_ids: Sequence[str]) -> type[ReportBody]:
    """`unit_refs` are the refs `StageContext.check_refs` accepts: `ctx.index.refs()`, every
    unit of every source, digested or not. `source_ids` are the ids `report_validator` accepts:
    the run's sources, in order. Subclassing keeps `ReportBody`'s claim-id validator."""
    claim = create_model(
        "Claim",
        __base__=Claim,
        __doc__=Claim.__doc__,
        evidence=enum_list(
            "UnitRef", unit_refs, description=Claim.model_fields["evidence"].description
        ),
    )
    # A run always has at least one source, so `source_ids` is never empty and needs no
    # `maxItems: 0` rule; `enum_item` gives a plain string above ENUM_LIMIT ids.
    source = create_model(
        "SourceEntry",
        __base__=SourceEntry,
        __doc__=SourceEntry.__doc__,
        source_id=(enum_item("SourceId", source_ids), ...),
    )
    return create_model(
        "ReportBody",
        __base__=ReportBody,
        __doc__=ReportBody.__doc__,
        sources=(list[source], ...),
        claims=(list[claim], ...),
    )
```

In `engine/corelata/stages/write.py` (line 108) and `engine/corelata/stages/convey.py` (line 60), the `schema=` argument becomes:

```python
        schema=report_output_type(
            ctx.index.refs(), [s.id for s in ctx.sources]
        ).model_json_schema(),
```

- [ ] **Step 4: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/stages tests/llm tests/test_pipeline.py tests/test_scenarios.py tests/schema --no-cov -q`
Expected: PASS (`tests/schema/test_export.py::test_committed_schema_matches_models` included: nothing exported changed).

Run: `make schema && git status --short schema web/src/api/schema.d.ts`
Expected: no output (`make schema` is a no-op).

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cat > <scratchpad>/m13-task2-commit.txt <<'EOF'
feat: the writer's schema enumerates the run's source ids (CRL-32)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/stages/audit_schema.py engine/corelata/stages/report_schema.py engine/corelata/stages/write.py engine/corelata/stages/convey.py engine/tests/stages/test_report_schema.py engine/tests/stages/test_audit_schema.py engine/tests/stages/test_write.py engine/tests/stages/test_convey.py engine/tests/llm/test_schema.py
git commit -F <scratchpad>/m13-task2-commit.txt
```

---

### Task 3: The bench table stays aligned for an errored run (CRL-33, part 1)

**Files:**
- Modify: `engine/corelata/bench/text.py` (constants lines 5-8; `_outcome` line 25; `format_bench` lines 60-71 and 90-98)
- Test: `engine/tests/bench/test_text.py` (import line 12; before `test_format_bench_when_everything_agrees_has_no_rule_or_mismatch_sections`; that test's last line)

**Interfaces:**
- Consumes: `bench.text._cut(text: str, limit: int) -> str`, `bench.schema.RunResult.error`.
- Produces: `bench.text.OUTCOME_WIDTH = 24`; the text report ends with `errors` and one `  <scenario> run <n>: <error>` line per errored run when any run errored.

- [ ] **Step 1: Failing test**

In `engine/tests/bench/test_text.py`, line 12 becomes:

```python
from corelata.bench.text import GATE_REASON_CHARS, OUTCOME_WIDTH, format_bench
```

Insert before `test_format_bench_when_everything_agrees_has_no_rule_or_mismatch_sections`:

```python
def test_an_errored_runs_long_error_keeps_every_column_aligned():
    report = _report()
    error = "PermanentBackendError: " + "x" * 277
    assert len(error) == 300
    report.scenarios[2].runs[0].error = error
    text = format_bench(report)
    header, rows = _rows(text)
    starts = [header.index(h) for h in ("agree", "outcome", "gate")]  # left-aligned columns
    ends = [header.index(h) + len(h) for h in ("time", "calls", "tokens")]  # right-aligned
    for row in rows:
        for start in starts:
            assert row[start - 1] == " " and row[start] != " ", row
        for end in ends:
            assert row[end - 1] != " " and row[end : end + 1] in ("", " "), row
    err = rows[2]
    outcome = header.index("outcome")
    assert err[outcome : outcome + OUTCOME_WIDTH] == error[: OUTCOME_WIDTH - 1] + "…"
    assert len(err) == len(header)  # nothing spills past the tokens column
    assert text.endswith("\nerrors\n  broken run 1: " + error + "\n")  # whole, after the table
    assert report.scenarios[2].runs[0].error == error  # bench.json keeps the whole error
    assert error in report.model_dump_json()


```

and append to `test_format_bench_when_everything_agrees_has_no_rule_or_mismatch_sections`:

```python
    assert "\nerrors\n" not in text
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd engine && uv run pytest tests/bench/test_text.py --no-cov -q`
Expected: collection fails with `ImportError: cannot import name 'OUTCOME_WIDTH'`. (With only the import added to `text.py`, the alignment assertion fails: the error row's `gate` column holds an `x`.)

- [ ] **Step 3: Cut the cell, list the error whole**

In `engine/corelata/bench/text.py`, insert before the `# The gate column fits …` comment (line 5):

```python
# The outcome column fits "gate_rejected" or "completed findings_open"; an errored run's error
# is cut to it, so the columns after it stay aligned (R-M13-4); bench.json keeps it whole.
OUTCOME_WIDTH = 24
```

`_outcome`'s first branch (line 25) becomes:

```python
        return "err", _cut(run.error or "", OUTCOME_WIDTH)
```

The header line (line 60) becomes:

```python
        f"{'scenario':<{width}}  {'run':>3}  {'agree':<5}  {'outcome':<{OUTCOME_WIDTH}} "
```

The row (lines 67-71) becomes:

```python
            row = (
                f"{scenario.name:<{width}}  {run.repeat:>3}  {agree:<5}  "
                f"{outcome:<{OUTCOME_WIDTH}} {gate:<{GATE_WIDTH}}  {run.duration_s:>6.1f}s  "
                f"{run.calls:>5}  "
                f"{run.tokens_in + run.tokens_out:>6}"
            )
```

and before the final `return "\n".join(lines) + "\n"` (after the `mismatches` block) insert:

```python
    errored = [(sc.name, run) for sc in report.scenarios for run in sc.runs if not run.ok]
    if errored:  # the table cuts an error to its column (R-M13-4); here it is whole (R-M13-9)
        lines += ["", "errors"]
        lines += [f"  {name} run {run.repeat}: {run.error or ''}" for name, run in errored]
```

- [ ] **Step 4: Run the tests**

Run: `cd engine && uv run pytest tests/bench tests/test_cli_bench.py --no-cov -q`
Expected: PASS (`test_bench_profile_missing_is_an_error_exit_1` still finds `PackError` and `nope` on stdout, now in the `errors` section).

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cat > <scratchpad>/m13-task3-commit.txt <<'EOF'
fix: keep the bench table aligned for an errored run (CRL-33)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/bench/text.py engine/tests/bench/test_text.py
git commit -F <scratchpad>/m13-task3-commit.txt
```

---

### Task 4: Pin the `ENGINE_CHECK` clause of `audited_iterations` on its own (CRL-33, part 2)

Test debt: the code is right; no test tells its two clauses apart mid-run. The test goes after `test_a_degraded_last_audit_leaves_the_rule_sets_unscored` because it reuses that test's `AuditorFailsFromIteration1`.

**Files:**
- Test: `engine/tests/test_scenarios.py` (imports line 19; after `test_a_degraded_last_audit_leaves_the_rule_sets_unscored`, line 321)

**Interfaces:**
- Consumes: `scenarios.audited_iterations(record: RunRecord) -> set[int]`, `scenarios.compare(scenario, record) -> list[str]`, `stages.audit.ENGINE_CHECK`, the test module's `_played`, `_expecting` and `AuditorFailsFromIteration1`.
- Produces: nothing for later tasks.

- [ ] **Step 1: The test**

In `engine/tests/test_scenarios.py`, after `from corelata.schema import RunState` (line 19) add:

```python
from corelata.stages.audit import ENGINE_CHECK
```

After `test_a_degraded_last_audit_leaves_the_rule_sets_unscored` (after line 321) add:

```python


async def test_engine_only_findings_alone_leave_an_iteration_unaudited(make_config):
    """The `ENGINE_CHECK` clause of `audited_iterations` on its own (R-M13-5). No pipeline path
    leaves an iteration with only engine findings and no `audit incomplete` note naming it: a
    degraded audit always ends the run and names its last iteration. So the record is built by
    hand from a played one: `unsourced-unfixable` with every audit after the first failing
    (iteration 0 audited; iteration 1 carries only the engine's icd203.tc.8 failure), with the
    report's degradation note removed."""
    scenario, played = await _played(
        "unsourced-unfixable", make_config, AuditorFailsFromIteration1(name="fake")
    )
    assert played.iterations == 1
    assert played.report.metadata.degradations[0].startswith("audit incomplete")
    meta = played.report.metadata.model_copy(update={"degradations": []})
    record = played.model_copy(
        update={"report": played.report.model_copy(update={"metadata": meta})}
    )
    late = [f for f in record.findings if f.iteration == 1]
    assert [f.rule_id for f in late] == ["icd203.tc.8"]
    assert all(f.evidence.startswith(ENGINE_CHECK) for f in late)
    assert audited_iterations(record) == {0}  # no note names iteration 1: the prefix decides
    worded = late[0].model_copy(update={"evidence": "The auditor's own words."})
    findings = [worded if f is late[0] else f for f in record.findings]
    assert audited_iterations(record.model_copy(update={"findings": findings})) == {0, 1}
    must_pass = _expecting(
        scenario, state="completed", rules_must_pass=["icd203.tc.8"], rules_may_fail=[]
    )
    assert compare(must_pass, record) == [
        "rules: no audit of the delivered draft (iteration 1 degraded)"
    ]
```

- [ ] **Step 2: Run it**

Run: `cd engine && uv run pytest tests/test_scenarios.py --no-cov -q`
Expected: PASS (the behaviour exists; the test is the debt).

- [ ] **Step 3: Prove it pins the clause**

In `engine/corelata/scenarios.py`, `audited_iterations`, temporarily replace `if not all(f.evidence.startswith(ENGINE_CHECK) for f in found)` with `if True`, then run:

Run: `cd engine && uv run pytest tests/test_scenarios.py --no-cov -q`
Expected: exactly one failure, `test_engine_only_findings_alone_leave_an_iteration_unaudited` (at `assert audited_iterations(record) == {0}`); `test_a_degraded_audit_counts_as_no_audit_ran` still passes, which is the gap CRL-33 names. Restore the line (`git diff --exit-code engine/corelata/scenarios.py` prints nothing), rerun, expect PASS.

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cat > <scratchpad>/m13-task4-commit.txt <<'EOF'
test: pin the engine-only clause of audited_iterations mid-run (CRL-33)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/tests/test_scenarios.py
git commit -F <scratchpad>/m13-task4-commit.txt
```

---

### Task 5: Docs

**Files:**
- Modify: `README.md` (new `## M13` section before `## Development`, line 243), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (after lines 330, 441, 552), `docs/operator-guide.md` (step 4 paragraph, lines 90-96; bench paragraph, lines 475-478; section 11 row, line 613), `docs/m12-followups.md` ("Should fix soon", five bullets)
- Create: `docs/m13-followups.md`

- [ ] **Step 1: README**

Insert before `## Development` (line 243):

```markdown
## M13: auditor schema probe, source-id enum, bench table

The M12 review left three items. `corelata doctor` now also sends the auditor's schema, the
largest a run sends (one required property per rule of the configured pack), on its own
`model <key> auditor schema` line for the model configured as auditor, so a server that takes
the gate's small schema but limits schema size fails in doctor rather than in a run; server
errors in the backend and test-completion lines are cut to 200 characters like the probe's
(CRL-31). The writer's and conveyor's schema restricts `sources[].source_id` to the run's source
ids (a `SourceId` enum next to `UnitRef`), so a `json_schema` server cannot let a model list a
source the run does not have; other servers still get the validator's message (CRL-32). The
bench table cuts an errored run's error to its column and lists it whole under `errors`, and a
test pins how an iteration with only the engine's own findings counts as not audited (CRL-33).

```

- [ ] **Step 2: Spec amendments**

§8.1, after the M12 amendment paragraph (it ends "…every other validator error.", line 330):

```markdown

M13 amendment (CRL-32): the same per-call variant restricts `SourceEntry.source_id` to the run's
source ids (one `SourceId` enum; a plain string above 200 sources), so a `json_schema` server
cannot list a source the run does not have. The sources check (`unknown source id '<id>' in
sources`) still runs on every server.
```

§10.2, after the M12 amendment paragraph (it ends "…parses as one.", line 441):

```markdown

M13 amendment (CRL-31): for the model configured as `auditor`, `doctor` adds a
`model <key> auditor schema` line after the model's own: it sends the auditor's by-rule
`AuditByRule` schema for the configured pack (one required property per rule; unit and claim
enums of a two-claim probe draft) through the same request builder, also on
`structured_output: none` (the schema then goes in the prompt), and passes only on a reply that
converts to the auditor's output. A server's error text in the backend, test-completion and
probe messages is cut to 200 characters.
```

§13, after the M12 amendment to the scenario-fixtures bullet (it ends "…keeps the gate's verdict.", line 552):

```markdown

  *M13 amendment (CRL-33):* the bench table cuts an errored run's error to the outcome column,
  so every row keeps the same column offsets, and lists each error whole under `errors` after
  the table; `bench.json` keeps it whole.
```

- [ ] **Step 3: Operator guide**

Replace step 4's paragraph (lines 90-96, from "`doctor` checks the configuration" to "…to skip the test completions."):

```markdown
   `doctor` checks the configuration, the database, the files volume, the standards pack and each
   model server. For a server it reports how many models it serves and whether each model you
   configured is among them (a missing one's fix suggests up to five ids with the same prefix);
   then it sends each model a small test completion and, for a model set to `json_schema` or
   `json_object`, asks for a real gate verdict with the same schema and request builder a run uses, so a server
   that would reject a run's schema fails here, with the server's own error. Every check must
   pass; a failing check says what to fix. Add `--no-probe` to skip the test completions.
```

with:

```markdown
   `doctor` checks the configuration, the database, the files volume, the standards pack and each
   model server. For a server it reports how many models it serves and whether each model you
   configured is among them (a missing one's fix suggests up to five ids with the same prefix);
   then it sends each model a small test completion and, for a model set to `json_schema` or
   `json_object`, asks for a real gate verdict with the same schema and request builder a run
   uses, so a server that would reject a run's schema fails here, with the server's own error.
   The model you configured as auditor gets one more line, `model <key> auditor schema`: the
   auditor's schema has one required property per rule of your pack, the largest a run sends,
   and some servers limit schema size. Every check must pass; a failing check says what to fix.
   Add `--no-probe` to skip the test completions.
```

In the bench section, replace

```markdown
bench leaves a `bench.json` with the runs that finished. A run whose last audit degraded
leaves the rule sets unscored and counts as a disagreement.
```

with

```markdown
bench leaves a `bench.json` with the runs that finished. A run whose last audit degraded
leaves the rule sets unscored and counts as a disagreement. A run that could not execute shows
`err` and the start of its error in the table, and the whole error under `errors` at the end.
```

In section 11, in the row `| \`doctor\` fails on a backend or a model | … |` (line 613), insert after the sentence that ends "…set that model's `structured_output` to `json_object`.":

```markdown
 A failing `model <key> auditor schema` line under a passing `model <key>` line means the server accepts the gate's small schema but not the auditor's larger one (one required property per rule): set that model's `structured_output` to `json_object`.
```

(one line, keeping the row a single table row; the leading space separates it from the previous sentence).

- [ ] **Step 4: Follow-ups**

In `docs/m12-followups.md`, "Should fix soon", append to each bullet (after its last word, on the same line):

- the bullet beginning "The doctor probes only the gate's schema": ` — **closed in M13** (CRL-31: the \`model <key> auditor schema\` line)`
- the bullet beginning "`SourceEntry.source_id` is a free string": ` — **closed in M13** (CRL-32: the \`SourceId\` enum)`
- the bullet beginning "`doctor`: the ping-failure": ` — **closed in M13** (CRL-31)`
- the bullet beginning "`bench/text.py`: an errored run's error text": ` — **closed in M13** (CRL-33: \`OUTCOME_WIDTH\`, the \`errors\` section)`
- the bullet beginning "`scenarios.audited_iterations`: the degraded-audit tests": ` — **closed in M13** (CRL-33: \`test_engine_only_findings_alone_leave_an_iteration_unaudited\`)`

Nothing else in the file changes (R-M13-6).

Create `docs/m13-followups.md`:

```markdown
# M13 follow-ups

## Divergences from Coglossa

- `corelata doctor` probes the auditor's per-call by-rule schema on its own check line, through
  the shared `_probe` (`doctor.py`) and the stages' request builder — **backport candidate**:
  Coglossa's doctor probes no per-call schema, and its largest per-call schemas fail only in a
  run, as Corelata's did before CRL-31.
- `stages.audit.auditor_payload` and `audit_schema.enum_item` — Corelata only.

## Spec deviations

- None. §8.1, §10.2 and §13 carry M13 amendments.

## Rulings during execution

- How the plan applied R-M13-1 to R-M13-6, and the rulings it added (R-M13-7 to R-M13-10), are
  in its Global Constraints. Number new ones from R-M13-11.

## Should fix soon

- None.

## Later

- `audited_iterations` reads "every finding of the iteration is the engine's" as "the audit did
  not complete". With `icd203-base` (17 rules) a completed audit always carries auditor-worded
  findings, but a pack whose only rules are `icd203.tc.8` and `icd206.src.2` would see a completed
  audit that both engine checks overrode counted as not audited. Mark degraded iterations on the
  record instead of inferring them, if such a pack appears.
- The auditor probe asks a real model for one finding per rule (17 for `icd203-base`, about 1k
  output tokens): `doctor` takes one more model call per installation, a few seconds on a hosted
  model, longer on a small local one.
- The probe's input is fixed (two units, two claims): a server limit on enum length (the writer's
  `UnitRef`, up to 200 values) still shows only in a run.
- `doctor` probes the auditor with the pack a run without `--profile` uses; a profile that
  disables or adds rules changes the schema's size.
- The bench `errors` section prints each error whole, which for a long server error is one long
  line.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint && git diff --stat main -- web api schema docs/m11-followups.md engine/corelata/bench/scenarios-real`
Expected: lint clean; the diff prints nothing.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m13-task5-commit.txt <<'EOF'
docs: M13 README section, spec amendments, operator notes, follow-ups

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/operator-guide.md docs/m12-followups.md docs/m13-followups.md
git commit -F <scratchpad>/m13-task5-commit.txt
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine
make test-api       # api/tests/test_system.py runs doctor against the fake server: the new line passes
make test-web       # unchanged; proves nothing in web/ moved
make e2e            # the Playwright journey runs on the synthetic model through the new writer schema
make deploy-check
make schema && git status --short schema web/src/api/schema.d.ts   # no output (R-M13-6)
grep -n '^version' engine/pyproject.toml                            # still 0.1.1
```

CI must be green on all six jobs (engine, api, web, e2e, deploy-check, airgap) before the merge.

## Live rehearsal (the controller runs this after the merge; not a task)

Against the CRL-1 OpenRouter configuration (`gate`/`writer` on `openai/gpt-4.1-mini`, `conveyor`/`auditor` on `google/gemini-2.5-flash`, every model `structured_output: json_schema`; the same file as the M12 rehearsal). `corelata doctor` probes by default (`--no-probe` skips the probes).

- [ ] `corelata doctor --config <openrouter.yaml>`. Expect, in order, `model <gate-writer key>` reading `test completion succeeded; json_schema output works (GateVerdict)`, `model <conveyor-auditor key>` reading the same, and `model <conveyor-auditor key> auditor schema` reading `json_schema output works (AuditByRule, 17 rules)`. Record the doctor's wall time (one more model call than M12) and whether the auditor line passed first time.
- [ ] Point one backend's `base_url` at a closed port (`http://127.0.0.1:9/v1`), run `corelata doctor --no-probe`, and check the `unreachable: …` message is at most 213 characters (`unreachable: ` plus 200); restore it.
- [ ] `corelata bench --config <openrouter.yaml> --scenarios real --store-io --out bench-m13-real/`. In a trace, check a writer request's `response_format.json_schema.schema.$defs.SourceId.enum` lists the scenario's source ids, and `grep -c "unknown source id" bench-m13-real/*/run-1/trace.json` should be 0 for writer and conveyor calls.
- [ ] If any run errors, check its table row keeps the columns aligned and the whole error appears under `errors`.
- [ ] Fill in the table and add it to Jira CRL-31, CRL-32 and CRL-33 (close them with the doctor output and the trace evidence); then cut 0.1.2.

| Measure | M12 baseline (2026-10-17) | M13 |
|---|---|---|
| `doctor` | all PASS (gate probe only) | |
| `doctor` auditor schema line | n/a | |
| Real set: scenarios / runs / errors | 8 / 8 / 0 | |
| Full agreement | 7/8 | |
| Gate agreement | 8/8 | |
| Rule-failure agreement | 4/4 | |
| Duration | 88 s | |
| Writer/conveyor repair turns for an unknown source id | not recorded | |
