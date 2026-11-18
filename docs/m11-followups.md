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

- **R-M11-6**: when an audit is incomplete the engine's own `icd203.tc.8` and `icd206.src.2`
  checks run on the delivered draft and their FAIL findings are merged into the delivered
  findings and the trace, so no unsourced claim passes with or without the auditor.
- **R-M11-7**: the report-facing degradation line is the error's first listed point, newlines
  collapsed, cut to 200 characters with a trailing `…`; the full text stays in the failed stage
  row and the trace. A pydantic enum error listing more than five values is rewritten in the
  repair message to name three of them.
- **R-M11-8**: when the draft cites no indexed unit or claim, the audit schema's `cited_units` and
  `claim_ids` are lists with `maxItems: 0`; above `ENUM_LIMIT` they stay plain strings.

## Should fix soon

- ~~Evidence refs in the writer's and conveyor's `ReportBody` are free strings (R-M11-5): a
  per-call schema with a unit-id enum for `Claim.evidence` would let a `json_schema` server stop
  a writer citing `src1` as a unit, as the auditor's schema now does.~~ — **closed in M12** (CRL-29,
  `stages/report_schema.py`) — CRL-29
- Pydantic's own messages ("findings.icd203.as.1: Field required", "Input should be 'pass',
  'fail' or 'not_applicable'") reach the repair turn unchanged; for a `json_object` server they
  could be rewritten into the R-M11-3 form.
- ~~`scenarios.py` and `bench/score.py` treat an iteration as audited when any finding carries it;
  an iteration with only engine findings (a degraded audit) now counts as audited with 0 rules
  passed, so a degraded bench run reports rule disagreements instead of "no audit ran". Teach
  both to recognise a degraded iteration from `metadata.degradations`.~~ — **closed in M12** (CRL-28,
  `scenarios.audited_iterations`) — CRL-28
- ~~A previous iteration's engine `icd203.tc.8` finding can stay in the appendix after the revision
  fixed the claim, when the next audit degrades; drop prior engine-check findings the engine no
  longer reproduces.~~ — **closed by CRL-30** (`stages.audit.merge_engine_findings`) — CRL-30
- A conveyor that fails on a conveyor-only loop appends identical "conveyance skipped" lines and
  re-audits an unchanged draft; add the revision number to the line or stop the loop.

## Later

- `strict_json_schema` leaves `oneOf` and `additionalProperties: true` alone; neither occurs in
  our output models, and OpenAI strict rejects both.
- Done (CRL-26): ~~OpenAI "strict" structured outputs.~~ Every `json_schema` request now sends the
  strict form (`llm/schema.py`: all properties required, `additionalProperties: false`, no
  `default`), so servers that require strict mode accept it. — CRL-26
- A run-level `pipeline.attempts_per_stage` setting (now fixed at one retry after the repair
  turn) would let a slow CPU deployment trade time for fewer degradations.
- A bench scenario with an auditor that never answers validly, so `corelata bench` measures the
  degraded delivery against a real model server.
- `audit_schema.ENUM_LIMIT` (200) is a guess; measure constrained-decoding time on the customer's
  server with a 500-unit run before changing it.
- `populate_by_name=True` on the per-call audit model lets a `json_object` reply keyed `r0…rN`
  be accepted; `validate_by_alias=True, validate_by_name=False` would be stricter.
- `engine/tests/prompts/test_library.py` hard-codes the auditor at v2 and every other prompt at
  v1; derive the expected version from the highest `v*.j2` in each template directory.
- The per-call finding models drop `FindingOut.evidence`'s description from the schema sent to
  the model (prompt v2 states it); carry the description over.
- `check_refs` shows the first three refs in the index as examples, not refs from the same
  source as the bad one.
- The backstop's unknown, duplicate, missing and verdict branches are unreachable from
  `run_auditor`; add a property test over `audit_output_type` and `to_audit_output`.
- Duplicate keys in the raw JSON are last-wins on `json_object` servers.
- The unit-ref enum is emitted twice in the schema; hoist it into one `$def` with a dynamic Enum. — **closed in M12** (`audit_schema.enum_list`)
- An auditor or conveyor overflow still triggers a full re-digest that cannot help their payload
  before the stage degrades.
- `_describe` in `llm/agent.py` extracts a `literal_error`'s allowed values with a single-quote
  regex; pydantic prints a value containing `'` with double quotes and non-string literals bare,
  so the collapse would silently not fire. Unit refs and claim ids never contain quotes; decide
  on the count of expected values instead of the regex matches.
- The R-M11-7 degradation test does not cover newline collapsing (no `\n` in its error); add one.
- `corelata trace --json` does not list degradations (`TraceSummary` was kept unchanged so the
  OpenAPI document and `schema.d.ts` stay as they are); the report JSON carries them.
