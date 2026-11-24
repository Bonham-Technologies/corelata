# Trace format

A run directory written by `corelata run` (and, for a queued run, what `corelata export RUN_ID --out DIR` writes from the database) is described
by one document: `trace.json`, a `RunRecord` with `schema_version: "1"`. Its JSON Schema is
generated into `schema/run-record.schema.json`; CI fails when the committed schema and the
models disagree (`make schema` regenerates it).

## Files in a run directory

| File | Present when | Content |
|---|---|---|
| `trace.json` | always | the `RunRecord`: everything below |
| `gate.json` | the gate ran | `GateVerdict` |
| `report.json` | a report was delivered | `Report` (body + `metadata`) |
| `report.md`, `report.html`, `report.docx` | a report was delivered | renders of `report.json`, with numbered source references (CRL-96); the appendix "Cited passages" lists the claims' quotes (when any claim quotes), "Stages incomplete at delivery" lists `metadata.degradations` and "Audit findings open at delivery" lists `delivered_open_findings` (the findings `metadata.open_findings` names) |
| `findings.csv` | a check run delivered its report (CRL-94) | the findings sheet: one row per rule of the audit, in pack order (`rule_id`, `title`, `verdict`, `severity`, `claim_ids`, `cited_units`, `evidence`, `recommendation`; ids space-separated; a cell starting `=`, `+`, `-` or `@` gets a leading `'`) |
| `reference.docx` | the run's profile named one (queued runs only) | the profile's DOCX reference as stored when the run was queued; `corelata report DIR --format docx` uses it |

`corelata report RUN_DIR --format …` re-renders any of the three from `trace.json` alone; the
DOCX uses the neutral template unless `--docx-reference` names the profile's reference document
(or `DIR/reference.docx` when present, which `corelata export` writes).

## RunRecord

- Identity: `run_id`, `created_at`, `corelata_version`, `config_hash`, `prompt_versions`
  (prompt id → version used), `pack_name`, `pack_hash`, `pack_snapshot` (the resolved pack as
  JSON — edit the pack directory later and this run still means what it meant), `profile`,
  `parent_run_id` (the run this one reruns after a review "return" or a gate rejection; null
  for a first run), `extra_guidance` (additional writer guidance the analyst or a reviewer
  supplied; empty when none).
- Kind (CRL-94): `kind` is `"check"` for a check run, which audits `checked_report` (the
  finished report as ingested, source id `report`, never one of `sources`) without rewriting it:
  its stages are `ingesting`, `structuring`, `auditing`, `rendering`, its one draft has the role
  `structurer` and claims that are the report's sentences, and it has no `gate`. A report run's
  trace has neither key (read as `"report"`).
- Outcome: `state` (spec §7.2 state machine; terminal states `completed`, `gate_rejected`,
  `failed`, `cancelled` — a `cancelled` run keeps the stages and model calls made before the
  analyst's cancel took effect and has no `report`), `status` (`clean` | `findings_open`, completed runs only), `error`.
- Inputs: `value_statement`, `sources[]` (each with its ordered `units[]`: `id`, `text`,
  `locator`, `kind`, `meta`), `digests[]` for sources over the digest threshold,
  `prior_reports[]` (CRL-97, below). A unit OCR read from a scanned PDF page has `meta`
  `{"ocr": true, "ocr_confidence": <0-100>}` (Tesseract's mean word confidence), and its source's
  `provenance` names `ocr_pages` and `ocr_languages` (`ingest.ocr: auto`, CRL-95); other units
  have empty `meta`.
- Process: `stages[]` — one entry per attempt of every stage, with `iteration`, `ok`,
  `started_at`, `finished_at`, `output` (small, stage-specific) or `error`; `drafts[]` — every
  writer and conveyor output with its `role` and `iteration`; `findings[]` — one `Finding` per
  rule per audit iteration (`rule_id`, `verdict`, `severity`, `route_to`, `evidence`,
  `cited_units`, `claim_ids`, `recommendation`, `iteration`); a finding's id is
  `<rule_id>@<iteration>`.
- Loop: `iterations` (revisions performed), `max_iterations`.
- Delivered: `report` — the final conveyed draft (the writer's when the conveyance was skipped)
  plus `metadata` (`run_id`, `pack_name`, `pack_hash`, `profile`, `iteration`, `status`,
  `open_findings` ids, `degradations`: the stages it was delivered without, M11; absent in older
  traces, read as empty; `prior_reports`, CRL-97, below).
- Cost: `usage` (calls and tokens, total and by role), `llm_calls[]` (one per model call;
  `request` and `response` present when `audit.store_llm_io` is on).
  Both cover the run's last attempt only. A run whose worker was taken for dead is started over
  (spec §16), and the new attempt clears the earlier one's stages and calls. An execution the
  fence stopped (its run ended under it, or another worker started the run over, CRL-56) writes
  nothing more, so the model calls it made after its last write are dropped, not recorded with
  a marker: the worker's log line for the stop gives their count and tokens.

## Claims and quotes

A claim in a draft or the report is `{id, text, kind, evidence, likelihood_term, quotes}`.
`evidence` lists unit refs (`<source_id>/<unit_id>`). `quotes` (CRL-93) lists the words the claim
copies from those units, each `{ref, text}` with `ref` one of the claim's evidence refs. It is
present only when the run had `pipeline.evidence_quotes` set to `required` or `optional` and
the claim quotes something; an empty list is left out, so a run with `off` (and every older
trace) has no `quotes` key at all. Read a missing key as empty.

The engine checks every quote against its unit's `text` in `sources[]`, comparing words (case,
whitespace, quote marks and other punctuation set aside; `pipeline.quote_match_threshold` below
1.0 allows a fuzzy match). A failure is an engine finding on `icd203.tc.8`, and on `icd206.src.2`
when a key judgment cites the claim, routed to the writer like an unsourced claim. Its `evidence`
starts with `engine check: ` and joins, with `; `, every problem with the rule's claims:

| Text | Meaning |
|---|---|
| `claims without evidence: c4, c9` | the claims cite no unit (unchanged from earlier versions) |
| `quote not found in src2/u14 (c3)` | claim c3 quotes words that unit src2/u14 does not contain |
| `no quote from src1/u2 (c3)` | `required` only: claim c3 cites src1/u2 but quotes nothing from it (units of digested sources are exempt) |

`claim_ids` lists the claims named, in report order. When the auditor already failed the rule,
its verdict and recommendation stand; quote problems are appended to its evidence after `; `
with the same `engine check: ` prefix (unsourced claims alone add nothing, as before quotes). The renders list every quote in the appendix
"Cited passages" (claim id, source name and locator, the quoted words).

When the run's pack lexicon has `likelihood_alternates`, `unlisted_probability_words` or
`confidence_phrases` (CRL-136), the engine also checks each key judgment's and `judgment` claim's
uncertainty wording and fails `icd203.tc.2` the same way, routed to the writer, with evidence
starting `engine check: ` and problems joined with `; `:

| Text | Meaning |
|---|---|
| `c3 puts a confidence level and a likelihood in one sentence ('high confidence', 'likely')` | one sentence of c3 holds both |
| `key judgment 1 uses probability wording outside the lexicon ('probable', 'perhaps')` | the text uses an alternate-row or unlisted word (named as listed; "probably" is reported as `probable`) |
| `c3 does not use its likelihood term 'likely' in its text` | the claim's `likelihood_term` is not in its text ("very likely" is a different term) |

`claim_ids` lists the claims named (key judgments have no id and are named in the text). When the
auditor already failed `icd203.tc.2`, its verdict and recommendation stand and these problems are
appended to its evidence after `; `.

## Sources section and source summary

A report's `sources[]` entry is `{source_id, descriptor, reliability_note, date_of_information,
origin, access}` (CRL-96). The last three are present when the run's pack lexicon had a
`source_access` list and the value is not blank; older traces, and runs whose pack or profile
turned them off, have no such keys: read a missing key as empty. The date and origin are the
writer's: it is offered the source's `provenance.date` and `provenance.origin` (hints ingest read
from the file) and confirms, corrects or blanks them, and the engine never fills a blank one back
in. A Coglossa export's `reliability_note` starts with `Coglossa reliability tier <A|B|C>.` (the
lowest tier among its scored spans) unless the note already names it.

`report.source_summary` (CRL-96) is present when the pack's template listed `source_summary`:
`{strengths_and_weaknesses, key_sources, corroboration, conflicting_sources}`, the two lists
being source ids. It is absent otherwise, and in every older trace.

Renders number the sources in `sources[]` order and cite them by that number in superscript after
each paragraph or item whose claims cite their units.

## Earlier accepted reports

A queued run reads the key judgments of its project's most recently accepted reports
(`pipeline.prior_judgments`, CRL-97). `prior_reports` lists what it was given, newest accept
first: each `{run_id, title, accepted_at, key_judgments: [{text, confidence}], cut}`, where
`cut: true` marks a report `budget_tokens` left out (the oldest go first); the writer and the
auditor read only the others. The key is absent when the run was given none: `max_reports: 0`
(the default), a project with no accepted report, a run outside a project (`corelata run`
without `--project`, the bench), and every older trace. Read a missing key as empty.

When the run read some, the writer's drafts and the report may carry
`changes_from_previous`: one `{prior_run_id, prior_judgment, change, explanation, claim_ids}` per
earlier judgment the report addresses, `change` `consistent` or `changed`, `prior_run_id` one of
the run ids read. The report's `metadata.prior_reports` lists the reports read (`{run_id, title,
accepted_at}`) so the renders' "Changes from previous analysis" section, after the key
judgments, can name each by its title and date. Both keys are absent when empty.

`pack_snapshot` keeps a rule's `with_prior_reports` block as the pack has it. A run that read
earlier reports sent that rule with the block's `checkability` and `evidence_required`; a run
whose project had none recorded the rule `not_applicable` with the evidence `initial coverage:
this project has no earlier accepted report whose judgments this report could be consistent with
or change`, whatever the auditor answered.

## Derived views

`corelata trace RUN_DIR` prints a `TraceSummary` (`schema/trace-summary.schema.json`):
sources with unit counts, digest flags, the number of pages OCR read (`ocr_pages`) and a Coglossa
export's `reliability_tier` (CRL-96), the gate verdict, a stage timeline with durations, failed and
open rule ids per iteration, findings open at delivery, usage by role, and the earlier accepted
reports the run was given (`prior_reports`, absent when none; the review screen's Process tab
lists them).
`corelata trace RUN_DIR --claim c1` prints a `ClaimProvenance`
(`schema/claim-provenance.schema.json`): the claim, its evidence units with source name and
locator, and where in the report it is cited; the claim carries its `quotes`, which the review
screen's Claims tab marks inside each evidence passage (the whole passage shows when the browser
cannot find a quote the engine matched fuzzily).

## Invariants (spec §8.4)

1. Every claim in a report delivered `clean` has at least one evidence unit ref.
2. Every rule in the resolved pack has exactly one finding per audit iteration.
3. No judgment uses a likelihood term outside the pack lexicon.
4. The auditor never produces report text; only structured findings flow back to the writer
   and conveyor.
5. Every render is a pure function of `report`, `pack_snapshot`, `sources` and the open
   findings, all of which are in `trace.json`.

## Compatibility

`schema_version` changes only when a reader of version N could misinterpret a version N+1
record. Adding optional fields does not bump it; renaming or removing a field, or changing a
field's meaning, does.
