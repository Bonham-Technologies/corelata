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
- **R-CRL94-4 (no source summary from the structurer).** The structurer's schema never asks for
  `source_summary` or `changes_from_previous`: a summary the report lacks is for the auditor to
  miss, not for the structurer to write. Source entries (descriptor, reliability note, the
  CRL-96 details) are metadata about the uploaded sources and are not checked against the text.
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

## Later

- **Starting a check from the web app.** The API and CLI start checks and the Review screen
  shows them, but the New report screen has no "check a report" form yet.
- **Reference lists.** A report's reference list is checked sentence by sentence; letting the
  structurer map it onto `sources` instead would need a verbatim rule for source entries.
- **Queued `corelata check --project`.** The CLI's check runs in-process only; a queued check is
  started through the API.
- **Migration number.** 0009 was written beside another branch's 0009; whichever merges second
  renumbers.
