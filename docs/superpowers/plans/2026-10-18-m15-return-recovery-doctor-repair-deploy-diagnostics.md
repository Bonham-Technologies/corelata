# M15 Return Recovery, Doctor Repair Turn, Deploy Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-34, CRL-35 and CRL-36, the two OPEN-M15 rows of the 2026-10-18 follow-up triage plus two deploy diagnostics. (1) A return is spent only while its rerun is live or completed: a rerun that fails, is cancelled or stops at the gate frees the report, which can be returned (or accepted) again; the return, its rerun and the stored decision commit in one transaction, so an interrupted return leaves nothing behind; every path that ends a rerun records its fate on the parent's `review_state` and announces the parent; the Review screen says what happened and offers Return and Accept again (CRL-34). (2) `corelata doctor`'s structured probes get exactly the one repair turn a run gets, built by the same code: a model that needs it is a WARN (doctor still passes), not a FAIL (CRL-35). (3) `restore.sh` shows psql's own message when the schema query fails, and `check-bundle.sh` ignores Python bytecode when it compares the shipped pack (CRL-36).

**Architecture:** Engine: `ReviewState` gains `child_state`, `child_error` and `note`; `service._review_state(events, reruns)` decides from the review events and each rerun's `(state, error)` (`store.runs.rerun_states`); `service.review_run` takes the parent's row lock, refuses only a *live* return (`_live_return`), and creates the rerun (`_create_run(..., session=s)`), the `return` event and the stored decision in that one transaction. Migration 0005 (data only) deletes `return` events an earlier version left unlinked and recomputes every stored decision with the new rule. `service.reruns_ended(s, run_ids)` recomputes and announces the parents of runs that just reached a terminal state; the service's queue-failure and cancel paths, the worker's cancel-at-start, both failure paths and outcome transaction, and the orphan sweep call it in their own transactions. Doctor: `llm/agent.py` exposes `repair_messages` and `rejection_errors`, which `AgentRunner.run` and `doctor._probe` both use; `_probe` sends the repair turn on a rejected reply and answers PASS / WARN / FAIL. `corelata fake-openai --needs-repair` plays such a model. Web: `pollInterval` keeps reading a finished run while its return's rerun has not ended (the progress stream ends at a terminal state, so the parent's notification reaches no Review page); `ReviewActions` shows the rerun's fate and re-enables both actions. Deploy: `restore.sh` sends psql's stderr to a temporary file and prints it under `psql said:`; `check-bundle.sh` passes `-x __pycache__ -x '*.pyc'` to `diff -r`.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async + psycopg 3, Alembic, pydantic 2, FastAPI; React 19, TanStack Query 5, Vitest 4, msw 2, Playwright; bash, shellcheck 0.10.0 (pinned container); Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §8.3 (`run.review_state`, M10 amendment), §10.1 (review route, M4a/M9/M10/M14 amendments), §10.2 (doctor, M12/M13 amendments), §10.3 (Review screen), §12 (restore). Ticket texts are Jira CRL-34, CRL-35, CRL-36. The plans that specified what this one changes: `docs/superpowers/plans/2026-10-15-m8-correctness.md` (R-M8-1, one return per run, the placeholder event), `docs/superpowers/plans/2026-10-15-m10-review-column-pack-index-cache-budget.md` (R-M10-1, `review_state` on the run row, the lock order), `docs/superpowers/plans/2026-10-16-m12-writer-enum-doctor-real-bench.md` and `2026-10-17-m13-auditor-probe-source-enum-bench-debt.md` (R-M12-3, R-M13-8/11/12, the probes), `2026-10-17-m14-notify-progress-frame-csp-cursor-paging.md` (R-M14-3, `notify_run`). The triage: `followups-triage-m15.md` (controller's scratchpad; its OPEN-M15 rows and FIXED list are copied into Task 6).

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean. Playwright journeys stay green (`make e2e`: 6). `ci-status` is the required check.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`, `make e2e`, `make deploy-check`. Do not run the full pytest and Vitest suites concurrently.
- **Schema changes (R-M15-2, R-M15-10), and nothing else.** `ReviewState` gains `child_state: RunState | None = None`, `child_error: str | None = None`, `note: str | None = None` and a new docstring. `make schema` changes exactly `schema/run-progress.schema.json`, `schema/openapi.json` and `web/src/api/schema.d.ts` (the `ReviewState` component). No route, request or response model changes otherwise; `api/tests/test_openapi.py::test_every_screen_has_its_routes` is untouched. Commit the three generated files with Task 1.
- **One migration, data only (R-M15-13).** `engine/corelata/store/migrations/versions/0005_review_state_rerun_fate.py`; no DDL; head becomes `0005` (`tests/store/test_migrations.py::HEAD`, `tests/test_doctor.py::test_a_healthy_installation`, `tests/test_cli_ops.py` read it). No config schema change. The trace format does not change.
- **Store API.** `store.runs.return_event`, `set_review_child` and `delete_review_event` are removed (nothing calls them after Task 1); `rerun_states(s, run_ids)` and `parent_ids(s, run_ids)` are added. `service._create_run` gains `session: AsyncSession | None = None`. `service.reruns_ended(s, run_ids)` and `service.FREED_BY` are new public names (the worker and the sweep import them).
- **Doctor (R-M15-14).** Message and fix texts are fixed by this plan and pinned by tests; `CheckStatus.WARN` keeps `DoctorReport.ok` true and the CLI's exit code 0, so `deploy/tests/smoke.py` (`doctor["ok"]`) and `airgap-test.sh` (`corelata doctor`'s exit code) pass on a model that needs a repair. `api/tests/test_system.py::test_doctor_is_healthy_against_the_fake_server` is untouched.
- Web tests mock every request with msw (`web/src/test/setup.ts` fails an unmocked one); poll intervals are read through `web/src/test/poll.ts` (`runRefetchInterval`), never fake timers. Fixtures live in `web/src/test/fixtures.ts`.
- Shell scripts pass the pinned shellcheck (`make deploy-check`); `deploy/tests/test-restore.sh` runs `restore.sh` against its stub `docker`.
- Commit messages end with exactly these two lines, nothing else after them (R-M15-8):
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK`
  Write the message to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Version stays `0.1.3` (`engine/pyproject.toml`, `tests/test_version.py`); the controller cuts 0.1.4 after the live rehearsal (R-M15-7).
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12, R-M10-1 to R-M10-10, R-M11-1 to R-M11-8, R-M12-1 to R-M12-10, R-M13-1 to R-M13-12 and R-M14-1 to R-M14-15 stay in force, except where R-M15-1 re-reads R-M8-1.
  - **R-M15-1 (CRL-34, what "one return" means).** R-M8-1's "one return per completed run" is read as one *live or successful* return. A `return` event spends the run's return while its child run is non-terminal or COMPLETED. A child that ends FAILED or CANCELLED, or a placeholder whose `child_run_id` is still null after the orphan sweep's grace, does not spend it: the run can be returned again (a new event and a new child; the old event stays as audit trail). Concurrent returns still produce exactly one live child (the parent's row lock, R-M10-1 lock order: `lock_run` first). Accept after a failed rerun is allowed again. CRL-21 (return *after accept*) is untouched: server and UI behave as today for an accepted run.
  - **R-M15-2 (CRL-34, where the state lives).** The parent's stored `review_state` must reflect its rerun's fate, because the Review screen reads only that column (M10). Every path that ends a child run FAILED or CANCELLED (find them all: the worker's failure paths, the sweep, the service's cancel and queue-failure) recomputes the parent's `review_state` in the same transaction and announces the parent with `runs.notify_run` (M14), so an open Review page updates. If `ReviewState` needs a field (for example the rerun's terminal state), add it and run `make schema` (allowed in M15: `schema/*.json`, `openapi.json`, `schema.d.ts` may change for this only); otherwise derive it. Choose the smallest shape and record it as a ruling.
  - **R-M15-3 (CRL-34, interruption).** The orphan sweep clears (or marks void) a `return` placeholder with a null `child_run_id` older than its grace, so a crash mid-return frees the run. The cleanup in `review_run` must not be interruptible by `CancelledError` (narrow the `except BaseException` or shield the cleanup; pin with a test that cancels during the cleanup). Consider one transaction for placeholder + child + link (`_create_run` taking an outer session); do it only if it is smaller than the sweep path, and say which you chose.
  - **R-M15-4 (CRL-34, web).** When the stored decision is a return whose rerun FAILED or was CANCELLED, the Review screen says so ("Returned; the rerun failed: <reason>" with the link to the rerun) and enables Return (note box available again, prefilled with the previous note if the API returns it, else empty) and Accept. Every other decided state behaves as today.
  - **R-M15-5 (CRL-35, doctor repair parity).** `doctor._probe` gets exactly the one repair turn `AgentRunner` gives a run, built by the same code (extract the repair-message builder from `AgentRunner` if needed so the bytes are identical; R-M12-3 "a probe and a run send the same thing" applies to the repair turn too). A first reply that parses → PASS as today. A first reply that fails and a repaired reply that parses → the check passes doctor's exit code and the message says `<mode> output works after one repair turn (<Name>)` with a fix/note that every structured call may cost a second request on this model; use doctor's non-fatal warning level if it has one that does not change the exit code or fail `deploy/tests/smoke.py`/`airgap-test.sh`, else PASS with that message (read how WARN is treated and rule). Both replies fail → FAIL as today with the cause-specific fix (R-M13-8/11/12), citing the repaired reply's error. Same for the auditor-schema probe. Truncation and backend errors keep their current handling (no repair turn on a backend error, as a run).
  - **R-M15-6 (CRL-36).** `restore.sh` keeps psql's stderr for the schema query and prints it under its own message; extend `deploy/tests/test-restore.sh` with a case where the stub psql fails with a message and assert the message reaches the output. `check-bundle.sh` excludes `__pycache__` (and `*.pyc`) from its `diff -r`. No digest pin for `postgres:16-alpine` (kept for later; see the CRL-36 text).
  - **R-M15-7 (scope, gates, docs).** No migration unless R-M15-2 needs one (prefer none: `review_state` is JSONB). Engine and api coverage 95%, Vitest 95%, Playwright stays green, `ci-status` the required check. Docs: README M15 section; spec amendments (§8.3 return semantics, §10.1/§10.3 as touched, the doctor section for the repair turn); operator guide (doctor row: the repair-turn line; restore troubleshooting: psql's message now shows); strike every item the triage lists as FIXED in its follow-up file ("— **closed**, verified 2026-10-18: <evidence>") and the items M15 closes ("— **closed in M15** (CRL-…)"); new `docs/m15-followups.md`. Version stays 0.1.3; the controller cuts 0.1.4 after the rehearsal.
  - **R-M15-8 (attribution).** Every commit message ends with exactly the two lines above (this changed from earlier milestones' `Claude Fable 5.1` line).
  - How the plan applies them (from reading the code at 5c7ac13 and applying every task to a scratch copy of `engine/`, `api/`, `web/` and `deploy/`: engine 884 passed (861 before), api 165 (164), web 176 Vitest (168), e2e 6 passed, ruff, `pnpm lint` and `pnpm build` clean, the pinned shellcheck clean on the three scripts, `test-restore.sh` 16 ok lines; `corelata doctor` against `corelata fake-openai --needs-repair` printed the two WARN lines and exited 0, and `corelata run` through it completed with 8 model calls):
    - R-M15-1: `service.FREED_BY = TERMINAL_STATES - {COMPLETED}`; `_live_return(events, reruns)` is the newest `return` whose rerun is unknown (null `child_run_id`, a legacy in-flight placeholder), non-terminal or COMPLETED. `review_run` refuses only when it finds one, with the existing two messages ("is being returned; its rerun is not ready yet" for a null child, "was already returned; its rerun is <id>. Return that run to iterate again" otherwise). Both checks run after `get_run(..., lock=True)`, so two returns at once serialize on the parent's row and the second sees the first's committed rerun (pinned).
    - R-M15-2: the fields and the call sites are R-M15-10. Every terminal write path calls `service.reruns_ended(s, [run_id])` after its own `notify_run`: `service._mark_run_failed` (the queue refused the rerun's job), `service.cancel_run` (a `created` run ends at once), `worker/execute.py` `_begin` (cancelled at job start), both branches of `_fail_run`, `execute_run`'s outcome transaction (completed, gate-rejected, failed and cancelled outcomes all end there), and `worker/sweep.py` `sweep_orphans` (one call for every run it fails). A run without a parent costs one indexed read and announces nothing more (pinned: the M14 test counting 14 announcements per run is unchanged).
    - R-M15-3: one transaction, not the sweep path (R-M15-12).
    - R-M15-4: R-M15-11 (how the page learns) and R-M15-17 (the copy).
    - R-M15-5: `CheckStatus.WARN` exists, `DoctorReport.of` sets `ok` from FAIL only, and the CLI returns `EXIT_OK if report.ok`, so a repaired probe is WARN (R-M15-14).
    - R-M15-6: R-M15-16.
    - R-M15-7: a migration is needed (R-M15-13).
  - Rulings this plan adds:
    - **R-M15-9 (CRL-34, a rerun stopped at the gate).** The brief lists FAILED and CANCELLED; the code has a third terminal state that is not a report, GATE_REJECTED, and a gate-rejected rerun cannot be reviewed either (only a completed run can, `review_run`), so under the brief's literal reading the report would stay stranded exactly as CRL-34 describes. Every terminal state except COMPLETED frees the return (`FREED_BY`); the web says "The rerun stopped at the gate (value not supported)". If wrong: drop `GATE_REJECTED` from `FREED_BY` (service, migration 0005, `web/src/api/runs.ts`) and one parametrized case.
    - **R-M15-10 (CRL-34, the stored shape and the lock order).** `ReviewState.child_state` is the rerun's state once it reached *any* terminal state (COMPLETED included, so a Review page knows when to stop reading) and `None` while it is created or running; `child_error` is the rerun's `error` then; `note` is the chosen return's note (`None` for an accept), so the dialog can offer it again. Live states are never stored on the parent (no write per stage). The decision: a live return wins over any accept (R-M9-1 unchanged); otherwise the latest event decides, so return(failed) → "returned" with its fate, return(failed) then accept → "accepted", return(failed) then return → the new one. Lock order: a path that ends a run holds that run's row lock and then takes its parent's (`reruns_ended` locks parents in sorted order when it is given several, as the sweep does); no path holds a parent's lock while it waits for a child's (`review_run` reads its reruns' states without locking them), so the order cannot deadlock. If wrong: three optional fields go; the web would need another read per Review page.
    - **R-M15-11 (CRL-34, how an open Review page learns; contradicts the brief).** R-M15-2 says the parent's `notify_run` makes an open Review page update. It cannot: `GET /runs/{id}/events` ends its stream as soon as the run is terminal (`api/corelata_api/routes/progress.py:30`), a parent under review is COMPLETED, and `ReviewPage` reads `useRun(runId)` without a stream. The plan keeps the announcement (it is the M14 contract and costs nothing) and makes the page read: `pollInterval` returns `POLL_MS` (3 s) for a terminal run whose stored decision is a return with no `child_state` yet (`rerunPending`), and `false` once the rerun ended. If wrong: a Review page left open while the rerun runs makes one `GET /api/runs/{id}` every 3 s, which the progress page already does without `EventSource`.
    - **R-M15-12 (CRL-34, one transaction instead of the sweep path).** One transaction is smaller: `review_run` loses its placeholder, its link transaction and its compensating delete (net fewer lines), `_create_run` gains a `session` parameter, and nothing new joins the sweep. Under the parent's row lock it inserts the rerun (and its `run_source` rows), then the `return` event with `child_run_id` set, then the stored decision; a concurrent return waits for the lock. A failure or a `CancelledError` anywhere before the commit rolls everything back; the only cleanup left is the rerun's copy of the reference document, removed with plain (synchronous) file calls in `except BaseException`, which a `CancelledError` cannot interrupt (pinned by a test that cancels the request while the transaction waits). Placeholders an earlier version left behind are deleted once by migration 0005, so the sweep never has to look for them. A rerun whose job never reached the queue (a crash between the commit and `_defer_run`) is failed by the existing orphan sweep after its 120 s grace, which now frees the parent (pinned). The parent's lock is now held while the reference document is read and copied (small local files; before M15 that happened outside the lock). If wrong: a return blocks other reviews of the same run for the length of one file copy.
    - **R-M15-13 (CRL-34, migration 0005; contradicts "prefer none").** Existing rows need the new fields, or a 0.1.3 report whose rerun already failed would stay "Returned" with both actions off and its Review page would read forever (`docs/m10-followups.md` predicted this: "a field added to `ReviewState` needs its own migration"). 0005 is data only: it deletes `return` events whose `child_run_id` is null (only an interrupted pre-M15 return leaves one; the stack is stopped during an upgrade), clears `review_state` of runs left with no events, and recomputes every reviewed run's decision with the new rule written out in the revision (the revision never imports the service, as 0004). The downgrade keeps the data (0.1.3's model ignores the extra keys; the deleted placeholders were dead). `test_0004_backfills_review_state_from_the_review_events` now upgrades to `"0004"` exactly. If wrong: drop 0005 and accept stale rows.
    - **R-M15-14 (CRL-35, the probe's three outcomes).** PASS: `<mode> output works (<works>)` as today. WARN: `<mode> output works after one repair turn (<works>)`, fix `nothing to change for a run, which repairs the reply the same way; every structured call on models.<key> may cost a second request`; the `model <key>` line takes the worst of its parts, so it reads `test completion succeeded; json_object output works after one repair turn (GateVerdict)`. FAIL: `the server did not return the requested JSON (<mode>), even after one repair turn: not a <Name>: <loc>: <msg>` with the repaired reply's first error and the existing `wrong_json` fix. The repair turn is built by `llm.agent.repair_messages(messages, content, errors)` from `llm.agent.rejection_errors(validation_error)` and the reply text as the model sent it, the same two functions `AgentRunner.run` now calls, and sent through `build_request` with the same schema and limits, so only the turn differs (pinned against a real `AgentRunner` repair). A truncated reply or a backend error on either request keeps today's message and fix and gets no further request. Doctor parses with the output type only (no semantic validator, as before), so its errors are the pydantic ones a run would list first. If wrong: the WARN becomes PASS by changing one `CheckStatus`.
    - **R-M15-15 (CRL-35, a model that needs a repair, on demand).** `FakeOpenAIServer(needs_repair=True)` and `corelata fake-openai --needs-repair` answer the first turn of every structured call (any task but `ping`, no `assistant` message yet) with `{}`, which lacks a required field of every output type, and the repaired turn with the synthetic answer. The rehearsal uses it; a run through it completes with every call doubled. If wrong: test infrastructure only.
    - **R-M15-16 (CRL-36, how psql's message is kept).** psql's stderr goes to a `mktemp` file, not into the captured stdout (`2>&1` would read a `docker compose` warning on stderr as a schema name and refuse the restore; pinned). On failure the script prints `error: could not list the database's schemas; is the database up (docker compose ps)?`, then `psql said:` and the message indented two spaces (the heading only when there is a message), removes the file and exits 1; on success it removes the file. `check-bundle.sh` gains no test of its own (it needs a built bundle); the step checks the two `-x` flags with a two-tree `diff` on both BSD and GNU diff. "Restore against a stopped database" (the brief's rehearsal) cannot happen: `restore.sh` starts the database itself (`docker compose up -d --wait postgres`) before it asks; the rehearsal refuses the connection with `ALTER DATABASE corelata ALLOW_CONNECTIONS false` instead. If wrong: shell text only.
    - **R-M15-17 (CRL-34, the Review screen's copy).** The decision badge keeps its text ("Accepted" / "Returned"); a freed return adds `<span role="note" aria-label="Rerun outcome">`: "The rerun failed: <child_error or 'no reason was recorded'>. Return the report again or accept it." / "The rerun was cancelled; return the report again or accept it." / "The rerun stopped at the gate (value not supported); return the report again or accept it.", next to the existing "Open the rerun" link. Return and Accept are enabled exactly when the decision is a freed return (`rerunFreed`) or there is none. Opening the dialog on a freed return puts the previous note in the box when the box is empty (a note typed and cancelled is kept, as today). If wrong: copy only.
    - **R-M15-18 (docs).** The spec's return text lives in §10.1 (the review bullet: "A second `return` on the same run is a 409 conflict; the first rerun is the only one"), so the §8.3 amendment records the column's new keys and the §10.1 amendment the semantics; the doctor's repair turn is a §10.2 amendment (where M12 and M13 put the probes); §10.3 records the Review screen. `docs/m8-followups.md`'s "Spec deviations" line on R-M8-1 and its partial-unique-index item are annotated as superseded by R-M15-1. If wrong: placement only.

## Review Focus

1. **Two reviewers return the same report at once after its rerun failed: exactly one new rerun must exist, the other request must get a 409 naming it, and the stored decision must point at the one that exists.** Pinned in Task 1 (`test_two_returns_at_once_after_a_failed_rerun_make_one_live_rerun`).
2. **A rerun fails while the parent's Review page is open: within a poll the page must say why and offer Return and Accept again, and stop reading once the rerun has ended.** Pinned in Task 2 (`test_a_rerun_that_fails_frees_its_parent_and_announces_it`, and one test per ending path in `tests/worker/test_rerun_end.py`) and Task 4 (`an open Review page keeps reading the run while its rerun runs, and shows its failure`).
3. **A return interrupted between writing its event and linking its rerun (a crash, a cancelled request) must not leave the report "being returned" forever.** Pinned in Task 1 (`test_a_return_cancelled_inside_its_transaction_leaves_nothing_behind` for M15's code, `test_0005_drops_unlinked_returns_and_records_each_reruns_fate` for what 0.1.3 left behind) and Task 2 (`test_a_rerun_the_sweep_fails_frees_the_parent` for a crash after the commit).
4. **A small model on `json_object` that needs its repair turn must not fail doctor (and so `install.sh`, `smoke.py` and the air-gap acceptance), while a model that fails twice still does, with the second reply's error.** Pinned in Task 3 (`test_a_model_that_needs_one_repair_turn_warns_and_doctor_still_passes`, `test_the_probes_repair_turn_is_the_one_a_run_sends`, `test_a_repaired_reply_that_is_still_wrong_fails_and_cites_its_own_error`).
5. **`restore.sh` against a database that refuses the connection must show psql's reason, stop nothing, and never mistake a stderr warning for a foreign schema.** Pinned in Task 5 (`test-restore.sh`: "a refused connection shows psql's own message", "a warning on stderr is not read as a schema name").

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/schema/progress.py` | `ReviewState.child_state`, `child_error`, `note` (Task 1). |
| `engine/corelata/store/runs.py` | `rerun_states`, `parent_ids`; `return_event`, `set_review_child`, `delete_review_event` removed (Task 1). |
| `engine/corelata/service.py` | `_create_run(session=)`, `FREED_BY`, `_reruns`, `_live_return`, `review_run` in one transaction, `_review_state(events, reruns)` (Task 1); `reruns_ended` and its calls in `_mark_run_failed` and `cancel_run` (Task 2). |
| `engine/corelata/store/migrations/versions/0005_review_state_rerun_fate.py` (new), `store/migrate.py` | the data migration (Task 1). |
| `engine/corelata/worker/execute.py`, `worker/sweep.py` | `reruns_ended` on every terminal write (Task 2). |
| `engine/corelata/llm/agent.py`, `engine/corelata/doctor.py` | `repair_messages`, `rejection_errors`; the probe's repair turn (Task 3). |
| `engine/corelata/testing/fake_openai.py`, `engine/corelata/cli.py` | `needs_repair`, `fake-openai --needs-repair` (Task 3). |
| `schema/run-progress.schema.json`, `schema/openapi.json`, `web/src/api/schema.d.ts` | regenerated by `make schema` (Task 1). |
| `web/src/api/runs.ts`, `web/src/pages/review/ReviewActions.tsx` | `rerunPending`, `rerunFreed`, `pollInterval`; the outcome note and the re-enabled actions (Task 4). |
| `deploy/restore.sh`, `deploy/tests/test-restore.sh`, `deploy/tests/check-bundle.sh` | psql's message, bytecode excluded (Task 5). |
| tests: `engine/tests/test_return.py` (new), `engine/tests/test_service.py`, `engine/tests/store/test_migrations.py`, `engine/tests/test_doctor.py`, `engine/tests/test_cli_ops.py`, `engine/tests/test_cli.py`, `engine/tests/worker/test_rerun_end.py` (new), `api/tests/test_runs.py`, `web/src/api/runs.test.tsx`, `web/src/pages/review/ReviewActions.test.tsx` | the tickets' tests. |
| `README.md`, spec, `docs/operator-guide.md`, `docs/m3-`, `m4b-`, `m5-`, `m8-`, `m10-`, `m12-`, `m13-followups.md`, `docs/m15-followups.md` (new) | docs (Task 6). |

Order: Task 1 before Task 2 (both edit `service.py`; Task 2 calls `_store_review_state` as Task 1 leaves it) and before Task 4 (the regenerated client types). Task 3 and Task 5 are independent of the others. Task 6 documents all five.

---

### Task 1: A return is spent only by a live or completed rerun, and commits in one transaction (CRL-34, engine)

**Files:**
- Modify: `engine/corelata/schema/progress.py` (`ReviewState`, lines 25-32), `engine/corelata/store/runs.py` (imports lines 18-31; `return_event` lines 544-552; `set_review_child` and `delete_review_event` lines 566-573), `engine/corelata/service.py` (`_create_run` lines 262-317; `_store_review_state` to `_review_state`, lines 377-479), `engine/corelata/store/migrate.py` (docstring lines 1-4), `engine/tests/test_service.py`, `engine/tests/store/test_migrations.py` (line 32, line 279, append), `engine/tests/test_doctor.py` (line 93), `engine/tests/test_cli_ops.py` (line 56)
- Create: `engine/corelata/store/migrations/versions/0005_review_state_rerun_fate.py`, `engine/tests/test_return.py`
- Regenerate: `schema/run-progress.schema.json`, `schema/openapi.json`, `web/src/api/schema.d.ts`

**Interfaces:**
- Consumes: `tests.test_service.Svc` and `_set_state(db, run_id, state)` (existing helpers); `store.runs.load_review_events`, `add_review_event`, `lock_run`, `set_review_state`, `run_source_ids` (unchanged).
- Produces: `ReviewState.child_state: RunState | None`, `child_error: str | None`, `note: str | None`; `store.runs.rerun_states(s, run_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, tuple[RunState, str | None]]`; `store.runs.parent_ids(s, run_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]` (sorted; used by Task 2); `service.FREED_BY: frozenset[RunState]`; `service.Reruns` (type alias); `service._reruns(s, events) -> Reruns`; `service._live_return(events, reruns) -> ReviewEvent | None`; `service._review_state(events, reruns) -> ReviewState | None` (was `_review_state(events)`); `service._store_review_state(s, run_id)` (same signature; Task 2 calls it); `service._create_run(..., session: AsyncSession | None = None)`. Alembic head `0005`.

- [ ] **Step 1: Failing tests**

Create `engine/tests/test_return.py`:

```python
"""A return is spent only while its rerun is live or completed (CRL-34, R-M15-1, R-M15-3)."""

import asyncio
import uuid

import pytest
from docx import Document

from corelata import service
from corelata.schema import ReviewAction, RunState
from corelata.store import runs
from corelata.store.models import ReviewEvent, utcnow
from tests.test_service import Svc, _set_state


@pytest.fixture
def svc(db, tmp_path, make_config):
    return Svc(db, tmp_path, make_config())


async def _completed(svc: Svc) -> tuple[uuid.UUID, uuid.UUID]:
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    return pid, run_id


def _review(svc: Svc, run_id: uuid.UUID, action: ReviewAction, **kw):
    return service.review_run(
        svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, action, **kw
    )


async def _children(svc: Svc, pid: uuid.UUID, run_id: uuid.UUID) -> list[str]:
    return [
        r.run_id for r in await service.list_runs(svc.db, pid) if r.parent_run_id == str(run_id)
    ]


@pytest.mark.parametrize("ending", ["failed", "cancelled", "gate_rejected"])
async def test_a_run_whose_rerun_ended_without_a_report_can_be_returned_again(svc, ending):
    pid, run_id = await _completed(svc)
    first = await _review(svc, run_id, ReviewAction.RETURN, note="Tighten the scope", actor="ana")
    await _set_state(svc.db, first, ending)
    second = await _review(svc, run_id, ReviewAction.RETURN, note="Tighten it", actor="bob")
    assert second is not None and second != first
    assert sorted(await _children(svc, pid, run_id)) == sorted([str(first), str(second)])
    async with svc.db.session() as s:
        events = await runs.load_review_events(s, run_id)
    assert [(e.action, e.child_run_id, e.actor) for e in events] == [
        ("return", first, "ana"),  # the old event stays as the audit trail
        ("return", second, "bob"),
    ]
    with pytest.raises(service.ConflictError, match=f"already returned; its rerun is {second}"):
        await _review(svc, run_id, ReviewAction.RETURN, note="Once more")


@pytest.mark.parametrize("live", ["created", "drafting", "completed"])
async def test_a_live_or_completed_rerun_still_spends_the_return(svc, live):
    pid, run_id = await _completed(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="x")
    await _set_state(svc.db, child, live)
    with pytest.raises(service.ConflictError, match=str(child)):
        await _review(svc, run_id, ReviewAction.RETURN, note="y")
    assert await _children(svc, pid, run_id) == [str(child)]


async def test_accept_after_a_failed_rerun_is_allowed_and_decides(svc):
    _, run_id = await _completed(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="x", actor="ana")
    await _set_state(svc.db, child, "failed")
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "bob")
    assert review.child_run_id is None


async def test_two_returns_at_once_after_a_failed_rerun_make_one_live_rerun(svc):
    pid, run_id = await _completed(svc)
    first = await _review(svc, run_id, ReviewAction.RETURN, note="x")
    await _set_state(svc.db, first, "failed")
    results = await asyncio.gather(
        _review(svc, run_id, ReviewAction.RETURN, note="a", actor="ana"),
        _review(svc, run_id, ReviewAction.RETURN, note="b", actor="bob"),
        return_exceptions=True,
    )
    made = [r for r in results if isinstance(r, uuid.UUID)]
    refused = [r for r in results if isinstance(r, service.ConflictError)]
    assert len(made) == 1 and len(refused) == 1, results
    assert f"its rerun is {made[0]}" in str(refused[0])
    assert sorted(await _children(svc, pid, run_id)) == sorted([str(first), str(made[0])])
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and review.child_run_id == str(made[0])
    assert review.child_state is None


async def test_a_return_cancelled_inside_its_transaction_leaves_nothing_behind(
    svc, monkeypatch, tmp_path
):
    pid, run_id = await _completed(svc)
    reference = tmp_path / "house.docx"
    Document().save(str(reference))
    svc.storage.put("reference/house.docx", reference.read_bytes())
    async with svc.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).docx_reference_key = "reference/house.docx"
    reached, never = asyncio.Event(), asyncio.Event()
    real = runs.add_review_event

    async def stall(s, rid, action, *args):
        if action == ReviewAction.RETURN.value:
            reached.set()
            await never.wait()  # the request is cancelled here: the rerun row is flushed
        return await real(s, rid, action, *args)

    monkeypatch.setattr(runs, "add_review_event", stall)
    task = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await reached.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.undo()
    async with svc.db.session() as s:
        assert await runs.load_review_events(s, run_id) == []
    assert await _children(svc, pid, run_id) == []
    assert svc.storage.list_keys("runs/") == []  # the rerun's reference copy went
    assert (await service.run_progress(svc.db, run_id)).review is None
    child = await _review(svc, run_id, ReviewAction.RETURN, note="again")
    assert await _children(svc, pid, run_id) == [str(child)]


def _event(action: str, at, child=None, note="") -> ReviewEvent:
    return ReviewEvent(action=action, note=note, actor=action, child_run_id=child, at=at)


def test_review_state_follows_the_reruns_fate():
    t = [utcnow() for _ in range(4)]
    a, b = uuid.uuid4(), uuid.uuid4()
    accepted = _event("accept", t[0])
    failed = _event("return", t[1], a, note="first note")
    live = _event("return", t[2], b, note="second note")
    later_accept = _event("accept", t[3])
    gone = {a: (RunState.FAILED, "could not queue the run: refused")}

    state = service._review_state([accepted, failed], gone)
    assert state is not None and state.decision == "returned" and state.note == "first note"
    assert (state.child_run_id, state.child_state, state.child_error) == (
        str(a),
        RunState.FAILED,
        "could not queue the run: refused",
    )
    # an accept after the failed rerun decides
    state = service._review_state([accepted, failed, later_accept], gone)
    assert state is not None and state.decision == "accepted" and state.at == t[3]
    # a live return wins over any accept, before or after it
    running = {**gone, b: (RunState.DRAFTING, None)}
    state = service._review_state([accepted, failed, live, later_accept], running)
    assert state is not None and state.decision == "returned" and state.child_run_id == str(b)
    assert state.child_state is None and state.note == "second note"
    # a completed rerun is recorded as ended, and still spends the return
    done = {**gone, b: (RunState.COMPLETED, None)}
    state = service._review_state([accepted, failed, live, later_accept], done)
    assert state is not None and state.child_state is RunState.COMPLETED
    assert service._live_return([accepted, failed, live], done) is live
    assert service._live_return([accepted, failed], gone) is None
```

Edit `engine/tests/test_service.py` (the placeholder is gone; `_review_state` takes the reruns; nothing of a return is visible before it commits):

In `test_a_failed_return_leaves_no_placeholder_event`, replace

```python
    async with svc.db.session() as s:
        assert await runs.return_event(s, run_id) is None
```

with

```python
    async with svc.db.session() as s:
        assert await runs.load_review_events(s, run_id) == []
    assert [r.run_id for r in await service.list_runs(svc.db, pid)] == [str(run_id)]
```

In `test_an_unreadable_reference_leaves_no_placeholder_and_can_be_retried`, replace `assert await runs.return_event(s, run_id) is None` with `assert await runs.load_review_events(s, run_id) == []`.

In `test_review_state_prefers_the_return_and_the_latest_accept`, replace the three calls

```python
    assert service._review_state([]) is None
    latest = service._review_state([accept_a, accept_b])
    assert latest is not None and latest.actor == "b"
    placeholder = service._review_state([accept_a, pending])
```

with

```python
    assert service._review_state([], {}) is None
    latest = service._review_state([accept_a, accept_b], {})
    assert latest is not None and latest.actor == "b"
    placeholder = service._review_state([accept_a, pending], {})
```

In `test_review_run_stores_the_decision_on_the_run_row`, replace

```python
    async def boom(*a, **kw):
        seen["during"] = await stored()  # after the placeholder's transaction committed
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_create_run", boom)
    with pytest.raises(RuntimeError):
        await service.review_run(*args, ReviewAction.RETURN, note="x", actor="bob")
    assert seen["during"]["decision"] == "returned" and seen["during"]["child_run_id"] is None
    assert await stored() == accepted  # the placeholder went, and its decision with it
```

with

```python
    async def boom(*a, **kw):
        seen["during"] = await stored()  # another session: the return has not committed
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_create_run", boom)
    with pytest.raises(RuntimeError):
        await service.review_run(*args, ReviewAction.RETURN, note="x", actor="bob")
    assert seen["during"] == accepted  # nothing of the return is visible before it commits
    assert await stored() == accepted  # and nothing of it stays (R-M15-3)
```

and at its end replace

```python
    async with svc.db.session() as s:
        events = await runs.load_review_events(s, run_id)
    assert returned == service._review_state(events).model_dump(mode="json")
```

with

```python
    async with svc.db.session() as s:
        events = await runs.load_review_events(s, run_id)
        reruns = await runs.rerun_states(s, [child])
    assert returned == service._review_state(events, reruns).model_dump(mode="json")
```

Edit `engine/tests/store/test_migrations.py`: `HEAD = "0004"` becomes `HEAD = "0005"`; in `test_0004_backfills_review_state_from_the_review_events` the `upgrade(url)` after the inserts (line 279) becomes `upgrade(url, "0004")` (0005 rewrites what 0004 wrote). Append:

```python


# A review event with its note, which revision 0005 keeps in the stored decision.
_NOTED_EVENT = (
    "INSERT INTO review_event (run_id, action, note, actor, child_run_id, at) "
    "VALUES (:run, :action, :note, :actor, :child, :at)"
)


def test_0005_drops_unlinked_returns_and_records_each_reruns_fate(pg_admin):
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0004")
        project = uuid.uuid4()
        ids = {k: uuid.uuid4() for k in ("failed", "placeholder", "orphan", "live", "after")}
        kids = {k: uuid.uuid4() for k in ("failed", "live", "after")}
        t = [datetime(2026, 10, 18, 9, minute, tzinfo=UTC) for minute in range(3)]
        ends = {
            "failed": ("failed", "boom"),
            "live": ("drafting", None),
            "after": ("cancelled", None),
        }
        events = [
            ("failed", "return", "first", "ana", kids["failed"], t[1]),
            ("placeholder", "accept", "", "ana", None, t[0]),
            ("placeholder", "return", "lost", "bob", None, t[1]),  # never linked: deleted
            ("orphan", "return", "lost", "bob", None, t[1]),  # never linked: deleted
            ("live", "return", "go", "carol", kids["live"], t[1]),
            ("after", "return", "x", "dave", kids["after"], t[1]),
            ("after", "accept", "", "erin", None, t[2]),  # an accept after a cancelled rerun
        ]
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": t[0]},
            )
            for run_id in [*ids.values(), *kids.values()]:
                conn.execute(text(_RUN_AT_0003), {"id": run_id, "project": project, "at": t[0]})
            for name, (state, error) in ends.items():
                conn.execute(
                    text("UPDATE run SET state = :state, error = :error WHERE id = :id"),
                    {"id": kids[name], "state": state, "error": error},
                )
            for run, action, note, actor, child, at in events:
                row = {"run": ids[run], "action": action, "note": note, "actor": actor}
                conn.execute(text(_NOTED_EVENT), {**row, "child": child, "at": at})
            conn.execute(
                text("UPDATE run SET review_state = CAST(:stale AS jsonb) WHERE id = :id"),
                {
                    "stale": '{"decision": "returned", "at": "2026-10-18T09:01:00Z"}',
                    "id": ids["orphan"],
                },
            )
        upgrade(url, "0005")
        with engine.connect() as conn:
            stored = dict(conn.execute(text("SELECT id, review_state FROM run")).all())
            left = conn.execute(text("SELECT count(*) FROM review_event")).scalar_one()
        assert left == len(events) - 2
        assert ReviewState.model_validate(stored[ids["failed"]]) == ReviewState(
            decision="returned",
            at=t[1],
            actor="ana",
            child_run_id=str(kids["failed"]),
            child_state="failed",
            child_error="boom",
            note="first",
        )
        assert ReviewState.model_validate(stored[ids["placeholder"]]) == ReviewState(
            decision="accepted", at=t[0], actor="ana"
        )
        assert stored[ids["orphan"]] is None  # its only event was the unlinked return
        assert ReviewState.model_validate(stored[ids["live"]]) == ReviewState(
            decision="returned", at=t[1], actor="carol", child_run_id=str(kids["live"]), note="go"
        )
        assert ReviewState.model_validate(stored[ids["after"]]) == ReviewState(
            decision="accepted", at=t[2], actor="erin"
        )
        assert all(stored[k] is None for k in kids.values())  # nobody reviewed the reruns
        downgrade(url, "0004")  # the data stays
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM review_event")).scalar_one() == left
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)
```

Edit the two revision strings: `engine/tests/test_doctor.py` line 93 `assert "0004" in checks["database"].message` becomes `assert "0005" in checks["database"].message`; `engine/tests/test_cli_ops.py` line 56 `"at revision 0004"` becomes `"at revision 0005"`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_return.py tests/test_service.py tests/store/test_migrations.py --no-cov -q`
Expected: FAIL. `test_return.py` stops at `ReviewEvent`/`_review_state(..., gone)` (`TypeError: _review_state() takes 1 positional argument`), the "returned again" cases raise `ConflictError: ... was already returned`, `test_service.py` fails on `runs.rerun_states` (`AttributeError`), the migration tests on the missing revision `0005`.

- [ ] **Step 3: The stored shape**

In `engine/corelata/schema/progress.py` replace the `ReviewState` class with:

```python
class ReviewState(BaseModel):
    """What a reviewer decided about a completed run (spec §10.1), from its review events and the
    reruns they created. A return whose rerun is live or completed wins over an accept: the rerun
    supersedes the accepted report (R-M9-1). A rerun that ended any other way spent nothing
    (R-M15-1): the latest event decides, and the run can be returned or accepted again."""

    decision: ReviewDecision
    at: datetime
    actor: str | None = None
    child_run_id: str | None = None  # the rerun a return created; None while it is being made
    child_state: RunState | None = None  # the rerun's state once it ended; None while it runs
    child_error: str | None = None  # why the rerun failed, when it did
    note: str | None = None  # a return's note for the writer, so it can be offered again
```

(`RunState` is already imported from `corelata.schema.run`.)

- [ ] **Step 4: The store reads**

In `engine/corelata/store/runs.py`, in the `from corelata.schema import (...)` list replace `ReviewAction,` with `RunState,` (nothing else in the module uses `ReviewAction` once `return_event` goes). Delete `return_event` (lines 544-552), `set_review_child` and `delete_review_event` (lines 566-573), and insert before `lock_run`:

```python
async def rerun_states(
    s: AsyncSession, run_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[RunState, str | None]]:
    """The state and error of each run in `run_ids` (the reruns returns created), by id: what
    decides whether a return is spent (R-M15-1). A run that no longer exists is left out."""
    ids = list(run_ids)
    if not ids:
        return {}
    rows = await s.execute(select(Run.id, Run.state, Run.error).where(Run.id.in_(ids)))
    return {row.id: (RunState(row.state), row.error) for row in rows}


async def parent_ids(s: AsyncSession, run_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """The distinct parents of the runs in `run_ids`, sorted: the order every transaction that
    locks several parents takes their row locks in (R-M15-2)."""
    found = await s.scalars(
        select(Run.parent_run_id)
        .where(Run.id.in_(list(run_ids)), Run.parent_run_id.is_not(None))
        .distinct()
    )
    return sorted(pid for pid in found if pid is not None)
```

- [ ] **Step 5: `_create_run` joins a caller's transaction**

In `engine/corelata/service.py` replace `_create_run` (lines 262-317) with:

```python
async def _create_run(
    db: Database,
    storage: Storage,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    req: RunRequest,
    *,
    pack_name: str,
    pack_hash_: str,
    pack_snapshot: dict[str, Any],
    profile: str | None,
    reference: bytes | None,
    session: AsyncSession | None = None,
) -> uuid.UUID:
    """The run row, its ordered sources and, when the profile has one, a copy of the reference
    document under runs/<id>/ so the run renders with the template it was queued with. With
    `session` the rows join the caller's transaction (a return, R-M15-3) and the caller removes
    runs/<id>/ if that transaction does not commit; without one they commit here."""
    run_id = uuid.uuid4()
    key = f"runs/{run_id}/reference.docx" if reference is not None else None

    async def insert(s: AsyncSession) -> None:
        if req.parent_run_id is not None:
            parent = await runs.get_run(s, req.parent_run_id)
            if parent.project_id != req.project_id:
                raise InvalidRequestError(
                    f"parent run {req.parent_run_id} belongs to another project"
                )
        await runs.create_run(
            s,
            project_id=req.project_id,
            value_statement=req.value_statement.strip(),
            profile=profile,
            max_iterations=(
                cfg.pipeline.max_iterations if req.max_iterations is None else req.max_iterations
            ),
            extra_guidance=req.extra_guidance,
            config_hash=config_hash(cfg),
            config_snapshot=cfg.model_dump(mode="json"),
            pack_name=pack_name,
            pack_hash=pack_hash_,
            pack_snapshot=pack_snapshot,
            prompt_versions=prompts.versions(run_prompt_ids()),
            corelata_version=__version__,
            docx_reference_key=key,
            parent_run_id=req.parent_run_id,
            source_ids=req.source_ids,
            run_id=run_id,
        )

    try:
        if key is not None:
            storage.put(key, reference)
        if session is not None:
            await insert(session)
        else:
            async with db.session() as s, s.begin():
                await insert(s)
    except BaseException:
        if key is not None:
            with contextlib.suppress(StorageError):
                storage.delete_prefix(f"runs/{run_id}/")
        raise
    return run_id
```

- [ ] **Step 6: The decision and the return**

In `engine/corelata/service.py` replace everything from `async def _store_review_state(` up to (not including) `def _progress(run: Run, stages: list)` (lines 377-480) with:

```python
# A rerun that ends in one of these produced no report to review, so its return is not spent
# (R-M15-1, R-M15-9): the run can be returned, or accepted, again.
FREED_BY = TERMINAL_STATES - {RunState.COMPLETED}

Reruns = dict[uuid.UUID, tuple[RunState, str | None]]


async def _store_review_state(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Recompute the decision from the events and reruns this transaction sees and store it on
    the run (CRL-17, R-M10-1, R-M15-2): two indexed reads per review, none per progress read. The
    row lock comes first, so a concurrent review of the same run waits and then sees this one's
    events."""
    await runs.lock_run(s, run_id)
    events = await runs.load_review_events(s, run_id)
    state = _review_state(events, await _reruns(s, events))
    await runs.set_review_state(s, run_id, state.model_dump(mode="json") if state else None)


async def _reruns(s: AsyncSession, events: list[ReviewEvent]) -> Reruns:
    return await runs.rerun_states(s, [e.child_run_id for e in events if e.child_run_id])


def _live_return(events: list[ReviewEvent], reruns: Reruns) -> ReviewEvent | None:
    """The return that spends the run's one return (R-M8-1 as R-M15-1 reads it): the newest
    return whose rerun is being created, still running, or completed."""
    for event in reversed(events):
        if event.action != ReviewAction.RETURN.value:
            continue
        rerun = reruns.get(event.child_run_id) if event.child_run_id else None
        if rerun is None or rerun[0] not in FREED_BY:
            return event
    return None


async def review_run(
    db: Database,
    storage: Storage,
    queue: JobQueue,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    run_id: uuid.UUID,
    action: ReviewAction,
    *,
    note: str = "",
    actor: str | None = None,
) -> uuid.UUID | None:
    """Spec §10.1 review: `accept` records the decision; `return` records it and creates a
    linked run (`parent_run_id`) over the same sources, statement and pack snapshot, with the
    note appended to the writer guidance. Returns the new run's id for a return. A run whose
    rerun ended without a report can be returned again (R-M15-1). The rerun, the return event
    and the stored decision commit in one transaction under the run's row lock (R-M15-3): a
    concurrent second return waits for the lock and then sees the first, and a return that is
    interrupted leaves nothing behind."""
    child: uuid.UUID | None = None
    try:
        async with db.session() as s, s.begin():
            run = await runs.get_run(s, run_id, lock=True)
            if RunState(run.state) is not RunState.COMPLETED:
                raise InvalidRunStateError(
                    f"run {run_id} is {run.state}; only a completed run can be reviewed"
                )
            if action is ReviewAction.ACCEPT:
                await runs.add_review_event(s, run_id, action.value, note, actor, None)
                await _store_review_state(s, run_id)
                return None
            if not note.strip():
                raise InvalidRequestError("a return needs a note for the writer")
            events = await runs.load_review_events(s, run_id)
            earlier = _live_return(events, await _reruns(s, events))
            if earlier is not None:
                if earlier.child_run_id is None:
                    raise ConflictError(
                        f"run {run_id} is being returned; its rerun is not ready yet"
                    )
                raise ConflictError(
                    f"run {run_id} was already returned; its rerun is {earlier.child_run_id}. "
                    "Return that run to iterate again"
                )
            reference = storage.get(run.docx_reference_key) if run.docx_reference_key else None
            guidance = f"{run.extra_guidance}\nReviewer note: {note.strip()}".strip()
            child = await _create_run(
                db,
                storage,
                cfg,
                prompts,
                RunRequest(
                    project_id=run.project_id,
                    source_ids=await runs.run_source_ids(s, run_id),
                    value_statement=run.value_statement,
                    profile=run.profile,
                    max_iterations=run.max_iterations,
                    extra_guidance=guidance,
                    parent_run_id=run_id,
                ),
                pack_name=run.pack_name,
                pack_hash_=run.pack_hash,
                pack_snapshot=run.pack_snapshot,
                profile=run.profile,
                reference=reference,
                session=s,
            )
            await runs.add_review_event(s, run_id, action.value, note, actor, child)
            await _store_review_state(s, run_id)
    except BaseException:
        # Nothing committed, so the database has nothing to undo. The rerun's copy of the
        # reference document goes with plain file calls: no await, so no CancelledError, can
        # stop it half way (R-M15-3).
        if child is not None:
            with contextlib.suppress(StorageError):
                storage.delete_prefix(f"runs/{child}/")
        raise
    await _defer_run(db, queue, child)
    return child


def _review_state(events: list[ReviewEvent], reruns: Reruns) -> ReviewState | None:
    """The decision the review events amount to, given each rerun's state and error (`reruns`,
    by run id). A live return (its rerun being created, running or completed) wins over any
    accept; otherwise the latest event decides, so an accept after a failed rerun is "accepted",
    and a return whose rerun failed, with nothing after it, is "returned" with the rerun's fate.
    None when nobody reviewed the run."""
    if not events:
        return None
    chosen = _live_return(events, reruns) or events[-1]
    if chosen.action == ReviewAction.ACCEPT.value:
        return ReviewState(decision=ReviewDecision.ACCEPTED, at=chosen.at, actor=chosen.actor)
    rerun = reruns.get(chosen.child_run_id) if chosen.child_run_id else None
    state, error = rerun if rerun is not None and rerun[0] in TERMINAL_STATES else (None, None)
    return ReviewState(
        decision=ReviewDecision.RETURNED,
        at=chosen.at,
        actor=chosen.actor,
        child_run_id=str(chosen.child_run_id) if chosen.child_run_id else None,
        child_state=state,
        child_error=error,
        note=chosen.note,
    )


```

- [ ] **Step 7: Migration 0005**

Create `engine/corelata/store/migrations/versions/0005_review_state_rerun_fate.py`:

```python
"""run.review_state: the rerun's fate (CRL-34)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 10:00:00.000000

From M15 a return is spent only while its rerun is live or completed (R-M15-1), and the stored
decision carries the rerun's terminal state, its error and the return's note (R-M15-2). A return
now commits with its rerun in one transaction (R-M15-3), so a `return` event whose rerun was never
linked can only be left over from an earlier version's interrupted return: it is deleted. Then
every reviewed run's decision is recomputed with `service._review_state`'s rule, written out here
so this revision never imports the service. Nothing in the table's shape changes; the downgrade
keeps the data (the older code ignores the new keys).
"""

import json
from collections.abc import Sequence
from datetime import UTC
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TERMINAL = {"completed", "gate_rejected", "failed", "cancelled"}
FREED_BY = TERMINAL - {"completed"}


def _iso(at: Any) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decision(events: list[Any], reruns: dict[Any, Any]) -> dict[str, Any]:
    """`events`: one run's (action, note, actor, child_run_id, at) rows, oldest first; `reruns`:
    (state, error) by run id."""
    live = next(
        (
            e
            for e in reversed(events)
            if e.action == "return"
            and (e.child_run_id not in reruns or reruns[e.child_run_id][0] not in FREED_BY)
        ),
        None,
    )
    chosen = live or events[-1]
    state: dict[str, Any] = {
        "decision": "accepted" if chosen.action == "accept" else "returned",
        "at": _iso(chosen.at),
        "actor": chosen.actor,
        "child_run_id": None,
        "child_state": None,
        "child_error": None,
        "note": None,
    }
    if chosen.action == "return":
        rerun = reruns.get(chosen.child_run_id)
        ended = rerun is not None and rerun[0] in TERMINAL
        state.update(
            child_run_id=str(chosen.child_run_id),
            child_state=rerun[0] if ended else None,
            child_error=rerun[1] if ended else None,
            note=chosen.note,
        )
    return state


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM review_event WHERE action = 'return' AND child_run_id IS NULL")
    )
    rows = bind.execute(
        sa.text(
            "SELECT run_id, action, note, actor, child_run_id, at FROM review_event "
            "ORDER BY run_id, at, id"
        )
    ).all()
    reruns = {
        r.id: (r.state, r.error)
        for r in bind.execute(
            sa.text(
                "SELECT id, state, error FROM run WHERE id IN "
                "(SELECT child_run_id FROM review_event WHERE child_run_id IS NOT NULL)"
            )
        ).all()
    }
    by_run: dict[Any, list[Any]] = {}
    for row in rows:
        by_run.setdefault(row.run_id, []).append(row)
    bind.execute(
        sa.text(
            "UPDATE run SET review_state = NULL WHERE review_state IS NOT NULL "
            "AND id NOT IN (SELECT run_id FROM review_event)"
        )
    )
    store = sa.text("UPDATE run SET review_state = CAST(:state AS jsonb) WHERE id = :id")
    for run_id, events in by_run.items():
        bind.execute(store, {"id": run_id, "state": json.dumps(_decision(events, reruns))})


def downgrade() -> None:
    pass  # the data stays: revision 0004's code reads the keys it knows and ignores the rest
```

In `engine/corelata/store/migrate.py` replace the first four docstring lines with:

```python
"""Schema migrations (spec §8.3: Alembic). Revision 0001 installs procrastinate's job-queue
schema, revision 0002 the Corelata tables, 0003 the orphan-sweep indexes, 0004
`run.review_state`, 0005 the rerun's fate in it; a procrastinate upgrade needs a new revision that
applies its migration SQL. Copied from Coglossa."""
```

- [ ] **Step 8: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_return.py tests/test_service.py tests/store tests/test_doctor.py tests/test_cli_ops.py --no-cov -q`
Expected: PASS (test_return.py 10, the migration tests 10).

- [ ] **Step 9: Regenerate the schema and check the web still type-checks**

Run: `make schema && git status --short schema web/src/api/schema.d.ts && cd web && pnpm exec tsc --noEmit`
Expected: exactly `M schema/openapi.json`, `M schema/run-progress.schema.json`, `M web/src/api/schema.d.ts`; `tsc` clean (the three fields are optional in the generated type, so the web's existing `ReviewState` literals still compile).

Run: `cd engine && uv run ruff check . && uv run ruff format --check . && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/schema --no-cov -q`
Expected: clean; `test_committed_schema_matches_models` passes.

- [ ] **Step 10: Commit**

```bash
cat > <scratchpad>/m15-task1-commit.txt <<'EOF'
fix: CRL-34 a return is spent only by a live or completed rerun

A rerun that fails, is cancelled or stops at the gate no longer strands the report: it can be
returned or accepted again. The rerun, the return event and the stored decision commit in one
transaction under the run's row lock; migration 0005 records each rerun's fate and drops
returns an earlier version left unlinked.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/schema/progress.py engine/corelata/store/runs.py engine/corelata/service.py engine/corelata/store/migrate.py engine/corelata/store/migrations/versions/0005_review_state_rerun_fate.py engine/tests/test_return.py engine/tests/test_service.py engine/tests/store/test_migrations.py engine/tests/test_doctor.py engine/tests/test_cli_ops.py schema/openapi.json schema/run-progress.schema.json web/src/api/schema.d.ts
git commit -F <scratchpad>/m15-task1-commit.txt
```

---

### Task 2: Every path that ends a rerun records its fate on the parent and announces it (CRL-34, engine and API)

**Files:**
- Modify: `engine/corelata/service.py` (`_mark_run_failed` lines 80-89; `cancel_run` lines 361-374; after `_reruns` from Task 1), `engine/corelata/worker/execute.py` (import line 32; `_begin` lines 126-129; `_fail_run` lines 219-221 and 229-231; `execute_run` line 290), `engine/corelata/worker/sweep.py` (imports line 11; `sweep_orphans` lines 54-55), `api/tests/test_runs.py` (append)
- Create: `engine/tests/worker/test_rerun_end.py`

**Interfaces:**
- Consumes: from Task 1, `service._store_review_state(s, run_id)` and `store.runs.parent_ids(s, run_ids) -> list[uuid.UUID]`; `store.runs.notify_run(s, run_id)` (M14); `tests.worker.conftest.submit`, `drain`; fixtures `services`, `fake_backend`, `run_channel`; API helpers `start_run(api)`, `set_run_state(db, run_id, state)`.
- Produces: `async def service.reruns_ended(s: AsyncSession, run_ids: list[uuid.UUID]) -> None` (call inside the transaction that made the runs terminal, after their writes and `notify_run`); every terminal write path calls it.

- [ ] **Step 1: Failing tests**

Create `engine/tests/worker/test_rerun_end.py`:

```python
"""Every path that ends a rerun records its fate on the parent and announces the parent
(CRL-34, R-M15-2), so an open Review page of the parent sees it."""

import uuid

import pytest
from sqlalchemy import text

from corelata import service
from corelata.llm.types import PermanentBackendError
from corelata.schema import ReviewAction, ReviewState, RunState
from corelata.store import runs
from corelata.worker import execute
from corelata.worker.sweep import ORPHAN_ERROR, sweep_orphans
from tests.worker.conftest import drain, submit


async def _returned(services) -> tuple[uuid.UUID, uuid.UUID]:
    """A completed run, returned once: (parent, rerun). The rerun's job is queued, not run."""
    parent = await submit(services)
    await drain(services)
    child = await service.review_run(
        services.db,
        services.storage,
        services.queue,
        services.cfg,
        services.prompts,
        parent,
        ReviewAction.RETURN,
        note="Say more about the tariffs",
    )
    assert child is not None
    return parent, child


async def _returned_in(services, project: str) -> tuple[uuid.UUID, uuid.UUID]:
    """As `_returned`, in another project, the parent completed without a worker; only the
    rerun's job stays queued."""
    parent = await submit(services, project=project)
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, parent, lock=True)).state = RunState.COMPLETED.value
    child = await service.review_run(
        services.db,
        services.storage,
        services.queue,
        services.cfg,
        services.prompts,
        parent,
        ReviewAction.RETURN,
        note="x",
    )
    services.queue.jobs = [j for j in services.queue.jobs if j.kwargs["run_id"] == str(child)]
    assert child is not None
    return parent, child


async def _review(services, run_id) -> ReviewState:
    review = (await service.run_progress(services.db, run_id)).review
    assert review is not None
    return review


async def test_a_rerun_that_fails_frees_its_parent_and_announces_it(
    services, fake_backend, run_channel
):
    parent, child = await _returned(services)
    assert (await _review(services, parent)).child_state is None  # queued: still live
    await run_channel.received()  # what the return itself announced
    fake_backend.script("gate", PermanentBackendError("down"), PermanentBackendError("down"))
    await drain(services)
    review = await _review(services, parent)
    assert review.child_run_id == str(child) and review.child_state is RunState.FAILED
    assert review.child_error and "down" in review.child_error
    assert review.note == "Say more about the tariffs"
    assert str(parent) in await run_channel.received()  # the Review page's run is announced


async def test_a_completed_rerun_is_recorded_too(services):
    parent, child = await _returned(services)
    await drain(services)
    review = await _review(services, parent)
    assert review.child_state is RunState.COMPLETED and review.child_error is None
    with pytest.raises(service.ConflictError, match=str(child)):  # and it spends the return
        await service.review_run(
            services.db,
            services.storage,
            services.queue,
            services.cfg,
            services.prompts,
            parent,
            ReviewAction.RETURN,
            note="again",
        )


async def test_an_internal_error_on_either_failure_path_frees_the_parent(services, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    parent, _ = await _returned(services)
    monkeypatch.setattr(execute, "run_report", boom)
    await drain(services)
    review = await _review(services, parent)
    assert review.child_state is RunState.FAILED and "boom" in (review.child_error or "")

    other, _ = await _returned_in(services, "q")
    real = runs.add_llm_calls

    async def broken(*args, **kwargs):  # the leftover calls cannot be written
        monkeypatch.setattr(runs, "add_llm_calls", real)
        raise RuntimeError("write failed")

    monkeypatch.setattr(runs, "add_llm_calls", broken)
    await drain(services)
    assert (await _review(services, other)).child_state is RunState.FAILED


async def test_cancelling_a_rerun_frees_the_parent_on_both_paths(services):
    parent, child = await _returned(services)
    assert await service.cancel_run(services.db, child) is RunState.CANCELLED  # still queued
    assert (await _review(services, parent)).child_state is RunState.CANCELLED

    other, flagged = await _returned_in(services, "q")
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, flagged, lock=True)).cancel_requested = True  # still created
    await execute.execute_run(services, flagged)  # the worker ends it at job start
    assert (await _review(services, other)).child_state is RunState.CANCELLED


async def test_a_rerun_the_sweep_fails_frees_the_parent(services, run_channel):
    parent, child = await _returned(services)
    services.queue.jobs.clear()  # the rerun's job never reached the queue
    async with services.db.session() as s, s.begin():
        await s.execute(
            text("UPDATE run SET created_at = now() - interval '10 minutes' WHERE id = :id"),
            {"id": child},
        )
    await run_channel.received()
    failed, _ = await sweep_orphans(services.db, grace_s=120)
    assert failed == [child]
    review = await _review(services, parent)
    assert review.child_state is RunState.FAILED
    assert review.child_error == ORPHAN_ERROR.format(what="run")
    assert sorted(await run_channel.received()) == sorted([str(child), str(parent)])


class _DownQueue:
    async def defer(self, task: str, *, lock: str | None = None, **kwargs: str) -> None:
        raise ConnectionRefusedError("connection refused")


async def test_a_rerun_the_queue_refused_frees_the_parent(services):
    parent = await submit(services)
    await drain(services)
    with pytest.raises(ConnectionRefusedError):
        await service.review_run(
            services.db,
            services.storage,
            _DownQueue(),
            services.cfg,
            services.prompts,
            parent,
            ReviewAction.RETURN,
            note="x",
        )
    review = await _review(services, parent)
    assert review.child_state is RunState.FAILED
    assert review.child_error == "could not queue the run: connection refused"


async def test_a_run_without_a_parent_announces_only_itself(services, run_channel):
    run_id = await submit(services)
    await drain(services)
    assert set(await run_channel.received()) == {str(run_id)}
```

Append to `api/tests/test_runs.py`:

```python


async def test_a_run_whose_rerun_was_cancelled_can_be_returned_again(api):
    run = await start_run(api)
    await set_run_state(api.db, run["run_id"], "completed")
    review = f"/api/runs/{run['run_id']}/review"
    first = (await api.client.post(review, json={"action": "return", "note": "Tighten it"})).json()
    cancelled = await api.client.post(f"/api/runs/{first['child']['run_id']}/cancel")
    assert cancelled.json()["state"] == "cancelled"
    shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
    assert shown == {
        "decision": "returned",
        "at": shown["at"],
        "actor": None,
        "child_run_id": first["child"]["run_id"],
        "child_state": "cancelled",
        "child_error": None,
        "note": "Tighten it",
    }
    again = await api.client.post(review, json={"action": "return", "note": "Tighten it more"})
    assert again.status_code == 200, again.text
    second = again.json()["child"]
    assert second["run_id"] != first["child"]["run_id"]
    shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
    assert shown["child_run_id"] == second["run_id"] and shown["child_state"] is None
    assert shown["note"] == "Tighten it more"
    third = await api.client.post(review, json={"action": "return", "note": "Once more"})
    assert third.status_code == 409 and second["run_id"] in third.json()["detail"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_rerun_end.py --no-cov -q`
Expected: FAIL: every test but the last asserts on `child_state` and finds `None` (nothing writes the parent when a rerun ends); `test_a_rerun_the_sweep_fails_frees_the_parent` also sees only the child announced.

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_runs.py --no-cov -q`
Expected: FAIL on `"child_state": "cancelled"` (the stored decision still says `null`).

- [ ] **Step 3: `reruns_ended` and the service's two paths**

In `engine/corelata/service.py`, insert after `_reruns` (Task 1):

```python
async def reruns_ended(s: AsyncSession, run_ids: list[uuid.UUID]) -> None:
    """The runs in `run_ids` reached a terminal state in this transaction: recompute each one's
    parent's stored decision and announce the parent (R-M15-2), so an open Review page sees the
    rerun's fate. Call it after the runs' own writes, with their row locks held; the parents'
    locks come second, in sorted order, and no path holds a parent's lock while it waits for a
    child's (R-M15-10). A run without a parent costs one read."""
    for parent in await runs.parent_ids(s, run_ids):
        await _store_review_state(s, parent)
        await runs.notify_run(s, parent)
```

In `_mark_run_failed`, after `await runs.notify_run(s, run_id)` add `await reruns_ended(s, [run_id])`. In `cancel_run` replace

```python
        await runs.notify_run(s, run_id)  # the flag shows on the progress page at once
        return RunState(run.state)
```

with

```python
        await runs.notify_run(s, run_id)  # the flag shows on the progress page at once
        if state is RunState.CREATED:
            await reruns_ended(s, [run_id])
        return RunState(run.state)
```

(`reruns_ended` is defined later in the module than `_mark_run_failed`; both are called at run time, so the order does not matter.)

- [ ] **Step 4: The worker's and the sweep's paths**

In `engine/corelata/worker/execute.py` change the import to `from corelata.service import TASK_DISCOVER, TASK_RUN, JobQueue, reruns_ended`, then:

- `_begin`, the cancel-at-start branch: after `await runs.notify_run(s, run_id)` and before `return None`, add `await reruns_ended(s, [run_id])`.
- `_fail_run`, both transactions: after each `await runs.notify_run(s, run_id)` add `await reruns_ended(s, [run_id])` (two places).
- `execute_run`'s outcome transaction: after the `await runs.notify_run(s, run_id)` that follows the export loop add `await reruns_ended(s, [run_id])  # every outcome is terminal (R-M15-2)`.

In `engine/corelata/worker/sweep.py` add `from corelata.service import reruns_ended` after the `corelata.schema` import, and replace

```python
            for run_id in run_ids:
                await runs.notify_run(s, run_id)
```

with

```python
            for run_id in run_ids:
                await runs.notify_run(s, run_id)
            await reruns_ended(s, run_ids)  # a swept rerun frees its parent's return (R-M15-2)
```

- [ ] **Step 5: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker tests/test_service.py tests/test_return.py --no-cov -q`
Expected: PASS (`tests/worker/test_notify.py` unchanged: a run without a parent still makes 14 announcements).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_runs.py tests/test_integration.py --no-cov -q`
Expected: PASS.

Run: `make test-engine && make test-api`
Expected: engine 879 passed (861, plus 11 from Task 1 and 7 here; Task 3 brings it to 884), api 165 passed, both above the 95% gate.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m15-task2-commit.txt <<'EOF'
fix: CRL-34 a rerun's ending is recorded on its parent and announced

The queue failure, the cancel, the worker's cancel at job start, both failure paths and the
outcome transaction, and the orphan sweep recompute the parent's review state in their own
transaction and announce the parent.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/service.py engine/corelata/worker/execute.py engine/corelata/worker/sweep.py engine/tests/worker/test_rerun_end.py api/tests/test_runs.py
git commit -F <scratchpad>/m15-task2-commit.txt
```

---

### Task 3: Doctor's probes get a run's repair turn (CRL-35)

**Files:**
- Modify: `engine/corelata/llm/agent.py` (after `_repair_message` line 63; `AgentRunner.run` lines 169-174; `_parse` line 275), `engine/corelata/doctor.py` (import line 18; `_probe` lines 448-514), `engine/corelata/testing/fake_openai.py` (`_Server` line 21; `_reply` after line 72; `__init__` lines 92-100), `engine/corelata/cli.py` (`fake-openai` parser line 174; `_fake_openai` line 689), `engine/tests/test_doctor.py` (imports; three message assertions; append), `engine/tests/test_cli.py` (`test_fake_openai_command_binds_and_stops`)

**Interfaces:**
- Consumes: `llm.agent.build_request`, `request_messages`, `extract_json`, `_repair_message`, `_describe` (existing); `doctor._fixes(key, mode) -> (rejected, wrong_json)`, `doctor._cut`, `doctor._check`.
- Produces: `llm.agent.repair_messages(messages: list[ChatMessage], content: str, errors: list[str]) -> list[ChatMessage]`; `llm.agent.rejection_errors(error: ValidationError) -> list[str]`; `doctor._rejected(parse, content) -> ValidationError | None`; `doctor._send(label, key, model, backend, output_type, schema, messages, needs) -> str | DoctorCheck`; `FakeOpenAIServer(..., needs_repair: bool = False)`; CLI flag `corelata fake-openai --needs-repair`.

- [ ] **Step 1: Failing tests**

In `engine/tests/test_doctor.py` add `ChatMessage,` to the `from corelata.llm.types import (...)` list (before `ChatResponse,`). Update the three messages a twice-wrong model now gets:

- in `test_json_that_is_not_a_gate_verdict_fails_the_probe`, the gate line's `endswith(...)` text becomes `"the server did not return the requested JSON (json_schema), even after one repair " "turn: not a GateVerdict: supported: Field required"` and the auditor line's `==` text becomes `"the server did not return the requested JSON (json_schema), even after one repair " "turn: not an AuditByRule: findings: Field required"`;
- in `test_a_none_model_that_returns_the_wrong_json_is_told_to_pick_another`, the auditor text becomes `"the server did not return the requested JSON (none), even after one repair turn: " "not an AuditByRule: findings: Field required"`.

Append:

```python


# ---------------------------------------------------------------- the repair turn (R-M15-5)


class RepairOnce(FakeBackend):
    """A model whose first structured reply is `first` and whose repaired reply is `repaired`
    (the synthetic answer by default); the test completion is answered as usual."""

    def __init__(self, first: str = '{"ok": true}', repaired: str | BaseException | None = None):
        super().__init__()
        self.first, self.repaired = first, repaired

    async def chat(self, request):
        if request.schema_name == "Ping":
            return await super().chat(request)
        self.requests.append(request)
        if not any(m.role == "assistant" for m in request.messages):
            return ChatResponse(content=self.first)
        if isinstance(self.repaired, BaseException):
            raise self.repaired
        if self.repaired is not None:
            return ChatResponse(content=self.repaired)
        payload = parse_input([m.model_dump() for m in request.messages])
        return ChatResponse(content=json.dumps(synthetic_response(payload)))


def _json_object_config(tmp_path):
    model = {"backend": "local", "context_window": 4096, "structured_output": "json_object"}
    return _config(tmp_path, "http://unused.test/v1", models={"fake-model": model})


async def test_a_model_that_needs_one_repair_turn_warns_and_doctor_still_passes(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = RepairOnce()
    report = await run_doctor(
        _json_object_config(tmp_path), backends_factory=lambda cfg: {"local": backend}
    )
    checks = _by_name(report)
    check = checks["model fake-model"]
    assert check.status is CheckStatus.WARN and report.ok  # WARN never fails doctor
    assert check.message == (
        "test completion succeeded; json_object output works after one repair turn (GateVerdict)"
    )
    assert check.fix == (
        "nothing to change for a run, which repairs the reply the same way; every structured "
        "call on models.fake-model may cost a second request"
    )
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.WARN
    assert audit.message == "json_object output works after one repair turn (AuditByRule, 17 rules)"
    sent = [r.schema_name for r in backend.requests]
    assert sent == ["Ping", "GateVerdict", "GateVerdict", "AuditByRule", "AuditByRule"]


async def test_the_probes_repair_turn_is_the_one_a_run_sends(tmp_path, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _json_object_config(tmp_path)
    cfg, _ = load_config(path)
    run_backend = RepairOnce()
    runner = AgentRunner(cfg, {"local": run_backend}, PromptLibrary(), CallLog())
    await runner.run(
        role="gate",
        model_key="fake-model",
        prompt_id="gate",
        prompt_vars={"mode": "verify", "tone": ""},
        payload=PROBE_PAYLOAD,
        output_type=GateVerdict,
    )
    probe_backend = RepairOnce()
    await run_doctor(path, backends_factory=lambda c: {"local": probe_backend})
    run_first, run_repair = run_backend.requests
    probe_first, probe_repair = [
        r for r in probe_backend.requests if r.schema_name == "GateVerdict"
    ]
    # the run's prompt is the gate template, the probe's its own; the repair turn is the same
    assert run_repair.messages[2:] == probe_repair.messages[2:]
    assert probe_repair.messages[:2] == probe_first.messages
    assert probe_repair.messages[2] == ChatMessage(role="assistant", content='{"ok": true}')
    assert probe_repair.messages[3].content.startswith("Your previous response was rejected.")
    assert probe_repair.model_copy(update={"messages": []}) == probe_first.model_copy(
        update={"messages": []}
    )  # the same schema, mode and limits: only the turn differs


async def test_a_repaired_reply_that_is_still_wrong_fails_and_cites_its_own_error(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = RepairOnce(repaired='{"supported": true}')
    report = await run_doctor(
        _json_object_config(tmp_path), backends_factory=lambda cfg: {"local": backend}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL and not report.ok
    assert check.message.endswith(
        "the server did not return the requested JSON (json_object), even after one repair "
        "turn: not a GateVerdict: substance: Field required"  # the repaired reply's first error
    )
    assert check.fix == (
        "set models.fake-model.structured_output to none, or pick a model that follows a "
        "JSON schema"
    )


async def test_a_backend_error_on_the_repair_turn_fails_with_its_cause(tmp_path, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = RepairOnce(repaired=TransientBackendError("local: timed out"))
    report = await run_doctor(
        _json_object_config(tmp_path), backends_factory=lambda cfg: {"local": backend}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL
    assert check.message == (
        "test completion succeeded; json_object request failed: local: timed out"
    )
    assert check.fix == "check the server logs; on a timeout raise backends.local.timeout_s"
    assert [r.schema_name for r in backend.requests].count("GateVerdict") == 2  # no third try


async def test_the_fake_server_can_play_a_model_that_needs_a_repair_turn(tmp_path, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    with FakeOpenAIServer(needs_repair=True) as srv:
        report = await run_doctor(_config(tmp_path, srv.base_url))
        checks = _by_name(report)
        assert report.ok
        assert checks["model fake-model"].message == (
            "test completion succeeded; json_schema output works after one repair turn "
            "(GateVerdict)"
        )
        assert checks["model fake-model auditor schema"].status is CheckStatus.WARN
        firsts = [r for r in srv.requests if len(r["messages"]) == 2]
        repairs = [r for r in srv.requests if len(r["messages"]) == 4]
        assert len(firsts) == 3 and len(repairs) == 2  # the ping needs no repair
```

In `engine/tests/test_cli.py`, at the end of `test_fake_openai_command_binds_and_stops`, add:

```python
    assert main(["fake-openai", "--port", "0", "--needs-repair"]) == 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_doctor.py tests/test_cli.py --no-cov -q`
Expected: FAIL: the repair tests see FAIL where they expect WARN (one request per probe), the three updated messages lack ", even after one repair turn", `FakeOpenAIServer(needs_repair=True)` is a `TypeError`, and `--needs-repair` is an unrecognized argument (exit code 2).

- [ ] **Step 3: One repair builder for runs and probes**

In `engine/corelata/llm/agent.py`, insert after `_repair_message`:

```python
def repair_messages(
    messages: list[ChatMessage], content: str, errors: list[str]
) -> list[ChatMessage]:
    """The one repair turn of a structured call: the first turn's messages, the rejected reply as
    the model sent it, and the rejection with every error. `AgentRunner.run` and `corelata
    doctor`'s probes both build it here, so a probe repairs exactly as a run does (R-M15-5)."""
    return [
        *messages,
        ChatMessage(role="assistant", content=content),
        ChatMessage(role="user", content=_repair_message(errors)),
    ]


def rejection_errors(error: ValidationError) -> list[str]:
    """A reply's validation errors as the repair turn lists them."""
    return [_describe(err) for err in error.errors()]
```

In `AgentRunner.run` replace

```python
            if errors:
                messages = [
                    *messages,
                    ChatMessage(role="assistant", content=content),
                    ChatMessage(role="user", content=_repair_message(errors)),
                ]
```

with

```python
            if errors:
                messages = repair_messages(messages, content, errors)
```

and in `_parse` replace `return None, [_describe(err) for err in e.errors()]` with `return None, rejection_errors(e)`.

- [ ] **Step 4: The probe repairs once**

In `engine/corelata/doctor.py` replace the import line `from corelata.llm.agent import build_request, extract_json, request_messages` with:

```python
from corelata.llm.agent import (
    build_request,
    extract_json,
    rejection_errors,
    repair_messages,
    request_messages,
)
```

Replace `_probe` (lines 448-514) with:

```python
async def _probe(
    label: str,
    key: str,
    model: ModelConfig,
    backend: Backend,
    output_type: type[BaseModel],
    system: str,
    payload: dict[str, Any],
    parse: Callable[[str], object],
    *,
    works: str,
    needs: str,
) -> DoctorCheck:
    """One structured call exactly as a run makes it: the stages' request builder, so the backend
    applies `strict_json_schema` as in a run, no `max_tokens` of its own (the model's cap if it
    has one, else none), and the one repair turn a run gives a rejected reply, built by the same
    code (R-M15-5). Passes when `parse` accepts the first reply, warns when it accepts the
    repaired one, fails when it accepts neither."""
    name = output_type.__name__
    article = "an" if name[0] in "AEIOU" else "a"
    mode = model.structured_output.value
    schema = output_type.model_json_schema()
    messages = request_messages(system, payload, model, schema)
    first = await _send(label, key, model, backend, output_type, schema, messages, needs)
    if isinstance(first, DoctorCheck):
        return first
    error = _rejected(parse, first)
    if error is None:
        return _check(label, CheckStatus.PASS, f"{mode} output works ({works})")
    # R-M15-5: a run repairs a rejected reply once (llm/agent.py); so does the probe
    repaired = repair_messages(messages, first, rejection_errors(error))
    second = await _send(label, key, model, backend, output_type, schema, repaired, needs)
    if isinstance(second, DoctorCheck):
        return second
    error = _rejected(parse, second)
    if error is None:
        return _check(
            label,
            CheckStatus.WARN,
            f"{mode} output works after one repair turn ({works})",
            f"nothing to change for a run, which repairs the reply the same way; every structured "
            f"call on models.{key} may cost a second request",
        )
    first_error = error.errors()[0]
    where = ".".join(str(p) for p in first_error["loc"]) or "<root>"
    return _check(
        label,
        CheckStatus.FAIL,
        f"the server did not return the requested JSON ({mode}), even after one repair turn: "
        + _cut(f"not {article} {name}: {where}: {first_error['msg']}"),
        _fixes(key, model.structured_output)[1],
    )


def _rejected(parse: Callable[[str], object], content: str) -> ValidationError | None:
    try:
        parse(extract_json(content))
    except ValidationError as e:
        return e
    return None


async def _send(
    label: str,
    key: str,
    model: ModelConfig,
    backend: Backend,
    output_type: type[BaseModel],
    schema: dict[str, Any],
    messages: list[ChatMessage],
    needs: str,
) -> str | DoctorCheck:
    """The reply's text, or the failed check a run would also fail on: a reply cut at the output
    limit, or a backend error (no repair turn follows either, as in a run)."""
    name = output_type.__name__
    mode = model.structured_output.value
    request = build_request(key, model, output_type, schema, messages)
    try:
        return (await backend.chat(request)).content
    except OutputTruncatedError:
        if request.max_tokens is None:  # no cap of ours: the server's own default cut the reply
            return _check(
                label,
                CheckStatus.FAIL,
                f"the {name} reply was cut by the server's default output limit",
                f"set models.{key}.max_output_tokens above the server's default: {needs}",
            )
        return _check(
            label,
            CheckStatus.FAIL,
            f"the {name} reply was cut at max_tokens={request.max_tokens}",
            f"raise models.{key}.max_output_tokens or unset it: {needs}",
        )
    except BackendError as e:
        # R-M13-11: the advice follows the cause, not only a rejected schema
        failed = f"{mode} request failed: {_cut(str(e))}"
        if isinstance(e, ContextOverflowError):
            fix = (
                "the request exceeds the model's context: raise the server's context length, "
                f"or set models.{key}.context_window to the server's real length; json_schema "
                "sends the schema out of band, json_object and none spell it into the prompt"
            )
        elif isinstance(e, TransientBackendError):
            fix = f"check the server logs; on a timeout raise backends.{model.backend}.timeout_s"
        else:
            fix = _fixes(key, model.structured_output)[0]
        return _check(label, CheckStatus.FAIL, failed, fix)
```

(`ChatMessage` is already imported from `corelata.llm.types`.)

- [ ] **Step 5: A fake model that needs the repair**

In `engine/corelata/testing/fake_openai.py`: add `needs_repair: bool` to `_Server`'s annotations (after `delay_s: float`); in `_Handler._reply`, after the `try/except` that builds `content` and before `reason = ...`, add:

```python
        first_turn = not any(m.get("role") == "assistant" for m in body["messages"])
        if self.server.needs_repair and first_turn and payload.get("task") != "ping":
            # R-M15-5 rehearsal: a model whose first reply never parses and whose repaired one
            # does; `{}` lacks a required field of every structured output
            content = "{}"
```

add the parameter `needs_repair: bool = False,` after `keep_requests: bool = True,` in `FakeOpenAIServer.__init__`, and `self._server.needs_repair = needs_repair` after `self._server.delay_s = delay_s`.

In `engine/corelata/cli.py`, after `fake.add_argument("--model", action="append", dest="models")` add:

```python
    fake.add_argument(
        "--needs-repair",
        action="store_true",
        help="answer the first turn of every structured call with '{}', so each call needs its "
        "repair turn (a model doctor warns about)",
    )
```

and in `_fake_openai` replace `server = FakeOpenAIServer(args.host, args.port, models, keep_requests=False)` with:

```python
    server = FakeOpenAIServer(
        args.host, args.port, models, keep_requests=False, needs_repair=args.needs_repair
    )
```

- [ ] **Step 6: Run the tests**

Run: `cd engine && uv run ruff check . && uv run ruff format --check . && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_doctor.py tests/test_cli.py tests/llm tests/testing tests/stages --no-cov -q`
Expected: clean; PASS (test_doctor.py 48).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_system.py --no-cov -q`
Expected: PASS (the fake server needs no repair, so the API's doctor stays all PASS).

Run: `make test-engine`
Expected: 884 passed, coverage above 95%.

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m15-task3-commit.txt <<'EOF'
fix: CRL-35 doctor's probes get the repair turn a run gets

A rejected probe reply gets the one repair turn AgentRunner gives a run, built by the same
code; a model that needs it is a warning, not a failure. corelata fake-openai --needs-repair
plays such a model.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/llm/agent.py engine/corelata/doctor.py engine/corelata/testing/fake_openai.py engine/corelata/cli.py engine/tests/test_doctor.py engine/tests/test_cli.py
git commit -F <scratchpad>/m15-task3-commit.txt
```

---

### Task 4: The Review screen offers Return and Accept again after a failed rerun (CRL-34, web)

**Files:**
- Modify: `web/src/api/runs.ts` (imports line 5; `POLL_MS` and `pollInterval`, lines 11-23), `web/src/pages/review/ReviewActions.tsx` (import line 4; lines 15-16; the Return button's `onClick`, lines 43-46; the decision block, lines 60-62; append), `web/src/api/runs.test.tsx` (imports; after the `pollInterval` describe), `web/src/pages/review/ReviewActions.test.tsx` (imports; append)

**Interfaces:**
- Consumes: the generated `ReviewState` with `child_state?: RunState | null`, `child_error?: string | null`, `note?: string | null` (Task 1); `runRefetchInterval(queryClient, runId)` from `web/src/test/poll.ts`; `renderApp` returning `{ router, user, queryClient }`.
- Produces: `rerunPending(review: ReviewState | null | undefined): boolean`, `rerunFreed(review: ReviewState | null | undefined): boolean` in `web/src/api/runs.ts`; `pollInterval` keeps its signature.

- [ ] **Step 1: Failing tests**

In `web/src/api/runs.test.tsx` add `import type { RunProgress } from "./types";` after the `./projects` import, and after the `describe("pollInterval", ...)` block:

```tsx
it("keeps reading a finished run while the rerun its return created has not ended (R-M15-2)", () => {
  const at = "2026-10-18T10:00:00Z";
  const pending = { decision: "returned" as const, at, child_run_id: "c", note: "x" };
  const done = (review: RunProgress["review"]) =>
    pollInterval(runProgress({ state: "completed", review }), false, undefined);
  expect(done(pending)).toBe(POLL_MS);
  expect(done({ ...pending, child_run_id: null })).toBe(POLL_MS); // being created
  expect(done({ ...pending, child_state: "failed" })).toBe(false);
  expect(done({ ...pending, child_state: "completed" })).toBe(false);
  expect(done({ decision: "accepted", at })).toBe(false);
  expect(done(null)).toBe(false);
});
```

In `web/src/pages/review/ReviewActions.test.tsx` replace the first three import lines with:

```tsx
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { POLL_MS } from "../../api/runs";
import type { ReviewState } from "../../api/types";
import { reportHtml, reportJson, RUN_ID, runProgress } from "../../test/fixtures";
import { runRefetchInterval } from "../../test/poll";
```

and append:

```tsx

const RERUN = "77777777-7777-7777-7777-777777777777";

function returned(overrides: Partial<ReviewState> = {}): ReviewState {
  return {
    decision: "returned",
    at: "2026-10-18T10:00:00Z",
    actor: "ana",
    child_run_id: RERUN,
    child_state: null,
    child_error: null,
    note: "Add the 2027 date",
    ...overrides,
  };
}

it.each([
  [
    { child_state: "failed" as const, child_error: "could not queue the run: connection refused" },
    "The rerun failed: could not queue the run: connection refused. Return the report again or accept it.",
  ],
  [
    { child_state: "failed" as const },
    "The rerun failed: no reason was recorded. Return the report again or accept it.",
  ],
  [
    { child_state: "cancelled" as const },
    "The rerun was cancelled; return the report again or accept it.",
  ],
  [
    { child_state: "gate_rejected" as const },
    "The rerun stopped at the gate (value not supported); return the report again or accept it.",
  ],
])(
  "a return whose rerun ended without a report offers both actions again (%o)",
  async (fate, says) => {
    serveCompleted({ review: returned(fate) });
    renderApp(`/runs/${RUN_ID}/review`);
    expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
      "Returned",
    );
    expect(screen.getByRole("note", { name: "Rerun outcome" })).toHaveTextContent(says);
    expect(screen.getByRole("link", { name: "Open the rerun" })).toHaveAttribute(
      "href",
      `/runs/${RERUN}`,
    );
    expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Return with note" })).toBeEnabled();
  },
);

it("a return whose rerun is live or completed keeps both actions off and says nothing more", async () => {
  for (const child_state of [null, "drafting" as const, "completed" as const]) {
    serveCompleted({ review: returned({ child_state }) });
    const { queryClient } = renderApp(`/runs/${RUN_ID}/review`);
    await screen.findByRole("status", { name: "Review decision" });
    expect(screen.queryByRole("note", { name: "Rerun outcome" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
    queryClient.clear();
    cleanup();
  }
});

it("returns again after a failed rerun, offering the previous note (R-M15-4)", async () => {
  serveCompleted({ review: returned({ child_state: "failed", child_error: "model down" }) });
  const second = runProgress({
    run_id: "88888888-8888-4888-8888-888888888888",
    parent_run_id: RUN_ID,
  });
  let posted: unknown;
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ action: "return", child: second });
    }),
    http.get(`*/api/runs/${second.run_id}`, () => HttpResponse.json(second)),
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note" }));
  const note = screen.getByRole("textbox", { name: "Note for the writer" });
  expect(note).toHaveValue("Add the 2027 date");
  await user.type(note, " and the tariff");
  await user.click(screen.getByRole("button", { name: "Return" }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${second.run_id}`));
  expect(posted).toEqual({ action: "return", note: "Add the 2027 date and the tariff" });
});

it("an open Review page keeps reading the run while its rerun runs, and shows its failure", async () => {
  let review = returned();
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean", iteration: 1, review })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
  );
  const { queryClient } = renderApp(`/runs/${RUN_ID}/review`);
  await screen.findByRole("status", { name: "Review decision" });
  expect(runRefetchInterval(queryClient, RUN_ID)).toBe(POLL_MS); // a finished run, still read
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  review = returned({ child_state: "failed", child_error: "model down" });
  await act(() => queryClient.refetchQueries({ queryKey: ["runs", RUN_ID] }));
  expect(await screen.findByRole("note", { name: "Rerun outcome" })).toHaveTextContent(
    "The rerun failed: model down.",
  );
  expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
  expect(runRefetchInterval(queryClient, RUN_ID)).toBe(false); // the rerun ended: no more reads
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/api/runs.test.tsx src/pages/review/ReviewActions.test.tsx`
Expected: FAIL: the poll test gets `false` for a pending rerun, the it.each cases find no "Rerun outcome" note and disabled buttons, the note box is empty, the open-page test reads `false` as the first interval.

- [ ] **Step 3: Read a finished run while its rerun runs**

In `web/src/api/runs.ts` replace the `import type` line with:

```ts
import type {
  CreateRun,
  ReviewAction,
  ReviewResult,
  ReviewState,
  RunProgress,
  RunState,
} from "./types";
```

and replace `pollInterval` and its comment (keep `export const POLL_MS = 3000;`) with:

```ts
/** A rerun that ended in one of these spent nothing: the run can be returned or accepted again
 * (R-M15-1). The server decides by the same states. */
const FREED_BY: ReadonlySet<RunState> = new Set(["gate_rejected", "failed", "cancelled"]);

/** The stored decision is a return whose rerun has not ended yet, so it will change when the
 * rerun ends (R-M15-2). */
export function rerunPending(review: ReviewState | null | undefined): boolean {
  return review?.decision === "returned" && !review.child_state;
}

/** The stored decision is a return whose rerun ended without a report (R-M15-4). */
export function rerunFreed(review: ReviewState | null | undefined): boolean {
  return (
    review?.decision === "returned" && !!review.child_state && FREED_BY.has(review.child_state)
  );
}

/** Poll while the run is live, or its rerun is (a finished run's stream has ended), and no event
 * stream is delivering updates; never after a 404. */
export function pollInterval(
  progress: RunProgress | undefined,
  live: boolean,
  error: unknown,
): number | false {
  if (error instanceof ApiError && error.status === 404) return false; // the run is gone
  if (live) return false;
  if (progress === undefined) return error ? POLL_MS : false;
  return isTerminal(progress.state) && !rerunPending(progress.review) ? false : POLL_MS;
}
```

- [ ] **Step 4: Say what happened and offer both actions**

In `web/src/pages/review/ReviewActions.tsx`:

- the import becomes `import { rerunFreed, useReview } from "../../api/runs";`
- replace `const decided = review !== null;` with

```tsx
  const freed = rerunFreed(review); // R-M15-4: Return and Accept are offered again
  const decided = review !== null && !freed;
```

- the "Return with note" button's `onClick` becomes

```tsx
        onClick={() => {
          send.reset();
          if (freed && !note) setNote(review?.note ?? "");
          setOpen(true);
        }}
```

- before `{review.child_run_id ? (` insert

```tsx
          {freed ? (
            <span role="note" aria-label="Rerun outcome" dir="auto">
              {rerunOutcome(review)}
            </span>
          ) : null}
```

- append to the file:

```tsx

/** Why a returned run can be returned again (R-M15-4). */
function rerunOutcome(review: ReviewState): string {
  switch (review.child_state) {
    case "cancelled":
      return "The rerun was cancelled; return the report again or accept it.";
    case "gate_rejected":
      return "The rerun stopped at the gate (value not supported); return the report again or accept it.";
    default:
      return `The rerun failed: ${review.child_error ?? "no reason was recorded"}. Return the report again or accept it.`;
  }
}
```

- [ ] **Step 5: Run the tests**

Run: `cd web && pnpm exec prettier --write src/api/runs.ts src/api/runs.test.tsx src/pages/review/ReviewActions.tsx src/pages/review/ReviewActions.test.tsx && pnpm lint && pnpm test`
Expected: lint clean; 176 tests pass; every coverage threshold at or above 95%.

Run: `make e2e`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m15-task4-commit.txt <<'EOF'
feat: CRL-34 the Review screen offers Return and Accept again after a failed rerun

The page keeps reading a returned run until its rerun ends, says why the rerun failed or was
cancelled, and offers the previous note again.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add web/src/api/runs.ts web/src/api/runs.test.tsx web/src/pages/review/ReviewActions.tsx web/src/pages/review/ReviewActions.test.tsx
git commit -F <scratchpad>/m15-task4-commit.txt
```

---

### Task 5: `restore.sh` shows psql's message; `check-bundle.sh` ignores bytecode (CRL-36)

**Files:**
- Modify: `deploy/restore.sh` (lines 31-36), `deploy/tests/test-restore.sh` (stub line 15; before the `STUB_FILES_RC=3` case, line 92), `deploy/tests/check-bundle.sh` (lines 45-46)

**Interfaces:**
- Consumes: the stub `docker` in `test-restore.sh` (`DOCKER_LOG`, `STUB_SCHEMA_RC`, `STUB_SCHEMAS`).
- Produces: the stub's new `STUB_SCHEMA_STDERR` (a line it writes to stderr for the schema query); `restore.sh`'s output `error: could not list the database's schemas; is the database up (docker compose ps)?` followed by `psql said:` and psql's lines indented two spaces.

- [ ] **Step 1: Failing tests**

In `deploy/tests/test-restore.sh` replace the stub's schema line

```bash
  *"pg_namespace"*) [ -z "${STUB_SCHEMA_RC:-}" ] || exit "$STUB_SCHEMA_RC"; printf '%s\n' ${STUB_SCHEMAS:-} ;;
```

with

```bash
  *"pg_namespace"*)
    [ -z "${STUB_SCHEMA_STDERR:-}" ] || echo "$STUB_SCHEMA_STDERR" >&2
    [ -z "${STUB_SCHEMA_RC:-}" ] || exit "$STUB_SCHEMA_RC"
    printf '%s\n' ${STUB_SCHEMAS:-} ;;
```

and insert before the line `if STUB_FILES_RC=3 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a clear failure was ignored"; fi`:

```bash
refused='psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: Connection refused'
if STUB_SCHEMA_RC=2 STUB_SCHEMA_STDERR="$refused" restore "$work/db.dump" "$work/files.tar.gz"; then fail "a refused connection was ignored"; fi
grep -q "^error: could not list the database's schemas" "$work/out" || fail "refused: $(cat "$work/out")"
grep -q "^psql said:$" "$work/out" || fail "refused: psql's message has no heading: $(cat "$work/out")"
grep -qF "  $refused" "$work/out" || fail "refused: psql's message is missing: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "refused: services were stopped"
echo "ok - a refused connection shows psql's own message"

if STUB_SCHEMA_RC=1 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a silent schema query failure was ignored"; fi
! grep -q "^psql said:" "$work/out" || fail "silent: an empty psql message got a heading: $(cat "$work/out")"
echo "ok - a schema query that fails silently prints no empty heading"

STUB_SCHEMA_STDERR='WARN[0000] The "X" variable is not set. Defaulting to a blank string.' \
  restore "$work/db.dump" "$work/files.tar.gz" || fail "a warning on stderr refused the restore: $(cat "$work/out")"
echo "ok - a warning on stderr is not read as a schema name"

```

- [ ] **Step 2: Run it to see it fail**

Run: `deploy/tests/test-restore.sh`
Expected: `FAIL: refused: psql's message has no heading: error: could not list the database's schemas; is the database up (docker compose ps)?` (today's `2>/dev/null` drops psql's line).

- [ ] **Step 3: Keep psql's stderr**

In `deploy/restore.sh` replace lines 31-36 (the comment and the `foreign=$(...)` command with its `|| die`) with:

```bash
# restore.sh empties and refills `public` only. Anything else in the database (an extension's
# schema, a reporting schema someone added) would be left out of step with the restored data,
# so it is refused here, before anything is stopped. psql's stderr goes to a file of its own, so
# a warning from docker compose can never be read as a schema name, and a failure shows why.
psql_err=$(mktemp)
if ! foreign=$(docker compose exec -T postgres psql -X -q -t -A -U corelata -d corelata -c \
  "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema') AND left(nspname, 3) <> 'pg_' ORDER BY 1" 2>"$psql_err" | tr '\n' ' ' | sed 's/ *$//'); then
  echo "error: could not list the database's schemas; is the database up (docker compose ps)?" >&2
  if [ -s "$psql_err" ]; then
    echo "psql said:" >&2
    sed 's/^/  /' "$psql_err" >&2
  fi
  rm -f "$psql_err"
  exit 1
fi
rm -f "$psql_err"
```

(The next line, `[ -z "$foreign" ] || die "the database holds schemas ..."`, stays.)

- [ ] **Step 4: Ignore bytecode in the pack comparison**

In `deploy/tests/check-bundle.sh` replace

```bash
diff -r "$b/config/packs.example/icd203-base" "$here/../../engine/corelata/standards/packs/icd203-base" >/dev/null \
  || fail "config/packs.example/icd203-base differs from the engine's built-in pack"
```

with

```bash
# bytecode a local test run left next to the engine's pack is not part of the pack
diff -r -x __pycache__ -x '*.pyc' "$b/config/packs.example/icd203-base" \
  "$here/../../engine/corelata/standards/packs/icd203-base" >/dev/null \
  || fail "config/packs.example/icd203-base differs from the engine's built-in pack"
```

- [ ] **Step 5: Run the checks**

Run: `deploy/tests/test-restore.sh`
Expected: 16 `ok -` lines, then `restore.sh: all tests passed`.

Run (the two flags on BSD and GNU diff; a scratch tree, nothing in the repo):

```bash
T=<scratchpad>/m15-difftest
mkdir -p "$T/a/rules" "$T/b/rules/__pycache__"
echo x > "$T/a/rules/r.yaml"; echo x > "$T/b/rules/r.yaml"
echo junk > "$T/b/rules/__pycache__/m.cpython-312.pyc"; echo junk > "$T/b/stray.pyc"
diff -r -x __pycache__ -x '*.pyc' "$T/a" "$T/b" && echo SAME
docker run --rm -v "$T:/t" alpine:3.20 sh -c "apk add -q diffutils >/dev/null 2>&1; diff -r -x __pycache__ -x '*.pyc' /t/a /t/b && echo GNU_SAME"
rm -rf "$T"
```

Expected: `SAME`, then `GNU_SAME`.

Run: `make deploy-check`
Expected: shellcheck clean on every script, `test-install.sh` and `test-restore.sh` pass, `check_compose.py` passes.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m15-task5-commit.txt <<'EOF'
fix: CRL-36 restore.sh shows psql's message; check-bundle.sh ignores bytecode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add deploy/restore.sh deploy/tests/test-restore.sh deploy/tests/check-bundle.sh
git commit -F <scratchpad>/m15-task5-commit.txt
```

---

### Task 6: Docs

**Files:**
- Modify: `README.md` (before `## Development`), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§8.3 after the M10 amendment; §10.1 after the M14 amendments; §10.2 after the M13 amendment; §10.3 after the M14 amendments), `docs/operator-guide.md` (§3 doctor paragraph; §7 `review --return` paragraph; §9 the foreign-schema paragraph; §11 the doctor row and a new row), `docs/m3-followups.md`, `docs/m4b-followups.md`, `docs/m5-followups.md`, `docs/m8-followups.md`, `docs/m10-followups.md`, `docs/m12-followups.md`, `docs/m13-followups.md`
- Create: `docs/m15-followups.md`

**Interfaces:**
- Consumes: the behaviour of Tasks 1-5 as their tests pin it (message texts, ruling numbers).
- Produces: documentation only.

- [ ] **Step 1: README**

Insert before `## Development`:

```markdown
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
it is a warning ("json_object output works after one repair turn"), which does not fail doctor,
`install.sh` or the air-gap acceptance; a model that fails twice still fails, citing the second
reply. `corelata fake-openai --needs-repair` plays such a model (CRL-35). `restore.sh` prints
psql's own message when it cannot list the database's schemas, and `check-bundle.sh` ignores
Python bytecode when it compares the shipped pack (CRL-36).
```

- [ ] **Step 2: Spec amendments**

§8.3, after the paragraph that starts `M10 amendment: \`run.review_state\` holds the review decision`:

```markdown
M15 amendment: `review_state` also holds `child_state` (the rerun's state once it ended, any
terminal state; null while it is created or running), `child_error` (the rerun's error) and
`note` (the return's note), written by every review action and by every transaction that ends a
rerun; migration 0005 recorded them for existing rows and deleted `return` events whose rerun was
never linked (CRL-34).
```

§10.1, after the paragraph that starts `M14 amendments: \`GET /runs?project_id=&limit=&before=\``:

```markdown
M15 amendments: a `return` is spent only while its rerun is running or completed. A rerun that
ended failed, cancelled or gate-rejected spends nothing: `POST /runs/{id}/review` accepts another
`return` (a new event and a new rerun; the earlier event stays) or an `accept`, and the 409 answers
only a return whose rerun is live or completed (it names that rerun). The rerun, the `return`
event and `review_state` commit in one transaction under the run's row lock. `review` on
`GET /runs/{id}` carries `child_state`, `child_error` and `note`; the decision is the live return
if there is one, else the latest event (CRL-34).
```

§10.2, after the paragraph that starts `M13 amendment (CRL-31):`:

```markdown
M15 amendment (CRL-35): both structured probes give a reply that does not parse the one repair
turn a run gives (the same messages, built by `llm/agent.repair_messages`). A repaired reply that
parses is a WARN, `<mode> output works after one repair turn (<Name>)`, which leaves doctor's
result and exit code passing; two replies that do not parse FAIL with the second reply's error. A
cut reply or a backend error gets no repair turn, as in a run.
```

§10.3, after the paragraph that starts `M14 amendments: the frame's policy allows`:

```markdown
M15 amendments: when the decision is a return whose rerun ended without a report, the Review
screen says so (the rerun failed, with its error; was cancelled; or stopped at the gate) next to
the link to the rerun, and enables **Accept** and **Return with note** again, the note box
holding the previous note. While a return's rerun has not ended, the screen reads
`GET /runs/{id}` every 3 s, because the run's progress stream ended with the run (CRL-34).
```

- [ ] **Step 3: Operator guide**

§3, in the doctor paragraph, replace `Every check must pass; a failing check says what to fix.` with:

```markdown
Every check must pass or warn; a failing check says what to fix. A model whose first reply to a
probe is not the requested JSON gets one repair turn, as every call in a run does: if the repaired
reply works, the line is a warning ("json_object output works after one repair turn") and the
model can be used, at the price of a second request on some calls.
```

§7, after the sentence `` `review --return` queues a new run that carries the note as guidance for the writer.`` add:

```markdown
If that run fails, is cancelled or stops at the gate, the report can be returned again (or
accepted); while the rerun is running or once it completed, a second return is refused and names
it.
```

§9, after the paragraph that starts `restore.sh works on the \`public\` schema only`, add:

```markdown
If the script cannot list the database's schemas it stops before changing anything and prints
psql's own message under `psql said:` (for example a refused connection or a database that does
not accept connections).
```

§11, append to the `doctor` fails on a backend or a model row's cause text:

```markdown
 A line that says "works after one repair turn" is a warning, not a failure: the model's first reply was not the requested JSON and its repaired one was; runs work, with a second request on such calls. "did not return the requested JSON …, even after one repair turn" means the repaired reply was wrong too: follow that line's fix.
```

and add two rows after the `A run ended \`failed\` with "no queued job exists"` row:

```markdown
| The Review screen says "The rerun failed: …" (or was cancelled, or stopped at the gate) | The run a return created ended without a report, often because the model server was unreachable. Fix the cause the message names (`docker compose logs worker`), then use **Return with note** again (the previous note is offered) or **Accept**. |
| `restore.sh` stops with "could not list the database's schemas" | Read the lines under `psql said:` (a refused connection, a database that does not accept connections); start the database (`docker compose up -d --wait postgres`) or fix what psql names, then run the restore again. |
```

- [ ] **Step 4: Follow-up files**

Strike what the 2026-10-18 triage found fixed (append to the last line of each bullet):

- `docs/m3-followups.md`, the bullet ending `nothing after the colon.` (line 83): ` — **closed**, verified 2026-10-18: \`doctor.py\` \`_model\` says "set models.<key>.name to a served id; see the server's model list" when nothing is similar.`
- `docs/m4b-followups.md` line 57 (`Key \`ValueStatement\` by project so stale suggestions clear.`): ` — **closed**, verified 2026-10-18: \`web/src/pages/new/NewRunPage.tsx\` renders it with \`key={projectId}\`.`
- `docs/m5-followups.md`, the bullet ending `header comment of \`compose.demo.yaml\` does not.` (line 59): ` — **closed**, verified 2026-10-18: \`deploy/compose.demo.yaml\` line 4 names \`CORELATA_DB_PASSWORD\`.`
- `docs/m5-followups.md` line 60 (`` `check_compose.py` has a formatting slip``): ` — **closed**, verified 2026-10-18: \`deploy/tests/check_compose.py\` line 57 is clean.`
- `docs/m13-followups.md` line 37: replace `— **closed after M13**:` with `— **closed after M13**, verified 2026-10-18:`.

Strike what M15 closes:

- `docs/m8-followups.md` line 16 (placeholder event): ` — **closed in M15** (CRL-34): the return, its rerun and the decision commit in one transaction; migration 0005 deleted the placeholders left behind (R-M15-12, R-M15-13).`
- `docs/m8-followups.md` line 17 (separate transactions; a failed queue uses up the return): ` — **closed in M15** (CRL-34): one transaction, and a rerun that failed frees the return (R-M15-1).`
- `docs/m8-followups.md` line 22 (`except BaseException` cleanup): ` — **closed in M15** (CRL-34): nothing is left to clean up in the database; the reference copy goes with synchronous file calls (R-M15-12).`
- `docs/m8-followups.md` line 35 (`restore.sh` keeps `2>/dev/null`): ` — **closed in M15** (CRL-36).`
- `docs/m8-followups.md` line 18 (partial unique index): ` — **dropped in M15**: a run may now hold several return events, one of them live (R-M15-1); the row lock keeps it to one.`
- `docs/m8-followups.md` line 11 (Spec deviations, returned once): append ` M15 re-reads it: one live or completed return (R-M15-1, spec §10.1 M15 amendment).`
- `docs/m5-followups.md` line 54 (`check-bundle.sh`'s `diff -r`): ` — **closed in M15** (CRL-36).`
- `docs/m10-followups.md`, the bullet ending `model and 0004's written-out rule must be changed together.` (line 45): ` — **done in M15**: migration 0005 backfilled \`child_state\`, \`child_error\` and \`note\` (R-M15-13).`
- `docs/m12-followups.md`, the bullet ending `where a run would pass.` (line 66): ` — **closed in M15** (CRL-35).`

Create `docs/m15-followups.md`:

```markdown
# M15 follow-ups

## Divergences from Coglossa

- `llm/agent.repair_messages` and `rejection_errors` (the repair turn as a function both
  `AgentRunner` and doctor call) — **backport candidate**: Coglossa's doctor has no structured
  probe, but its `AgentRunner` builds the same repair turn inline.
- Doctor's repair turn and `fake-openai --needs-repair` — Corelata only (Coglossa's doctor sends a
  ping only).
- `restore.sh`'s `psql said:` block — **backport** with CGL-18: Coglossa's restore script keeps
  the same `2>/dev/null`.
- Return semantics, `ReviewState.child_state`/`child_error`/`note`, migration 0005 — Corelata only.

## Spec deviations

- None. §8.3, §10.1, §10.2 and §10.3 carry M15 amendments.

## Rulings during execution

- How the plan applied R-M15-1 to R-M15-8, and the rulings it added (R-M15-9 to R-M15-18), are
  in its Global Constraints. Number new ones from R-M15-19.

## Should fix soon

- None.

## Later

- A `CancelledError` (or a lost connection) during the COMMIT round trip of a return whose commit
  in fact landed makes `review_run` delete the rerun's reference-document copy; that rerun then
  fails at its DOCX render and frees the report again. Rare; the report can be returned once more.
- A return now holds the parent's row lock while it reads and copies the reference document (a
  small local file); a slow storage volume would hold other reviews of the same run that long.
- A Review page left open on a returned run reads `GET /api/runs/{id}` every 3 s until the rerun
  ends; a progress stream that stays open for a completed run whose rerun is live would replace
  the poll if many reviewers keep such pages open.
- The parent of a manual rerun (`POST /runs` with `parent_run_id`, after a gate rejection) is
  announced and its `review_state` recomputed when that rerun ends, which changes nothing; a
  check that the parent has a `return` event pointing at the run would save the write.
- `corelata review --return` on the CLI says nothing about a rerun that failed; `corelata status
  <parent>` shows the stored decision only in `--json`.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint && git diff --stat main -- docs/m1-followups.md docs/m2-followups.md docs/m4a-followups.md docs/m6-followups.md docs/m7-followups.md docs/m9-followups.md docs/m11-followups.md docs/m14-followups.md engine/corelata/bench .github`
Expected: lint clean; the diff prints nothing.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m15-task6-commit.txt <<'EOF'
docs: M15 README section, spec amendments, operator guide, follow-ups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/operator-guide.md docs/m3-followups.md docs/m4b-followups.md docs/m5-followups.md docs/m8-followups.md docs/m10-followups.md docs/m12-followups.md docs/m13-followups.md docs/m15-followups.md
git commit -F <scratchpad>/m15-task6-commit.txt
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine    # 884 passed
make test-api       # 165 passed
make test-web       # 176 passed
make e2e            # 6 passed
make deploy-check
make schema && git status --short schema web/src/api/schema.d.ts   # no output: committed in Task 1
git diff --name-only main -- schema   # schema/openapi.json and schema/run-progress.schema.json only
grep -n '^version' engine/pyproject.toml                            # still 0.1.3
```

CI must be green on all six jobs (engine, api, web, e2e, deploy, airgap) and `ci-status` before the merge. The `airgap` job runs migration 0005 on install and `corelata doctor` against the demo model (all PASS: the demo model needs no repair).

## Live rehearsal (the controller runs this after the merge; not a task)

A stack by hand, so the model server can be stopped and started under a running worker (`devstack.py` stops the whole stack when its fake server exits). From the repository root, `make db-up` first and `web/dist` built (`cd web && pnpm build`). Write `<scratchpad>/m15.yaml`:

```yaml
backends:
  local: {base_url: "http://127.0.0.1:8000/v1", max_concurrency: 4}
models:
  m1: {backend: local, name: fake-model, context_window: 32768}
roles:
  gate: {model: m1}
  writer: {model: m1}
  conveyor: {model: m1}
  auditor: {model: m1}
retry: {max_attempts: 1}   # an unreachable server fails the rerun in seconds, not minutes
storage: {path: <scratchpad>/m15-files}
```

```sh
export CORELATA_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/corelata_m15
psql postgresql://corelata:corelata@127.0.0.1:55433/postgres -c 'CREATE DATABASE corelata_m15'
CFG=<scratchpad>/m15.yaml
(cd engine && uv run corelata migrate --config $CFG)     # brings the new database to revision 0005
# three terminals, each with CORELATA_DATABASE_URL exported:
cd engine && uv run corelata fake-openai --port 8000                       # A: the model
cd engine && uv run corelata worker --config $CFG                          # B: the worker
cd api && uv run corelata-api --config $CFG --port 8080 --web-dir ../web/dist   # C: the API
```

- [ ] Open http://127.0.0.1:8080, start a run on `docs/examples/varna-port.txt` ("Varna port capacity expansion matters to shippers"), wait for `completed`, open its review. Open the same review URL in a second tab and leave it there.
- [ ] Stop terminal A (Ctrl+C). In the first tab, **Return with note** ("Add the 2027 date"); the page moves to the rerun, which ends `failed` within a few seconds (the worker logs `run … finished: failed`; the error names the unreachable server).
- [ ] The second tab, untouched, shows within about 3 s: the "Returned" badge, "The rerun failed: …. Return the report again or accept it.", the "Open the rerun" link, and both buttons enabled. The browser's network tab shows `GET /api/runs/<parent>` every 3 s until then and none after.
- [ ] Two returns at once against the freed report: `for n in 1 2; do curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/api/runs/<parent>/review -H 'content-type: application/json' -d '{"action":"return","note":"again"}' & done; wait` prints one `200` and one `409`. Cancel the rerun that 200 made (`curl -X POST localhost:8080/api/runs/<child>/cancel`; if the worker already claimed it, it fails on its own, since A is still stopped); the second tab offers both actions again ("The rerun was cancelled; …" or "The rerun failed: …").
- [ ] Start terminal A again. In the second tab, **Return with note**: the box holds the previous note; send it. The rerun completes. `psql "$CORELATA_DATABASE_URL" -c "SELECT action, child_run_id FROM review_event WHERE run_id = '<parent>' ORDER BY at"` lists three `return` rows; `psql "$CORELATA_DATABASE_URL" -c "SELECT state FROM run WHERE parent_run_id = '<parent>' ORDER BY created_at"` lists `failed`, then `cancelled` (or `failed`), then `completed`: one live (completed) rerun. A further return answers 409 naming the completed one.
- [ ] Doctor against a model that needs a repair turn: stop terminal A, run `cd engine && uv run corelata fake-openai --port 8000 --needs-repair`, then `cd engine && uv run corelata doctor --config $CFG; echo "exit=$?"`. Expect `WARN  model m1: test completion succeeded; json_schema output works after one repair turn (GateVerdict)` with the fix line `nothing to change for a run, which repairs the reply the same way; every structured call on models.m1 may cost a second request`, `WARN  model m1 auditor schema: json_schema output works after one repair turn (AuditByRule, 17 rules)`, every other line PASS, and `exit=0`. Start a run in the browser: it completes, and `curl -s localhost:8080/api/runs/<id> | jq .usage.calls` gives 8 (4 for the same run without the flag: one call per stage, each repaired once). Restart terminal A without the flag; doctor is all PASS again.
- [ ] `restore.sh` and a database that refuses connections, in an install directory (the 0.1.3 rehearsal install, or `make bundle` + `./install.sh`), with the M15 `deploy/restore.sh` copied over the installed one: `./backup.sh`, then `docker compose exec -T postgres psql -U corelata -d postgres -c "ALTER DATABASE corelata ALLOW_CONNECTIONS false"`, then `./restore.sh --yes <dump> <archive>`. Expect `error: could not list the database's schemas; is the database up (docker compose ps)?`, `psql said:`, and an indented `psql: error: … FATAL:  database "corelata" is not currently accepting connections`; `docker compose ps` shows `api` and `worker` still running. Undo with `docker compose exec -T postgres psql -U corelata -d postgres -c "ALTER DATABASE corelata ALLOW_CONNECTIONS true"`. (`restore.sh` starts the database itself before it asks, so "a stopped database" cannot reach the schema query; R-M15-16.)
- [ ] Drop the rehearsal database: `psql postgresql://corelata:corelata@127.0.0.1:55433/postgres -c 'DROP DATABASE corelata_m15'`.

Regression against OpenRouter (the CRL-1 configuration, as in the M14 rehearsal):

- [ ] `corelata doctor --config <openrouter.yaml>`: every line PASS, as in M14. A WARN "works after one repair turn" on a model line is not a regression of M15 (the model needed a repair before too, and runs repaired it); note it on CRL-35.
- [ ] `corelata bench --config <openrouter.yaml> --scenarios real --out bench-m15-real/`: compare with the M14 baseline below; M15 changes nothing a run sends, so a difference is model variance.
- [ ] Fill in the table, add it to Jira CRL-34, CRL-35 and CRL-36 (close them with the rehearsal evidence: the second tab's outcome note, the 200/409 pair, the doctor WARN lines and exit code, the `psql said:` output); then cut 0.1.4.

| Measure | M14 baseline (2026-10-17) | M15 |
|---|---|---|
| `doctor` (OpenRouter) | all PASS | |
| Real set: full agreement | 7/8 | |
| Gate agreement | 7/8 | |
| Rule-failure agreement | 3/3 | |
| Duration | 30 s | |
| Failed rerun shown on an open Review page | n/a | |
| Concurrent returns after a failed rerun (200 + 409) | n/a | |
| `doctor` against `fake-openai --needs-repair` (2 WARN, exit 0) | n/a | |
| `restore.sh` with connections refused (`psql said:` shown, nothing stopped) | n/a | |
