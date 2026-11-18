# Corelata v1 design

Date: 2026-10-12
Status: approved in conversation; awaiting written review
Sibling product: Coglossa (multi-agent translation), github.com/Bonham-Technologies/coglossa

Code docstrings cite sections of this document by number (for example "see spec §7.3").

---

## §1 Purpose and scope

Corelata turns source material plus an analyst's statement of intelligence value into a finished intelligence report that meets a published standard (ICD 203 by default) or the customer's own standard, with a complete trace of how it was produced.

v1 produces **one report product**: an analytic assessment shaped by ICD 203 (key judgments with confidence, sourcing, analysis, alternatives, gaps). Other shapes are the customer's to define in a standards pack (§6).

v1 ships as a **CLI, an HTTP API and a focused web review UI**, packaged as an offline Docker Compose bundle for an air-gapped site that supplies its own OpenAI-compatible model endpoints.

**In scope for v1**

- Ingest of DOCX, PDF, TXT, Markdown, HTML, JSON, CSV and Coglossa exports.
- Value discovery (system proposes candidate value statements) and value gating (system verifies the analyst's statement).
- Unattended run: gate → writer → conveyance reviewer → auditor, with one bounded revision loop.
- Structured, versioned standards pack with per-team profiles; ICD 203 + ICD 206 base pack.
- Claim-level provenance, per-rule audit verdicts, full process trace.
- Rendering to Markdown, HTML and DOCX.
- Postgres persistence, job queue, SSE progress, trusted-header auth.
- Offline bundle, install/backup/restore, air-gap CI test, operator guide.
- Profile extractor that drafts a team profile from example reports (M6, may slip past first deployment).

**Out of scope for v1** (see §15): PDF rendering, user management and billing, live web collection, multiple report products in the base pack, classification-guide enforcement beyond a handling marking string, bundled models.

## §2 Context and decisions

### §2.1 Customer

Same first customer as Coglossa: air-gapped, in-house models exposed over OpenAI-compatible APIs, machine may or may not have a GPU (irrelevant to Corelata, which runs no local models). The customer will **not** supply a corpus of past reports or style guides. Several teams in the organisation have their own reporting nuances.

### §2.2 Decisions log

| Date | Decision |
|---|---|
| 2026-10-12 | Name: Corelata. corelata.com registered. Trademark knock-out search is a manual step owned by the user. |
| 2026-10-12 | v1 report product: one ICD 203-shaped analytic assessment. |
| 2026-10-12 | Surface: CLI + API + focused web review UI. |
| 2026-10-12 | Code sharing with Coglossa: copy reusable modules now, parameterise the product name, log divergences, extract a shared package only after both products are deployed. Coglossa leads; improvements may flow back. |
| 2026-10-12 | Standards: structured, versioned pack directory; customer replaces it on their deployment. |
| 2026-10-12 | Agent loop: linear with one bounded loop (default 2 iterations); report always delivered; auditor cannot edit (schema has no report field). |
| 2026-10-12 | Operating model: analyst kicks off; system runs unattended to a finished report; analyst reviews output and trace. |
| 2026-10-12 | Coglossa hook: Coglossa export is a source kind; optional API fetch; no shared code dependency at runtime. |

### §2.3 Non-goals

Corelata is not a collection tool, not a search engine over the customer's holdings, and not a chat assistant. It takes material the analyst already has and produces a report.

## §3 Concepts and glossary

| Term | Meaning |
|---|---|
| **Project** | A container for sources and runs, typically one per task or tasking line. |
| **Source** | One uploaded file or one imported Coglossa run. Has a kind, a SHA-256, and provenance. |
| **Source unit** | The smallest addressable piece of a source: a paragraph, a table row, a list item, or a Coglossa span. Has a stable id and a locator (page, paragraph index, span id). |
| **Digest** | A traced summary of an oversized source produced before drafting (§5.4). |
| **Value statement** | The analyst's one-to-three-sentence assertion of what the material shows, why it matters, and to whom. |
| **Discovery** | A short job in which the gate role proposes candidate value statements with evidence (§7.1). |
| **Run** | One unattended execution of the pipeline for one value statement against a set of sources, under one resolved standards pack. |
| **Draft** | The structured report as produced by one role in one iteration. |
| **Claim** | An addressable assertion in the report: a fact, a judgment or an assumption. Every claim lists its evidence (source unit ids). |
| **Standards pack** | A versioned directory of rules, a template, a lexicon, profiles and prompt overrides (§6). |
| **Profile** | A per-team overlay on a pack. |
| **Rule** | One checkable standard with an id, severity, and the evidence an auditor must cite. |
| **Finding** | The auditor's verdict on one rule in one iteration: pass, fail, not applicable, or attested (§6.2). |
| **Trace** | Everything recorded about a run: stage results, drafts, claims, evidence, findings, LLM calls, token usage, review events. |

## §4 Architecture

### §4.1 Stack

Python 3.12+, uv, hatchling, pydantic v2, jinja2, httpx, SQLAlchemy 2 async, psycopg 3, alembic, procrastinate (Postgres-backed job queue), python-docx, lxml, pdfminer, FastAPI. Web: React 19, Vite 7, TypeScript, @tanstack/react-query, openapi-fetch, react-router 7. Node 22+, pnpm. Tests: pytest, pytest-asyncio, pytest-cov, hypothesis, Vitest, msw, Playwright.

### §4.2 Repository layout

```
engine/      package `corelata`: config, llm, prompts, ingest, standards, schema,
             stages, pipeline, render, store, worker, cli, testing
api/         package `corelata_api` (FastAPI)
web/         React single-page app
schema/      generated JSON Schema + openapi.json
deploy/      compose files, Dockerfiles, bundle/install/backup/restore, deploy tests
docs/        superpowers/specs, superpowers/plans, m<N>-followups.md, operator-guide.md
Makefile     entry point for everything
```

No scorer service. No model weights.

### §4.3 Copy-from-Coglossa rule

The following Coglossa modules are copied, renamed and otherwise left unchanged apart from deletions: `config` skeleton (backends, models, roles, retry, database, storage, worker, api, auth; strict pydantic; `ConfigIssue`; `config_hash`), `llm/` (backend protocol, OpenAI-compatible client, entry-point registry, retry, `AgentRunner` with structured output and one repair turn, `CallLog`), `prompts/` (`PromptLibrary`, versioned Jinja, `prompts_dir` override), `testing/` (fake backend, fake OpenAI server, Postgres pytest plugin), worker wiring with stalled-job requeue, `Storage`, `doctor`, the API shell (lifespan, trusted-header auth, error handlers, SPA mount, SSE), the web shell (typed client, msw harness, Vite proxy), and all of `deploy/`.

Rules:

1. Product name is parameterised: env prefix `CORELATA_`, entry-point group `corelata.backends`, queue name `corelata`.
2. Every intentional change to a copied module is recorded in `docs/m<N>-followups.md` under **Divergences from Coglossa**, with a one-line reason, so extraction into a shared package later is a checklist, not an archaeology project.
3. An improvement discovered while building Corelata that would help Coglossa is noted in the same section tagged **backport**.

### §4.4 Roles

Roles are typed config (`RolesConfig`), each mapped to a model key, each with a versioned Jinja prompt at `engine/corelata/prompts/templates/<role>/v<N>.j2`.

| Role | Reads | Produces | Cannot |
|---|---|---|---|
| `gate` | value statement (or none, in discovery), source digests, source units | `GateVerdict` or `DiscoveryResult` | write report text |
| `writer` | template, resolved rules, lexicon, digests, cited units, prior draft + routed findings (iteration ≥ 1) | `Report` | see auditor's reasoning beyond the routed findings |
| `conveyor` | draft `Report`, template, profile tone/format, routed findings (iteration ≥ 1) | `Report` | change the claim set (M1: reword only; the engine keeps the claim set fixed, and adding claims that cite existing units is deferred until real models need it) |
| `auditor` | draft `Report`, resolved rules, lexicon, the source units each claim cites | `AuditResult` (findings only) | edit: `AuditResult` has no report field |
| `profiler` | example reports, plus the base pack's rule ids, template and lexicon so it proposes only valid overrides | `Profile` with `draft: true` | be used in a run |

## §5 Ingest and sources

### §5.1 Accepted kinds

`file` (DOCX, PDF, TXT, MD, HTML, JSON, CSV) and `coglossa_export`. Kind is detected by extension and sniffed; mismatches are rejected with a clear error.

### §5.2 Source units

Every source is split into ordered units with stable ids `u<n>` scoped to the source, a `locator` (`page:3/para:7`, `row:42`, `coglossa:<run_id>/span:p14`), the unit text, and metadata (for Coglossa: reliability tier, flags, agreement). Tables become one unit per row with the header carried in metadata. HTML is reduced to text blocks; scripts and navigation are dropped. JSON becomes one unit per top-level record (array) or one unit per top-level key (object).

### §5.3 Coglossa export adapter

The adapter validates the export with a pydantic model of the fields Corelata uses (a test checks its field names against the vendored copy of Coglossa's export JSON Schema at `engine/corelata/ingest/vendor/coglossa-export-<version>.schema.json`) and refuses unknown schema versions. Spans become units; the translation guide, if present, is stored as a sibling text source so the writer can cite locked terms. The Coglossa run id is kept in source provenance and appears in the trace and in the rendered sources section.

When `integrations.coglossa` is configured (§11), the API and web can fetch a run export by id from Coglossa instead of accepting an upload. The adapter path is identical after fetch. The client caps an export at 50 MB and refuses to send a request when the configured key variable is unset (M8).

### §5.4 Digests

A source whose unit text exceeds `pipeline.digest_threshold_tokens` gets a digest: the writer role summarises it in sections, each section citing the unit ids it covers. Digests are stored in the run's `digests` column (the `ingesting` stage result lists which sources were digested) and shown in the trace. Drafting reads digests plus the full text of units the gate cited; the auditor always reads full unit text for cited claims, never digests.

## §6 Standards pack

### §6.1 Layout

```
packs/<name>/
  pack.yaml        name, version, extends (optional pack name), description
  rules/*.yaml     one rule per file
  template.yaml    sections, order, required/optional, length guidance, element limits
  lexicon.yaml     estimative language with probability bands, confidence levels,
                   source descriptor phrases, handling markings
  profiles/*.yaml  per-team overlays
  prompts/         optional Jinja overrides, same mechanism as prompts_dir
```

### §6.2 Rule

```yaml
id: icd203.tc.2
title: Properly expresses and explains uncertainties
source: "ICD 203 (2015) D.6.e(2)"
text: >
  Quoted directive text.
severity: blocking | major | minor
checkability: verifiable | advisory
applies_to: [writer, conveyor, auditor]
evidence_required: >
  What the auditor must cite to pass or fail (e.g. "each key judgment carries a
  confidence level from the lexicon and a sentence on the basis of uncertainty").
route_to: writer | conveyor
```

- `verifiable` rules get verdicts `pass | fail | not_applicable`.
- `advisory` rules (for example "independent of political consideration", "timely") cannot be verified from the text alone; the auditor records `attested` with a note, and the trace shows them separately. They never block.
- `blocking` and `major` failures trigger a loop iteration while iteration budget remains. `minor` failures are reported, never looped on. Only `blocking` and `major` findings still open at delivery set `status=findings_open`.

CRL-97 amendment: a rule may carry `with_prior_reports: {checkability, evidence_required}`, which
marks it as judging a report against the project's earlier accepted reports (§7.4). This is how
a pack says "checkable when prior judgments exist, not applicable otherwise" without a new
checkability: a run that read earlier reports sends the rule with the block's two fields in
place of its own (to the writer, the auditor and the auditor's per-call schema); a run whose
project has no accepted report sends the rule as written and the engine records it
`not_applicable` with the evidence "initial coverage: …", whatever the auditor answered; a run
that reads none (`max_reports: 0`, no project, or every report cut by the budget) uses the rule as
written. The block is left out of every dump when unset, so a pack without it snapshots and
hashes as before; `ResolvedPack.for_run` drops it from the rules the stages send, so their
requests are those of a pack without it. Profiles cannot override the block (a follow-up); a
profile `override` changes the rule as written.

### §6.3 Template

Ordered sections for the v1 product: `title`, `handling_marking`, `key_judgments` (min 1, max 5, each with confidence), `scope_note`, `sources` (one entry per source, with a descriptor from the lexicon), `analysis` (one or more headed sections), `alternatives` (min 1 when any key judgment is `moderate` or `low` confidence), `gaps_and_indicators`. Each section declares `required`, `max_words`, and element rules. The template is data; the writer prompt renders it.

### §6.4 Lexicon

ICD 203 likelihood terms with bands: almost no chance 1–5%, very unlikely 5–20%, unlikely 20–45%, roughly even chance 45–55%, likely 55–80%, very likely 80–95%, almost certain 95–99%. Confidence levels high, moderate, low with the ICD 203 definitions. ICD 206 source descriptor phrases. Handling markings as an allowed list (default `UNCLASSIFIED`, with the customer adding theirs). The auditor fails `icd203.tc.2` when a judgment uses a likelihood term not in the lexicon.

### §6.5 Profile

```yaml
name: team-east
extends: icd203-base
draft: false
rules:
  add: [ {inline rule} ]
  disable: [icd203.tc.9]
  override: [ {id: icd203.tc.5, severity: blocking} ]
template:
  key_judgments: {max: 3}
tone: >
  Guidance the writer and conveyor read verbatim.
format:
  docx_reference: templates/team-east.docx
  heading_style: numbered
lexicon:
  handling_markings: ["UNCLASSIFIED//FOUO"]
```

Resolution order: base pack → `extends` chain → profile. `disable` removes a rule; `override` replaces named fields; `add` appends; a profile that both disables and overrides the same rule id is a load error. Resolution is a pure function with property tests (§13). A profile with `draft: true` is refused by `load_pack` for a run; `corelata pack validate` reports it as a warning.

### §6.6 Snapshot

A run stores the resolved pack as JSON (`run.pack_snapshot`) and its hash (`run.pack_hash`: the first 16 hex characters of the SHA-256 of the key-sorted compact JSON of the resolved pack, excluding `docx_reference_path`; the same convention as `config_hash`). Every finding, draft and rendered report refers to the snapshot, never to the directory. Editing the pack never changes the meaning of an old run.

### §6.7 Base pack contents

`icd203-base` ships inside the engine package and is copied into the bundle's `config/packs/` on install (never overwritten on upgrade).

| Rule id | Standard | Checkability |
|---|---|---|
| icd203.as.1 | Objective | advisory |
| icd203.as.2 | Independent of political consideration | advisory |
| icd203.as.3 | Timely | advisory |
| icd203.as.4 | Based on all available sources | verifiable (every provided source is either cited or explicitly set aside in the scope note) |
| icd203.as.5 | Implements and exhibits analytic tradecraft standards | verifiable (aggregate of tc.1–tc.9) |
| icd203.tc.1 | Describes quality and credibility of sources, data, methodologies | verifiable |
| icd203.tc.2 | Expresses and explains uncertainties | verifiable |
| icd203.tc.3 | Distinguishes information from assumptions and judgments | verifiable (claim kinds) |
| icd203.tc.4 | Incorporates analysis of alternatives | verifiable |
| icd203.tc.5 | Demonstrates customer relevance and addresses implications | verifiable (against the value statement) |
| icd203.tc.6 | Uses clear and logical argumentation | verifiable |
| icd203.tc.7 | Explains change to or consistency of judgments | advisory as written; verifiable when the run read the project's earlier accepted reports, `not_applicable` (initial coverage) when the project has none (CRL-97, `with_prior_reports`) |
| icd203.tc.8 | Makes accurate judgments and assessments | verifiable (claim-to-evidence check; the auditor's core job) |
| icd203.tc.9 | Incorporates effective visual information | advisory in v1 (no visuals generated); a profile may override to verifiable |
| icd206.src.1 | Source summary statement present | verifiable |
| icd206.src.2 | Source reference citations for key judgments | verifiable |
| icd206.src.3 | Source descriptors from the lexicon | verifiable |

### §6.8 CLI

`corelata pack validate [dir]`, `corelata pack show <name> [--profile <p>]` (prints the resolved pack), `corelata pack diff <a> <b>`, `corelata profile extract --from <dir> --out <file>` (M6).

*M6 amendment:* `corelata profile extract --from <dir> --out <file> [--name <n>] [--extends <pack>] [--packs-dir <dir>] [--budget-tokens <n>] [--force]`; the output always has `draft: true`; an existing `--out` is never overwritten without `--force`. `corelata bench [--scenarios <dir>] [--only <name>…] [--repeat <n>] [--concurrency <n>] [--store-io] [--out <dir>] [--json]` exits 0 on full agreement, 3 on any disagreement, 1 when a run errored. *M7 amendment:* `corelata pack diff <left> <right> [--profile-left <p>] [--profile-right <p>] [--packs-dir <dir>] [--json]`; a side is a pack name, a pack directory or a run directory (its snapshot); exit 0 same, 3 different, 1 a side did not load, 2 when `--profile-left/right` is given for a run snapshot.

## §7 Pipeline

### §7.1 Discovery job

Separate from a run. Input: project, source ids, optional audience hint. The gate role, in discovery mode, returns up to five `CandidateStatement{text, audience, evidence[unit ids], confidence_note}`. Stored in `discovery`. The analyst picks one (or writes their own) and starts a run. Discovery never starts a run by itself.

### §7.2 Run state machine

```
created -> ingesting -> gating -> drafting -> conveying -> auditing
auditing -> drafting   (routed findings for writer, iteration += 1, while revisions made < max_iterations)
auditing -> conveying  (routed findings for conveyor only, iteration += 1, while revisions made < max_iterations)
auditing -> rendering -> completed            status: clean | findings_open
gating   -> gate_rejected                     terminal; reasons + what would be needed
any      -> failed                            engine error, recorded
any      -> cancelled                         analyst action
```

- `ingesting` parses sources into units and writes digests where needed. In the queued deployment (M3) sources are parsed when they are uploaded, so a bad file is refused at once; the run's `ingesting` stage then does the budget check and the digests.
- `gating` produces `GateVerdict{supported: bool, substance: sufficient | thin | insufficient, reasons[], evidence[unit ids], suggested_scope}`. `supported=false` or `substance=insufficient` → `gate_rejected`. `thin` proceeds with a scope note the writer must include.
- `drafting` produces iteration 0's `Report` (writer). On loop entry it produces iteration n's `Report` from the previous conveyed draft plus routed findings.
- `conveying` produces the conveyed `Report`.
- `auditing` produces `AuditResult{findings[], summary}`; the loop decision is made by the engine from severities (§6.2), not by the model.
- `max_iterations` is the number of revisions (default 2, so up to three audits). When that many revisions have been made and blocking or major findings remain, the run proceeds to `rendering` with `status=findings_open`; unresolved findings are attached to the report's metadata and shown in the review UI.
- `rendering` writes Markdown, HTML and DOCX exports.

### §7.3 Routing

Each finding carries the rule's `route_to`. If any routed-to-writer finding exists, the next stage is `drafting` (the conveyor runs again afterwards as normal). If all are routed to the conveyor, the next stage is `conveying`. The auditor's free-text reasoning is stored in the trace but only the structured findings are passed to the writer or conveyor, to keep the context small and the auditor's role bounded.

### §7.4 Context budgets

| Role | Receives |
|---|---|
| gate | value statement; all digests; full text of units up to `pipeline.gate_unit_budget_tokens`, prioritised by lexical overlap with the statement |
| writer | template; resolved rules with `applies_to: writer`; lexicon; digests; full text of units the gate cited, then every other unit of non-digested sources in document order up to `pipeline.writer_unit_budget_tokens` (amended M2: the writer must be able to cite or set aside every listed source, so no non-digested source may be invisible to it); prior conveyed draft and routed findings on iteration ≥ 1. When the non-digested sources together exceed the budget, the largest are digested until the rest fit, so every source is visible either in full or as a digest. A source whose largest unit exceeds `digest_chunk_tokens` is never forced into a digest; the writer's unit cut covers it, and the gate keeps reading forced-digest sources in full (M8). |
| conveyor | draft; template; profile tone and format; routed findings on iteration ≥ 1 |
| auditor | draft; all rules; lexicon; full text of every unit cited by any claim (never digests) |

Every role call records prompt id and version, token counts, and the `CallLog`.

CRL-97 amendment (project memory): a queued run, when the worker claims it, reads the key
judgments (text, confidence), title and acceptance time of its project's
`pipeline.prior_judgments.max_reports` (unset: 0, off; the example config sets 3) most recently
accepted reports: completed runs
whose stored review decision (§8.3 `review_state`) is `accepted`, newest accept first, never the
run itself. Returned, gate-rejected and unreviewed runs, and other projects', are never read.
Their entries are kept newest first while they fit `budget_tokens` (default 2000, estimated with
the writer's `bytes_per_token`); the first that does not fit and every older one are cut. The
writer and the auditor both receive the kept ones as `prior_reports` (`{run_id, title, date,
key_judgments}`); the writer's per-call schema then adds `changes_from_previous` with
`prior_run_id` an enum of their run ids (`PriorRunId`) and its validator checks the same; the
conveyor may reword an entry's explanation only. With none kept the payloads, prompts and
schemas are byte for byte those sent before project memory existed (`writer/v3` and `auditor/v4`
render as `writer/v2` and `auditor/v3`), so `max_reports: 0` restores the earlier behaviour.
`corelata run` without a project and the bench have no project memory.

### §7.5 Error handling

- Structured-output failure: one repair turn (copied `AgentRunner`), then one stage retry, then `failed` with the `StructuredOutputError` recorded.
- Transient backend errors: capped exponential backoff with jitter (copied `retry`).
- Context overflow reported by the model: for a gate or writer overflow, `digest_threshold_tokens`, `digest_chunk_tokens` and `writer_unit_budget_tokens` are halved together for that run (floor 500), the writer-budget rule re-applied and the stage retried once, then `failed`; an auditor or conveyor overflow cannot be shrunk by the ladder, so once it is spent the stage degrades (see the M11 amendment).
- A claim citing a unit id that does not exist is a schema validation error at the writer or conveyor stage and triggers the repair turn.
- Stalled jobs are requeued by the worker's periodic task (copied).
- A worker that dies mid-run: the stalled-job task re-queues the job and the run starts over (`attempts` counts executions); a cancel is honoured at the next stage boundary.
- `gate_rejected` and `findings_open` are outcomes, not errors, and are never retried automatically.

M11 amendment (CRL-25): a conveyor or auditor failure no longer fails the run. When either stage
still raises after its repair turn and stage retry (or once the overflow ladder is spent), the
run goes on and the report is delivered with `status=findings_open` and an engine-owned line in
`metadata.degradations`: "conveyance skipped after N attempts: <error>" (the conveyor's input
draft goes forward unedited and is audited) or "audit incomplete after N attempts: <error>" (the
loop ends; `open_findings` is the previous audit's open findings with `icd203.tc.8` and
`icd206.src.2` replaced by the engine's own results on the delivered draft (R-M11-6), so it can
be non-empty on iteration 0). An earlier iteration's engine-check failure that the engine no
longer reproduces on the delivered draft is dropped, while the auditor's own findings stay
(CRL-30). The degradation line is the error's first listed point cut to 200
characters (R-M11-7); the full text stays in the failed stage row. The
failed stage rows stay in the trace. Gate and writer failures still end in `failed`. Repair
messages are worded as instructions that name the values to use (the verdicts a rule takes, the
pack's rule ids, real unit ids).

M17 amendments (CRL-38): a discovery has two limits (§11), both measured on the database's
clock. The start limit, `worker.discovery_start_deadline_s`, counts from `created_at` while no
worker has claimed the discovery (`created`); past it the discovery is failed with `Discovery did
not start within <N minutes> and was stopped: the worker was stopped or busy with runs. Start a
new discovery.` The work limit, `worker.discovery_deadline_s`, counts from `started_at`, which the
worker's claim records as the database's `now()` (`running`); past it the discovery is failed
with `Discovery did not finish within <N minutes> and was stopped. Start a new discovery.` (whole
minutes as "10 minutes"; otherwise whole seconds or a plain decimal, never an exponent). Whichever
looks first fails it: the API's read (`GET /discoveries/{id}`, the POST's answer,
`corelata status`), the worker's minute sweep, or the worker itself. A claim at or after the
start limit makes no model call; a first claim before it gives the model work the whole work
limit, a redelivered job keeps the first claim's `started_at` and gets what is left of it (none
past it: failed at once, no model call), and the work stops when that is up (logged as a WARNING). A finish fails the discovery with the work
limit's text when its budget expired or, for an answer, when `started_at` is the work limit or
more old; an error the agent raised is kept as the discovery's error. Every decision is taken
under the discovery's row lock, so whichever transaction commits first decides, and nothing turns
a failed discovery back. Runs, discoveries and the periodic tasks share one queue and
`worker.concurrency`; a discovery's job has procrastinate priority 1 (everything else 0), so the
worker fetches it ahead of waiting runs. A cancel of a run whose job is
`doing` on a worker that is gone (its heartbeat `worker.stalled_after_s` old, or its worker row
deleted: the stalled-job requeue's own test) ends the run as cancelled at once, with the
ending every cancel has, and closes the job as `aborted`; a run a live worker holds still stops at
its next stage boundary. A worker that writes to a run that has ended (it was taken for dead)
stops without writing: nothing more is recorded for the run, its in-flight stage's model calls
and token usage included, and its later acknowledgement of the closed job fails harmlessly. The
stalled-job requeue skips a job a cancel has closed since it listed it.

## §8 Data model and trace

### §8.1 Report schema (pydantic, `engine/corelata/schema/report.py`)

```
Report
  title: str
  handling_marking: str                      # from lexicon allowed list
  key_judgments: list[KeyJudgment]           # KeyJudgment{text, confidence: high|moderate|low, claim_ids}
  scope_note: str
  sources: list[SourceEntry]                 # SourceEntry{source_id, descriptor, reliability_note}
  analysis: list[Section]                    # Section{heading, paragraphs: list[Paragraph{text, claim_ids}]}
  alternatives: list[Alternative]            # Alternative{hypothesis, assessment, claim_ids}
  gaps_and_indicators: list[str]
  claims: list[Claim]                        # Claim{id, text, kind: fact|judgment|assumption, evidence: list[unit_id], likelihood_term?: str, quotes?: list[Quote{ref, text}]}
  metadata: ReportMetadata                   # {run_id, pack_name, pack_hash, profile, iteration, status, open_findings: list[finding_id]}
```

CRL-97 amendment: `ReportBody` gains `changes_from_previous: list[JudgmentChange{prior_run_id,
prior_judgment, change: consistent | changed, explanation, claim_ids}]`, the optional "Changes
from previous analysis" element, asked for only when the run read earlier accepted reports
(§7.4); its claim ids must resolve like any other. `ReportMetadata` gains `prior_reports:
list[{run_id, title, accepted_at}]`, the reports the writer read, set by the engine so the
renders name each by title and date. Both are left out of every dump when empty, and the
per-call schema without earlier reports is built on `ReportBodyCore`, the body without the
element, so it is the schema sent before. The element is not in the pack's `section_order`; the
renders place it right after the key judgments (or before the appendices when a template has
no key judgments).

Validation at the schema level: every `claim_id` referenced exists in `claims`; every `evidence` unit id exists among the run's units; every `likelihood_term`, if present, is in the lexicon; `handling_marking` is in the allowed list.

M12 amendment (CRL-29): the writer and the conveyor send a per-call variant of `ReportBody`
(`stages/report_schema.py`) whose `Claim.evidence` items are an enum of the run's unit ids (every
unit of every source, as the validator accepts; plain strings above 200 units, an empty list when
there are none), so a `json_schema` server enforces the unit-id rule while generating. The reply is
parsed as the canonical `ReportBody` (R-M12-8), so on any other server `check_refs` reports a bad
ref in the same repair message as every other validator error.

M13 amendment (CRL-32): the same per-call variant restricts `SourceEntry.source_id` to the run's
source ids (one `SourceId` enum; a plain string above 200 sources), so a `json_schema` server
cannot list a source the run does not have. The sources check (`unknown source id '<id>' in
sources`) still runs on every server.

CRL-93 amendment (quote-anchored evidence): `Claim.quotes` lists verbatim spans, each
`Quote{ref, text}` naming one of the claim's evidence units, and `pipeline.evidence_quotes`
(`required` | `optional` | `off`; unset means `off`, the example config says `required`) decides
whether the writer is asked for them. With `off` the per-call schema is built on `ClaimCore` and is
byte for byte the schema sent before quotes existed, payloads and prompts are unchanged, and an
empty `quotes` list is left out of every dump, so the run and its trace are the same. Otherwise the
writer's and conveyor's per-call schema adds `quotes` (its `ref` drawn from the same `UnitRef`
enum), the validator requires each quote's ref to be a unit the claim cites, the conveyor may not
change a quote, and the auditor receives each cited unit's quotes beside its text. Whether the
words are in the unit is an engine check (§8.4), not a repair. The prompts that mention quotes are
new versions (`writer/v2`, `conveyor/v2`, `auditor/v3`; the previous ones stay for the record) and
render, with `off`, exactly as the previous versions did, so only the trace's `prompt_versions`
tells such a run from one made before.

### §8.2 Audit schema

```
AuditResult
  findings: list[Finding]      # Finding{rule_id, verdict: pass|fail|not_applicable|attested, severity, evidence: str, cited_units: list[unit_id], claim_ids: list[str], recommendation: str, route_to}
  summary: str
```

There is no report field. The auditor returns exactly one finding per rule in the resolved pack.

M11 amendment: the auditor's output schema is built per call (`stages/audit_schema.py`):
`findings` is an object with one required property per rule id; each allows only the verdicts
its checkability permits (verifiable: pass | fail | not_applicable; advisory: attested |
not_applicable), and `cited_units` and `claim_ids` are enums of the units the draft cites and of
its claim ids (plain strings above 200 entries). A `json_schema` server enforces it while
generating. The parsed object is converted to the list above, in pack order, before anything else
reads it, so `Finding`, the trace and the API are unchanged; the validator still checks the
converted list for `json_object` and `none` servers. `ReportMetadata` (§8.1) gains
`degradations: list[str]` (§7.5).

### §8.3 Tables (Postgres 16, alembic)

`project`, `source`, `source_unit`, `run`, `run_source` (the run's sources in order; ordinal n is
`src<n>` in the trace), `discovery`, `discovery_source`, `discovery_candidate`, `stage_result`
(one row per attempt of every stage, with iteration and output JSON), `draft` (role, iteration,
`Report` JSON), `claim`, `claim_evidence` (the delivered report's claims and the units they
cite), `audit_finding`, `llm_call`, `review_event`, `export` (the worker's stored renders).
Procrastinate's tables are vendored as in Coglossa. `run` holds `state`, `status`, `config_hash`,
`config_snapshot`, `pack_hash`, `pack_snapshot`, `profile`, `value_statement`, `extra_guidance`,
`iteration`, `max_iterations`, `parent_run_id` (for reruns after rejection or return),
`docx_reference_key` (the profile's reference document as stored when the run was queued),
`gate`, `digests` (M3: on the run row rather than in stage_result), `report`, `token_usage` JSON,
`cancel_requested`, `attempts`, `error`, `export_error`, `created_at`, `started_at`,
`finished_at`. A discovery's few model calls are a JSON column on `discovery`.

M10 amendment: `run.review_state` holds the review decision (`ReviewState` JSON: `decision`,
`at`, `actor`, `child_run_id`), written by every review action in the event's transaction;
`review_event` stays the audit trail, and migration 0004 backfilled the column from it.

M15 amendment: `review_state` also holds `child_state` (the rerun's state once it ended, any
terminal state; null while it is created or running), `child_error` (the rerun's error) and
`note` (the return's note), written by every review action and by every transaction that ends a
rerun; migration 0005 recorded them for existing rows and deleted `return` events whose rerun was
never linked (CRL-34).

CRL-97 amendment: `run.prior_reports` (nullable JSONB, migration 0008, add-only) holds the
earlier accepted reports the run was given (`RunRecord.prior_reports`, cut ones marked); NULL on
runs made before it, read as none. No table is added: accepted runs and their key judgments are
read from `run.review_state` and `run.report`.

M17 amendment: `run` has the index `ix_run_project_created` on `(project_id, created_at DESC, id
DESC)`, the run list's order (migration 0006, CRL-39). It serves every lookup by project, so
migration 0007 drops the single-column `ix_run_project_id` (CRL-58).

### §8.4 Trace invariants (enforced in code and tests)

1. Every claim in a report with `status=clean` has at least one evidence unit id; the engine forces `icd203.tc.8` (and `icd206.src.2` for key judgments) to FAIL for any unsourced claim, so a `findings_open` report keeps its unsourced claims and lists them in `metadata.open_findings`.
2. Every applicable rule has exactly one finding per iteration.
3. No `judgment` claim uses a likelihood term outside the lexicon.
4. The auditor never produces report text: `AuditResult` has no such field, and the pipeline passes only `findings` onward.
5. Every rendered export is derived from a stored `draft` row; renders are reproducible from the database alone.

M11 amendment: invariant 2 (exactly one finding per rule) holds for every completed audit. An
iteration whose audit is named in `metadata.degradations` carries only the engine's own
`icd203.tc.8` and `icd206.src.2` FAIL findings for the delivered draft (R-M11-6), so invariant 1
(no unsourced claim passes) holds with or without the auditor.

CRL-93 amendment: with `pipeline.evidence_quotes` on, the same engine check also fails
`icd203.tc.8` (and `icd206.src.2` for a claim a key judgment cites) for a quote whose words are
not found in the unit it names (`engine check: quote not found in src2/u14 (c3)`) and, with
`required`, for a cited unit the claim does not quote (`no quote from src1/u2 (c3)`; units of
digested sources are exempt, the writer never saw their words). Matching compares words: case,
whitespace, quote marks and other punctuation are set aside, and `pipeline.quote_match_threshold`
(default 1.0, exact) allows a fuzzy match. A rule the auditor already failed keeps the
auditor's verdict and recommendation, with the quote problems appended to its evidence.

## §9 Rendering and exports

Markdown and HTML renderers are pure functions of `Report` + resolved template + lexicon. DOCX uses python-docx; if the profile names a `docx_reference`, its styles are used, otherwise a neutral built-in reference. Rendered documents show claim ids as unobtrusive superscripts when `--with-claim-ids` is passed (default on for HTML in the review UI, off for DOCX downloads). A sources section lists each source with its descriptor, and for Coglossa sources the Coglossa run id. Open findings, when present, render as an appendix headed "Audit findings open at delivery".

M11 amendment: a report with `metadata.degradations` lists them under "Stages incomplete at
delivery", before the open-findings appendix, in all three renders.

CRL-97 amendment: a report with `changes_from_previous` has a "Changes from previous analysis"
section after the key judgments in all three renders, one item per entry: "Consistent with
earlier analysis." or "Changed from earlier analysis.", the explanation, and the earlier judgment
with the earlier report's title and acceptance date (never its run id).

## §10 API, CLI and web

### §10.1 API (`corelata_api`)

- `POST/GET /projects`, `GET /projects/{id}`
- `POST /projects/{id}/sources` (multipart; `kind: file | coglossa_export`), `GET /projects/{id}/sources`
- `POST /projects/{id}/sources/from-coglossa` `{run_id}` (only when `integrations.coglossa` is configured)
- `POST /discoveries` `{project_id, source_ids, audience_hint?}`, `GET /discoveries/{id}`
- `POST /runs` `{project_id, source_ids, value_statement, profile?, max_iterations?}`, `GET /runs/{id}`, `GET /runs/{id}/events` (SSE), `POST /runs/{id}/cancel`
- `GET /runs/{id}/report?format=json|md|html|docx[&with_claim_ids=1]`
- `GET /runs/{id}/trace` (stage results, drafts, findings, token usage), `GET /runs/{id}/findings`, `GET /runs/{id}/claims/{claim_id}` (claim + evidence units)
- `POST /runs/{id}/review` `{action: accept | return, note?}` → `return` creates a linked run seeded with the note as additional writer guidance and returns its id. A second `return` on the same run is a 409 conflict; the first rerun is the only one.
- `GET /packs`, `GET /packs/{name}/resolved?profile=`, `GET /packs/{name}/validate`
- `GET /system/doctor`, `GET /api/openapi.json` (behind auth)

Auth: `none` or `trusted_header` (`X-Remote-User`), as Coglossa. The API never calls models except `doctor`.

M4a amendments: every route is mounted under `/api` (`/api/projects`, …), as in Coglossa, so the
SPA owns every other path. Added: `GET /api/system/info` (version, auth mode, caller, whether the
Coglossa fetch is configured, upload limit, default pack and profile — what a client needs before
its first screen), `GET /api/runs?project_id=&limit=` (a project's runs, newest first) and
`GET /api/runs/{id}/exports/{name}` (a stored export as stored: `trace.json`, `gate.json`,
`report.*`). `GET /runs/{id}/trace` returns a `RunTrace` (the `TraceSummary`, draft-to-draft
changes, model calls without bodies); the full trace is the `trace.json` export. `POST /runs`
accepts `extra_guidance` and `parent_run_id` too. `POST /runs/{id}/review` returns
`{action, child}` with the child's progress for a `return`. `from-coglossa` answers 409 when
`integrations.coglossa` is not configured; Coglossa's 404/409 pass through, anything else is 502.
`GET /runs/{id}/report` serves the worker's stored export unless `with_claim_ids=1`, which
re-renders from the stored record.

M9 amendments: `GET /runs/{id}` carries `review` for a completed run (`decision` accepted or
returned, `at`, `actor`, `child_run_id` for a return); a live run's progress carries `null`. The
report route checks the run's state before loading anything and caches claim-id re-renders per
run and format for the life of the process. Every `GET /runs/{id}/events` stream on one run
shares one database poller. `GET /packs` is re-read only when a file under the pack directories
changes; `/packs/{name}/...` still read on every call.

M10 amendments: `GET /runs/{id}` reads `review` from `run.review_state` (§8.3), not from the
review events. `GET /packs` checks the pack files at most once a second and follows symlinked
pack directories. The claim-id re-render cache is bounded by `api.render_cache_mb` (default 64)
as well as by its 64 entries.

M14 amendments: `GET /runs?project_id=&limit=&before=` answers `{runs, next_before}`: the runs
newest first by `(created_at, id)`, `limit` (default 100, at most 500) at a time; `next_before` is
an opaque cursor (`<created_at, ISO-8601 UTC>|<run_id>`) when more runs follow and `null` on the
last page, and `before=<next_before>` answers the runs after it, so a run created while a client
pages does not shift its pages; a malformed cursor is a 422 (CRL-24). The worker and the service
announce every committed change to a run's progress on the Postgres channel `corelata_run`
(payload: the run id) in the transaction that writes it; the API holds one `LISTEN` connection,
and the shared reader of a run's `GET /runs/{id}/events` streams reads it on a notification, with
a heartbeat every `api.progress_poll_s` × 10 (at most 30 s, never below `api.progress_poll_s`); while that connection is down it
reads every `api.progress_poll_s` and reconnects after 1, 2, 4, 8, 16, then every 30 s (CRL-22).

M15 amendments: a `return` is spent only while its rerun is running or completed. A rerun that
ended failed, cancelled or gate-rejected spends nothing: `POST /runs/{id}/review` accepts another
`return` (a new event and a new rerun; the earlier event stays) or an `accept`, and the 409 answers
only a return whose rerun is live or completed (it names that rerun). The rerun, the `return`
event and `review_state` commit in one transaction under the run's row lock. `review` on
`GET /runs/{id}` carries `child_state`, `child_error` and `note`; the decision is the live return
if there is one, else the latest event (CRL-34). The orphan sweep records each swept rerun's end
on its parent in a savepoint per parent: a parent that cannot be recomputed is logged and
skipped, and the orphans are still failed (R-M15-21).

M16 amendment: an accept is final. `POST /runs/{id}/review` with `return` on a run whose stored
decision is `accepted` is a 409 (`run <id> was accepted; start a new run to change it`), decided
on the decision read under the run's row lock; `corelata review --return` prints the same and
exits 2. A note-less return is still a 422 first. Unchanged: an accept after a rerun that ended
without a report is allowed, an accept after a live or completed return leaves the decision
"returned", and accept after accept is allowed, the latest deciding (CRL-21).

M17 amendments (CRL-38): `GET /discoveries/{id}` (and `POST /discoveries`' answer) carries
`deadline_at`, the limit that applies: `started_at` + `worker.discovery_deadline_s` once the
worker has claimed the discovery (ended or not), otherwise `created_at` +
`worker.discovery_start_deadline_s`. The read fails a discovery past it before answering (§7.5).
`POST /runs/{id}/cancel` ends a run whose worker is gone at once (§7.5).

M18 amendments (CRL-41): `ProjectView` (on `GET /projects`, `GET /projects/{id}` and
`POST /projects`) carries `last_activity_at` (the latest of the project's, its sources' and its
runs' stamps), `reports_writing`, `reports_to_review` (completed with no decision, or a return
whose rerun ended without a report) and `latest_run` (`{run_id, state, status, decision,
child_state}`), computed by three statements for the whole list. `RunSummary` carries
`review_decision` and `review_child_state` from the stored decision. `SystemInfo` carries
`logout_url`. No new route.

### §10.2 CLI

`corelata ingest`, `discover`, `run`, `report`, `trace`, `review`, `pack validate|show|diff`, `profile extract`, `doctor`, `fake-openai`, `migrate`, `worker`. `corelata run` can execute in-process without Postgres for M1 (results written to a directory), and against the database from M3. With `--project NAME` (M3) `run` and `discover` ingest their inputs into the project and queue the work; `ingest`, `status`, `cancel`, `review`, `export`, `migrate`, `worker` and `doctor` complete the queued surface.

M12 amendment (CRL-27): `doctor`'s backend check reports how many models the server serves and,
for each configured model on that backend, whether it is served; a missing model's fix names up
to five served ids with the same prefix. Its structured-output probe sends the gate's
`GateVerdict` schema through the request builder the stages use and passes only on a reply that
parses as one.

M13 amendment (CRL-31): for the model configured as `auditor`, `doctor` adds a
`model <key> auditor schema` line after the model's own: it sends the auditor's by-rule
`AuditByRule` schema for the configured pack (one required property per rule; unit and claim
enums of a two-claim probe draft) through the same request builder, also on
`structured_output: none` (the schema then goes in the prompt), and passes only on a reply that
converts to the auditor's output. The line appears only when the model's test completion
succeeded, and its fix names the cause: schema rejected, reply cut by the model's cap or by the
server's default output limit, context overflow, or timeout. A server's error text in the backend, test-completion and
probe messages is cut to 200 characters.

M15 amendment (CRL-35): both structured probes give a reply that does not parse the one repair
turn a run gives (the same messages, built by `llm/agent.repair_messages`). A repaired reply that
parses is a WARN, `<mode> output works after one repair turn (<Name>)`, which leaves doctor's
result and exit code passing; two replies that do not parse FAIL with the second reply's error. A
cut reply or a backend error gets no repair turn, as in a run. A backend error on the repair
request itself FAILs with `<mode> request failed on the repair turn: <error>`; unless it is a
context overflow or transient, its fix is `check the model id and server logs`, since the schema
was accepted on the first turn (R-M15-21).

### §10.3 Web

Three screens:

1. **New run.** Project picker; source list with upload and, when configured, "Fetch from Coglossa"; value statement text area with a **Suggest value** button that runs a discovery and shows candidates with their evidence; profile select; max iterations; **Start**.
2. **Progress.** Stage timeline over SSE with iteration count and token usage so far; cancel.
3. **Review.** Left: rendered HTML report. Right: tabs **Provenance** (select a claim → its evidence units highlighted with locators and source names), **Audit** (one row per rule: verdict, severity, evidence, iteration history; advisory rules in their own group), **Process** (stage timeline, draft-to-draft diff per iteration, token usage per role), **Sources** (list with kinds, hashes, Coglossa run ids). Actions: **Accept**, **Return with note**, **Download** (DOCX, Markdown, HTML, trace JSON).

M4b amendments: the screens are `/new?project=<id>` (the project, the open tab and the selected
claim live in the URL so a reload keeps them), `/runs/<id>` and `/runs/<id>/review?tab=&claim=`;
the New run screen also lists the project's runs. The report is shown in a sandboxed frame (`srcdoc`, scripts allowed, no origin of its own; M7)
loaded from `GET /runs/{id}/report?format=html&with_claim_ids=1`; selecting a claim (in the
Provenance tab or by clicking a cited paragraph) highlights every element whose `data-claim-ids`
contains it. A small script inside the frame relays clicks on cited elements to the page and
applies the highlight the page asks for; links inside the report navigate nothing. The Audit tab takes rule titles and the advisory grouping from
`GET /packs/{pack}/resolved?profile=` for the run's pack name and profile (the live pack; when it
no longer resolves, rows show rule ids in one group). Progress follows `GET /runs/{id}/events` and
polls `GET /runs/{id}` every 3 s when the browser has no `EventSource` or the stream gave up.
No System screen in v1 (`corelata doctor` and `GET /api/system/doctor` cover it; M18 adds Settings, §10.3). The Sources tab shows each source's SHA-256 (M7).
The report frame's document carries its own Content-Security-Policy (`default-src 'none'`, the
bridge by nonce, inline styles only, `img-src data:`; M9). The review screen derives "Accepted" / "Returned" from
`GET /runs/{id}`'s `review`; the run list on the New run screen pages fifty at a time up to the API's 500; discovery
polling backs off to 15 s (M9; 5 s since M16).

M14 amendments: the frame's policy allows the report's stylesheet by its SHA-256 hash, computed
when the web app is built from the engine's `render/templates/report.css` (the report's one
`<style>` element holds exactly that file), and the bridge's script and highlight style by the
per-render nonce: `style-src` has no `'unsafe-inline'`, and the report has no `style` attributes
(CRL-23). The run list pages fifty at a time by the API's cursor to the project's oldest run,
with no ceiling (CRL-24).

M15 amendments: when the decision is a return whose rerun ended without a report, the Review
screen says so (the rerun failed, with its error; was cancelled; or stopped at the gate) next to
the link to the rerun, and enables **Accept** and **Return with note** again, the note box
holding the previous note. While a return's rerun has not ended, the screen reads
`GET /runs/{id}` every 3 s, because the run's progress stream ended with the run (CRL-34).

M16 amendments: the New run screen keeps the discovery in its URL (`?project=<id>&discovery=<id>`,
replaced by each **Suggest value**), so a reload reads it again. Discovery polling backs off 1, 2,
4 s, then every 5 s, and stops once a read finds the discovery still created or running 10
minutes after its `created_at`, measured on the server's clock (the answer's `Date` header);
the screen then says, in a polite live region, "Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery." A reload reads once and shows the same without polling; a discovery seen
completed or failed shows as before, however old. After an accept, **Accept** and **Return with
note** stay disabled; a page opened before another reviewer accepted gets the 409 in the Return
dialog and re-reads the run (CRL-21).

M17 amendments: the New run screen keeps the chosen sources in its URL as well
(`?project=<id>&sources=<id>,<id>&discovery=<id>`, replace navigation; no `sources` means every
source; ids that are not the project's are dropped; another project drops both), so a reload
keeps them (CRL-40). CRL-54 writes the choice as `pick=i.<token>…` (chosen) or `pick=x.<token>…`
(left out), whichever is shorter, one 6-character token per source, so 500 sources stay under
2 kB; `sources=` is still read. Discovery polling stops once the server's clock is 15 s past the latest
read's `deadline_at` and the discovery is at least 10 minutes old (`max(10 minutes, deadline_at -
created_at + 15 s)` of age), so the screen shows the server's failure at either limit without a
reload, and the ceiling moves with the claim; the 10-minute message is the fallback for a server
that did not end it (CRL-38). While the discovery is `created` the screen says, in its polite live
region, "Waiting for the worker to start the discovery…", and once it is `running`, "Looking for
value in the selected sources…". Leaving a page cancels its pending reads, which is not shown as an
error; the Provenance tab says "Loading evidence…" while a claim's evidence loads; the Suggest
request leaves out an empty `audience_hint` (CRL-40).

CRL-97 amendment: the Process tab lists the earlier accepted reports the run was given
(`TraceSummary.prior_reports`: run id, title, acceptance time, and how many key judgments were
read or "left out: over the token budget"). The Standards tab groups a rule the pack marks
advisory with the checked rules once any of its verdicts is pass or fail, as `icd203.tc.7` is
when checked against earlier reports.

M18 amendments (CRL-41): the web app is on Coglossa's design system, specified in
`docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md` §2 to §9 and the
M18 plan's rulings. A header (theme toggle, Help, Settings, the signed-in name, Sign out when
`auth.logout_url` is set) and a project sidebar frame every screen. New run is New report
(`/new`, choose or create a project) and the project page (`/new?project=<id>&sources=&discovery=`,
the same URL state); Progress is Writing the report; Review's tabs keep their ids and read
Claims, Standards, Process and Sources; `/settings` is added (Appearance, Status from
`GET /system/doctor`, Technical details), which replaces "No System screen in v1". M17's
live-region text "Waiting for the worker to start the discovery…" reads "Waiting for Corelata
to start looking…"; "Looking for value in the selected sources…" and the 10-minute fallback are
unchanged. The report frame follows the app's theme by a class the bridge sets on the frame's
root, in its nonce-bound style; `report.css`, its hash and the frame's policy are unchanged.

## §11 Configuration (`corelata.yaml`)

```yaml
backends:
  local: {kind: openai_compat, base_url: http://models:8000/v1, api_key_env: CORELATA_LOCAL_KEY, max_concurrency: 4, timeout_s: 120}
models:
  strong: {backend: local, name: qwen3-32b, context_window: 32768, structured_output: json_schema, max_output_tokens: 8192, temperature: 0.2}
  fast:   {backend: local, name: qwen3-8b,  context_window: 32768, structured_output: json_schema, max_output_tokens: 4096, temperature: 0.2}
roles:
  gate:     {model: strong}
  writer:   {model: strong}
  conveyor: {model: strong}
  auditor:  {model: strong}
  profiler: {model: strong}
retry: {max_attempts: 4, base_delay_s: 2, max_delay_s: 60}
standards:
  packs_dir: /data/packs
  default_pack: icd203-base
  default_profile: null
pipeline:
  max_iterations: 2
  digest_threshold_tokens: 6000
  digest_chunk_tokens: 4000
  writer_unit_budget_tokens: 16000
  gate_unit_budget_tokens: 12000
audit: {store_llm_io: true}
database: {url_env: CORELATA_DATABASE_URL}
storage: {kind: local, path: /data/files}
worker: {concurrency: 2, stalled_after_s: 900, job_retention_days: 30, discovery_deadline_s: 600, discovery_start_deadline_s: 3600}
api: {max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64, web_dir: /app/web}
auth: {mode: trusted_header, header: X-Remote-User}
integrations:
  coglossa: {base_url: http://coglossa-api:8080, api_key_env: CORELATA_COGLOSSA_KEY}   # optional
```

The listening address is a `corelata-api --host/--port` flag (default 127.0.0.1:8080), not configuration (M4a; as Coglossa).

Strict pydantic (`extra=forbid`). `load_config` returns errors and warnings; `config_hash` is stored on every run. API keys are named by environment variable only.

M14 amendment (CRL-22): `api.progress_poll_s` (default 1.0) is the progress streams' fallback:
the interval while the API's `LISTEN` connection is down, and the base of the heartbeat while it
is up (× 10, at most 30 s, never below `api.progress_poll_s`).

M17 amendments: `worker.discovery_deadline_s` (default 600, at least 60) is a discovery's work
limit, from the worker's claim, and `worker.discovery_start_deadline_s` (default 3600, at least 60)
its start limit, from its creation while no worker has claimed it (§7.5, CRL-38); both are in the
operational `worker` section, outside `config_hash`. `worker.concurrency` covers runs and
discoveries together. A backend `base_url` with a query string or a fragment is a configuration error
(the request path would land inside the query; keys go in the variable `api_key_env` names), so
`corelata doctor` fails its config check (CRL-39).

CRL-97 amendment: `pipeline.prior_judgments: {max_reports, budget_tokens}` (`max_reports` 0 to
20, default 0; `budget_tokens` at least 100, default 2000) is project memory (§7.4). It shapes
output, so it is inside `config_hash`. Unset it is off, as `evidence_quotes` is (CRL-93): an
upgraded install changes nothing until it opts in, and `icd203.tc.7` stays attested as before
(never `not_applicable`). `engine/corelata.example.yaml` sets `max_reports: 3`. Once on,
`icd203.tc.7` is checked only by a pack with the `with_prior_reports` block (an upgrade never
overwrites the customer's pack).

M18 amendment: `auth.logout_url` (optional, operational, outside `config_hash`) is the
proxy's sign-out page: a `/path` (not `//`, no backslash, whitespace or control character) or an
`http(s)` URL, refused otherwise when the configuration loads. When it is set the web header shows
Sign out, a POST to it.

## §12 Packaging and operations

*(Superseded in part — see the M5 amendment below: `.env.example`, `packs/icd203-base` and "runs `docker compose up`" in this section are now `.env` written by `install.sh`, `config/packs.example/icd203-base`, and a printed next step.)*

Compose services: `postgres`, one-shot `migrate`, `worker`, `api`. One app image (API, web build, worker, CLI, fake OpenAI server). Overlays: `compose.demo.yaml` (fake model, sample sources) and `compose.dev.yaml`.

Bundle `corelata-<ver>-linux-amd64.tar` + `.sha256`: `images/*.tar`, `config/` (example `corelata.yaml`, `.env.example`, `packs/icd203-base`), `install.sh`, `backup.sh`, `restore.sh`, `operator-guide.md`, `sbom/`, manifest, `SHA256SUMS`. `install.sh` verifies checksums, loads images, creates config, pack directory and `.env` only if missing, runs `docker compose up -d --wait` and `corelata doctor`. Upgrades never overwrite the customer's pack directory.

CI: ruff check and format, pytest per package, web type generation diff check, lint, test, build, Playwright e2e, `make deploy-check` (shellcheck, install and restore tests, compose check), `make airgap-test` (install on a network with no route out, run a full report against the fake model, back up, upgrade, restore).

M5 amendments: the bundle carries the base pack as `config/packs.example/icd203-base/` and
`install.sh` copies it to `config/packs/` once, so the customer's pack directory is never in
`SHA256SUMS` and never overwritten (the operator merges a newer base pack by hand with
`diff -r`). The bundle also carries `examples/` (the sample source) and a `VERSION` file; the
version is the git tag at HEAD, else `<package version>-g<sha>`; the image bakes the version
into CORELATA_BUILD_VERSION, so /api/health, /api/system/info, the web footer and corelata --version
report the bundle version (M7); a source checkout reports the package version. The
worker's `stop_grace_period` is 5 minutes. There is no GPU overlay and no scorer. The demo
overlay adds a `fake-openai` service and points `CORELATA_CONFIG` at `config/corelata.demo.yaml`.
The air-gap test also covers a pack edit surviving an upgrade and an invalid config stopping
`migrate`. Bundles are built with `make bundle` on a developer machine; a tag `v<version>` that
equals the package version runs the `release` workflow (M7), which repeats the air-gap test, builds
the bundle and publishes the tar, its `.sha256` and the manifest as a GitHub release; the `airgap`
CI job itself runs on pull requests only. `install.sh` prints `docker compose up -d --wait` and `corelata doctor` as the
next steps instead of running them, so the operator edits `config/corelata.yaml` first (as in
Coglossa). No `.env.example` ships: `install.sh` creates `.env` with the generated database
password, and the guide documents the other variables (`CORELATA_HTTP_BIND`, `CORELATA_HTTP_PORT`,
model-server keys named by `api_key_env`).

M17 amendment: migration 0006 adds an index (§8.3) and runs inside `migrate` like every other;
a restore of an older backup is migrated by the restore's final `docker compose up -d --wait`.

## §13 Testing and quality gates

- 95% branch coverage per Python package (`--cov-fail-under=95`), `filterwarnings=error`. Vitest 95% on lines, branches, functions and statements.
- Real Postgres in tests via the copied pytest plugin (`CORELATA_TEST_DATABASE_URL`).
- **Synthetic responder** (`testing/synthetic.py`), deterministic per role: the gate supports a statement when at least two of its key terms appear in the units, otherwise rejects with reasons; discovery returns one candidate per source; the writer emits a template-conformant `Report` whose claims cite real unit ids, and copies any `UNSOURCED` marker from the sources into a claim with no evidence; the conveyor returns the draft with a changed title; the auditor fails `icd203.tc.8` when any claim lacks evidence and `icd203.tc.2` when a `BADTERM` marker appears, otherwise passes every verifiable rule. Faults (timeouts, malformed JSON, oversized-context errors) are scriptable as in Coglossa.
- **Property tests** (hypothesis): profile resolution (idempotent, order-independent for `add`, disable plus override of one rule id is an error), and the five trace invariants in §8.4.
- **Golden tests**: base pack loads and resolves to a checked-in JSON; Markdown and DOCX renders of a fixture `Report` match structure assertions (section order, heading count, superscripts on/off).
- **Scenario fixtures** (`engine/tests/fixtures/scenarios/*.yaml`): sources plus statement plus expected gate verdict plus expected failing rules. Run in CI with the fake; runnable against real models with `corelata bench` (M6), which reports gate agreement and rule-failure agreement.

  *M6 amendment:* the scenario files ship inside the package at `engine/corelata/bench/scenarios/*.yaml` (not `engine/tests/fixtures/`), so `corelata bench` runs in the deployed image; the tests load them from there. The bench reports full agreement, gate agreement, rule-failure agreement (one decision per run: every iteration the scenario specifies must match) and state agreement, plus a per-rule tally of hits, misses and unexpected failures.

  *M12 amendment (CRL-28):* a second set, `engine/corelata/bench/scenarios-real/`, is written for
  real models: short invented sources with dates, actors and figures, and expectations stated as
  ranges and rule sets (`state_in`, `status_in`, `iterations_max`, `gate_supported_in`,
  `substance_in`, `rules_must_pass`, `rules_may_fail`, `rules_must_fail`). `corelata bench
  --scenarios synthetic|real|DIR` picks the set (default `synthetic`; CI scores only that one).
  An iteration whose audit degraded (M11) counts as not audited. Each run in `bench.json` keeps
  the gate's verdict.

  *M13 amendment (CRL-33):* the bench table cuts an errored run's error to the outcome column,
  so every row keeps the same column offsets, and lists each error whole under `errors` after
  the table; `bench.json` keeps it whole.
- **Playwright**: the three screens against the fake model and a seeded database.

  *M14 amendment (CRL-23):* one journey runs behind `api/csp_proxy.py`, a proxy in front of the
  dev stack (`devstack.py --csp-proxy-port`) that adds the operator guide's sample
  `Content-Security-Policy` to every response; it follows a run's progress, highlights a claim in
  the report frame, and fails on any policy violation. A pytest test checks that the proxy's
  policy is the guide's sample word for word.
- **Air-gap test**: a full report end to end in the sealed network.

## §14 Milestones

| Milestone | Delivers | Exit test |
|---|---|---|
| **M1 engine + CLI** | config, llm, prompts, pack loader + `icd203-base`, schemas, ingest (all kinds incl. Coglossa export), pipeline with loop, Markdown render, in-process `corelata run` writing to a directory | `corelata run` on fixture sources with the fake backend produces a report and trace JSON; `pack validate` passes on the base pack |
| **M2 trace + rendering** | trace export format, HTML and DOCX render, open-findings appendix, scenario fixtures | golden renders; scenario fixtures pass with the fake |
| **M3 persistence + worker** | Postgres schema, alembic, procrastinate worker, service layer, discovery job, stalled requeue, `parent_run_id` reruns | a run executes through the queue; cancel and requeue tested |
| **M4a API** | all routes in §10.1, SSE, auth, openapi.json, `from-coglossa` fetch | route tests against the fake and a real Postgres |
| **M4b web** | the three screens | Vitest + Playwright |
| **M5 packaging** | bundle, install/backup/restore, operator guide, airgap test, SBOM | `make airgap-test` green |
| **M6 profile extractor + bench** | `profile extract`, `corelata bench` against real models | extractor produces a valid draft profile from three example reports; bench runs the scenario set against a hosted open model |

M6 may slip past the first customer deployment.

*M6 amendment:* the exit test's "against a hosted open model" half is a manual step: CI proves the extractor and the bench against the synthetic model; the operator guide shows the commands for a real model server.

## §15 Out of scope for v1 (candidates for later)

- PDF rendering (needs an offline HTML-to-PDF toolchain; evaluate weasyprint).
- Additional report products in the base pack (short alert / BOLO, situational report).
- ~~Prior-report memory so `icd203.tc.7` becomes verifiable.~~ Delivered by CRL-97 in its
  narrow, project-local form: a run reads only the key judgments of Corelata's own accepted
  reports in the same project (§7.4). Memory across projects or of reports written outside
  Corelata stays out of scope.
- Visual information generation (`icd203.tc.9`).
- Classification guide enforcement beyond the handling marking allowed list.
- User management, billing, cost estimation.
- Live collection or search.
- Bundled models.
- Extraction of the shared Coglossa/Corelata foundation package (after both products are deployed).

## §16 Assumptions

- The customer's model endpoints support JSON-schema structured output or at least JSON mode; `structured_output: none` is supported with the repair turn as fallback, at lower reliability.
- Source files are the analyst's to upload; Corelata never fetches from the network except the optional Coglossa API.
- A single run fits one analyst's attention span: minutes, not hours. `max_iterations` defaults to 2 for that reason.
- DOCX is the format analysts edit after delivery; Markdown and HTML serve the review UI and downstream automation.
