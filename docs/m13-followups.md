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
- **R-M13-11**: `doctor._probe` gives the fix for the cause. A context overflow says to raise the
  server's context length or set `models.<key>.context_window` to the server's real length
  (`context_window` is the engine's budget, sent to no server); a transient error (a timeout, the
  auditor probe asks for about 1k output tokens) says to check the server logs and raise
  `backends.<name>.timeout_s`; only a permanent rejection gets the schema fix, and on a
  `json_object` model that is `check the model id and server logs` (setting `json_object` on a
  `json_object` model was circular). Why: the one-size fix sent operators to change a mode that
  did nothing. If wrong: an operator follows a fix for the wrong cause; the message still
  carries the server's error.
- **R-M13-12**: a reply cut when the model has no `max_output_tokens` says it was cut by the
  server's default output limit and asks to set `max_output_tokens` above it; with a cap the
  wording is unchanged. Why: `cut at max_tokens=None` told the operator to raise a cap that was
  not set. If wrong: the same advice as before, worded oddly.

## Should fix soon

- The auditor line runs on `check.message.startswith(PING_OK)`, a string-prefix coupling to
  `_model`'s wording; return the ping result from `_model` instead (whole-branch review minor 2).
  — **closed after M13**, verified 2026-10-18: `_model` returns `(check, pinged)` and `_backend` reads the flag.

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
