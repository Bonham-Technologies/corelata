# M11 Audit Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-25 (Bug, High). The CRL-1 deployment dry run (local Ollama, CPU, 2026-10-15/16) ended both runs `failed` with no report because the auditor's output was still invalid after its repair turn and the stage's retry (`qwen2.5:1.5b`: an advisory rule passed, an invented rule id `icd203.as.6`; `phi4-mini`: a source id `src1` cited as a unit, a verifiable rule attested). Spec §7 says the report is always delivered. M11 (1) puts the validator's constraints into the auditor's JSON schema so a `json_schema` server enforces them while generating, (2) delivers the report with `findings_open` and an engine-owned degradation note when the auditor or the conveyor still fails, and (3) rewords repair messages as instructions a small model can act on.

**Architecture:** Engine side, a new `stages/audit_schema.py` builds a per-call pydantic model `AuditByRule` whose `findings` is an object with one required property per rule id (field names `r0…rN`, aliases the rule ids); each property is a finding model whose `verdict` is a `Literal` restricted by the rule's checkability and whose `cited_units`/`claim_ids` are `Literal` enums of the draft's cited unit refs and claim ids (plain strings above 200). `run_auditor` sends it, converts the parsed object to the existing `AuditOutput` in pack order, and keeps `audit_validator` as the backstop on the converted list. The auditor prompt moves to v2 (keyed shape) and the synthetic responder answers in it. In the pipeline loop, a conveying failure forwards the conveyor's input draft and an auditing failure ends the loop with the previous findings; each records a line in the new `ReportMetadata.degradations`, which forces `findings_open` and renders as an appendix "Stages incomplete at delivery" in Markdown, HTML and DOCX. `delivered_open_findings` reads the ids in `metadata.open_findings`, so the appendix and the metadata agree when the last audit did not complete. Web side, the Review page lists the degradations under its header and the Audit tab says the audit did not complete. `make schema` runs once (Task 3).

**Tech Stack:** Python 3.12, pydantic 2 (`create_model`, `Literal`), Jinja2, python-docx; React 19 + TypeScript, TanStack Query 5, Vitest + msw; Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §4.4 (roles: the auditor produces findings only), §7.2 and §7.5 (state machine, error handling: one repair turn, one stage retry), §7.3 (routing), §8.1 (`ReportMetadata`), §8.2 (audit schema: exactly one finding per rule), §8.4 (trace invariants 1 and 2), §9 (open-findings appendix), §13 (quality gates, synthetic responder). The ticket text is Jira CRL-25.

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`.
- **No new API route** (R-M11-4). `api/tests/test_openapi.py::test_every_screen_has_its_routes` lists exactly 22 paths and stays as it is. `ReportMetadata.degradations` is a model change, so `make schema` runs once, in Task 3, and that task commits every file it rewrites. `ReportMetadata` is not in the OpenAPI document (the `report.json` export route returns bytes; the web's `ReportJson` type is hand-written in `web/src/api/types.ts`), so the expected rewrite is `schema/report.schema.json` and `schema/run-record.schema.json` only; `schema/openapi.json` and `web/src/api/schema.d.ts` should come out unchanged, and `test_committed_schema_matches_models`, `test_committed_openapi_matches_the_app` and the `web` CI job (`pnpm gen:api && git diff --exit-code src/api/schema.d.ts`) enforce whatever does change.
- The trace format gains only `report.metadata.degradations` (default `[]`, so every older trace and `report.json` still loads). `Finding`, `RunRecord.findings`, the findings route and every export other than the new appendix are unchanged (R-M11-1).
- `api/tests/test_reports.py::test_re_render_failures` monkeypatches `reports._render`; that name stays.
- Web tests mock every request with msw (`web/src/test/setup.ts` fails an unmocked one); poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts`. A loading state is held open by a deferred msw response the test resolves (`web/src/test/deferred.ts`), never by a real delay.
- Commit messages end with the two attribution lines the session uses; write them to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12 and R-M10-1 to R-M10-10 (`docs/superpowers/plans/2026-10-15-m9-efficiency-and-review-state.md`, `docs/m9-followups.md`, `docs/superpowers/plans/2026-10-15-m10-review-column-pack-index-cache-budget.md`, `docs/m10-followups.md`) stay in force.
  - **R-M11-1 (schema-enforced audit output).** `run_auditor` builds a per-call output type `audit_output_type(pack, unit_refs, claim_ids) -> type[BaseModel]` (new module `engine/corelata/stages/audit_schema.py`): a model `AuditByRule` whose `findings` field is an object model with **one required property per rule id** (Python field names `r0…rN`, `alias=<rule id>`, `populate_by_name=True`, `by_alias` JSON schema and `model_validate_json` by alias) and `summary: str`. Each rule's property is its own finding model: `verdict: Literal[...]` restricted by checkability (`VERIFIABLE` → `"pass" | "fail" | "not_applicable"`; `ADVISORY` → `"attested" | "not_applicable"`), `evidence: str`, `cited_units: list[Literal[<the unit refs in scope>]]` when `0 < len(unit_refs) <= 200` else `list[str]`, `claim_ids: list[Literal[<draft claim ids>]]` when `0 < len(claim_ids) <= 200` else `list[str]`, `recommendation: str = ""`. The parsed object is converted to the existing `AuditOutput` (`FindingOut` per rule, in pack order) before anything else uses it, so `Finding`, the trace, exports and the API are unchanged. `audit_validator` stays as the backstop (it still runs on the converted `AuditOutput`) for servers configured `json_object` or `none`. The schema name sent to the server stays a plain identifier (`AuditByRule`).
  - **R-M11-2 (degrade, never lose the report).** In the pipeline loop, the auditing stage and the conveying stage are each wrapped: when `self.stage(...)` raises one of `AGENT_FAILURES` or `StageError` for AUDITING, the loop records the failure as a degradation and leaves the loop with `findings` unchanged from the previous iteration (empty on iteration 0); for CONVEYING, it uses the writer's draft as the conveyed draft and records a degradation, then continues to the audit. `ReportMetadata` gains `degradations: list[str] = []` with entries like `"audit incomplete after 2 attempts: <error>"` and `"conveyance skipped after 2 attempts: <error>"`. `status` is `FINDINGS_OPEN` whenever `degradations` is non-empty (even with no open findings). Gate and writer failures stay fatal (nothing to deliver). The stage's own error recording (`_record_stage` with the error) is unchanged, so the Progress screen still shows the failed stage row. The renders (Markdown, HTML, DOCX) print the degradations under the report's status line; `corelata run` exits 3 as for findings open.
  - **R-M11-3 (repair messages are instructions).** `audit_validator` messages: `"rule '<id>' is advisory: set its verdict to 'attested' (or 'not_applicable'), not '<given>'"`, `"rule '<id>' is verifiable: set its verdict to 'pass', 'fail' or 'not_applicable', not 'attested'"`, `"'<id>' is not a rule in this pack; the rule ids are: <comma list>"`, `"give exactly one finding for rule '<id>'"`, `"missing a finding for rule '<id>'"`. `StageContext.check_refs` message: `"'<ref>' is not a unit id; cite unit ids exactly as given in the input, such as <up to 3 real refs>"`. `_repair_message` header: `"Your previous response was rejected. Fix every point below and return the complete corrected JSON object only:"`. Tests that assert the old strings are updated.
  - **R-M11-4 (schema regeneration).** `ReportMetadata.degradations` changes the API's response models (the report JSON export and anything that embeds `ReportMetadata`), so `make schema` runs once, in the task that adds the field, and that task commits every file the target rewrites together. `test_every_screen_has_its_routes` is unchanged (no new route).
  - **R-M11-5 (scope).** The writer's and conveyor's `evidence` refs stay free strings in M11 (the writer passed first time with the 3.8B model); a unit-id enum for them is filed in `docs/m11-followups.md`. OpenAI "strict" structured outputs (`additionalProperties: false`, every field required) are not targeted; note in follow-ups.
  - **R-M11-6 (invariant 1 survives an incomplete audit).** When the audit degrades, the engine still applies its own checks to the delivered draft: `stages.audit.engine_only_findings(draft, pack, iteration)` returns FAIL findings for `icd203.tc.8` (every unsourced claim) and `icd206.src.2` (an unsourced claim cited by a key judgment) built through `apply_engine_checks`, nothing else; the pipeline merges them into the delivered findings (replacing a previous iteration's finding for the same rule) and the trace, so the open-findings appendix and `metadata.open_findings` list them. A report with an unsourced claim is therefore never delivered without that claim named, auditor or no auditor (spec §8.4 invariant 1).
  - How the plan applies them (from reading the code at 3f843fd): the two finding models are built once per call, one per checkability (`VerifiableFinding`, `AdvisoryFinding`), and every rule's property points at the one for its checkability, which keeps the `$defs` at three entries however many rules the pack has; `cited_units` and `claim_ids` default to `[]` like `FindingOut`'s. "The unit refs in scope" are the refs the auditor's payload carries (`cited_units`, the draft's evidence refs the index knows). "The writer's draft" in R-M11-2 is the conveyor's input: the writer's draft, or on a conveyor-only iteration the previous conveyed draft. "N attempts" counts the stage rows `stage()` recorded as failed for that stage and iteration (2 after a repair-and-retry, 1 after an overflow once the ladder is spent). Markdown and DOCX have no status line (only the HTML footer prints the status), so the degradations render through `build_outline` as an unnumbered appendix, "Stages incomplete at delivery", placed before "Audit findings open at delivery" in all three renders.

## Review Focus

1. **A `json_schema` server must be unable to produce the dry run's four failures (an advisory rule passed, a verifiable rule attested, an invented rule id, a source id cited as a unit).** Pinned in Task 1 (`test_verdicts_are_restricted_by_checkability`, `test_every_rule_id_is_a_required_property_of_findings`, `test_an_out_of_enum_value_fails_and_names_the_rule_alias`).
2. **The converted output must be exactly what the list-shaped path produced, so findings, the trace, the exports and the API do not move.** Pinned in Task 1 (`test_run_auditor_sends_the_by_rule_schema_and_returns_the_same_outcome`, `test_a_reply_keyed_by_rule_id_converts_to_audit_output_in_pack_order`).
3. **An auditor that never answers validly must still deliver a `findings_open` report that says so, `corelata run` must exit 3, and gate or writer failures must still end in `failed`.** Pinned in Task 3 (`test_an_auditor_that_never_answers_delivers_the_report_marked_incomplete`, `test_run_with_an_unusable_auditor_delivers_and_exits_3`; `test_permanent_failure_is_recorded_not_raised` unchanged).
4. **A later audit that fails must keep the previous audit's open findings in the metadata and in the appendix, and a failed conveyor must deliver the writer's draft byte for byte.** Pinned in Task 3 (`test_an_audit_that_fails_after_a_loop_keeps_the_previous_findings_open`, `test_a_conveyor_that_never_answers_delivers_the_writers_draft`).
5. **The analyst must see on the Review page that the report was delivered without a stage, and the Audit tab must not claim "no findings" or "every rule passed" when the audit did not complete.** Pinned in Task 4 (`lists what did not complete when the report was delivered degraded`, `says the audit did not complete instead of saying no findings were recorded`).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/stages/audit_schema.py` (new) | `audit_output_type`, `to_audit_output`, `ENUM_LIMIT`. |
| `engine/corelata/stages/audit.py` | `run_auditor` sends the per-call type and converts; `audit_validator` wording. |
| `engine/corelata/prompts/templates/auditor/v2.j2` (new) | the auditor prompt for the keyed shape. |
| `engine/corelata/testing/synthetic.py` | the synthetic auditor answers keyed by rule id. |
| `engine/corelata/stages/context.py` | `check_refs` wording with real refs. |
| `engine/corelata/llm/agent.py` | `_repair_message` header. |
| `engine/corelata/schema/report.py` | `ReportMetadata.degradations`. |
| `engine/corelata/pipeline.py` | conveying and auditing degrade; `_degradation`; status. |
| `engine/corelata/trace.py` | `delivered_open_findings` reads `metadata.open_findings`. |
| `engine/corelata/render/outline.py`, `render/html.py`, `render/templates/report.html.j2` | the "Stages incomplete at delivery" appendix. |
| `engine/corelata/cli.py` | `corelata run` prints the degradations. |
| `schema/report.schema.json`, `schema/run-record.schema.json` | regenerated by `make schema`. |
| `web/src/api/types.ts`, `web/src/pages/review/ReviewPage.tsx`, `web/src/pages/review/AuditTab.tsx`, `web/src/test/fixtures.ts` | the notice and the Audit tab's incomplete state. |
| tests: `engine/tests/stages/{test_audit_schema (new),test_audit,test_context,test_gate,test_write}.py`, `engine/tests/llm/test_agent.py`, `engine/tests/testing/test_synthetic.py`, `engine/tests/{test_pipeline,test_cli}.py`, `engine/tests/render/{test_outline,test_html,test_docx}.py`, `engine/tests/schema/test_report.py`, `web/src/pages/review/{ReviewPage,AuditTab}.test.tsx` | the ticket's tests. |
| `README.md`, spec, `docs/operator-guide.md`, `docs/trace-format.md`, `docs/m11-followups.md` (new) | docs. |

---

### Task 1: The auditor's schema enforces the rules (CRL-25 part 1)

`run_auditor` sends `AuditOutput.model_json_schema()`, a list of `{rule_id, verdict, …}` objects with `verdict` any of four values and refs any string, so a `json_schema` server can only enforce the list's shape. The validator then rejects what the schema allowed. Keying `findings` by rule id makes every rule required and every other id meaningless (pydantic ignores extra keys), and the per-checkability `Literal` makes an illegal verdict ungeneratable.

**Files:**
- Create: `engine/corelata/stages/audit_schema.py`, `engine/corelata/prompts/templates/auditor/v2.j2`, `engine/tests/stages/test_audit_schema.py`
- Modify: `engine/corelata/stages/audit.py` (import lines 4-10, `run_auditor` lines 76-114), `engine/corelata/testing/synthetic.py` (`_auditor` lines 160-193)
- Test: `engine/tests/stages/test_audit.py` (imports lines 1-10, tests lines 40-79), `engine/tests/testing/test_synthetic.py` (`test_auditor_one_finding_per_rule` lines 151-163)

**Interfaces:**
- Produces: `audit_schema.ENUM_LIMIT = 200`; `audit_output_type(pack: ResolvedPack, unit_refs: list[str], claim_ids: list[str]) -> type[BaseModel]` (named `AuditByRule`; `$defs` `AuditFindings`, `VerifiableFinding`, `AdvisoryFinding`); `to_audit_output(parsed: BaseModel, pack: ResolvedPack) -> AuditOutput`. Auditor prompt version 2. `run_auditor`'s signature and `AuditOutcome` are unchanged.

- [ ] **Step 1: Failing tests**

Create `engine/tests/stages/test_audit_schema.py`:

```python
import json

import pytest
from pydantic import ValidationError

from corelata.schema import AuditOutput, Verdict
from corelata.stages.audit_schema import ENUM_LIMIT, audit_output_type, to_audit_output
from corelata.standards.schema import Checkability

REFS = ["src1/u1", "src1/u2", "src2/u1"]
CLAIMS = ["c0", "c1"]


def _reply(pack) -> dict:
    return {
        "findings": {
            r.id: {
                "verdict": "attested" if r.checkability is Checkability.ADVISORY else "pass",
                "evidence": f"e-{r.id}",
            }
            for r in pack.rules
        },
        "summary": "s",
    }


def test_every_rule_id_is_a_required_property_of_findings(pack):
    model = audit_output_type(pack, REFS, CLAIMS)
    schema = model.model_json_schema()
    findings = schema["$defs"]["AuditFindings"]
    assert findings["required"] == pack.rule_ids()
    assert list(findings["properties"]) == pack.rule_ids()
    assert schema["required"] == ["findings", "summary"] and model.__name__ == "AuditByRule"


def test_verdicts_are_restricted_by_checkability(pack):
    schema = audit_output_type(pack, REFS, CLAIMS).model_json_schema()
    props = schema["$defs"]["AuditFindings"]["properties"]
    assert {r.checkability for r in pack.rules} == set(Checkability)  # the pack has both kinds
    for r in pack.rules:
        name = props[r.id]["$ref"].rsplit("/", 1)[1]
        verdict = schema["$defs"][name]["properties"]["verdict"]
        if r.checkability is Checkability.ADVISORY:
            assert verdict["enum"] == ["attested", "not_applicable"], r.id
        else:
            assert verdict["enum"] == ["pass", "fail", "not_applicable"], r.id


def test_cited_units_and_claim_ids_are_enumerated_up_to_the_limit(pack):
    def items(refs, claims):
        schema = audit_output_type(pack, refs, claims).model_json_schema()
        props = schema["$defs"]["VerifiableFinding"]["properties"]
        return props["cited_units"]["items"], props["claim_ids"]["items"]

    assert items(REFS, CLAIMS) == (
        {"enum": REFS, "type": "string"},
        {"enum": CLAIMS, "type": "string"},
    )
    many = [f"src1/u{i}" for i in range(1, ENUM_LIMIT + 2)]
    assert len(items(many[:ENUM_LIMIT], CLAIMS)[0]["enum"]) == ENUM_LIMIT
    assert items(many, []) == ({"type": "string"}, {"type": "string"})  # too many; none


def test_a_reply_keyed_by_rule_id_converts_to_audit_output_in_pack_order(pack):
    model = audit_output_type(pack, REFS, CLAIMS)
    data = _reply(pack)
    first = pack.rules[0].id
    data["findings"][first] |= {
        "cited_units": ["src1/u2"],
        "claim_ids": ["c1"],
        "recommendation": "r",
    }
    data["findings"] = dict(reversed(list(data["findings"].items())))  # order is not meaning
    data["findings"]["icd203.as.6"] = {"verdict": "pass", "evidence": "x"}  # not a rule: ignored
    out = to_audit_output(model.model_validate_json(json.dumps(data)), pack)
    assert isinstance(out, AuditOutput) and out.summary == "s"
    assert [f.rule_id for f in out.findings] == pack.rule_ids()
    assert all(f.evidence == f"e-{f.rule_id}" for f in out.findings)
    head = out.findings[0]
    assert (head.cited_units, head.claim_ids, head.recommendation) == (["src1/u2"], ["c1"], "r")
    assert {f.verdict for f in out.findings} == {Verdict.PASS, Verdict.ATTESTED}


def test_an_out_of_enum_value_fails_and_names_the_rule_alias(pack):
    model = audit_output_type(pack, REFS, CLAIMS)
    advisory = next(r.id for r in pack.rules if r.checkability is Checkability.ADVISORY)
    verifiable = next(r.id for r in pack.rules if r.checkability is Checkability.VERIFIABLE)
    data = _reply(pack)
    data["findings"][advisory]["verdict"] = "pass"
    data["findings"][verifiable]["cited_units"] = ["src1"]  # a source id, not a unit
    with pytest.raises(ValidationError) as e:
        model.model_validate_json(json.dumps(data))
    assert {err["loc"] for err in e.value.errors()} == {
        ("findings", advisory, "verdict"),
        ("findings", verifiable, "cited_units", 0),
    }
```

In `engine/tests/stages/test_audit.py`, replace the imports (lines 1-10) with:

```python
import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Finding, Verdict
from corelata.stages.audit import AuditOutcome, apply_engine_checks, open_findings, run_auditor
from corelata.stages.write import run_writer
from corelata.standards.schema import Checkability
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT
```

Replace `test_validator_requires_one_finding_per_rule`, `test_validator_rejects_attested_verifiable_and_unknown_rule` and `lenient_reply` (lines 40-79) with:

```python
def lenient_reply(pack) -> str:
    """An auditor that waives everything: pass verifiable rules, attest advisory ones."""
    findings = {
        r.id: {
            "verdict": "attested" if r.checkability.value == "advisory" else "pass",
            "evidence": "looks fine",
        }
        for r in pack.rules
    }
    return json.dumps({"findings": findings, "summary": "All good."})


async def test_run_auditor_sends_the_by_rule_schema_and_returns_the_same_outcome(
    make_ctx, fake_backend
):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    outcome = await run_auditor(ctx, iteration=0, draft=draft)
    request = fake_backend.requests[-1]
    assert request.schema_name == "AuditByRule"
    defs = request.json_schema["$defs"]
    assert defs["AuditFindings"]["required"] == ctx.pack.rule_ids()
    cited = sorted({r for c in draft.claims for r in c.evidence})
    assert defs["VerifiableFinding"]["properties"]["cited_units"]["items"]["enum"] == cited
    claim_ids = defs["VerifiableFinding"]["properties"]["claim_ids"]["items"]["enum"]
    assert claim_ids == [c.id for c in draft.claims]
    assert ctx.runner.log.records[-1].prompt_version == 2
    expected = [
        Finding(
            rule_id=r.id,
            verdict=Verdict.ATTESTED if r.checkability is Checkability.ADVISORY else Verdict.PASS,
            evidence="Synthetic attestation."
            if r.checkability is Checkability.ADVISORY
            else "Synthetic check passed.",
            severity=r.severity.value,
            route_to=r.route_to.value,
            iteration=0,
        )
        for r in ctx.pack.rules
    ]
    assert outcome == AuditOutcome(expected, "Synthetic audit.")


async def test_the_schema_requires_a_finding_for_every_rule(make_ctx, fake_backend):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    reply = json.loads(lenient_reply(ctx.pack))
    del reply["findings"]["icd203.as.1"]
    bad = json.dumps(reply)
    fake_backend.script("auditor", bad, bad)
    with pytest.raises(StructuredOutputError, match=r"findings\.icd203\.as\.1: Field required"):
        await run_auditor(ctx, iteration=0, draft=draft)


async def test_the_schema_rejects_a_verdict_the_rule_does_not_allow(make_ctx, fake_backend):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    reply = json.loads(lenient_reply(ctx.pack))
    reply["findings"]["icd203.tc.8"]["verdict"] = "attested"
    reply["findings"]["zzz.x.1"] = {"verdict": "pass", "evidence": "e"}  # ignored, not an error
    bad = json.dumps(reply)
    fake_backend.script("auditor", bad, lenient_reply(ctx.pack))
    outcome = await run_auditor(ctx, iteration=0, draft=draft)
    assert outcome.summary == "All good."
    repair = fake_backend.requests[-1].messages[-1].content
    assert (
        "findings.icd203.tc.8.verdict: Input should be 'pass', 'fail' or 'not_applicable'"
        in repair
    )
    assert "zzz" not in repair
```

In `engine/tests/testing/test_synthetic.py`, replace `test_auditor_one_finding_per_rule` (lines 151-163) with:

```python
def _audit(draft) -> AuditOutput:
    raw = synthetic_response(audit_payload(draft))
    assert list(raw["findings"]) == [r["id"] for r in RULES]  # keyed by rule id, in order
    findings = [{"rule_id": rid, **f} for rid, f in raw["findings"].items()]
    return AuditOutput.model_validate({"findings": findings, "summary": raw["summary"]})


def test_auditor_one_finding_per_rule():
    draft = synthetic_response(writer_payload([*UNITS, extra_unit("UNSOURCED BADTERM")]))
    verdicts = {f.rule_id: f.verdict.value for f in _audit(draft).findings}
    assert verdicts == {
        "icd203.tc.2": "fail",
        "icd203.tc.8": "fail",
        "icd203.as.1": "attested",
        "icd203.as.5": "fail",
    }
    clean = synthetic_response(writer_payload())
    assert {f.verdict.value for f in _audit(clean).findings} == {"pass", "attested"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/stages/test_audit_schema.py tests/stages/test_audit.py tests/testing/test_synthetic.py --no-cov -q`
Expected: `test_audit_schema.py` fails to import `corelata.stages.audit_schema`; the `test_audit.py` tests fail (schema name `AuditOutput`, prompt version 1, the list-shaped synthetic reply); `test_auditor_one_finding_per_rule` fails on `raw["findings"]` being a list.

- [ ] **Step 3: The schema module**

Create `engine/corelata/stages/audit_schema.py`:

```python
"""The auditor's output schema, built per call (R-M11-1): `findings` is an object with one
required property per rule id, each allowing only the verdicts its checkability permits and,
while the lists are short enough to enumerate, only the unit refs and claim ids in scope. A
server configured `json_schema` enforces it while generating, so an advisory rule cannot be
passed, an invented rule id means nothing and a source id cannot be cited as a unit.
`audit_validator` still checks the converted output for servers that do not enforce schemas."""

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


def _choice(values: list[str]) -> Any:
    """`Literal[values]` when the list is short and not empty, else `str`."""
    return Literal[tuple(values)] if 0 < len(values) <= ENUM_LIMIT else str


def _finding_model(kind: Checkability, unit: Any, claim: Any) -> type[BaseModel]:
    return create_model(
        _NAMES[kind],
        verdict=(Literal[_VERDICTS[kind]], ...),
        evidence=(str, ...),
        cited_units=(list[unit], Field(default_factory=list)),
        claim_ids=(list[claim], Field(default_factory=list)),
        recommendation=(str, ""),
    )


def audit_output_type(
    pack: ResolvedPack, unit_refs: list[str], claim_ids: list[str]
) -> type[BaseModel]:
    unit, claim = _choice(unit_refs), _choice(claim_ids)
    models = {kind: _finding_model(kind, unit, claim) for kind in Checkability}
    fields: dict[str, Any] = {
        f"r{i}": (models[r.checkability], Field(alias=r.id)) for i, r in enumerate(pack.rules)
    }
    findings = create_model(
        "AuditFindings", __config__=ConfigDict(populate_by_name=True), **fields
    )
    return create_model("AuditByRule", findings=(findings, ...), summary=(str, ...))


def to_audit_output(parsed: BaseModel, pack: ResolvedPack) -> AuditOutput:
    """The list form everything downstream reads: one `FindingOut` per rule, in pack order."""
    by_rule = parsed.findings  # an AuditFindings built by audit_output_type for this pack
    return AuditOutput(
        findings=[
            FindingOut(rule_id=r.id, **getattr(by_rule, f"r{i}").model_dump())
            for i, r in enumerate(pack.rules)
        ],
        summary=parsed.summary,
    )
```

Only the models a pack uses appear in `$defs`, so a pack with no advisory rules sends no `AdvisoryFinding`.

- [ ] **Step 4: `run_auditor` sends it**

In `engine/corelata/stages/audit.py`, add after `from corelata.schema import AuditOutput, Finding, ReportBody, Verdict` (line 8):

```python
from corelata.stages.audit_schema import audit_output_type, to_audit_output
```

Replace `run_auditor` (lines 76-114) with:

```python
async def run_auditor(ctx: StageContext, *, iteration: int, draft: ReportBody) -> AuditOutcome:
    cited = sorted({r for c in draft.claims for r in c.evidence if ctx.index.has(r)})
    output_type = audit_output_type(ctx.pack, cited, [c.id for c in draft.claims])
    backstop = audit_validator(ctx)
    parsed = await ctx.runner.run(
        role="auditor",
        model_key=ctx.model_key("auditor"),
        prompt_id="auditor",
        prompt_vars={},
        payload={
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
                for r in ctx.pack.rules
            ],
            "lexicon": ctx.pack.lexicon.model_dump(),
            "cited_units": [{"ref": r, "text": ctx.index.text(r)} for r in cited],
            "value_statement": ctx.value_statement,
        },
        output_type=output_type,
        validate=lambda o: backstop(to_audit_output(o, ctx.pack)),
    )
    out = to_audit_output(parsed, ctx.pack)
    by_id = {f.rule_id: f for f in out.findings}
    findings = [
        Finding(
            **by_id[r.id].model_dump(),
            severity=r.severity.value,
            route_to=r.route_to.value,
            iteration=iteration,
        )
        for r in ctx.pack.rules
    ]
    return AuditOutcome(apply_engine_checks(draft, findings, ctx.pack), out.summary)
```

`AuditOutput` stays imported (the validator's annotation).

- [ ] **Step 5: The prompt and the synthetic auditor**

Create `engine/corelata/prompts/templates/auditor/v2.j2` (v1 stays for the record; the library serves the highest version):

```jinja
You are the compliance auditor for an intelligence reporting team. You never edit the report: you return findings only.
INPUT_JSON.draft is the report as JSON. INPUT_JSON.rules are the standards to check, each with an id, severity, checkability and the evidence required to decide it. INPUT_JSON.cited_units are the source passages the draft's claims cite, by "ref", so you can check that each claim is actually supported. INPUT_JSON.lexicon lists the only permitted likelihood terms, confidence levels, source descriptors and handling markings. INPUT_JSON.value_statement is what the analyst asked the report to establish.
Return "findings": a JSON object with exactly one key for every rule in INPUT_JSON.rules, the rule's id written exactly as given, whose value is that rule's finding; and a one-paragraph "summary". Do not add keys for anything that is not a rule id in INPUT_JSON.rules.
- verdict: for a rule whose checkability is "verifiable", "pass" or "fail", or "not_applicable" when the rule's subject is absent by design (say why). For a rule whose checkability is "advisory", "attested" with a note on what you observed, or "not_applicable"; never "pass" or "fail".
- evidence: what in the draft, or missing from it, decided the verdict. For icd203.tc.8 and icd206.src.2, name every claim whose cited passages do not support it, or that cites nothing.
- cited_units: the refs you examined for this rule, copied exactly from INPUT_JSON.cited_units (a ref has the form "<source id>/<unit id>"; a source id alone is not a ref). claim_ids: the ids from INPUT_JSON.draft.claims you examined.
- recommendation: for a fail, one or two sentences the writer or reviewer can act on.
Be strict: a claim whose evidence list is empty fails icd203.tc.8. A judgment using a likelihood term outside the lexicon fails icd203.tc.2.
Respond with a single JSON object only.
```

In `engine/corelata/testing/synthetic.py`, `_auditor` (lines 160-193): change `findings = []` (line 164) to `findings: dict[str, Payload] = {}`, and replace the `findings.append(...)` call (lines 183-192) with:

```python
        findings[rid] = {
            "verdict": verdict,
            "evidence": evidence,
            "cited_units": [],
            "claim_ids": unsourced if verdict == "fail" else [],
            "recommendation": rec,
        }
```

The `return {"findings": findings, "summary": "Synthetic audit."}` line stays. The demo stack, the e2e journey and the bench all answer through `synthetic_response`, so they move with it.

- [ ] **Step 6: Run the engine suite and lint**

Run: `make test-engine` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, coverage ≥ 95%. `test_clean_draft_passes`, `test_marked_draft_fails_with_routing`, both engine-override tests, `test_lenient_auditor_cannot_deliver_clean_with_unsourced_claims` (it imports `lenient_reply`) and `tests/test_invariants.py` pass unchanged; `test_override_dir_wins` still reports `{"auditor": 2}` from its own override. If ruff format reflows the new code, accept its formatting.

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m11-task1-commit.txt <<'EOF'
feat(engine): the auditor's schema enforces one legal finding per rule (CRL-25)

run_auditor sends a per-call AuditByRule schema: findings keyed by rule id,
every rule required, verdicts restricted by checkability, cited units and
claim ids enumerated from the draft. A json_schema server enforces it while
generating; the parsed object is converted to AuditOutput in pack order and
audit_validator still checks it. Auditor prompt v2; the synthetic auditor
answers in the keyed shape.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/stages/audit_schema.py engine/corelata/stages/audit.py engine/corelata/prompts/templates/auditor/v2.j2 engine/corelata/testing/synthetic.py engine/tests/stages/test_audit_schema.py engine/tests/stages/test_audit.py engine/tests/testing/test_synthetic.py
git commit -F <scratchpad>/m11-task1-commit.txt
```

---

### Task 2: Repair messages say what to write (CRL-25 part 3)

The dry run's repair turns fed back "advisory rule 'icd203.as.1' is attested, not passed or failed" and "unknown unit ref 'src1'": statements of what was wrong, which a 1.5B model answered by repeating the mistake. The new messages are imperative and carry the values to copy.

**Files:**
- Modify: `engine/corelata/stages/audit.py` (`audit_validator` lines 16-39), `engine/corelata/stages/context.py` (`check_refs` lines 69-71), `engine/corelata/llm/agent.py` (`_repair_message` lines 55-57)
- Test: `engine/tests/stages/test_audit.py`, `engine/tests/stages/test_context.py`, `engine/tests/llm/test_agent.py` (import line 6; `test_invalid_output_is_repaired_once` line 90), `engine/tests/stages/test_gate.py` (line 53), `engine/tests/stages/test_write.py` (line 71)

**Interfaces:**
- Produces: the R-M11-3 strings. No signature changes.

- [ ] **Step 1: Failing tests**

In `engine/tests/stages/test_audit.py`, change the imports from Task 1 to:

```python
from corelata.schema import AuditOutput, Finding, FindingOut, Verdict
from corelata.stages.audit import (
    AuditOutcome,
    apply_engine_checks,
    audit_validator,
    open_findings,
    run_auditor,
)
```

and append:

```python
def _legal(pack) -> list[FindingOut]:
    return [
        FindingOut(
            rule_id=r.id,
            verdict=Verdict.ATTESTED if r.checkability is Checkability.ADVISORY else Verdict.PASS,
            evidence="e",
        )
        for r in pack.rules
    ]


def _errors(ctx, findings: list[FindingOut]) -> list[str]:
    return audit_validator(ctx)(AuditOutput(findings=findings, summary="s"))


def _swap(findings: list[FindingOut], rule_id: str, **update) -> list[FindingOut]:
    return [f.model_copy(update=update) if f.rule_id == rule_id else f for f in findings]


def test_validator_accepts_one_legal_finding_per_rule(make_ctx):
    ctx = make_ctx()
    assert _errors(ctx, _legal(ctx.pack)) == []


def test_validator_tells_the_model_the_verdicts_an_advisory_rule_takes(make_ctx):
    ctx = make_ctx()
    assert _errors(ctx, _swap(_legal(ctx.pack), "icd203.as.1", verdict=Verdict.PASS)) == [
        "rule 'icd203.as.1' is advisory: set its verdict to 'attested' (or 'not_applicable'), "
        "not 'pass'"
    ]


def test_validator_tells_the_model_the_verdicts_a_verifiable_rule_takes(make_ctx):
    ctx = make_ctx()
    assert _errors(ctx, _swap(_legal(ctx.pack), "icd203.tc.8", verdict=Verdict.ATTESTED)) == [
        "rule 'icd203.tc.8' is verifiable: set its verdict to 'pass', 'fail' or "
        "'not_applicable', not 'attested'"
    ]


def test_validator_lists_the_rule_ids_for_an_unknown_rule(make_ctx):
    ctx = make_ctx()
    extra = FindingOut(rule_id="icd203.as.6", verdict=Verdict.ATTESTED, evidence="e")
    assert _errors(ctx, [*_legal(ctx.pack), extra]) == [
        "'icd203.as.6' is not a rule in this pack; the rule ids are: "
        + ", ".join(ctx.pack.rule_ids())
    ]


def test_validator_asks_for_exactly_one_finding_and_names_a_missing_one(make_ctx):
    ctx = make_ctx()
    legal = _legal(ctx.pack)
    twice = next(f for f in legal if f.rule_id == "icd203.tc.8")
    assert _errors(ctx, [*legal, twice]) == ["give exactly one finding for rule 'icd203.tc.8'"]
    missing = [f for f in legal if f.rule_id != "icd203.as.1"]
    assert _errors(ctx, missing) == ["missing a finding for rule 'icd203.as.1'"]


def test_validator_names_real_unit_ids_for_a_bad_ref(make_ctx):
    ctx = make_ctx()
    found = _swap(_legal(ctx.pack), "icd203.tc.8", cited_units=["src1"])
    assert _errors(ctx, found) == [
        "'src1' is not a unit id; cite unit ids exactly as given in the input, such as "
        "src1/u1, src1/u2, src1/u3"
    ]
```

In `engine/tests/stages/test_context.py`, change the imports to:

```python
from corelata.ingest.units import UnitIndex
from corelata.stages.context import StageError, estimate_tokens
from corelata.testing.sources import text_source
```

and append:

```python
HINT = "is not a unit id; cite unit ids exactly as given in the input, such as"


def test_check_refs_names_up_to_three_real_refs_to_copy(make_ctx):
    ctx = make_ctx(text_source("src1", "alpha", "beta"), text_source("src2", "gamma", "delta"))
    assert ctx.check_refs(["src1/u1", "src1", "src2/u9"]) == [
        f"'src1' {HINT} src1/u1, src1/u2, src2/u1",
        f"'src2/u9' {HINT} src1/u1, src1/u2, src2/u1",
    ]
    assert ctx.check_refs(["src2/u2"]) == []
    ctx.index = UnitIndex()  # no units at all: the form is the only example there is
    assert ctx.check_refs(["x"]) == [f"'x' {HINT} <source_id>/<unit_id>"]
```

In `engine/tests/llm/test_agent.py`, change line 6 to `from corelata.llm.agent import StructuredOutputError, _repair_message, extract_json`; in `test_invalid_output_is_repaired_once` replace `assert "invalid" in repair[3].content` (line 90) with:

```python
    assert repair[3].content.startswith("Your previous response was rejected.")
```

and append:

```python
def test_the_repair_message_is_an_instruction_with_every_point():
    assert _repair_message(["first", "second"]) == (
        "Your previous response was rejected. Fix every point below and return the complete "
        "corrected JSON object only:\n- first\n- second"
    )
    assert _repair_message([str(i) for i in range(25)]).count("\n- ") == 20
```

In `engine/tests/stages/test_gate.py` line 53 change the match to `match="'src7/u1' is not a unit id"`; in `engine/tests/stages/test_write.py` line 71 change it to `match="'src9/u1' is not a unit id"`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/stages/test_audit.py tests/stages/test_context.py tests/llm/test_agent.py tests/stages/test_gate.py tests/stages/test_write.py --no-cov -q`
Expected: the five new validator tests, the `check_refs` test, the two agent tests and the gate and writer ref tests fail on the old wording; `test_validator_accepts_one_legal_finding_per_rule` passes.

- [ ] **Step 3: The wording**

In `engine/corelata/stages/audit.py`, replace `audit_validator` (lines 16-39) with:

```python
def audit_validator(ctx: StageContext) -> Callable[[AuditOutput], list[str]]:
    """The backstop for servers that do not enforce the schema (R-M11-1); every message tells the
    model what to write (R-M11-3)."""
    rules = {r.id: r for r in ctx.pack.rules}
    known = ", ".join(rules)

    def validate(out: AuditOutput) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for f in out.findings:
            rule = rules.get(f.rule_id)
            if rule is None:
                errors.append(
                    f"'{f.rule_id}' is not a rule in this pack; the rule ids are: {known}"
                )
                continue
            if f.rule_id in seen:
                errors.append(f"give exactly one finding for rule '{f.rule_id}'")
            seen.add(f.rule_id)
            if rule.checkability is Checkability.VERIFIABLE and f.verdict is Verdict.ATTESTED:
                errors.append(
                    f"rule '{f.rule_id}' is verifiable: set its verdict to 'pass', 'fail' or "
                    "'not_applicable', not 'attested'"
                )
            advisory = rule.checkability is Checkability.ADVISORY
            if advisory and f.verdict in (Verdict.PASS, Verdict.FAIL):
                errors.append(
                    f"rule '{f.rule_id}' is advisory: set its verdict to 'attested' (or "
                    f"'not_applicable'), not '{f.verdict.value}'"
                )
            errors += ctx.check_refs(f.cited_units)
        errors += [f"missing a finding for rule '{rid}'" for rid in rules if rid not in seen]
        return errors

    return validate
```

In `engine/corelata/stages/context.py`, replace `check_refs` (lines 69-71) with:

```python
    def check_refs(self, refs: list[str]) -> list[str]:
        """Validation errors for refs that are not in the index (used by every validator),
        worded as an instruction with real refs to copy (R-M11-3)."""
        bad = [r for r in refs if not self.index.has(r)]
        if not bad:
            return []
        examples = ", ".join(self.index.refs()[:3]) or "<source_id>/<unit_id>"
        return [
            f"'{r}' is not a unit id; cite unit ids exactly as given in the input, "
            f"such as {examples}"
            for r in bad
        ]
```

In `engine/corelata/llm/agent.py`, replace `_repair_message` (lines 55-57) with:

```python
def _repair_message(errors: list[str]) -> str:
    bullets = "\n".join(f"- {e}" for e in errors[:20])
    return (
        "Your previous response was rejected. Fix every point below and return the complete "
        f"corrected JSON object only:\n{bullets}"
    )
```

- [ ] **Step 4: Run the engine suite and lint**

Run: `make test-engine` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, coverage ≥ 95%. `test_invariant_2_one_finding_per_rule_with_legal_verdict` passes unchanged (it compares `errors == []` only), as does `test_digest_validator_rejects_gaps_and_foreign_refs` (the digest validator has its own messages). Grep for leftovers: `grep -rn "unknown unit ref\|missing finding for\|cannot be attested\|previous response was invalid" engine api` prints nothing.

- [ ] **Step 5: Commit**

```bash
cat > <scratchpad>/m11-task2-commit.txt <<'EOF'
fix(engine): repair messages tell the model what to write (CRL-25)

The audit validator names the verdicts a rule takes and the rule ids a pack
has; check_refs names real unit ids to copy; the repair turn asks for the
complete corrected object.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/stages/audit.py engine/corelata/stages/context.py engine/corelata/llm/agent.py engine/tests/stages/test_audit.py engine/tests/stages/test_context.py engine/tests/llm/test_agent.py engine/tests/stages/test_gate.py engine/tests/stages/test_write.py
git commit -F <scratchpad>/m11-task2-commit.txt
```

---

### Task 3: Deliver the report when the auditor or the conveyor fails (CRL-25 part 2)

`execute()` catches `(*AGENT_FAILURES, StageError)` once, around the whole run, and sets `failed`. The writer's draft exists by the time either the conveyor or the auditor runs, so the run has something to deliver. `delivered_open_findings` picks the findings of iteration `record.iterations`; after an audit that did not complete at iteration k ≥ 1, the open findings are iteration k-1's, so it must read the ids `metadata.open_findings` names instead (the same result for every run that audited its last iteration).

**Files:**
- Modify: `engine/corelata/schema/report.py` (`ReportMetadata` lines 105-112), `engine/corelata/pipeline.py` (docstring lines 1-2; after `_record_stage` line 221; loop lines 244-309), `engine/corelata/trace.py` (`delivered_open_findings` lines 131-135), `engine/corelata/render/outline.py` (line 18; lines 133-136), `engine/corelata/render/html.py` (line 9; lines 31-37), `engine/corelata/render/templates/report.html.j2` (line 45), `engine/corelata/cli.py` (lines 322-326), `schema/report.schema.json`, `schema/run-record.schema.json` (generated)
- Test: `engine/tests/test_pipeline.py`, `engine/tests/test_cli.py`, `engine/tests/render/test_outline.py`, `engine/tests/render/test_html.py`, `engine/tests/render/test_docx.py`, `engine/tests/schema/test_report.py`

**Interfaces:**
- Produces: `ReportMetadata.degradations: list[str]` (default `[]`); `outline.DEGRADATION_TITLE = "Stages incomplete at delivery"`; `_Run._degradation(what, state, iteration, error) -> str`; the template variable `appendix_titles` (replaces `appendix_title`).

- [ ] **Step 1: Failing tests**

In `engine/tests/test_pipeline.py`, add to the imports (keep isort order):

```python
from corelata.exports import render_outputs
from corelata.render.outline import DEGRADATION_TITLE
from corelata.trace import delivered_open_findings
```

and append:

```python
BAD = "this is not JSON"  # four of them: two stage attempts, each a first try and a repair


async def test_an_auditor_that_never_answers_delivers_the_report_marked_incomplete(
    run, fake_backend
):
    fake_backend.script("auditor", *[BAD] * 4)
    rec = await run()
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.FINDINGS_OPEN
    assert rec.error is None and rec.findings == [] and rec.iterations == 0
    meta = rec.report.metadata
    assert meta.status is ReportStatus.FINDINGS_OPEN and meta.open_findings == []
    [note] = meta.degradations
    assert note.startswith(
        "audit incomplete after 2 attempts: auditor: invalid output after repair: "
    )
    assert [s.ok for s in rec.stages if s.stage == "auditing"] == [False, False]
    assert rec.stages[-1].stage == "rendering" and rec.stages[-1].ok
    assert rec.report.title.startswith("Conveyed: ")  # the conveyed draft is what is delivered
    files = render_outputs(rec, load_pack("icd203-base"), with_claim_ids=False, formats=["md"])
    assert f"## {DEGRADATION_TITLE}\n\n- {note}\n" in files["report.md"]


async def test_an_audit_that_fails_after_a_loop_keeps_the_previous_findings_open(
    run, fake_backend
):
    from tests.stages.test_audit import lenient_reply

    # iteration 0: the engine check fails icd203.tc.8 for the unsourced claim, so the writer
    # revises; iteration 1's audit never answers
    fake_backend.script("auditor", lenient_reply(load_pack("icd203-base")), *[BAD] * 4)
    rec = await run(text_source("src1", *PORT, "UNSOURCED detail on Varna."))
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.FINDINGS_OPEN
    assert rec.iterations == 1 and {f.iteration for f in rec.findings} == {0}
    assert rec.report.unsourced_claims() == []  # the revision fixed it, but no audit said so
    assert rec.report.metadata.open_findings == ["icd203.tc.8@0"]
    assert [f.id for f in delivered_open_findings(rec)] == ["icd203.tc.8@0"]
    [note] = rec.report.metadata.degradations
    assert note.startswith("audit incomplete after 2 attempts: ")


async def test_a_conveyor_that_never_answers_delivers_the_writers_draft(run, fake_backend):
    fake_backend.script("conveyor", *[BAD] * 4)
    rec = await run()
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.FINDINGS_OPEN
    assert [d.role for d in rec.drafts] == ["writer"]
    writer = rec.drafts[0].report
    assert rec.report.model_dump(exclude={"metadata"}) == writer.model_dump()
    assert _payloads(fake_backend, "auditor")[0]["draft"] == writer.model_dump()
    assert rec.report.metadata.open_findings == []
    [note] = rec.report.metadata.degradations
    assert note.startswith(
        "conveyance skipped after 2 attempts: conveyor: invalid output after repair: "
    )
    assert [s.stage for s in rec.stages if s.ok] == [
        "ingesting",
        "gating",
        "drafting",
        "auditing",
        "rendering",
    ]


async def test_an_auditor_overflow_once_the_ladder_is_spent_degrades_after_one_attempt(
    run, fake_backend
):
    fake_backend.script("gate", ContextOverflowError("too long"))  # spends the halving ladder
    fake_backend.script("auditor", ContextOverflowError("auditor window exceeded"))
    rec = await run()
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.FINDINGS_OPEN
    assert rec.report.metadata.degradations == [
        "audit incomplete after 1 attempt: auditor window exceeded"
    ]
```

In `engine/tests/test_cli.py`, add the imports `from corelata.render.outline import DEGRADATION_TITLE` and `from corelata.testing import synthetic` (isort order), and append:

```python
def test_run_with_an_unusable_auditor_delivers_and_exits_3(
    config_path, inputs, tmp_path, capsys, monkeypatch
):
    # the fake server answers through synthetic._HANDLERS in this process
    monkeypatch.setitem(synthetic._HANDLERS, "auditor", lambda p: {"findings": [], "summary": ""})
    out = tmp_path / "out"
    statement = "Varna port capacity expansion matters to shippers"
    code = main(
        ["run", *inputs, "--statement", statement, "--config", str(config_path), "--out", str(out)]
    )
    assert code == 3
    meta = json.loads((out / "report.json").read_text())["metadata"]
    assert meta["status"] == "findings_open" and meta["open_findings"] == []
    [note] = meta["degradations"]
    assert note.startswith("audit incomplete after 2 attempts: auditor: invalid output after")
    assert "findings: Input should be an object" in note
    md = (out / "report.md").read_text()
    assert f"## {DEGRADATION_TITLE}" in md and note in md
    captured = capsys.readouterr()
    assert "completed findings_open" in captured.out and note in captured.err
```

In `engine/tests/render/test_outline.py`, add `DEGRADATION_TITLE` to the `corelata.render.outline` import and append:

```python
def test_degradations_come_before_the_open_findings_appendix_unnumbered():
    report = make_report(status="findings_open", degradations=["audit incomplete: boom"])
    blocks = build_outline(report, NUMBERED, SOURCES, open_findings=[make_finding()])
    labels = [b.label for b in blocks if isinstance(b, Heading)]
    assert labels[-2:] == [DEGRADATION_TITLE, APPENDIX_TITLE]
    assert blocks[-4] == Bullets((Item("audit incomplete: boom"),), "degradations")
    plain = build_outline(make_report(), PACK, SOURCES)
    assert all(not (isinstance(b, Heading) and b.text == DEGRADATION_TITLE) for b in plain)
    md = render_markdown(report, PACK, SOURCES)
    assert f"## {DEGRADATION_TITLE}\n\n- audit incomplete: boom\n" in md
```

In `engine/tests/render/test_html.py`, add `from corelata.render.outline import DEGRADATION_TITLE` and append:

```python
def test_html_puts_degradations_in_an_appendix_section():
    report = make_report(status="findings_open", degradations=["conveyance skipped: boom"])
    out = render_html(report, PACK, SOURCES)
    doc = _doc(out)
    assert doc.xpath("//section[@class='appendix']/h2/text()") == [DEGRADATION_TITLE]
    assert doc.xpath("//ul[@class='degradations']/li/text()") == ["conveyance skipped: boom"]
    assert "status findings_open" in out
```

In `engine/tests/render/test_docx.py`, add `from corelata.render.outline import DEGRADATION_TITLE` and append:

```python
def test_docx_lists_degradations():
    report = make_report(status="findings_open", degradations=["audit incomplete: boom"])
    doc = _open(render_docx(report, PACK, SOURCES))
    assert _texts(doc, "Heading 2")[-1] == DEGRADATION_TITLE
    assert _texts(doc, "List Bullet")[-1] == "audit incomplete: boom"
```

In `engine/tests/schema/test_report.py`, append:

```python
def test_metadata_degradations_default_to_none_and_older_reports_load():
    older = ReportMetadata.model_validate({"pack_name": "p", "pack_hash": "h", "status": "clean"})
    assert older.degradations == []
    m = ReportMetadata(pack_name="p", pack_hash="h", degradations=["audit incomplete: x"])
    assert m.model_dump(mode="json")["degradations"] == ["audit incomplete: x"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_pipeline.py tests/test_cli.py tests/render tests/schema/test_report.py --no-cov -q`
Expected: import errors for `DEGRADATION_TITLE`; once it exists, the pipeline tests end `failed`, the CLI exits 1, and `ReportMetadata` rejects nothing but has no `degradations`.

- [ ] **Step 3: The metadata field**

In `engine/corelata/schema/report.py`, after `open_findings: list[str] = Field(default_factory=list)  # Finding ids` (line 112) add:

```python
    # Stages the report was delivered without (R-M11-2), for example
    # "audit incomplete after 2 attempts: <error>"; any entry makes the status findings_open.
    degradations: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: The pipeline**

In `engine/corelata/pipeline.py`, replace the module docstring (lines 1-2) with:

```python
"""The run: gate → writer → conveyor → auditor with one bounded loop (spec §7). A gate or writer
failure ends the run in `failed` with the error recorded; a conveyor or auditor failure is
recorded as a degradation and the report is still delivered (R-M11-2). Nothing raises."""
```

After `_record_stage` (ends line 221) add:

```python
    def _degradation(self, what: str, state: RunState, iteration: int, error: Exception) -> str:
        """R-M11-2: the line the report carries for a stage it was delivered without, counting
        the attempts `stage()` recorded as failed for that stage and iteration."""
        n = sum(
            1
            for s in self.record.stages
            if s.stage == state.value and s.iteration == iteration and not s.ok
        )
        return f"{what} after {n} attempt{'' if n == 1 else 's'}: {error}"
```

In `engine/corelata/stages/audit.py`, after `apply_engine_checks` add (R-M11-6):

```python
def engine_only_findings(draft: ReportBody, pack: ResolvedPack, iteration: int) -> list[Finding]:
    """Spec §8.4 invariant 1 without an auditor (R-M11-6): the engine fails icd203.tc.8 on every
    unsourced claim and icd206.src.2 on one a key judgment cites; it asserts nothing else."""
    rules = {r.id: r for r in pack.rules}
    seeds = [
        Finding(
            rule_id=rid,
            verdict=Verdict.PASS,
            evidence="",
            severity=rules[rid].severity.value,
            route_to=rules[rid].route_to.value,
            iteration=iteration,
        )
        for rid in ("icd203.tc.8", "icd206.src.2")
        if rid in rules
    ]
    return [f for f in apply_engine_checks(draft, seeds, pack) if f.verdict is Verdict.FAIL]
```

and import it in `pipeline.py` next to `apply_engine_checks`/`open_findings`/`run_auditor` (line 186 of the plan's import list: `from corelata.stages.audit import AuditOutcome, engine_only_findings, open_findings, run_auditor`, dropping names the module no longer uses).

In `execute()`, after `findings: list[Finding] = []` (line 244) add `degradations: list[str] = []`, and replace the block from `draft = await self.stage(RunState.CONVEYING, …` through `findings = outcome.findings` (lines 265-286) with:

```python
                try:
                    draft = await self.stage(
                        RunState.CONVEYING,
                        iteration,
                        lambda it=iteration, d=draft, r=routed: run_conveyor(
                            self.ctx,
                            iteration=it,
                            draft=d,
                            findings=[f for f in r if f.route_to == "conveyor"],
                        ),
                        lambda b: {"title": b.title},
                    )
                except (*AGENT_FAILURES, StageError) as e:
                    # R-M11-2: the conveyor's input goes forward unedited and is audited
                    degradations.append(
                        self._degradation("conveyance skipped", RunState.CONVEYING, iteration, e)
                    )
                else:
                    rec.drafts.append(
                        DraftRecord(role="conveyor", iteration=iteration, report=draft)
                    )
                try:
                    outcome: AuditOutcome = await self.stage(
                        RunState.AUDITING,
                        iteration,
                        lambda it=iteration, d=draft: run_auditor(self.ctx, iteration=it, draft=d),
                        lambda o: {
                            "open": [f.id for f in open_findings(o.findings)],
                            "summary": o.summary,
                        },
                    )
                except (*AGENT_FAILURES, StageError) as e:
                    # R-M11-2: deliver with the previous audit's findings (none on iteration 0);
                    # R-M11-6: the engine's own checks still run on the delivered draft.
                    degradations.append(
                        self._degradation("audit incomplete", RunState.AUDITING, iteration, e)
                    )
                    engine = engine_only_findings(draft, self.ctx.pack, iteration)
                    replaced = {f.rule_id for f in engine}
                    findings = [f for f in findings if f.rule_id not in replaced] + engine
                    rec.findings.extend(engine)
                    break
                findings = outcome.findings
```

Also in Step 1, add to `engine/tests/test_pipeline.py` a test for R-M11-6 next to the auditor-never-answers test, scripting the writer (with the same helper the file already uses to script a writer reply) to return a draft with one claim whose `evidence` is `[]` and the auditor with `*[BAD] * 4`:

```python
async def test_an_incomplete_audit_still_fails_unsourced_claims(run, fake_backend):
    fake_backend.script("writer", UNSOURCED_DRAFT)  # a valid ReportBody with one claim, evidence []
    fake_backend.script("auditor", *[BAD] * 4)
    rec = await run()
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.FINDINGS_OPEN
    failed = {f.rule_id: f for f in rec.findings if f.verdict is Verdict.FAIL}
    assert "icd203.tc.8" in failed and failed["icd203.tc.8"].evidence.startswith("engine check")
    assert "icd203.tc.8@0" in rec.report.metadata.open_findings
    assert len(rec.report.metadata.degradations) == 1
```

`UNSOURCED_DRAFT` is the JSON text of a `ReportBody` the file's existing writer fixtures produce, with the claim's `evidence` list emptied (build it with `model_copy(update=...)` + `model_dump_json()` from the fixture the file already has; do not invent a new draft shape). Add `from corelata.schema import Verdict` to the imports if it is not there.

Replace `status = ReportStatus.FINDINGS_OPEN if still_open else ReportStatus.CLEAN` (line 295) with:

```python
            degraded = still_open or degradations
            status = ReportStatus.FINDINGS_OPEN if degraded else ReportStatus.CLEAN
```

and in the `ReportMetadata(...)` call, after `open_findings=[f.id for f in still_open],` (line 308) add `degradations=degradations,`. A `RunCancelled` raised at a stage boundary is not caught by the new `except` clauses, so a cancel still ends the run `cancelled`.

- [ ] **Step 5: The appendix reads the metadata**

In `engine/corelata/trace.py`, replace `delivered_open_findings` (lines 131-135) with:

```python
def delivered_open_findings(record: RunRecord) -> list[Finding]:
    """What the appendix lists: the findings `metadata.open_findings` names, which are the last
    completed audit's looping failures (the previous one's when the last audit did not complete,
    R-M11-2)."""
    if record.report is None:
        return []
    ids = set(record.report.metadata.open_findings)
    return [f for f in record.findings if f.id in ids]
```

`open_findings` stays imported (`summarize` uses it). `test_summarize_findings_loop_and_open_at_delivery`'s order (`as.5`, `tc.8`, `src.2`) is the order of `record.findings`, as before.

- [ ] **Step 6: The renders and the CLI**

In `engine/corelata/render/outline.py`, after `APPENDIX_TITLE = "Audit findings open at delivery"` (line 18) add:

```python
DEGRADATION_TITLE = "Stages incomplete at delivery"  # R-M11-2: stages it was delivered without
```

and replace the appendix lines (133-135) with:

```python
    if report.metadata.degradations:
        out.append(Heading(DEGRADATION_TITLE))
        items = tuple(Item(d) for d in report.metadata.degradations)
        out.append(Bullets(items, "degradations"))
    if open_findings:
        out.append(Heading(APPENDIX_TITLE))
        out.append(Bullets(tuple(Item(finding_line(f)) for f in open_findings), "findings"))
```

Add `degradations` to the `Bullets.role` comment (line 62): `# key_judgments | sources | alternatives | gaps | degradations | findings`.

In `engine/corelata/render/html.py`, change line 9 to `from corelata.render.outline import APPENDIX_TITLE, DEGRADATION_TITLE, build_outline` and `appendix_title=APPENDIX_TITLE,` in the render call to `appendix_titles=(DEGRADATION_TITLE, APPENDIX_TITLE),`. In `engine/corelata/render/templates/report.html.j2` line 45, `{% if b.text == appendix_title %}` becomes `{% if b.text in appendix_titles %}`. The goldens (`varna.html`, the Markdown golden) do not change: their reports have no degradations.

In `engine/corelata/cli.py`, replace the closing lines of the run command (322-326) with:

```python
    print(
        f"run {record.run_id}: completed {record.status.value} after {record.iterations} "
        f"revision(s), {record.usage.calls} model calls -> {out_dir}"
    )
    assert record.report is not None  # a completed run always has one
    for note in record.report.metadata.degradations:
        print(f"run {record.run_id}: {note}", file=sys.stderr)
    return EXIT_FINDINGS_OPEN if record.status is ReportStatus.FINDINGS_OPEN else EXIT_OK
```

- [ ] **Step 7: Regenerate the schemas**

Run: `make schema`, then `git status --short schema web/src/api`
Expected: exactly `M schema/report.schema.json` and `M schema/run-record.schema.json` (each gains `degradations` under `ReportMetadata`). If `schema/openapi.json` or `web/src/api/schema.d.ts` also changed, they belong in this commit too (R-M11-4); add them to the `git add` below.

- [ ] **Step 8: Run the engine and API suites and lint**

Run: `make test-engine`, `make test-api` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, coverage ≥ 95%. `test_committed_schema_matches_models` passes with the regenerated files; `test_permanent_failure_is_recorded_not_raised` (writer) and `test_second_oversize_fails` (gate) still end `failed`; `test_a_cancel_during_the_loop_keeps_the_findings_so_far` still ends `cancelled`; `test_auditing_stage_records_summary` and the scenario tests are unchanged. `test_committed_openapi_matches_the_app` passes.

- [ ] **Step 9: Commit**

```bash
cat > <scratchpad>/m11-task3-commit.txt <<'EOF'
feat(engine): deliver the report when the auditor or conveyor fails (CRL-25)

A conveying failure forwards the conveyor's input draft; an auditing failure
ends the loop with the previous audit's findings. Each records a line in the
new ReportMetadata.degradations, which forces findings_open, renders as the
"Stages incomplete at delivery" appendix and is printed by corelata run (exit
3). The appendix of open findings reads metadata.open_findings. Gate and
writer failures still end the run failed. Schemas regenerated.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/schema/report.py engine/corelata/pipeline.py engine/corelata/trace.py engine/corelata/render/outline.py engine/corelata/render/html.py engine/corelata/render/templates/report.html.j2 engine/corelata/cli.py schema/report.schema.json schema/run-record.schema.json engine/tests/test_pipeline.py engine/tests/test_cli.py engine/tests/render/test_outline.py engine/tests/render/test_html.py engine/tests/render/test_docx.py engine/tests/schema/test_report.py
git commit -F <scratchpad>/m11-task3-commit.txt
```

---

### Task 4: The review screen says what did not complete (web)

`ReviewPage` already loads `report.json` (`useReportJson`, `staleTime: Infinity`) for the title, status and open-finding count; the degradations come from the same object, and the Audit tab receives them as a prop rather than issuing its own request. `ReportJson` is the hand-written type in `web/src/api/types.ts`; `degradations` is optional there because a report delivered before M11 has no such key.

**Files:**
- Modify: `web/src/api/types.ts` (`ReportJson` lines 50-62), `web/src/pages/review/ReviewPage.tsx` (lines 51-69, 91-92), `web/src/pages/review/AuditTab.tsx` (lines 78-99), `web/src/test/fixtures.ts` (after `reportJson`, line 398)
- Test: `web/src/pages/review/ReviewPage.test.tsx`, `web/src/pages/review/AuditTab.test.tsx`

**Interfaces:**
- Produces: `ReportJson.metadata.degradations?: string[]`; `AuditTab({ runId, degradations = [] })`; fixtures `AUDIT_INCOMPLETE`, `degradedReportJson`.

- [ ] **Step 1: Fixtures and failing tests**

In `web/src/test/fixtures.ts`, after `reportJson` add:

```ts
/** What a run's report carries when its last audit failed twice (R-M11-2). */
export const AUDIT_INCOMPLETE =
  "audit incomplete after 2 attempts: auditor: invalid output after repair: " +
  "findings.icd203.as.1: Field required";

export const degradedReportJson: ReportJson = {
  ...reportJson,
  metadata: {
    ...reportJson.metadata,
    status: "findings_open",
    degradations: [AUDIT_INCOMPLETE],
  },
};
```

In `web/src/pages/review/ReviewPage.test.tsx`, add `AUDIT_INCOMPLETE` and `degradedReportJson` to the fixtures import, add to the end of the first test (after the click on the Audit tab):

```tsx
  expect(screen.queryByRole("region", { name: "Incomplete at delivery" })).toBeNull();
```

and append:

```tsx
it("lists what did not complete when the report was delivered degraded", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "findings_open" })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json(degradedReportJson),
    ),
    ...tabHandlers,
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  const notice = await screen.findByRole("region", { name: "Incomplete at delivery" });
  expect(notice).toHaveTextContent("delivered without every stage completing");
  expect(within(notice).getByRole("listitem")).toHaveTextContent(AUDIT_INCOMPLETE);
  expect(screen.getByText("Findings open")).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Audit" }));
  expect(
    await screen.findByText(
      "The audit did not complete: auditor: invalid output after repair: " +
        "findings.icd203.as.1: Field required",
    ),
  ).toBeInTheDocument();
}, 15_000);
```

In `web/src/pages/review/AuditTab.test.tsx`, add `AUDIT_INCOMPLETE` to the fixtures import and append:

```tsx
const REASON = AUDIT_INCOMPLETE.slice(AUDIT_INCOMPLETE.indexOf(": ") + 2);

it("says the audit did not complete instead of saying no findings were recorded", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(
    <AuditTab
      runId={RUN_ID}
      degradations={["conveyance skipped after 2 attempts: x", AUDIT_INCOMPLETE]}
    />,
  );
  expect(await screen.findByText(`The audit did not complete: ${REASON}`)).toBeInTheDocument();
  expect(screen.queryByText("No audit findings were recorded.")).toBeNull();
});

it("keeps the previous audit's rows without the pass notice", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} degradations={[AUDIT_INCOMPLETE]} />);
  expect(await screen.findByRole("table", { name: "Verifiable rules" })).toBeInTheDocument();
  expect(screen.getByText(`The audit did not complete: ${REASON}`)).toBeInTheDocument();
  expect(screen.queryByText("Every verifiable rule passed in the last iteration.")).toBeNull();
});

it("ignores a conveyance degradation", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(
    <AuditTab runId={RUN_ID} degradations={["conveyance skipped after 2 attempts: x"]} />,
  );
  expect(await screen.findByText("No audit findings were recorded.")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm vitest run src/pages/review/ReviewPage.test.tsx src/pages/review/AuditTab.test.tsx`
Expected: `tsc` errors on `degradations` (the type and the prop); the new tests fail.

- [ ] **Step 3: The type, the page and the tab**

In `web/src/api/types.ts`, in `ReportJson.metadata`, after `open_findings: string[];` add:

```ts
    /** Stages the report was delivered without (R-M11-2); absent before M11. */
    degradations?: string[];
```

In `web/src/pages/review/ReviewPage.tsx`, after `const open = json.data?.metadata.open_findings.length ?? 0;` (line 52) add:

```tsx
  const degradations = json.data?.metadata.degradations ?? [];
```

after the closing `</header>` (line 68) add:

```tsx
      {degradations.length > 0 ? (
        <section aria-label="Incomplete at delivery" className="notice">
          <p>This report was delivered without every stage completing:</p>
          <ul>
            {degradations.map((d, i) => (
              <li key={i} dir="auto">
                {d}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
```

and change `return <AuditTab runId={runId} />;` (line 92) to `return <AuditTab runId={runId} degradations={degradations} />;`.

In `web/src/pages/review/AuditTab.tsx`, replace the signature line (78) with:

```tsx
export function AuditTab({
  runId,
  degradations = [],
}: {
  runId: string;
  degradations?: string[];
}) {
```

after the `openNow` assignment (ends line 90) add:

```tsx
  // R-M11-2: "audit incomplete after N attempts: <reason>"; the rows shown are the previous audit's
  const incomplete = degradations.find((d) => d.startsWith("audit incomplete"));
```

and replace the two notices (lines 96-99) with:

```tsx
      {incomplete ? (
        <p className="notice">
          The audit did not complete: {incomplete.slice(incomplete.indexOf(": ") + 2)}
        </p>
      ) : null}
      {rows.length === 0 && !incomplete ? (
        <p className="muted">No audit findings were recorded.</p>
      ) : null}
      {rows.length > 0 && openNow.length === 0 && !incomplete ? (
        <p className="notice">Every verifiable rule passed in the last iteration.</p>
      ) : null}
```

- [ ] **Step 4: Run the web suite and lint**

Run: `make test-web` and `cd web && pnpm lint`
Expected: all pass, coverage ≥ 95% on all four measures. If prettier reflows the new code, run `cd web && pnpm prettier --write src/pages/review src/test/fixtures.ts src/api/types.ts` and re-run `pnpm lint`.

- [ ] **Step 5: Commit**

```bash
cat > <scratchpad>/m11-task4-commit.txt <<'EOF'
feat(web): show what a degraded report was delivered without (CRL-25)

The review header lists metadata.degradations from report.json; the Audit tab
says the audit did not complete instead of "no findings" or "every rule
passed".

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add web/src/api/types.ts web/src/pages/review/ReviewPage.tsx web/src/pages/review/AuditTab.tsx web/src/test/fixtures.ts web/src/pages/review/ReviewPage.test.tsx web/src/pages/review/AuditTab.test.tsx
git commit -F <scratchpad>/m11-task4-commit.txt
```

---

### Task 5: Docs

The degradation is error handling, so its spec amendment goes after §7.5 (where "then `failed`" is written); §7.3 (routing) is unchanged, because a degraded stage routes nothing. The schema-enforced audit is a §8.2 amendment, with one-line amendments to §8.4 (invariants 1 and 2 read differently for a degraded audit) and §9 (the new appendix).

**Files:**
- Modify: `README.md` (new `## M11` section before `## Development`, line 203), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (after lines 288, 318, 345 and 349), `docs/operator-guide.md` (section 5 "Models and roles", after the `structured_output` bullet, lines 182-184; section 11, after the "no queued job exists" row, line 593), `docs/trace-format.md` (lines 15 and 42-43)
- Create: `docs/m11-followups.md`

- [ ] **Step 1: README**

Insert before `## Development` (line 203):

```markdown
## M11: audit robustness

The deployment dry run (CRL-1) ended both of its runs `failed`, with no report, because a small
model's audit was still invalid after its repair turn and retry. M11 (CRL-25) closes that: the
auditor's schema now has one required property per rule id, each allowing only the verdicts its
checkability permits and only the unit refs and claim ids the draft has, so a `json_schema`
server enforces the shape while generating (auditor prompt v2). When the auditor or the conveyor
still fails, the run is delivered anyway with status `findings_open` and an engine-owned note in
`metadata.degradations` ("audit incomplete…", "conveyance skipped…"): the renders list it under
"Stages incomplete at delivery", the review screen shows it, and `corelata run` exits 3; a
skipped conveyance delivers the writer's draft. Gate and writer failures still end the run
`failed`. Repair messages now tell the model what to write, with the rule ids and unit ids to
copy.

```

- [ ] **Step 2: Spec amendments**

§7.5, after line 288 ("- `gate_rejected` and `findings_open` are outcomes, not errors, and are never retried automatically."):

```markdown

M11 amendment (CRL-25): a conveyor or auditor failure no longer fails the run. When either stage
still raises after its repair turn and stage retry (or once the overflow ladder is spent), the
run goes on and the report is delivered with `status=findings_open` and an engine-owned line in
`metadata.degradations`: "conveyance skipped after N attempts: <error>" (the conveyor's input
draft goes forward unedited and is audited) or "audit incomplete after N attempts: <error>" (the
loop ends; `open_findings` keeps the previous audit's open findings, none on iteration 0). The
failed stage rows stay in the trace. Gate and writer failures still end in `failed`. Repair
messages are worded as instructions that name the values to use (the verdicts a rule takes, the
pack's rule ids, real unit ids).
```

§8.2, after line 318 ("There is no report field. The auditor returns exactly one finding per rule in the resolved pack."):

```markdown

M11 amendment: the auditor's output schema is built per call (`stages/audit_schema.py`):
`findings` is an object with one required property per rule id; each allows only the verdicts
its checkability permits (verifiable: pass | fail | not_applicable; advisory: attested |
not_applicable), and `cited_units` and `claim_ids` are enums of the units the draft cites and of
its claim ids (plain strings above 200 entries). A `json_schema` server enforces it while
generating. The parsed object is converted to the list above, in pack order, before anything else
reads it, so `Finding`, the trace and the API are unchanged; the validator still checks the
converted list for `json_object` and `none` servers. `ReportMetadata` (§8.1) gains
`degradations: list[str]` (§7.5).
```

§8.4, after line 345 (invariant 5):

```markdown

M11 amendment: invariant 2 holds for every audit that completed; an iteration whose audit is
named in `metadata.degradations` has no findings. A report delivered with its iteration-0 audit
incomplete is `findings_open` but lists no unsourced claims under invariant 1, because the engine
checks run on the auditor's findings (`docs/m11-followups.md`).
```

§9, after line 349 (the paragraph ending "…headed \"Audit findings open at delivery\"."):

```markdown

M11 amendment: a report with `metadata.degradations` lists them under "Stages incomplete at
delivery", before the open-findings appendix, in all three renders.
```

- [ ] **Step 3: Operator guide**

In section 5, "Models and roles", after the `structured_output` bullet (ends line 184 "…Use the strongest the server supports."), add:

```markdown
- With `json_schema` the server also enforces the auditor's shape: every rule id exactly once,
  only the verdicts the rule allows, only unit ids the draft cites. With `json_object` or `none`
  the same schema is in the prompt and Corelata checks the reply itself, so a small model needs
  its repair turn more often. If you override prompts (`prompts_dir`), an `auditor` override
  must return `findings` as an object keyed by rule id, as the built-in `auditor/v2.j2` does; an
  override that still returns a list fails every audit.
```

In section 11, after the row `| A run ended \`failed\` with "no queued job exists" | … |` (line 593), add:

```markdown
| A report is `findings_open` and lists "Stages incomplete at delivery" (the review screen shows the same notice) | The auditor or the conveyor could not produce valid output after its repair turn and one retry, so the report was delivered without it. "audit incomplete" means the rules were not checked on the delivered draft (any findings listed are the previous audit's); "conveyance skipped" means the writer's draft was delivered unedited. The run's progress page shows the failed stage and its error. Usually the model is too small for that role: give the role a stronger model, or set `structured_output: json_schema` if the server supports it, then return the report for a rerun. |
```

- [ ] **Step 4: Trace format**

In `docs/trace-format.md`, line 15, `the appendix "Audit findings open at delivery" lists \`delivered_open_findings\`` becomes `the appendix "Stages incomplete at delivery" lists \`metadata.degradations\` and "Audit findings open at delivery" lists \`delivered_open_findings\` (the findings \`metadata.open_findings\` names)`. Lines 42-43 become:

```markdown
- Delivered: `report` — the final conveyed draft (the writer's when the conveyance was skipped)
  plus `metadata` (`run_id`, `pack_name`, `pack_hash`, `profile`, `iteration`, `status`,
  `open_findings` ids, `degradations`: the stages it was delivered without, M11; absent in older
  traces, read as empty).
```

- [ ] **Step 5: `docs/m11-followups.md`**

```markdown
# M11 follow-ups

## Divergences from Coglossa

- `_repair_message` (copied `AgentRunner`) is worded as an instruction ("Your previous response
  was rejected. Fix every point below…") — **backport**: Coglossa's small-model runs repair the
  same way.
- `StageContext.check_refs` names real unit ids — Corelata only (Coglossa has no unit refs).
- The per-call audit schema (`stages/audit_schema.py`) — Corelata only; the pattern (enums built
  from the request) would suit any Coglossa output that cites ids.

## Spec deviations

- None. §7.5, §8.2, §8.4 and §9 carry M11 amendments (degradation, the schema-enforced audit,
  the invariants for a degraded audit, the new appendix).

## Rulings during execution

- None yet; number new ones from R-M11-6.

## Should fix soon

- Evidence refs in the writer's and conveyor's `ReportBody` are free strings (R-M11-5): a
  per-call schema with a unit-id enum for `Claim.evidence` would let a `json_schema` server stop
  a writer citing `src1` as a unit, as the auditor's schema now does.
- Pydantic's own messages ("findings.icd203.as.1: Field required", "Input should be 'pass',
  'fail' or 'not_applicable'") reach the repair turn unchanged; for a `json_object` server they
  could be rewritten into the R-M11-3 form.

## Later

- OpenAI "strict" structured outputs (`additionalProperties: false`, every field required) are
  not targeted (R-M11-5); a server that requires strict mode would reject the audit schema's
  optional fields.
- A run-level `pipeline.attempts_per_stage` setting (now fixed at one retry after the repair
  turn) would let a slow CPU deployment trade time for fewer degradations.
- A bench scenario with an auditor that never answers validly, so `corelata bench` measures the
  degraded delivery against a real model server.
- `audit_schema.ENUM_LIMIT` (200) is a guess; measure constrained-decoding time on the customer's
  server with a 500-unit run before changing it.
```

- [ ] **Step 6: Check nothing else moved**

Run: `make lint` and `git diff --stat main -- docs/m10-followups.md`
Expected: lint clean; the diff prints nothing (`docs/m10-followups.md` is untouched).

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m11-task5-commit.txt <<'EOF'
docs: M11 README section, spec amendments, operator notes, follow-ups

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/operator-guide.md docs/trace-format.md docs/m11-followups.md
git commit -F <scratchpad>/m11-task5-commit.txt
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine
make test-api
make test-web
make e2e            # the Playwright journey runs on the synthetic model, whose auditor changed shape
make deploy-check   # the demo stack's fake model server answers through the same responder
git diff --stat main -- schema web/src/api/schema.d.ts   # only report.schema.json and run-record.schema.json (R-M11-4)
```

CI must be green on all six jobs (engine, api, web, e2e, deploy-check, airgap) before the merge. After the merge, re-run the CRL-1 dry run (`qwen2.5:1.5b` and `phi4-mini` on Ollama with `structured_output: json_schema`): each run must end `completed`, with either a clean audit or a `findings_open` report that names what did not complete.
