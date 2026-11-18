# Corelata

Standards-enforced intelligence report production with a full trace. An analyst supplies
source material and a statement of its intelligence value; Corelata gates the statement
against the sources, drafts an ICD 203-shaped assessment, reviews it for the reader, audits
it rule by rule against a replaceable standards pack, and delivers the report with every
claim linked to its evidence.

Design: `docs/superpowers/specs/2026-10-12-corelata-v1-design.md`. Plans: `docs/superpowers/plans/`.

## M1: engine and CLI

    cd engine && uv sync --all-groups
    uv run corelata fake-openai &                      # a synthetic model for a smoke test
    cp corelata.example.yaml corelata.yaml             # points at 127.0.0.1:8000 by default
    uv run corelata run ../docs/examples/*.txt --statement "Varna port capacity expansion matters to shippers" --out /tmp/run1
    kill %1                                            # stop the fake model
    uv run corelata pack show icd203-base

Exit codes: 0 clean, 3 findings open, 4 gate rejected, 1 failed, 2 usage, 130 interrupted.

## M2: rendering and trace

Every run directory holds `report.md`, `report.html` (self-contained, provenance attributes on
every paragraph) and `report.docx` (neutral template, or the profile's `format.docx_reference`),
plus `report.json`, `gate.json` and `trace.json`. Open audit findings are appended to all three
renders under "Audit findings open at delivery".

    uv run corelata trace /tmp/run1                       # timeline, findings per iteration, usage
    uv run corelata trace /tmp/run1 --claim c1            # a claim's evidence units and locators
    uv run corelata report /tmp/run1 --format html --claim-ids > review.html
    uv run corelata report /tmp/run1 --format docx --out report.docx --docx-reference house.docx

`report` re-renders from `trace.json` alone, so a stored trace is enough to reproduce every
export. The trace format is documented in `docs/trace-format.md`.

## M3: queued runs against Postgres

The same engine runs unattended behind a job queue. Point `CORELATA_DATABASE_URL` at Postgres
16, set `storage.path` in `corelata.yaml`, then:

    uv run corelata migrate                                 # create or upgrade the schema
    uv run corelata worker &                                # process queued runs and discoveries
    uv run corelata run ../docs/examples/*.txt --project demo --statement "Varna port capacity expansion matters to shippers"
    uv run corelata status <run-id>                         # state, stages, token usage
    uv run corelata cancel <run-id>                         # stops after the current stage
    uv run corelata review <run-id> --return --note "Tighten the scope"   # a linked rerun
    uv run corelata export <run-id> --out /tmp/run2         # trace and renders from the database
    uv run corelata report /tmp/run2 --format docx --out report.docx      # uses the stored reference
    uv run corelata discover ../docs/examples/*.txt --project demo        # proposes value statements
    uv run corelata ingest more.pdf --project demo          # sources for later runs (--source-id)
    uv run corelata doctor                                  # config, prompts, pack, models, database, storage

A run is one queue job: progress, stage results and model calls land in Postgres as it goes,
and a worker that dies mid-run is detected by the stalled-job task; the run starts over and its
trace describes the attempt that produced the report (`attempts` counts them). Every export the
worker stores is reproducible from the database alone (`corelata export`).

## M4a: the REST API

`api/` is the `corelata-api` package: every route of spec §10.1 under `/api`, serving the same
`corelata.service` the CLI uses. It never calls a model except `GET /api/system/doctor`.

    cd api && uv sync --all-groups
    uv run corelata-api --config ../engine/corelata.yaml --port 8080     # needs a migrated database and a worker
    curl -s localhost:8080/api/health
    curl -s -X POST localhost:8080/api/projects -H 'content-type: application/json' -d '{"name":"demo"}'
    curl -s -F file=@../docs/examples/varna-port.txt localhost:8080/api/projects/<project-id>/sources
    curl -s -X POST localhost:8080/api/runs -H 'content-type: application/json' \
         -d '{"project_id":"<project-id>","source_ids":["<source-id>"],"value_statement":"Varna port capacity expansion matters to shippers"}'
    curl -N localhost:8080/api/runs/<run-id>/events                       # progress as server-sent events
    curl -s "localhost:8080/api/runs/<run-id>/report?format=docx" -o report.docx
    curl -s localhost:8080/api/runs/<run-id>/trace | head -c 400

Auth is `none` or `trusted_header` (`auth:` in `corelata.yaml`): a reverse proxy signs people in and
passes the user name in `X-Remote-User`; a review records it as the actor. With
`integrations.coglossa` configured, `POST /api/projects/{id}/sources/from-coglossa {"run_id": …}`
imports a Coglossa run by id. The contract is `schema/openapi.json` (`make schema` regenerates it;
`GET /api/openapi.json` serves it behind auth); `GET /api/system/info` tells a client the version,
the auth mode and whether the Coglossa fetch is available.

## M4b: the web app

`web/` is the review UI (spec §10.3): **New run** (project, sources, value statement with
"Suggest value", profile, iterations), **Progress** (stage timeline over server-sent events, token
usage, cancel) and **Review** (the rendered report with claim highlighting; Provenance, Audit,
Process and Sources tabs; Accept, Return with note, downloads). It is a static build the API
serves. M18 rebuilt every screen and renamed several; the M18 section below describes them as
they are now.

    (cd web && pnpm install)
    make dev-stack      # repository root; a throwaway database, the fake model, a worker and the API on 8080
    cd web && pnpm dev  # second terminal (the dev stack stays in the foreground); live reload, /api proxied to 8080
    cd web && pnpm test # Vitest, 95% coverage gate
    make e2e            # repository root; Playwright journeys against the dev stack

For a deployment, build once (`cd web && pnpm build`) and start the API with
`corelata-api --config corelata.yaml --web-dir web/dist`. `--web-dir` is relative to the current
directory; `api.web_dir` in the YAML is relative to the config file. The app is served from the same origin as the API, so a reverse
proxy that signs people in covers both. The client is generated from `schema/openapi.json`
(`make schema`); CI fails when it is stale.

## M5: deploy it

One image, one Compose stack, one offline bundle (spec §12). On a build machine with Docker and
internet access:

    make image-app                       # build corelata/app:dev and check its contract
    make demo                            # the stack with the synthetic model on http://127.0.0.1:8080
    make demo-down
    make bundle                          # dist/corelata-<version>-linux-amd64.tar (+ .sha256), with SBOMs
    make deploy-check                    # shellcheck, install/restore tests, compose check (no images needed)
    make airgap-test                     # install the bundle on a sealed network, run a report, back up, upgrade, restore

A release is a tag: bump `engine/corelata/__init__.py` and `engine/pyproject.toml`, merge, then
`git tag v<version> && git push origin v<version>`. The `release` workflow checks that the tag
names the package version, runs the air-gap test, builds the bundle and publishes the tar, its
`.sha256` and the manifest as a GitHub release.

On the customer's host: verify the checksum, extract, `./install.sh`, edit `config/corelata.yaml`
(and `config/packs/` for the standards), `docker compose up -d --wait`,
`docker compose exec api corelata doctor`. `docs/operator-guide.md` (shipped in the bundle as
`operator-guide.md`) has the whole procedure, backups, restore, upgrades and troubleshooting.

## M6: profiles from examples, and the bench

Two commands for the standards team, both model calls and no database (spec §4.4, §6.8, §13):

    corelata profile extract --from team-east-reports/ --out config/packs/icd203-base/profiles/team-east.yaml
    corelata bench --config corelata.yaml --out bench-2026-10-14/

`profile extract` reads a directory of a team's finished reports (any ingestible format), shows
the `profiler` role the pack the profile will extend, and writes a profile with `draft: true`:
tone guidance, heading style, template limits, extra handling markings and source descriptors,
and any rules the team disables or re-grades. The header comments carry the model's observations.
Review it, then remove `draft: true`; `corelata pack validate` lists a draft as a warning and a
run refuses it. `roles.profiler` must be configured. Exit 0 means a draft was written, 1 that the
model could not produce a valid one, 2 a usage, config, pack or ingest problem, or an `--out` that
exists (pass `--force`). Long example reports get the budget the short ones leave, so a team's one
long report is not cut to a third; the command warns when the profile name already exists in the
pack it extends.

`bench` plays a scenario set against the configured models and reports agreement with each
scenario's expectations: full agreement (nothing to object to), gate agreement, rule-failure
agreement, state agreement, and a per-rule tally of misses and unexpected failures.
`--scenarios synthetic` (the default; `engine/corelata/bench/scenarios/`) is the set written for
the synthetic model's markers, `--scenarios real` (`engine/corelata/bench/scenarios-real/`, M12)
the set written for real models, and `--scenarios DIR` any directory. `--only NAME` (repeatable)
picks scenarios, `--repeat N` plays each scenario N times; `--out DIR` keeps `bench.json` and
every run's `trace.json` (a re-run into the same directory replaces the traces of the scenarios it
runs); `--json` prints the report. `--concurrency N` runs up to N scenario runs at once (the
backend's `max_concurrency` still caps the server), `--store-io` keeps the model requests and
responses in the traces for diagnosing a disagreement, and `bench.json` is rewritten after every
finished run, so Ctrl-C keeps what finished. Exit 0 means full agreement, 3 some disagreement, 1 a
run that errored, 2 a usage error. A real model disagrees with the synthetic set often, which says
little about it; the real set is how you measure a model or a prompt change. Neither is a
pass/fail gate.

## M7: hardening after v1

Six follow-ups from the first release (Jira BORG-35, 36, 40, 41, 42, 43): `/api/health`,
`/api/system/info`, the web footer and `corelata --version` report the bundle version the image
was built with (`CORELATA_BUILD_VERSION`); `corelata pack diff <left> <right>` compares packs,
profiles (`--profile-left/right`) and run snapshots (a run directory) and exits 3 on a
difference; the Sources tab shows each source's SHA-256; the report frame is sandboxed with no
origin of its own (`srcdoc`, `sandbox="allow-scripts"`, a `postMessage` bridge; links inside the
report are inert); `corelata bench` keeps a partial `bench.json` on Ctrl-C and takes
`--concurrency` and `--store-io`; `corelata profile extract` gives long example reports the budget
short ones leave and warns when the name is already a profile.

## M8: correctness and operations

Seven tickets from the follow-up triage (CRL-6, 7, 10, 11, 12, 13, 14): a restarted run and a
rejected upload leave no files behind; `restore.sh` refuses a database with schemas it does not
manage; the worker purges closed jobs nightly (`worker.job_retention_days`, default 30) and the
orphan sweep is indexed (migration 0003); the Coglossa fetch fails clearly on a bad URL, an unset
key variable (409) or an export over 50 MB, and `corelata doctor` checks the integration; a parent
run must be in the same project and a completed run can be returned once (409 after that); header
logos inside `mc:AlternateContent` or a `w:object` survive the marking; the digest ladder never
forces a source no chunk can hold, keeps forced-digest sources in the gate's pool, and records a
failed re-digest in the trace.

## M9: efficiency and review state

The last four triage tickets (CRL-8, 9, 15, 16): the report routes check the run's state before
loading anything, serve the stored file for the plain case and cache claim-id re-renders per run
and format; every progress stream on one run shares one database poller and the progress read
skips the run row's large JSON columns; the pack listing is re-read only when a pack file changes;
`GET /api/runs/{id}` carries the review decision of a completed run, so the review screen shows
"Accepted" or "Returned" (with a link to the rerun) after a reload, a cancel invalidates the
project's run list, the run list pages fifty at a time, and a cancel that arrived too late is
explained on the outcome; discovery polling backs off to 15 s (5 s since M16); the report frame
carries its own Content-Security-Policy (bridge by nonce, nothing loads from anywhere) and the
operator guide says what a proxy policy must allow; `corelata doctor` warns about pack directories
the API cannot address.

## M10: stored review state and bounded caches

Four follow-ups from M9 (CRL-17 to 20): the review decision is stored on the run row (migration
0004 backfills it from the review events), so a progress read on a completed run no longer queries
`review_event`; the pack listing checks the pack files at most once a second and follows
symlinked pack directories (a link cycle ends the walk), and `corelata doctor` checks pack names
against the API's own pattern and 100-character limit; the claim-id render cache is bounded by
`api.render_cache_mb` (default 64) as well as by its 64 entries; the report frame's policy lands
inside a `<head>` with attributes; the M9 test debt is paid (a cancelled stream, the shared
poller, the review note, the run-list ceiling, loading states without real delays); and a
duplicate React key on the New run page, which kept the previous project's value statement on
screen after a switch, is fixed.

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
copy. When the last audit degrades, the engine's own unsourced-claim checks run on the delivered
draft, and an earlier iteration's engine finding that the revision fixed no longer stays open;
the auditor's own findings from the last completed audit do (CRL-30).

## M12: writer evidence enum, doctor probes, bench scenarios for real models

The rehearsal against OpenRouter (CRL-1) found three gaps. The writer's and conveyor's schema now
restricts `Claim.evidence` to the run's unit ids (one `UnitRef` enum built per call; plain strings
above 200 units), so a `json_schema` server cannot let a model cite `src1` as a unit (CRL-29).
The reply is still parsed as the canonical `ReportBody`, so every other server gets the ref error
in the same repair message as the other validator errors. The auditor's unit and claim enums are emitted once each. `corelata doctor` prints how many models a
server serves and whether each configured model is among them, never the whole list, and its
structured-output probe asks for a real gate verdict with the same schema and request builder a run uses (no output cap unless the model sets
`max_output_tokens`), so it fails
when a run's schema would be rejected (CRL-27). `corelata bench --scenarios real` plays eight
scenarios written for real models: short sources with dates, actors and figures, and
expectations stated as ranges and rule sets (`state_in`, `substance_in`, `rules_must_pass`, ...);
the synthetic set stays the default and the one CI runs. The bench table shows the gate's verdict
and, when it disagrees, its first reason; `bench.json` keeps the verdict per run, and a run whose
audit degraded scores as "no audit ran"; when only the last audit of a delivered report
degraded, the rule sets stay unscored and the run counts as a disagreement (CRL-28).

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

## M14: event-driven progress, a frame policy without inline styles, cursor paging

The last M9 follow-ups (CRL-22 to 24). The worker and the service announce every committed change
to a run with `NOTIFY corelata_run, '<run_id>'` in the transaction that writes it, and the API
holds one `LISTEN` connection, so a progress page updates as soon as a stage is recorded, and a
watched run that is not changing costs one read per heartbeat (`api.progress_poll_s` × 10, at
most 30 s and never below `api.progress_poll_s`) instead of one per `progress_poll_s`; while that connection is down the streams poll
every `api.progress_poll_s` as before and the API reconnects after 1, 2, 4, 8, 16, then every
30 s (CRL-22). The report frame's policy allows the report's stylesheet by its SHA-256 hash,
computed when the web app is built from the engine's `report.css`, and the bridge's highlight
style by the frame's nonce, so `style-src` no longer carries `'unsafe-inline'`; a Playwright
journey runs a report behind a proxy that adds the operator guide's sample policy to every
response, so the sample is a tested configuration (CRL-23). `GET /api/runs` answers
`{runs, next_before}` and takes `before=<next_before>`: keyset paging on `(created_at, id)`, so
the run list pages fifty at a time to a project's oldest run and the 500-run ceiling is gone
(CRL-24).

## M15: a failed rerun no longer strands a report, doctor repairs like a run

CRL-34 to 36, from the 2026-10-18 follow-up triage. A return is spent only while its rerun is
running or has completed: a rerun that fails (the model server was down), is cancelled or stops at
the gate leaves the report free to be returned again, with a new note, or accepted; the old return
stays in the review history. Two reviewers returning at once still make exactly one rerun. The
return, its rerun and the stored decision commit in one transaction, so an interrupted request
leaves nothing behind, and migration 0005 records each existing rerun's fate and removes returns
an earlier version left half made. Every way a rerun ends (the worker, a cancel, a refused queue,
the orphan sweep) records its fate on the returned run and announces it; the Review screen keeps
reading a returned run until its rerun ends, then says why it failed and offers Return (with the
previous note) and Accept again (CRL-34). `corelata doctor` gives a structured probe that got
unusable JSON the same single repair turn a run gives, built by the same code: a model that needs
it is a warning ("json_object output works after one repair turn"), which does not fail doctor
or the air-gap acceptance (`install.sh` never runs doctor); a model that fails twice still fails, citing the second
reply. `corelata fake-openai --needs-repair` plays such a model (CRL-35). `restore.sh` prints
psql's own message when it cannot list the database's schemas, and `check-bundle.sh` ignores
Python bytecode when it compares the shipped pack (CRL-36).

## M16: an accepted report is final, a stuck discovery says so

CRL-21 (the owner's decisions of 2026-10-18), CRL-37 (review minors) and the CRL-1 rehearsal
findings. An accept is the reviewer's final word: `POST /api/runs/{id}/review` with `return` on
an accepted run answers 409 "run … was accepted; start a new run to change it", and
`corelata review --return` says the same; the decision is taken under the run's row lock, so a
return that waited for an accept is refused. An accept after a rerun that failed, was cancelled
or stopped at the gate is still allowed, and a live or completed return still wins over a later
accept. The New run screen (since M18 the project page, under New report) stops asking about a
discovery 10 minutes after it was created (measured on the server's clock) and says that it has not
finished; the discovery is in the URL, so a reload reads it again, and polling backs off 1, 2, 4 s,
then every 5 s (was 15 s) (CRL-21). `restore.sh` removes its temporary file on every exit, a Ctrl-C
included; the API's shutdown closes the database pool even when its listener died, and no longer
swallows its own cancellation; the development CSP proxy answers 502 when the stack behind it is
down; a web test that makes an unmocked request now fails, and the notification tests wait for what
they expect instead of a fixed time (CRL-37). A run whose model server is down fails with "model
server unreachable (<url>)" before the network error. The operator guide shows how to rehearse an
installation, its backups, an upgrade and a restore with the demo model, names `CORELATA_HTTP_BIND`,
points at the HTTP API's OpenAPI description, writes the pre-upgrade backup outside the bundle
directory and removes the old image after an upgrade (CRL-1).

## M17: stuck work ends on its own, operator mistakes caught early

CRL-38 to 40, from the 2026-10-19 follow-up triage. A discovery has two limits, both at least
60 s, whether or not a worker is running. One the worker has not started is failed
`worker.discovery_start_deadline_s` (default 3600 s) after it was created, with "Discovery did
not start within 60 minutes and was stopped: the worker was stopped or busy with runs. Start a
new discovery."; one the worker started is failed `worker.discovery_deadline_s` (default 600 s)
after the start, with "Discovery did not finish within 10 minutes and was stopped. Start a new
discovery.". So a discovery queued behind two long runs is not failed when it is 10 minutes
old, and it gets its whole 10 minutes once it starts.
Discoveries are queued with a higher priority than runs, so one takes the next free worker slot
ahead of waiting runs. Whoever looks first ends a discovery past its limit: the API when the
discovery is read, the worker when it takes the job or finishes, or the worker's minute sweep; a
worker that answers after the work limit does not bring it back, and an error the model gave is
kept as the reason. `GET /api/discoveries/{id}` carries `deadline_at`, the limit that applies
(the start limit while it waits, the work limit from its start), and the New run screen (since M18
the project page) keeps asking until 15 s past it, so it shows the server's reason without a reload;
while the discovery waits it says "Waiting for Corelata to start looking…" (M18). M16's "has not
finished after 10 minutes" message remains for a server that did not end it. Cancelling a run whose
worker is gone (its heartbeat `worker.stalled_after_s` old, or its worker row deleted) ends the run
at once and closes its job; a live worker, however slow, still stops at its next stage, and a worker
that was taken for dead stops at its next write instead of overwriting the cancel, recording nothing
more (not even its in-flight stage's model calls and token usage). The requeue skips a job a cancel
has closed (INFO in the worker's log). After the first press the web's **Stop writing…** button is
replaced by the text "Stopping after the current step…" (the CLI prints `run <id>: cancel requested;
it stops after the current stage`), so a run whose worker died less than `worker.stalled_after_s`
ago needs `corelata cancel` (or the API) again after that threshold, or ends on its own when a
running worker requeues its job after it (CRL-38). A backend `base_url` with a query string or a
fragment is refused when the configuration loads, so `corelata doctor` fails its config check with
the reason; doctor's suggestions for a missing model ignore case; migration 0006 indexes the run
list by `(project_id, created_at DESC, id DESC)`, which took the first page of a 10,000-run project
from 6.9 ms to 0.08 ms in the measurement (CRL-39). The New run screen (since M18 the project page)
keeps the chosen sources in its URL (`?sources=`), so a reload keeps them; leaving a page cancels
what it was loading without showing a network error; the evidence panel says it is loading; the
Suggest request leaves out an empty audience hint; three M16 tests wait for what they mean (CRL-40).
Coverage now runs with `concurrency = ["greenlet", "thread"]` in `engine/pyproject.toml` and
`api/pyproject.toml`, so lines run in SQLAlchemy's greenlets and in threads are counted.

## M18: Corelata on Coglossa's design system

CRL-41. Corelata's web app now looks and behaves like Coglossa's: the same colour tokens in a
light and a dark set, the same type (Noto Sans, `@fontsource/noto-sans` 5.3.0 as Coglossa ships
it, the one new package), buttons, header and sidebar. The theme follows the computer until
someone picks one (the header's ☾ / ☀, or Settings ▸ Appearance); it is set before the page
draws, and the report inside the review frame follows it too, with `report.css`, its hash and
the frame's policy unchanged. A sidebar lists the projects, newest activity first, grouped Today,
This week and Earlier, each with one status ("… writing", "● 2 waiting for review", "! needs
attention"); `GET /api/projects` carries what it needs (`last_activity_at`, `reports_writing`,
`reports_to_review`, `latest_run`), computed by three grouped statements however many projects
there are. The screens speak the reader's words: a run is a report, the gate is the value check,
the audit is the standards check; the engine's words stay in the Process and Sources tabs,
Settings ▸ Technical details, the API, the CLI and the trace. New report asks which project it
is for; the project page holds Sources (drop several files at once, as documents or Coglossa
exports, uploaded one after another), the value statement and its suggestions, More options
(team profile, revision rounds), Write the report and the Reports list (`GET /api/runs` rows
carry `review_decision` and `review_child_state`). Writing the report lists eight steps, each a
symbol and a word, with a Details fold and Stop writing…. Review has the title, a status pill,
Accept, Return with note… and a Download menu in its header, a one-sentence banner, and the report
beside the Claims, Standards (each rule a block: not met, minor issues, met and not applicable,
advisory), Process and Sources tabs. "Not met" means what the engine counts as open, a rule whose
latest verdict is a blocking or major fail; a minor fail leaves the report clean, as the engine
has it, so it is listed under Minor issues with its severity, the pill still says "✓ Meets the
standards" and the banner adds "1 minor issue is listed under Standards." (R-M18-27). Settings holds
Appearance, the installation's status in one plain sentence with a full check, and Technical details
(the doctor's check names live there); Help (the header, or `?`) explains the keys, statuses and
steps. `auth.logout_url` (a `/path` or an `http(s)` URL) adds Sign out to the header for a proxy
with a sign-out page. Text meets WCAG AA in both themes (a test checks every listed colour pair), no
stylesheet but `tokens.css` holds a raw colour, and the behaviour M9 to M17 pinned is unchanged. The
rulings, the divergences from Coglossa and the fixes still to come are in `docs/m18-followups.md`.

## M19: a hosted demo

CRL-42. A password-protected Corelata on the internet for demonstrations, built like Coglossa's
preview so one runbook serves both: a Vercel front door (`deploy/hosted/vercel`: the web app, a
sign-in page and middleware that checks a signed session cookie, then forwards `/api/*` to Modal
with the user's name, Corelata's proxy secret and Modal's proxy-auth token), a Modal app
(`deploy/hosted/modal/app.py`: the API, a burst worker started by a kick after each queued job, a
cron every 5 minutes and a daily purge, all scaling to zero; `migrate`, `doctor` and `seed` by
hand), Supabase (the database `corelata` and the bucket `corelata-files`, in Coglossa's project;
Coglossa's database and bucket are never touched) and OpenRouter (`gpt-4.1-mini` writes,
`gemini-2.5-flash` checks the standards). The site is the `*.vercel.app` address of the project
`corelata-demo`, with the logins `people-first` and `ci`. The seed writes one example report
("Example: Varna port") the first time.
The engine and API gain what the demo needs, each off unless configured: `storage.kind: s3`, every
storage call off the event loop (a cancelled call is waited for, so a cleanup never races it),
`worker.kick_url`, `auth.proxy_secret_env` and its middleware, and the cron's `cron_pass` and
`purge_pass`. The proxy secret, the kick token and the database name fail closed. The air-gapped
install is unchanged: the app image carries no S3 client
(`check-app-image.sh` checks), and the bundle, `install.sh` and the `airgap` job are as before. CI
adds `hosted-web` (the front door's Vitest at 95 % and `tsc`) and `hosted-modal` (the settings,
start-clean and smoke tests, and the Modal app's import without an account);
the hosted workflow deploys on push once the owner adds its tokens, and until then the
demo is deployed by hand. `deploy/hosted/README.md` is the runbook; the rulings, the divergences
from Coglossa and the follow-ups are in `docs/m19-followups.md`.

## Development

    make db-up && make lint && make test   # Postgres 16 in Docker; ruff and pytest for engine and api; Vitest for web

Tests need `CORELATA_TEST_DATABASE_URL` (an admin URL; `make test-engine` sets it to the dev
database on 127.0.0.1:55433). The suite creates a throwaway database per session.

Scenario fixtures (`engine/corelata/bench/scenarios/*.yaml`) pin the pipeline's behaviour
against the synthetic model: sources, statement, expected gate verdict, failing rules per
iteration. They ship inside the package so `corelata bench` can play them against real models
(see M6). Add one when you change what a run does. The real-model set
(`engine/corelata/bench/scenarios-real/*.yaml`) states ranges and rule sets instead; CI only checks
that the real set loads and that `off-topic-sources` runs to an outcome on the synthetic
model (the other seven are only loaded).

## Licence

Corelata is licensed under the Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Contributions are welcome under the same terms: see [CONTRIBUTING.md](CONTRIBUTING.md) for how,
and [SECURITY.md](SECURITY.md) to report a vulnerability.
