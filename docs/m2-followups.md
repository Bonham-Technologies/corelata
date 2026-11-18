# M2 follow-ups

## Divergences from Coglossa

- `config.py` (a Coglossa copy): `PipelineConfig` gained `digest_chunk_tokens` and
  `writer_unit_budget_tokens`. Corelata-only section; nothing to backport.

## Spec deviations

- §9 "if the profile names a `docx_reference`, its styles are used": true for `corelata run`
  (the loader resolves the path and the renderer takes it) but `corelata report RUN_DIR
  --format docx` cannot locate it from a run directory and renders with the neutral template
  unless `--docx-reference` is passed; it says so on stderr. The path is deliberately kept out
  of `pack_snapshot` and `pack_hash` so both stay identical across installs (§6.6). M3 should
  store the reference bytes (or their hash plus a copy under `storage`) with the run. Closed in M3
  (see Should fix soon).
- §9 superscripts: HTML always carries `data-claim-ids` attributes (invisible) so the review UI
  can highlight provenance without re-rendering; the visible superscripts follow
  `--claim-ids` as specified.
- §7.4 writer row amended in M2 (Task 10): the writer receives all non-digested units within
  `pipeline.writer_unit_budget_tokens`, gate-cited first. Recorded in the spec itself.
- Writer budget (final review I3, recorded in the §7.4 writer row): after the threshold
  digests, if the non-digested sources together exceed `pipeline.writer_unit_budget_tokens`
  (each source counted as the sum of its units' token estimates, as the writer selection counts
  them), ingest digests the largest remaining source, ties to the earlier one, and repeats until
  the rest fit or every source is digested. Every source therefore reaches the writer in full or
  as a digest. The budget stays in the writer's unit selection as a safety cut (gate-cited units
  of digested sources also count against it, and the gate runs after ingest); whatever it cuts
  is listed in `StageContext.withheld_refs` and counted in the drafting stage's trace output as
  `withheld_units`, which is 0 whenever the rule held.
- §7.5 oversize ladder now halves `digest_chunk_tokens` and `writer_unit_budget_tokens` (floor
  500 each) together with `digest_threshold_tokens`, then re-applies the writer-budget rule. It
  still cannot shrink an auditor or conveyor request (the §7.5 bullet under "Spec issues still
  open from M1" below, open).
- §6.6 `pack_hash` is now a key-sorted compact JSON dump (first 16 hex chars). Hashes of packs
  loaded by M1 differ from M2's; nothing persisted them yet.

## Should fix soon

- `corelata report` and the M3 API should render DOCX with the stored reference document, not
  the neutral fallback (see Spec deviations). — **Closed in M3**: the reference is stored at
  submit under `runs/<id>/reference.docx`, the worker renders with it, and `corelata export`
  writes it beside the trace.
- `ResolvedPack.docx_reference_path` is an excluded pydantic field; when the shared foundation
  package is extracted, consider a separate "pack location" object instead of a field that is
  half in, half out of the model. — still open; the worker sets the field from the stored copy.
- Scenario fixtures cover the synthetic responder's markers only (UNSOURCED, UNFIXABLE, BADTERM,
  thin, rejected, digested). Add scenarios for conveyor-routed findings and for a profile with
  an added rule once the synthetic auditor can be steered to fail a conveyor-routed rule. —
  parked: the synthetic auditor cannot be steered to fail a conveyor-routed rule.
- `format_summary` prints durations from the frozen test clock as 0 ms; a real run shows real
  numbers. No test pins a non-zero duration.
- ~~DOCX header rebuild (final-review fix wave): a logo whose picture is wrapped in
  `mc:AlternateContent` or an embedded `w:object` is dropped along with the stale text (only
  plain `w:drawing`/`w:pict` image runs are kept). Fails safe — no old marking survives — but a
  grouped or shape-based logo vanishes. Keep such wrappers when they contain a `pic:pic`.~~ — **closed in M8** (a run child stays when it holds a picture; CRL-13). — CRL-13
- ~~Writer-budget forced digests (final-review fix wave) also remove those sources' units from the
  gate's full-text pool (the gate skips digested sources and reads their digests instead), so
  many-source runs give the gate less full text than `gate_unit_budget_tokens` allows.~~ —
  **closed in M8** (CRL-14; `StageContext.forced_digests` keeps those sources in the pool). — CRL-14
- ~~`writer_overflow` picks the largest non-digested source even when one of its units exceeds
  `digest_chunk_tokens`; `check_unit_sizes` then fails the run at ingest with "split the
  source". M1 would have completed with a silent writer cut; fail-fast is the better outcome,
  but choosing the next-largest digestible source would complete more runs.~~ — **closed in M8**
  (CRL-14; an undigestible source is never forced). — CRL-14
- ~~Pre-existing (noted by the final re-review): an error raised by the ladder's re-digest inside
  the overflow handler bypasses the stage's own recording; `corelata report` catches only
  `RenderError` around the DOCX render.~~ — **closed in M8** (CRL-14; the re-digest's
  `StageError` is recorded as the stage's failure). — CRL-14

## Spec issues still open from M1

- §7.2 loop-count wording ("iteration < max_iterations" vs "iteration == max_iterations →
  rendering"); M1/M2 implement `max_iterations` = number of revisions (default 2 → up to three
  audits). The scenario fixtures `unsourced-unfixable` and `max-iterations-zero` pin this.
- §7.5 ladder cannot shrink auditor/conveyor requests.

## Later

- `GET /runs/{id}/trace`, `/findings`, `/claims/{claim_id}` (M4a) should serve `TraceSummary`,
  `IterationFindings` and `ClaimProvenance` from `corelata.trace` unchanged; `draft_changes`
  backs the Process tab's draft-to-draft diff.
- `corelata bench` (M6) = `scenarios.load_scenarios` + `run_scenario` against a real backend +
  `compare`, aggregated into gate-agreement and rule-failure-agreement rates — **closed in M6**.
