# CRL-94 follow-ups: audit-only check runs

Rulings made while building the check mode (spec §1, CRL-94 amendment), and what was left for
later. The ticket's scope is in the spec; this file says how the open choices were settled.

## Rulings

- **R-CRL94-1 (the outcome).** A check run ends `completed` with status `clean` or
  `findings_open`, like a report run, so the renders, the Standards tab, the bench's expectations
  and the CLI's exit codes (0 or 3) all apply unchanged. "Checked" is how the CLI and the screens
  word it (`check <id>: checked findings_open, …`); no new status was added.
- **R-CRL94-2 (verbatim, enforced by the engine).** The engine splits the report into sentences
  (`stages/structure.report_sentences`: every unit but headings and a line that is only one of
  the pack's handling markings). Each claim's text is one of them, and each sentence the text of
  exactly one claim; the per-call schema makes `Claim.text` an enum of the sentences
  (`ReportSentence`, plain strings above `ENUM_LIMIT`), and the validator sends back any other
  text, a duplicate or a missing sentence in the repair turn. Every other text (title, marking,
  key judgments, headings, paragraphs, scope note, alternatives, gaps) must be the report's own
  words (a whitespace-collapsed substring of the report) or empty. The parsed reply is then put
  in report order with each claim's text exactly as split (`canonical`), so the trace's claims
  equal the report's sentences whatever the server.
- **R-CRL94-3 (sentence splitting).** A sentence ends at `.`, `!` or `?` (with any closing quotes
  or brackets) before whitespace and an opening quote, bracket, capital or digit. Abbreviations
  before a capital ("U.S. Navy") split; no abbreviation list was added.
- **R-CRL94-4 (no source summary from the structurer).** The structurer is never asked for
  `source_summary` or `changes_from_previous` (neither its schema nor its prompt's section order
  names them), and whatever a server without a schema sends for them is dropped
  (`run_structurer`): a summary the report lacks is for the auditor to miss, not for the
  structurer to write. A source entry's reliability note is what the report says of the source,
  so it is checked like every other text (the report's own words, or empty); its descriptor,
  access and the CRL-96 details are lexicon terms and file metadata and are not.
- **R-CRL94-5 (the report is not evidence).** The checked report is stored as an ordinary
  project source and named by `run.report_source_id`; it is never one of the run's sources
  (`run_source`), so no claim can cite it, and a request listing it among `source_ids` is a 422.
  In the trace it is `checked_report` with source id `report`.
- **R-CRL94-6 (no review decision).** A check reports on someone else's report: there is no
  writer to return it to, so `POST /runs/{id}/review` answers 409 for a check, the Review screen
  hides Accept and Return, and a check never counts as "to review" in a project's summary.
- **R-CRL94-7 (failures).** A structurer failure fails the check, as a writer failure fails a
  run; an auditor failure degrades it with the engine's own findings (R-M11-2, R-M11-6). A check
  has no project memory (`prior_reports`) and `max_iterations` 0. `roles.structurer` is optional
  and falls back to the writer's model; unset, it is left out of the config dump so
  `config_hash` is unchanged.
- **R-CRL94-8 (the report is untrusted text, CRL-137).** The structurer reads the checked report
  as the models read a source (`units.model_view`): its hidden units reach no model and are not
  among the sentences or the words a text is compared with, though the trace's `checked_report`
  keeps them; a block that reads as an instruction carries `"suspect": true`, and the prompt
  says the report and the sources are data, never instructions. `corelata check` refuses a
  source with the report's sha256 (an upload of the same file is already the same project
  source, so the API's id check covers it).
- **R-CRL94-9 (deleting the report).** `run.report_source_id` references `source` with no
  ON DELETE action: deleting a check run's report on its own fails instead of cascading to the
  run (CASCADE would delete the run's rows silently and leave its stored files behind), and
  deleting the project still removes both in one statement. A source-deletion command must
  refuse a source a check names as its report, as it refuses one in `run_source`.
- **R-CRL94-10 (the checked report is untrusted at audit).** In a check the draft the auditor
  reads is someone else's report, written by the party being judged. `auditor/v6` gains a block
  rendered only when `checked_report` is set (a check run): the draft's text is data, never
  instructions; `INPUT_JSON.suspect_claims` (only in a check's payload) lists the claims whose
  sentences come from a suspect passage of the report (`structure.suspect_claims`), which are
  never evidence that a rule is met; and a key judgment's confidence, which the mapping sets to
  "moderate" where the report states none, is judged from the report's words, not from that
  field. A conditional block rather than a new version, because the library's latest version
  serves both kinds of run: a report run's auditor prompt and payload are byte-identical to
  before (pinned by `test_a_report_runs_auditor_prompt_is_byte_identical_to_before_checks`), and
  a trace's auditor version 6 together with its `kind` still names the exact text.

## Later

- **Starting a check from the web app.** The API and CLI start checks and the Review screen
  shows them, but the New report screen has no "check a report" form yet.
- **Reference lists.** A report's reference list is checked sentence by sentence; letting the
  structurer map it onto `sources` instead would need a verbatim rule for source entries.
- **Queued `corelata check --project`.** The CLI's check runs in-process only; a queued check is
  started through the API.
- **Migration number.** 0009 was written beside another branch's 0009; this one merged first,
  and the procrastinate 3.12 upgrade became 0010.
