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

- How the plan applied R-M12-1 to R-M12-7 is in its Global Constraints ("How the plan applies
  them"). The three below came out of the whole-branch review.
- **R-M12-8** (supersedes the conversion step in R-M12-1): the writer and the conveyor send the
  per-call schema whose `evidence` items are the run's unit ids, but parse the reply as the
  canonical `ReportBody` (`AgentRunner.run(..., schema=)`), so `check_refs` reports a bad ref in
  the same repair message as every other validator error; `to_report_body` is gone. A
  `json_schema` server still cannot generate a bad ref.
- **R-M12-9**: the doctor's structured probe sends the output cap a run sends
  (`max_tokens=model.max_output_tokens`, omitted when unset); the truncation fix advises raising
  or unsetting `max_output_tokens` only when the user's own cap cut the reply; a model served as
  `<name>:latest` counts as found; a `json_object` model whose probe reply does not parse is told
  to try `none`.
- **R-M12-10**: when the delivered iteration's audit degraded, `rules_must_pass` and a closed
  `rules_may_fail` are not scored against an earlier iteration; `compare` adds
  `rules: no audit of the delivered draft (iteration <n> degraded)`, `rules_agree` is `False`
  (the auditor not answering is a model-quality signal, as with `rules: no audit ran`), and no
  per-rule tally is made for those sets; `rules_must_fail` is still scored over the audited
  iterations.

## Should fix soon

- ~~The doctor probes only the gate's schema, the smallest. A server limit on schema size or enum
  length (the writer's `UnitRef` enum, up to 200 values; the auditor's one required property per
  rule) shows only in a run. Probe the auditor's schema for a small fixed pack as well.~~ — **closed in M13** (CRL-31: the `model <key> auditor schema` line) — CRL-31
- ~~`SourceEntry.source_id` is a free string in the writer's schema; an enum of the run's source
  ids (the validator already requires one entry per source) would stop an invented source id the
  same way `UnitRef` stops an invented unit.~~ — **closed in M13** (CRL-32: the `SourceId` enum) — CRL-32
- ~~`doctor`: the ping-failure (`test completion failed: …`) and `unreachable: …` messages are not
  bounded by `_cut`; only the structured probe's error is cut to `ERROR_CHARS`.~~ — **closed in M13** (CRL-31) — CRL-31
- ~~`bench/text.py`: an errored run's error text in the 24-character outcome column pushes the gate,
  time, calls and tokens columns out of alignment on that row (pre-existing, one more column now).~~ — **closed in M13** (CRL-33: `OUTCOME_WIDTH`, the `errors` section) — CRL-33
- ~~`scenarios.audited_iterations`: the degraded-audit tests on `max-iterations-zero` cannot tell
  the `ENGINE_CHECK` clause from the `audit incomplete` clause.~~ The mid-run test now exists
  (`test_a_degraded_last_audit_leaves_the_rule_sets_unscored`: iteration 0 audited, iteration 1
  degraded, R-M12-10) and pins the `audit incomplete` clause; the `ENGINE_CHECK` clause alone
  (engine-only findings, no degradation note) is still pinned only by `max-iterations-zero`. — **closed in M13** (CRL-33: `test_engine_only_findings_alone_leave_an_iteration_unaudited`) — CRL-33

## Later

- The enum schema costs prompt tokens on `json_object` and `none` servers, where it is spelled
  in the system prompt: about 2.5 KB (~1k tokens) at 200 refs. `_check_budgets`' 2000-token
  margin does not count it.
- `→` and `·` in the CLI output (doctor, bench table) are non-ASCII and would raise on a
  non-UTF-8 stdout.
- ~~The doctor probe has no repair turn, so a `json_object` model that needs one FAILs doctor
  where a run would pass.~~ — **closed in M15** (CRL-35). — CRL-35
- The conveyor may not add or remove claims, so its schema could enumerate the draft's claim ids
  in `key_judgments`, `analysis` and `alternatives` as well.
- `rules_must_fail` is unused by the shipped real set: no real-model scenario has a failure a good
  writer cannot avoid (the planner could not write one a good model reliably fails), so it is
  covered by unit tests only. Add one if the customer's pack gains a rule their material always
  trips.
- The real set is English, short and port-and-logistics themed. The customer's own material, when
  they give any, would make a better set, played with `--scenarios DIR`.
- `--scenarios real` shadows a directory named `real` in the working directory (write `./real`);
  likewise `synthetic`. `bench.scenarios_path` does not check that a directory exists
  (`load_scenarios` reports it).
- `ENUM_LIMIT` (200) now also caps the writer's enum: a run with more units sends plain strings
  and relies on the validator. Measure constrained decoding with a 500-unit run before raising it.
- `bench.json` keeps the gate's reasons whole; the table cuts the first to 60 characters.
- ~~`doctor._similar`: the prefix match is case-sensitive (`OpenAI/…` would not suggest `openai/…`).~~ — **closed in M17** (CRL-39). — CRL-39
- `tests/test_doctor.py::_is_strict`: stricter than OpenAI strict mode (requires `required` in
  property order; flags an object with empty `properties` and no `required`).
