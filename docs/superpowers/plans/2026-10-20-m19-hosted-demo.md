# M19 Corelata Hosted Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-42: a public, password-protected Corelata demo built on Coglossa's hosted-preview template (Vercel front door, Modal compute that scales to zero, Supabase Postgres and Storage in Coglossa's project, OpenRouter models), with the engine and API additions it needs off by default, so the air-gapped install, its bundle and the `airgap` job are unchanged.

**Architecture:** The engine gains `storage.kind: s3` (`S3Storage`, with Corelata's `list_keys`), `storage_call` (every storage call on the event loop runs in a thread and is waited for even when cancelled), the kick (`HttpKicker`, `KickingQueue` passing `priority`), `queue_status`/`needs_worker` and the cron's `cron_pass`/`purge_pass`; the API gains `ProxySecretMiddleware` and wraps its queue in `KickingQueue` when `worker.kick_url` is set. `deploy/hosted/` is Coglossa's directory copied and renamed: a Modal app (`api`, `worker`, `kick`, `cron`, `purge`, `migrate`, `doctor`, `seed`) whose settings render `corelata.hosted.yaml` from the Modal Secret at container start, a guarded start-clean script, a Vercel front door (middleware, PBKDF2 logins, HMAC session cookie `crl_session`, the operator guide's CSP in `vercel.json`), a smoke test and a README. CI gains `hosted-web` and `hosted-modal`, which `ci-status` needs; `hosted.yml` deploys on push once the owner adds tokens, and until then the controller deploys by hand (the last section).

**Tech Stack:** Python 3.12, FastAPI, procrastinate 3.10, SQLAlchemy 2.1 async + psycopg 3, boto3 1.43 (the `s3` extra), moto 5 (engine dev only), pytest; Modal 1.6.2; TypeScript 5.9, Vitest 4.1, `@vercel/functions` 3.10.1, pnpm 10, Node 22; Vercel CLI 61.1.0; Supabase (session pooler, Storage S3 API); OpenRouter.

**Spec:** `docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md`, Part B (§10 to §22) and §23 (the owner's decisions and spike S2, added with this plan; where §23 and §10 to §22 disagree, §23 wins). The v1 spec stays the authority for everything M19 does not change. Coglossa reference: `$COGLOSSA` is the read-only clone at `<scratchpad>/coglossa-ref` (if it is gone: `gh repo clone Bonham-Technologies/coglossa "$COGLOSSA" && git -C "$COGLOSSA" checkout 72dd055`, the commit M18 copied from). Its hosted design is `$COGLOSSA/docs/superpowers/specs/2026-10-14-coglossa-hosted-preview-design.md`.

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). The front door's Vitest thresholds are 95% on lines, branches, functions and statements (`deploy/hosted/vercel/vitest.config.ts`, copied). `pnpm typecheck` clean. `make deploy-check` clean. `ci-status` is the required check.
- Baselines on this branch at 37a8b43, measured for this plan: engine 979 passed (98.47%), api 174 (99.69%). After each task in the scratch copy: engine 1012, 1017, 1020, 1037, 1047 (Tasks 1 to 5; 98.50% at the end), api 180 after Task 3 and 181 after Task 4 (99.70%); the front door 50 Vitest tests in 5 files (99.28 / 99.15 / 100 / 100%) after Task 7; `hosted-modal`'s pytest 22 after Task 6 and 37 after Task 8.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make lint`, `make deploy-check`. Do not run the full pytest and Vitest suites concurrently. Never stop the dev Postgres container (`corelata-dev-postgres-1`); drop any database you create.
- **Everything new is off by default** (spec §1.1, §12.1): `storage.kind: local`, no `worker.kick_url`, no `auth.proxy_secret_env` behave exactly as today. The new settings are in operational sections (`storage`, `worker`, `auth`), so `config_hash` is unchanged (tests pin it). No schema or migration change; `make schema` changes nothing (no API model changes).
- **The air-gapped deployment is unchanged:** `deploy/docker/app.Dockerfile`, the compose files, `install.sh`, `backup.sh`, `restore.sh`, `bundle.sh`, `check-bundle.sh`, the `airgap` job and `release.yml` are not touched. The app image installs no extra, so it carries no `boto3`; `deploy/tests/check-app-image.sh` gains that check (Task 1). Nothing under `web/` changes.
- **Dependencies:** `boto3>=1.36,<2` only in the new `s3` extras (`engine`: `s3 = ["boto3>=1.36,<2"]`; `api`: `s3 = ["corelata[s3]"]`); `boto3` and `moto[s3]>=5.0,<6` in the engine's dev group only. `uv lock` in `engine` and `api` adds exactly boto3 1.43.116, botocore 1.43.116, jmespath 1.1.0, s3transfer 0.19.3, urllib3 2.8.0 (and in the engine moto 5.2.4, py-partiql-parser 0.6.3, requests 2.34.2, responses 0.26.3, werkzeug 3.1.9, xmltodict 1.0.4); no other version moves. The front door's packages are Coglossa's exact pins and lock (copied unchanged). The Modal client is `modal==1.6.2` (`deploy/hosted/modal/requirements.txt`, copied).
- **No secret in any committed file.** Account-specific URLs (the S3 endpoint, the kick URL) come from the Modal Secret `corelata-hosted` when a container starts (`settings.render_config`); the Vercel env holds the front door's. `~/.config/corelata/hosted.env` (mode 600) is the controller's, never read by implementers. No implementer contacts Supabase, Modal, Vercel or OpenRouter: every test runs offline (moto, httpx mock transports, the dev Postgres).
- **Copy faithfully** (spec §12, v1 spec §4.3): Coglossa's files are copied, renamed (`COGLOSSA_` → `CORELATA_`, `coglossa` → `corelata`, `Coglossa` → `Corelata`, `cg_session` → `crl_session`) and otherwise changed only where this plan says; each change is a "Divergences from Coglossa" entry in `docs/m19-followups.md` (Task 9 writes the list).
- **Coglossa's data is never touched** (spec §23.1): nothing in M19 addresses a database other than `corelata` or a bucket other than `corelata-files`.
- **CI style** (PR #72's `ci.yml` on this branch): jobs on `ubuntu-24.04`, actions by their major tags (`actions/checkout@v7`, `astral-sh/setup-uv@v7`, `pnpm/action-setup@v6`, `actions/setup-node@v7`), a `timeout-minutes` on each new job, the workflow-level `concurrency` that cancels superseded pull-request runs. The current `ci.yml` has no path filters and no SHA-pinned actions; `hosted.yml` keeps Coglossa's SHA pins (R-M19-16).
- Commit messages end with exactly these two lines, nothing after them:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK`
  (implementer subagents use their own harness's model line instead). Write the message to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .`: add the task's files by name. Plain single shell commands with `git -C <path>`.
- Version stays `0.1.7` (R-M19-18).
- Rulings: R-M9-1 to R-M9-12, R-M10-1 to R-M10-10, R-M11-1 to R-M11-8, R-M12-1 to R-M12-10, R-M13-1 to R-M13-12, R-M14-1 to R-M14-15, R-M15-1 to R-M15-22, R-M16-1 to R-M16-24, R-M17-1 to R-M17-29 and R-M18-1 to R-M18-27 stay in force; R-M19-4 restates R-M15-3's guarantee for the threaded cleanups. This plan's rulings (from reading the code at 37a8b43 and Coglossa's template, and applying Tasks 1 to 9 to a scratch copy; results under "Final verification"):
  - **R-M19-1 (owner decisions, spec §23).** Coglossa's Supabase project `coglossa-preview` with Corelata's own database `corelata` (the session pooler, port 5432, path `/corelata`) and private bucket `corelata-files`, both already created; Coglossa's project-wide S3 keys and database password; the existing OpenRouter key and its $25 limit; the logins `people-first` (Coglossa's hash) and `ci`, no `demo` or owner login; the `*.vercel.app` address of Vercel project `corelata-demo` in team `bonham-technologies`; deployed by hand from the controller's machine with Coglossa's Modal proxy-auth token. §10.5 becomes "`hosted.yml` deploys on push once the owner adds CI tokens; until then the controller deploys by hand."
  - **R-M19-2 (spike S2 passed).** The API's `LISTEN` goes through the session pooler; `api.progress_poll_s` stays 1.0; no fallback, no self-`NOTIFY` follow-up. S2's second half (stage changes through the site within 2 s, "progress listener connected" in the log) is part of the final acceptance (the last section).
  - **R-M19-3 (off by default).** As in the constraint above; `test_config.py` pins `config_hash` against each new setting.
  - **R-M19-4 (storage off the event loop).** Every storage call on an event-loop path goes through `corelata.storage.storage_call(fn, *args)`: `fn` runs in a thread, and the call is waited for to its end even when the awaiting task is cancelled meanwhile, then the cancellation is raised. So a cleanup in an `except BaseException` never runs beside the `put` it undoes, and no cancellation can stop a cleanup half way: the guarantee R-M15-3 had from a plain call. A plain `asyncio.to_thread` gives the second but not the first (the cancelled await returns while the thread still writes). The call sites, from reading the code (line numbers at 37a8b43):
    - `engine/corelata/service.py`: `add_source` `storage.put` (276) and its cleanup `storage.delete_prefix` (292); `_create_run` `storage.put` of the reference copy (352) and its cleanup (361); `review_run` `storage.get` of the reference document, under the run's row lock (549), and its cleanup of the rerun's copy (580, whose comment cited R-M15-3); `stored_export` (704, already `asyncio.to_thread`, now `storage_call` for one rule); `reference_document` (716). `_parse_stored` (277) stays in `asyncio.to_thread`: it already runs off the loop, and a parse is not a write a cleanup could race.
    - `engine/corelata/worker/execute.py`: `execute_run`'s stale-file listing `_stray_files` → `list_keys` (283) and each `delete_prefix` (285); the reference document `_reference` → `local_file` (290, R-M19-5); each export's `storage.put` inside the saving transaction (329).
    - `engine/corelata/doctor.py`: the storage check (`_storage` → `check_writable`, 209), which the API runs for Settings (`GET /api/system/doctor`).
    - Not moved, because nothing else shares the loop yet or there is no loop: `worker/app.build_services` (172–173, before the worker fetches a job), `api/corelata_api/app.py`'s `build_storage` in the lifespan (104, a client object, no request), `corelata_api/main.py` (42, before uvicorn starts) and the CLI (`cli_ops.py` 195, 210, 244, 346, 367, which runs its own `asyncio.run`; its async paths reach the service, which is now threaded).
  - **R-M19-5 (the reference document in the worker).** `execute._reference` becomes an async context manager: entering `storage.local_file` (a download for S3) runs in `storage_call`; leaving it (removing the temporary copy, a local unlink) runs on the loop.
  - **R-M19-6 (`S3Storage.list_keys`).** The keys under `prefix + "/"`, sorted, without the configured `storage.prefix`, exactly as `LocalStorage.list_keys` gives them (a test runs both); paginated; a failure raises `StorageError("cannot list <prefix>: <code>: <message>")`. `check_key` moves to module level and is shared by both stores (Coglossa's shape).
  - **R-M19-7 (doctor).** `storage` reports `describe_storage(cfg.storage)` ("/data/files is writable", "s3://corelata-files at https://… is writable") and, for S3, the fix "fix storage (bucket, endpoint_url, keys)"; a `worker` line "kicks <url> when a job is queued" only when `worker.kick_url` is set (the URL is never called: a call would start a worker); an `auth` line only when `auth.proxy_secret_env` is set. Both always pass, because an unset variable already fails the `config` check. Settings ▸ Status shows them under R-M18-8's "any other" row only if one ever fails, so `web/` does not change.
  - **R-M19-8 (the kick in the API).** The lifespan wraps the queue in `KickingQueue` when `build_kicker(cfg.worker)` returns one and closes the kicker (cancelling kicks in flight) before the queue closes. A kick is fire-and-forget: it never holds up the request that queued the job and never raises; the cron is the backstop (Review Focus 1).
  - **R-M19-9 (the cron and the purge).** `corelata.worker.app.cron_pass(cfg) -> bool` runs `sweep_orphans(grace_s=ORPHAN_GRACE_S)` and `expire_discoveries(...)` against the database, as the worker's minute task does, then returns `needs_worker(...)`; `purge_pass(cfg) -> int` runs `purge_closed_jobs(retention_days=...)`. Both live in the engine with Postgres tests; the Modal `cron` and `purge` only call them. Coglossa's cron has only `needs_worker` (it has no sweep to stand in for).
  - **R-M19-10 (the proxy secret).** `auth.proxy_secret_env` names the variable; `ProxySecretMiddleware` (pure ASGI, constant-time compare) refuses every request without `X-Corelata-Proxy-Secret` with 401 "this address only answers requests from the Corelata sign-in proxy", except `/api/health`. The static web app (unused on the demo) is behind it too, as in Coglossa.
  - **R-M19-11 (the hosted config).** `deploy/hosted/corelata.hosted.yaml` is spec §14's YAML as data (a test compares the two); its first comment says "Placeholder values (dollar sign, braces, NAME)" instead of `${NAME}`, which `string.Template.substitute` would try to fill (as Coglossa's comment does). A spec deviation entry.
  - **R-M19-12 (the seed).** `settings.seed_command(project_names)` returns the `corelata run --project "Example: Varna port" --statement STATEMENT /etc/corelata/examples/varna-port.txt` argv, or `None` when the project exists. `EXAMPLE_PROJECT`, `EXAMPLE_SOURCE` and `STATEMENT` are constants in `settings.py`, which `app.py` imports (settings is importable without Modal, so CI tests them; §13.6 puts STATEMENT "in app.py": a spec deviation entry). After queueing, `seed` spawns the deployed app's worker by name (`modal.Function.from_name("corelata", "worker").spawn()`): a function spawned from a `modal run` belongs to that run's short-lived app and would stop with it. The cron starts one within 5 minutes anyway.
  - **R-M19-13 (start clean).** `deploy/hosted/modal/start_clean.py`, run by the controller from `engine/` with the hosted values exported, refuses a database URL that does not name `corelata`, checks `current_database()` again on the open connection, truncates Corelata's tables and procrastinate's (`RESTART IDENTITY CASCADE`; `alembic_version` stays, so no migration reruns) and deletes the files under `projects/` and `runs/` (every stored key, `service.py`) of `corelata-files`, a constant; then the controller runs the seed. A script, not a ninth Modal function: the spec lists eight.
  - **R-M19-14 (the front door).** Copied and renamed; comments and the misconfigured message changed; groups kept for Coglossa's account shape (so `people-first`'s line is copied as it is) and ignored by Corelata; the sign-in page's title "Sign in – Corelata" (§3.4's pattern), its colours checked against `web/src/styles/tokens.css`; `vercel.json` sends the operator guide's sample `Content-Security-Policy` on `/(.*)`, checked word for word against the guide's nginx line by `lib/site.test.ts`.
  - **R-M19-15 (the smoke test).** Six checks: checks 2 and 4 read `/api/system/info` (Corelata has no `/api/me`); check 6 finds "Example: Varna port" in `GET /api/projects` through the site. Its tests run in `hosted-modal` (Coglossa's run in no CI job).
  - **R-M19-16 (CI).** `hosted-web` (pnpm install, `pnpm typecheck`, `pnpm test`) and `hosted-modal` (the settings, start-clean and smoke tests in the engine's environment with `CORELATA_FORBID_SKIP=1`, then `check_app.py`) on every run (each takes about a minute, so no skip rule); `ci-status` needs both. `hosted-modal` runs `python -m pytest` under `uv run --with …`: the bare `pytest` can resolve to the project environment's own entry point without the overlay (it failed that way on macOS), and `check_app.py` runs with `--no-project`. `hosted.yml` keeps Coglossa's SHA-pinned actions (it holds deploy secrets), adds the seed after the deploy, runs on `ubuntu-24.04` with a 30-minute limit, and skips with a notice without `MODAL_TOKEN_ID` or `VERCEL_TOKEN`.
  - **R-M19-17 (lockfiles).** `uv lock` rewrites both locks' format revision from 3 to 5 under uv 0.13 (R-M18-17 avoided that churn; M19 adds packages, so it cannot). The image's `ghcr.io/astral-sh/uv:0.13.0` reads it: checked by `make image-app` on the scratch copy.
  - **R-M19-18 (version).** Stays 0.1.7; the controller cuts the next version after the acceptance.
  - **R-M19-19 (deploy checks).** `make deploy-check` shellchecks `deploy/hosted/vercel/*.sh` too (Coglossa's Makefile line); Dependabot watches `deploy/hosted/vercel` (npm) and `deploy/hosted/modal` (pip), as in Coglossa.
  - **R-M19-20 (provisioning).** The controller provisions and deploys by the last section, "Provisioning and deploy", which replaces spec §16; no implementer task touches a hosted service.

## Review Focus

1. **A queued report on a sleeping demo whose kick is lost** (the placeholder kick URL of the first deploy, a 5xx, a timeout, a refused connection). The request that queued it must answer at once, and a worker must still start within the cron's 5 minutes. Pinned in Task 4 (`test_queue_defers_then_kicks_without_waiting_for_the_kick`, `test_a_failed_kick_is_logged_not_raised`, and the API's `test_the_queue_kicks_a_worker_only_when_configured`, whose kick is refused) and Task 5 (`test_cron_pass_starts_a_worker_for_a_run_whose_kick_was_lost`).
2. **A slow S3 call that stalls every other demo user**, or a cleanup that races the upload it undoes after a cancellation. Every storage call on the API's and the worker's loop runs in a thread, and a cancelled call is waited for before its cleanup. Pinned in Task 2 (`test_service_and_worker_storage_calls_run_off_the_event_loop`, `test_a_cancelled_storage_call_waits_for_its_thread_then_raises_the_cancellation`, `test_a_failed_return_removes_the_reruns_reference_copy_off_the_loop`).
3. **A caller that holds the Modal token Coglossa shares but not Corelata's proxy secret** (Coglossa's own front door, a leaked token) sending a forged `X-Remote-User`. It must get 401 and change nothing, while the progress stream still streams through the middleware. Pinned in Task 3 (`test_a_forged_user_without_the_secret_reaches_nothing`, `test_the_progress_stream_still_streams`, `test_the_middleware_passes_chunks_on_as_they_come`) and Task 8 (smoke check 4).
4. **Starting clean or tearing down that touches Coglossa's data** in the shared Supabase project. The script must refuse any database but `corelata`, also when the URL looked right but the connection is elsewhere, and any bucket but `corelata-files`. Pinned in Task 6 (`test_any_database_but_corelata_is_refused`, `test_a_connection_to_another_database_truncates_nothing`, `test_the_bucket_is_emptied_and_coglossas_is_left_alone`, `test_another_bucket_is_refused`).
5. **A redeploy, or a second `modal run …::seed`, that writes a second example report**, and a seed whose worker dies with the `modal run` that spawned it. Pinned in Task 6 (`test_seed_runs_only_when_the_example_is_missing`; the spawn by name is R-M19-12, read in review) and Task 8 (smoke check 6 finds exactly the project).

---

## File structure

| Path | Responsibility | Task |
|---|---|---|
| `engine/corelata/config.py` | `S3StorageConfig` and the storage union; `auth.proxy_secret_env`; `worker.kick_url`, `kick_token_env`, `extra_headers_env`, `env_headers`; `validate_config` for each variable; S3 not path-resolved | 1, 3, 4 |
| `engine/corelata/storage.py` | `check_key`, `S3Storage` (+ `list_keys`), `describe_storage`, `build_storage`; `storage_call` | 1, 2 |
| `engine/corelata/service.py`, `worker/execute.py` | storage calls through `storage_call` | 2 |
| `engine/corelata/doctor.py` | the storage line (described, off the loop), the `worker` and `auth` lines | 1, 2, 3, 4 |
| `engine/corelata/worker/kick.py` (copied) | `HttpKicker`, `KickingQueue`, `build_kicker` | 4 |
| `engine/corelata/worker/app.py` | `QueueStatus`, `queue_status`, `needs_worker` (copied); `cron_pass`, `purge_pass` | 5 |
| `engine/pyproject.toml`, `api/pyproject.toml`, both `uv.lock` | the `s3` extras, `moto` in the engine's dev group | 1 |
| `api/corelata_api/proxy.py` (copied), `app.py` | the proxy-secret middleware; the kicking queue | 3, 4 |
| `deploy/tests/check-app-image.sh` | the app image carries no `boto3` | 1 |
| `deploy/hosted/corelata.hosted.yaml`, `deploy/hosted/modal/*` | the hosted config; the Modal app, its settings, `check_app.py`, start clean, their tests | 6 |
| `deploy/hosted/vercel/*`, `deploy/hosted/add-user.mjs` (copied) | the front door | 7 |
| `deploy/hosted/smoke.py`, `test_smoke.py` (copied) | the post-deploy smoke test | 8 |
| `.github/workflows/ci.yml`, `hosted.yml`, `.github/dependabot.yml`, `Makefile` | CI jobs, the deploy workflow, updates, shellcheck | 8 |
| `deploy/hosted/README.md`, `docs/m19-followups.md`, `docs/operator-guide.md`, `README.md` | docs | 9 |

Order: 1, 2 (it builds on Task 1's `storage.py` and `doctor.py`), 3, 4 (both edit `config.py`, `doctor.py` and `app.py` after the one before), 5, then 6 (it needs the config fields of Tasks 1, 3 and 4 and Task 5's functions), 7 (independent; any time), 8 (after 6 and 7: the smoke test imports `settings`, and CI runs both directories), 9.

How to read the code blocks. A whole file is given in full: write it as it is. A change to a file that exists is a patch with `a/` and `b/` paths from the repository root: `git -C <repo> apply <patch-file>` (save the block to a scratchpad file first), or make the same edit by hand. A file copied from Coglossa is copied, renamed, then patched:

```bash
cp "$COGLOSSA/<path>" <path>
python3 "$SCRATCH/rename.py" <path or directory>   # the script below; never committed
git -C <repo> apply "$SCRATCH/<the task's patch>"   # when the plan gives one
```

`$SCRATCH/rename.py`, the renaming every copy gets (it skips `pnpm-lock.yaml`, which is copied as it is):

```python
"""Rename Coglossa's names to Corelata's in a file, or every file under a directory."""

import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for p in [root] if root.is_file() else sorted(root.rglob("*")):
    if p.is_file() and p.name != "pnpm-lock.yaml":
        t = p.read_text(encoding="utf-8")
        n = (
            t.replace("COGLOSSA_", "CORELATA_")
            .replace("coglossa", "corelata")
            .replace("Coglossa", "Corelata")
            .replace("cg_session", "crl_session")
        )
        if n != t:
            p.write_text(n, encoding="utf-8")
            print("renamed in", p)
```

Every block was produced from the scratch copy the plan was checked on: applied in task order to a fresh copy of 37a8b43, the blocks rebuild that scratch copy byte for byte (the two `uv.lock` files come from `uv lock`).

---

### Task 1: `storage.kind: s3` (copied from Coglossa), the `s3` extras, the image without boto3

**Files:**
- Copy from Coglossa (with the patch below): `engine/tests/test_storage_s3.py`
- Modify: `engine/corelata/config.py`, `engine/corelata/storage.py`, `engine/corelata/doctor.py` (`_storage`), `engine/pyproject.toml`, `api/pyproject.toml`, `engine/uv.lock`, `api/uv.lock` (regenerated), `deploy/tests/check-app-image.sh`
- Test: `engine/tests/test_storage_s3.py`, `engine/tests/test_config.py`, `engine/tests/test_doctor.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `corelata.config.S3StorageConfig` (`kind: Literal["s3"]`, `endpoint_url: str | None = None`, `region: str = "us-east-1"`, `bucket: str` (3–63), `prefix: str = ""`, `access_key_id_env: str = "CORELATA_S3_ACCESS_KEY_ID"`, `secret_access_key_env: str = "CORELATA_S3_SECRET_ACCESS_KEY"`); `CorelataConfig.storage: StorageConfig | S3StorageConfig` (discriminated by `kind`, default local); `corelata.storage.check_key(key) -> list[str]`, `S3Storage(cfg, *, client=None)` with the `Storage` protocol's six methods, `describe_storage(cfg) -> str`, `build_storage(cfg) -> Storage`; the extras `corelata[s3]`, `corelata-api[s3]`.

- [ ] **Step 1: Write the failing tests**

Copy `$COGLOSSA/engine/tests/test_storage_s3.py` to `engine/tests/test_storage_s3.py`, run the rename on it, then apply this patch (it adds Corelata's `list_keys` tests; the copied tests are unchanged):

````diff
--- a/engine/tests/test_storage_s3.py
+++ b/engine/tests/test_storage_s3.py
@@ -170,3 +170,35 @@
     assert config.request_checksum_calculation == "when_required"
     assert config.response_checksum_validation == "when_required"
     assert config.s3 == {"addressing_style": "path"}
+
+
+# Corelata's own: list_keys (the Storage protocol has it; the worker clears stale exports).
+
+
+@pytest.mark.parametrize("prefix", ["", "demo", "/demo/"])
+def test_list_keys_matches_local_storage(s3, tmp_path, prefix):
+    from corelata.storage import LocalStorage
+
+    stores = [S3Storage(_cfg(prefix=prefix)), LocalStorage(tmp_path)]
+    for store in stores:
+        for key in ["runs/r1/report.json", "runs/r1/sub/a.txt", "runs/r10/keep.txt", "runs/r1"]:
+            if not (store is stores[1] and key == "runs/r1"):  # a file and a directory locally
+                store.put(key, b"x")
+    s3_keys, local_keys = (store.list_keys("runs/r1/") for store in stores)
+    assert s3_keys == local_keys == ["runs/r1/report.json", "runs/r1/sub/a.txt"]
+    assert stores[0].list_keys("runs/none") == stores[1].list_keys("runs/none") == []
+
+
+def test_list_keys_pages_through_many_keys(s3):
+    store = S3Storage(_cfg())
+    for i in range(1005):  # more than one list page (1000)
+        store.put(f"many/{i:04}.txt", b"x")
+    keys = store.list_keys("many")
+    assert len(keys) == 1005 and keys[0] == "many/0000.txt" and keys == sorted(keys)
+
+
+def test_list_keys_failures(s3):
+    with pytest.raises(StorageError, match="invalid storage key"):
+        S3Storage(_cfg()).list_keys("../x")
+    with pytest.raises(StorageError, match="cannot list runs/: .*NoSuchBucket"):
+        S3Storage(_cfg(bucket="no-such-bucket")).list_keys("runs/")
````

Add the config tests (`engine/tests/test_config.py`) and the doctor tests (`engine/tests/test_doctor.py`):

````diff
--- a/engine/tests/test_config.py
+++ b/engine/tests/test_config.py
@@ -265,3 +265,51 @@
 def test_logout_url_refuses_what_a_browser_reads_as_another_site(make_config, url):
     with pytest.raises(ValueError, match="site path starting with /"):
         make_config(auth={"logout_url": url})
+
+
+# M19: storage.kind s3 (copied from Coglossa, spec §12.1)
+
+S3_KEYS = ("CORELATA_S3_ACCESS_KEY_ID", "CORELATA_S3_SECRET_ACCESS_KEY")
+
+
+def test_storage_kind_defaults_to_local_and_s3_is_accepted(make_config):
+    assert make_config().storage.kind == "local"
+    assert make_config(storage={"path": "/x"}).storage.kind == "local"
+    cfg = make_config(storage={"kind": "s3", "bucket": "bkt", "endpoint_url": "https://e/s3"})
+    assert (cfg.storage.kind, cfg.storage.bucket, cfg.storage.endpoint_url) == (
+        "s3",
+        "bkt",
+        "https://e/s3",
+    )
+    assert cfg.storage.region == "us-east-1" and cfg.storage.prefix == ""
+    assert (cfg.storage.access_key_id_env, cfg.storage.secret_access_key_env) == S3_KEYS
+
+
+def test_s3_storage_rejects_unknown_fields_and_kinds(make_config):
+    with pytest.raises(ValidationError):
+        make_config(storage={"kind": "s3", "bucket": "bkt", "path": "/x"})
+    with pytest.raises(ValidationError):
+        make_config(storage={"kind": "s3"})  # a bucket is required
+    with pytest.raises(ValidationError):
+        make_config(storage={"kind": "gcs"})
+
+
+@pytest.mark.parametrize("missing", S3_KEYS)
+def test_s3_storage_keys_must_be_set(tmp_path, monkeypatch, missing):
+    for var in S3_KEYS:
+        monkeypatch.setenv(var, "set")
+    monkeypatch.setenv(missing, "")
+    path = _write(tmp_path, {**BASE_CONFIG, "storage": {"kind": "s3", "bucket": "bkt"}})
+    with pytest.raises(ConfigError, match=f"storage: environment variable {missing} is not set"):
+        load_config(path)
+
+
+def test_s3_storage_is_not_path_resolved_and_leaves_the_config_hash(tmp_path, monkeypatch):
+    for var in S3_KEYS:
+        monkeypatch.setenv(var, "set")
+    local, _ = load_config(_write(tmp_path, BASE_CONFIG))
+    s3, issues = load_config(
+        _write(tmp_path, {**BASE_CONFIG, "storage": {"kind": "s3", "bucket": "bkt"}})
+    )
+    assert s3.storage.kind == "s3" and s3.storage.bucket == "bkt" and issues == []
+    assert config_hash(s3) == config_hash(local)  # storage is operational
````

````diff
--- a/engine/tests/test_doctor.py
+++ b/engine/tests/test_doctor.py
@@ -1160,3 +1160,41 @@
         firsts = [r for r in srv.requests if len(r["messages"]) == 2]
         repairs = [r for r in srv.requests if len(r["messages"]) == 4]
         assert len(firsts) == 3 and len(repairs) == 2  # the ping needs no repair
+
+
+# M19: the hosted demo's storage (spec §12.1)
+
+
+@pytest.fixture
+def s3_env(monkeypatch):
+    import boto3
+    from moto import mock_aws
+
+    monkeypatch.setenv("CORELATA_S3_ACCESS_KEY_ID", "test-key")
+    monkeypatch.setenv("CORELATA_S3_SECRET_ACCESS_KEY", "test-secret")
+    with mock_aws():
+        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="corelata-files")
+        yield
+
+
+async def test_s3_storage_writable(tmp_path, server, s3_env):
+    storage = {"kind": "s3", "bucket": "corelata-files", "prefix": "demo"}
+    report = await run_doctor(_config(tmp_path, server.base_url, storage=storage), probe=False)
+    check = _by_name(report)["storage"]
+    assert check.status is CheckStatus.PASS
+    assert check.message == "s3://corelata-files/demo is writable"
+
+
+async def test_s3_storage_missing_bucket(tmp_path, server, s3_env):
+    storage = {"kind": "s3", "bucket": "no-such-bucket", "endpoint_url": None}
+    report = await run_doctor(_config(tmp_path, server.base_url, storage=storage), probe=False)
+    check = _by_name(report)["storage"]
+    assert check.status is CheckStatus.FAIL
+    assert check.message.startswith("storage bucket no-such-bucket at AWS S3 is not writable")
+    assert check.fix == "fix storage (bucket, endpoint_url, keys)"
+
+
+async def test_local_storage_names_its_path(tmp_path, server):
+    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
+    check = _by_name(report)["storage"]
+    assert check.message == f"{(tmp_path / 'files').resolve()} is writable"
````

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_storage_s3.py tests/test_config.py tests/test_doctor.py --no-cov -q`
Expected: collection fails with `ModuleNotFoundError: No module named 'boto3'` (and, once boto3 is there, `ImportError: cannot import name 'S3StorageConfig'`).

- [ ] **Step 3: The extras and the locks**

````diff
--- a/engine/pyproject.toml
+++ b/engine/pyproject.toml
@@ -17,6 +17,9 @@
   "procrastinate>=3.10,<3.11",
 ]
 
+[project.optional-dependencies]
+s3 = ["boto3>=1.36,<2"]  # storage.kind: s3 (the hosted demo); an air-gapped install never needs it
+
 [project.scripts]
 corelata = "corelata.cli:main"
 
@@ -30,6 +33,8 @@
   "pytest-cov>=5.0",
   "hypothesis>=6.112",
   "ruff>=0.7",
+  "boto3>=1.36,<2",
+  "moto[s3]>=5.0,<6",
 ]
 
 [build-system]
````

````diff
--- a/api/pyproject.toml
+++ b/api/pyproject.toml
@@ -9,6 +9,9 @@
   "uvicorn>=0.32,<1",
   "python-multipart>=0.0.18",
 ]
+
+[project.optional-dependencies]
+s3 = ["corelata[s3]"]  # the hosted demo's Modal image; the air-gapped app image has no S3 client
 
 [project.scripts]
 corelata-api = "corelata_api.main:main"
````

Then `cd engine && uv lock && uv sync --all-groups`, and `cd api && uv lock && uv sync --all-groups`. Check that the locks only add packages: the Global Constraints list them; `git -C <repo> diff --stat engine/uv.lock api/uv.lock` shows the two files, and a version that moved for any package already in a lock is a stop-and-report.

- [ ] **Step 4: The config, the store and the doctor line**

````diff
--- a/engine/corelata/config.py
+++ b/engine/corelata/config.py
@@ -5,10 +5,18 @@
 import re
 from enum import StrEnum
 from pathlib import Path
-from typing import Any, Literal
+from typing import Annotated, Any, Literal
 
 import yaml
-from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
+from pydantic import (
+    BaseModel,
+    ConfigDict,
+    Discriminator,
+    Field,
+    Tag,
+    ValidationError,
+    field_validator,
+)
 
 CONFIG_ENV = "CORELATA_CONFIG"
 ROLE_NAMES = ("gate", "writer", "conveyor", "auditor", "profiler")
@@ -131,8 +139,34 @@
 
 
 class StorageConfig(_Strict):
-    kind: Literal["local"] = "local"
+    kind: Literal["local"] = "local"  # or "s3": S3StorageConfig
     path: Path = Path("/data/files")
+
+
+class S3StorageConfig(_Strict):
+    """Files in an S3-compatible bucket (Supabase Storage on the hosted demo; copied from
+    Coglossa). The keys are read from the environment variables named here; they never go in
+    the config file."""
+
+    kind: Literal["s3"]
+    endpoint_url: str | None = None  # None: AWS S3 itself
+    region: str = "us-east-1"
+    bucket: str = Field(min_length=3, max_length=63)
+    prefix: str = ""  # keys go under this prefix, e.g. one bucket shared by several sites
+    access_key_id_env: str = "CORELATA_S3_ACCESS_KEY_ID"
+    secret_access_key_env: str = "CORELATA_S3_SECRET_ACCESS_KEY"
+
+
+def _storage_kind(value: Any) -> str:
+    if isinstance(value, dict):
+        return value.get("kind", "local")
+    return getattr(value, "kind", "local")
+
+
+AnyStorageConfig = Annotated[
+    Annotated[StorageConfig, Tag("local")] | Annotated[S3StorageConfig, Tag("s3")],
+    Discriminator(_storage_kind),
+]
 
 
 class WorkerConfig(_Strict):
@@ -224,7 +258,7 @@
     audit: AuditConfig = Field(default_factory=AuditConfig)
     prompts_dir: Path | None = None
     database: DatabaseConfig = Field(default_factory=DatabaseConfig)
-    storage: StorageConfig = Field(default_factory=StorageConfig)
+    storage: AnyStorageConfig = Field(default_factory=StorageConfig)
     worker: WorkerConfig = Field(default_factory=WorkerConfig)
     api: ApiConfig = Field(default_factory=ApiConfig)
     auth: AuthConfig = Field(default_factory=AuthConfig)
@@ -273,6 +307,10 @@
     key_env = coglossa.api_key_env if coglossa is not None else None
     if key_env and os.environ.get(key_env) is None:
         add("error", f"integrations.coglossa: environment variable {key_env} is not set")
+    if isinstance(cfg.storage, S3StorageConfig):
+        for var in (cfg.storage.access_key_id_env, cfg.storage.secret_access_key_env):
+            if not os.environ.get(var):
+                add("error", f"storage: environment variable {var} is not set")
     return issues
 
 
@@ -308,6 +346,9 @@
         raise ConfigError(f"{path}: {_first_error(e)}") from e
     # Relative paths are relative to the config file (spec §11).
     base = path.resolve().parent
+    storage = cfg.storage
+    if isinstance(storage, StorageConfig):
+        storage = storage.model_copy(update={"path": (base / storage.path).resolve()})
     cfg = cfg.model_copy(
         update={
             "prompts_dir": _resolve(base, cfg.prompts_dir),
@@ -315,7 +356,7 @@
                 update={"packs_dir": _resolve(base, cfg.standards.packs_dir)}
             ),
             "api": cfg.api.model_copy(update={"web_dir": _resolve(base, cfg.api.web_dir)}),
-            "storage": cfg.storage.model_copy(update={"path": (base / cfg.storage.path).resolve()}),
+            "storage": storage,
         }
     )
     issues = validate_config(cfg)
````

````diff
--- a/engine/corelata/storage.py
+++ b/engine/corelata/storage.py
@@ -1,18 +1,21 @@
 """Stored files (spec §4.2 `storage`, §11): uploaded sources, the reference document of a run and
-the worker's exports, behind a Storage interface with a local-volume implementation.
-Keys are relative '/'-separated paths; nothing outside the storage root is reachable."""
+the worker's exports, behind a Storage interface with a local-volume implementation and an S3
+one (the hosted demo, copied from Coglossa). Keys are relative '/'-separated paths; nothing
+outside the storage root is reachable. Every call blocks: callers on the event loop run them in
+`asyncio.to_thread`."""
 
 import contextlib
 import os
 import re
 import shutil
 import tempfile
+import uuid
 from collections.abc import Iterator
 from contextlib import AbstractContextManager
 from pathlib import Path, PurePosixPath
-from typing import Protocol
-
-from corelata.config import StorageConfig
+from typing import Any, Protocol
+
+from corelata.config import S3StorageConfig, StorageConfig
 
 
 class StorageError(Exception):
@@ -58,20 +61,20 @@
     return _CONTROL.sub(" ", base).strip()
 
 
+def check_key(key: str) -> list[str]:
+    """The key's parts; raises StorageError for a key that could escape the storage root."""
+    parts = key.split("/")
+    if not key or key.startswith("/") or "\\" in key or any(p in ("", ".", "..") for p in parts):
+        raise StorageError(f"invalid storage key: {key!r}")
+    return parts
+
+
 class LocalStorage:
     def __init__(self, root: Path) -> None:
         self.root = root
 
     def _path(self, key: str) -> Path:
-        parts = key.split("/")
-        if (
-            not key
-            or key.startswith("/")
-            or "\\" in key
-            or any(p in ("", ".", "..") for p in parts)
-        ):
-            raise StorageError(f"invalid storage key: {key!r}")
-        return self.root.joinpath(*parts)
+        return self.root.joinpath(*check_key(key))
 
     def put(self, key: str, data: bytes) -> None:
         path = self._path(key)
@@ -157,5 +160,145 @@
             ) from e
 
 
-def build_storage(cfg: StorageConfig) -> Storage:
-    return LocalStorage(cfg.path)  # kind is validated by StorageConfig (local only in v1)
+class S3Storage:
+    """Files in an S3-compatible bucket. boto3 comes with the `s3` extra and is imported here,
+    so a local-storage install neither needs nor loads it (the air-gapped image has none).
+    Supabase Storage needs path-style addressing. Copied from Coglossa; `list_keys` is
+    Corelata's (the worker clears a restarted run's stale exports with it)."""
+
+    def __init__(self, cfg: S3StorageConfig, *, client: Any | None = None) -> None:
+        self.cfg = cfg
+        if client is None:
+            try:
+                import boto3
+                from botocore.config import Config
+            except ImportError as e:
+                raise StorageError("S3 storage needs the s3 extra: install corelata[s3]") from e
+
+            keys = {}
+            for field, var in (
+                ("aws_access_key_id", cfg.access_key_id_env),
+                ("aws_secret_access_key", cfg.secret_access_key_env),
+            ):
+                value = os.environ.get(var)
+                if not value:
+                    raise StorageError(f"environment variable {var} is not set")
+                keys[field] = value
+            client = boto3.client(
+                "s3",
+                endpoint_url=cfg.endpoint_url,
+                region_name=cfg.region,
+                config=Config(
+                    s3={"addressing_style": "path"},
+                    retries={"mode": "standard"},
+                    # boto3 1.36+ adds checksums to every upload by default, which some
+                    # S3-compatible stores refuse; send and check them only where S3 requires
+                    request_checksum_calculation="when_required",
+                    response_checksum_validation="when_required",
+                ),
+                **keys,
+            )
+        self._s3 = client
+
+    def _key(self, key: str) -> str:
+        check_key(key)
+        prefix = self.cfg.prefix.strip("/")
+        return f"{prefix}/{key}" if prefix else key
+
+    def _under(self, prefix: str) -> list[str]:
+        """Every object key under `prefix` + "/", as stored (with the configured prefix)."""
+        pages = self._s3.get_paginator("list_objects_v2").paginate(
+            Bucket=self.cfg.bucket, Prefix=prefix + "/"
+        )
+        return [o["Key"] for page in pages for o in page.get("Contents", [])]
+
+    def put(self, key: str, data: bytes) -> None:
+        try:
+            self._s3.put_object(Bucket=self.cfg.bucket, Key=self._key(key), Body=data)
+        except _s3_errors() as e:
+            raise StorageError(f"cannot store {key}: {_reason(e)}") from e
+
+    def get(self, key: str) -> bytes:
+        try:
+            got = self._s3.get_object(Bucket=self.cfg.bucket, Key=self._key(key))
+            return got["Body"].read()
+        except _s3_errors() as e:
+            if _code(e) in ("NoSuchKey", "404"):
+                raise StorageError(f"stored file not found: {key}") from e
+            raise StorageError(f"cannot read {key}: {_reason(e)}") from e
+
+    @contextlib.contextmanager
+    def local_file(self, key: str) -> Iterator[Path]:
+        data = self.get(key)  # ingestors pick a format by the suffix, so the temp file keeps it
+        fd, name = tempfile.mkstemp(suffix=PurePosixPath(key).suffix, prefix="corelata-")
+        path = Path(name)
+        try:
+            with os.fdopen(fd, "wb") as f:
+                f.write(data)
+            yield path
+        finally:
+            path.unlink(missing_ok=True)
+
+    def delete_prefix(self, prefix: str) -> None:
+        base = self._key(prefix.rstrip("/"))
+        try:
+            # One DeleteObject per key, not DeleteObjects: Supabase's S3 API refuses that with
+            # a bare 400 whatever its parameters, and a run or a source holds a handful of files.
+            for key in [base, *self._under(base)]:
+                self._s3.delete_object(Bucket=self.cfg.bucket, Key=key)
+        except _s3_errors() as e:
+            raise StorageError(f"cannot delete {prefix}: {_reason(e)}") from e
+
+    def list_keys(self, prefix: str) -> list[str]:
+        """Keys under a prefix, sorted and without the configured prefix, as LocalStorage gives
+        them; [] when nothing is stored there."""
+        base = self._key(prefix.rstrip("/"))
+        own = len(base) - len(prefix.rstrip("/"))  # the configured prefix and its "/"
+        try:
+            return sorted(key[own:] for key in self._under(base))
+        except _s3_errors() as e:
+            raise StorageError(f"cannot list {prefix}: {_reason(e)}") from e
+
+    def check_writable(self) -> None:
+        probe = self._key(f".corelata-check-{uuid.uuid4().hex}")
+        try:
+            self._s3.put_object(Bucket=self.cfg.bucket, Key=probe, Body=b"")
+            self._s3.delete_object(Bucket=self.cfg.bucket, Key=probe)
+        except _s3_errors() as e:
+            raise StorageError(
+                f"storage bucket {self.cfg.bucket} at {self.cfg.endpoint_url or 'AWS S3'} "
+                f"is not writable: {_reason(e)}"
+            ) from e
+
+
+def _s3_errors() -> tuple[type[Exception], ...]:
+    from botocore.exceptions import BotoCoreError, ClientError
+
+    return (BotoCoreError, ClientError)
+
+
+def _code(e: Exception) -> str:
+    return str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
+
+
+def _reason(e: Exception) -> str:
+    error = getattr(e, "response", {}).get("Error", {})
+    if error:
+        return f"{error.get('Code', '')}: {error.get('Message', '')}".strip(": ")
+    return " ".join(str(e).split())
+
+
+def describe_storage(cfg: StorageConfig | S3StorageConfig) -> str:
+    """Where files are kept, for doctor and the logs: the path, or s3://bucket[/prefix] [at
+    endpoint]."""
+    if isinstance(cfg, StorageConfig):
+        return str(cfg.path)
+    prefix = cfg.prefix.strip("/")
+    where = f"s3://{cfg.bucket}" + (f"/{prefix}" if prefix else "")
+    return f"{where} at {cfg.endpoint_url}" if cfg.endpoint_url else where
+
+
+def build_storage(cfg: StorageConfig | S3StorageConfig) -> Storage:
+    if isinstance(cfg, S3StorageConfig):
+        return S3Storage(cfg)
+    return LocalStorage(cfg.path)
````

````diff
--- a/engine/corelata/doctor.py
+++ b/engine/corelata/doctor.py
@@ -40,7 +40,7 @@
 from corelata.stages.audit import auditor_payload
 from corelata.stages.audit_schema import audit_output_type, to_audit_output
 from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN, PackError, list_packs
-from corelata.storage import StorageError, build_storage
+from corelata.storage import StorageError, build_storage, describe_storage
 from corelata.store.db import redact
 from corelata.store.migrate import connect_error, migration_state
 from corelata.worker.execute import DB_ERRORS
@@ -654,8 +654,13 @@
 
 
 def _storage(cfg: CorelataConfig) -> DoctorCheck:
+    fix = (
+        "fix storage (bucket, endpoint_url, keys)"
+        if cfg.storage.kind == "s3"
+        else "fix storage.path or its permissions"
+    )
     try:
         build_storage(cfg.storage).check_writable()
     except StorageError as e:
-        return _check("storage", CheckStatus.FAIL, str(e), "fix storage.path or its permissions")
-    return _check("storage", CheckStatus.PASS, f"{cfg.storage.path} is writable")
+        return _check("storage", CheckStatus.FAIL, str(e), fix)
+    return _check("storage", CheckStatus.PASS, f"{describe_storage(cfg.storage)} is writable")
````

- [ ] **Step 5: The image check**

````diff
--- a/deploy/tests/check-app-image.sh
+++ b/deploy/tests/check-app-image.sh
@@ -14,6 +14,9 @@
 run corelata --version | grep -qF "$label" || die "corelata --version does not carry the image version ($label)"
 [ "$(run sh -c 'echo $CORELATA_BUILD_VERSION')" = "$label" ] || die "CORELATA_BUILD_VERSION must equal the image version label"
 run corelata-api --help >/dev/null || die "corelata-api --help does not work"
+# M19: the S3 client belongs to the hosted demo (the `s3` extra); the air-gapped image has none.
+run python -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("boto3") is not None)' \
+  || die "boto3 is in the image: the app image must not install the s3 extra"
 [ "$(run sh -c 'echo $CORELATA_CONFIG')" = /etc/corelata/corelata.yaml ] \
   || die "CORELATA_CONFIG must be /etc/corelata/corelata.yaml"
 run test -f /opt/corelata/web/index.html || die "the web app is missing (/opt/corelata/web/index.html)"
````

- [ ] **Step 6: Run the tests to see them pass**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_storage_s3.py tests/test_storage.py tests/test_config.py tests/test_doctor.py --no-cov -q`
Expected: PASS (`test_storage_s3.py` collects 25 tests).

- [ ] **Step 7: The gates**

Run: `make test-engine` (expected 1012 passed, coverage at or above 95%), `make test-api` (174 passed: the API is unchanged but its environment now has the extra declared), `make lint`, and `make image-app` (builds the image with the new locks and runs `check-app-image.sh`; expected the last line `ok: corelata/app:dev`; remove the image afterwards with `docker rmi corelata/app:dev` if you do not keep it).

- [ ] **Step 8: Commit**

```bash
git -C <repo> add engine/corelata/config.py engine/corelata/storage.py engine/corelata/doctor.py engine/pyproject.toml engine/uv.lock api/pyproject.toml api/uv.lock engine/tests/test_storage_s3.py engine/tests/test_config.py engine/tests/test_doctor.py deploy/tests/check-app-image.sh
git -C <repo> commit -F "$SCRATCH/m19-t1-msg.txt"   # "feat(engine): storage.kind s3 for the hosted demo (CRL-42)" + the two lines
```

---

### Task 2: Every storage call off the event loop (`storage_call`)

**Files:**
- Modify: `engine/corelata/storage.py` (`storage_call`), `engine/corelata/service.py` (`add_source`, `_create_run`, `review_run`, `stored_export`, `reference_document`), `engine/corelata/worker/execute.py` (`_reference`, `execute_run`), `engine/corelata/doctor.py` (`run_doctor`), `engine/tests/test_service.py` (`test_add_source_parses_off_the_event_loop`)
- Create: `engine/tests/test_storage_calls.py`

**Interfaces:**
- Consumes: Task 1's `storage.py` (`Any` is imported there).
- Produces: `async def storage_call[T](fn: Callable[..., T], *args: Any) -> T` in `corelata.storage`, the one way the service, the worker and doctor reach storage from the loop (R-M19-4).

- [ ] **Step 1: Write the failing tests**

`engine/tests/test_storage_calls.py`, whole:

````python
"""M19 (spec §12.1): every storage call on the API's and the worker's event loop runs in a
thread, because on the hosted demo each one is a request to S3; and `storage_call` waits for its
thread even when cancelled, so a cleanup never runs beside the call it undoes (R-M19-4)."""

import asyncio
import contextlib
import dataclasses
import threading

import pytest

from corelata import service
from corelata.ingest.base import IngestError
from corelata.schema import ReviewAction, RunState
from corelata.storage import LocalStorage, storage_call
from corelata.store import runs
from tests.worker.conftest import drain, make_services, submit
from tests.worker.test_execute import _house_pack


async def test_storage_call_returns_the_result_and_raises_the_calls_error():
    assert await storage_call(lambda a, b: a + b, 2, 3) == 5

    def broken():
        raise OSError("disk gone")

    with pytest.raises(OSError, match="disk gone"):
        await storage_call(broken)


async def test_a_cancelled_storage_call_waits_for_its_thread_then_raises_the_cancellation():
    started, release, done = threading.Event(), threading.Event(), []

    def slow_put():
        started.set()
        release.wait(5)
        done.append("stored")

    task = asyncio.create_task(storage_call(slow_put))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()  # still waiting for the thread: a cleanup must not start yet
    task.cancel()  # a second cancellation changes nothing
    await asyncio.sleep(0.05)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done == ["stored"]


async def test_a_cancelled_call_that_failed_still_raises_the_cancellation():
    started, release = threading.Event(), threading.Event()

    def failing():
        started.set()
        release.wait(5)
        raise OSError("refused")

    task = asyncio.create_task(storage_call(failing))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


class LoopWatchingStorage(LocalStorage):
    """Local storage that records each call and whether it ran on an event loop's thread."""

    def __init__(self, root) -> None:
        super().__init__(root)
        self.calls: list[str] = []
        self.on_loop: list[str] = []

    def _seen(self, name: str) -> None:
        self.calls.append(name)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # a worker thread: what we want
        self.on_loop.append(name)

    def put(self, key, data):
        self._seen("put")
        super().put(key, data)

    def get(self, key):
        self._seen("get")
        return super().get(key)

    @contextlib.contextmanager
    def local_file(self, key):
        self._seen("local_file")  # when it is entered: S3Storage downloads the file then
        with super().local_file(key) as path:
            yield path

    def delete_prefix(self, prefix):
        self._seen("delete_prefix")
        super().delete_prefix(prefix)

    def list_keys(self, prefix):
        self._seen("list_keys")
        return super().list_keys(prefix)


async def test_service_and_worker_storage_calls_run_off_the_event_loop(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    storage = LoopWatchingStorage(tmp_path / "watched")
    svc = dataclasses.replace(svc, storage=storage)
    # an upload, and one that is refused after it was stored (its file is deleted)
    run_id = await submit(svc, profile="east")  # stores the source and the reference document
    pid = (await service.run_progress(db, run_id)).project_id
    with pytest.raises(IngestError):
        await service.add_source(db, storage, pid, "empty.pdf", b"not a pdf")
    # the worker: a restarted run clears its stale files, reads the reference, stores exports
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state, run.attempts = "drafting", 1
    storage.put(f"runs/{run_id}/stale.bin", b"x")  # the test's own call, from the loop
    storage.on_loop.clear()
    await drain(svc)
    assert (await service.run_progress(db, run_id)).state is RunState.COMPLETED
    # the API's reads, and a return that copies the reference document
    assert await service.reference_document(db, storage, run_id)
    assert await service.stored_export(db, storage, run_id, "report.json")
    child = await service.review_run(
        db,
        storage,
        svc.queue,
        svc.cfg,
        svc.prompts,
        run_id,
        ReviewAction.RETURN,
        note="Tighten it.",
    )
    assert child is not None
    assert {"put", "get", "local_file", "delete_prefix", "list_keys"} <= set(storage.calls)
    assert storage.on_loop == []


async def test_a_failed_return_removes_the_reruns_reference_copy_off_the_loop(
    db, fake_backend, tmp_path, monkeypatch
):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    storage = LoopWatchingStorage(tmp_path / "watched")
    svc = dataclasses.replace(svc, storage=storage)
    run_id = await submit(svc, profile="east")
    await drain(svc)

    async def refused(*args, **kwargs):
        raise RuntimeError("the review event could not be written")

    monkeypatch.setattr(runs, "add_review_event", refused)
    storage.on_loop.clear()
    with pytest.raises(RuntimeError, match="could not be written"):
        await service.review_run(
            db, storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN, note="n"
        )
    assert [k for k in storage.list_keys("runs") if not k.startswith(f"runs/{run_id}/")] == []
    assert storage.on_loop == ["list_keys"]  # only the line above, from the test itself
````

The M14 test that spies on `asyncio.to_thread` now sees the upload's `put` as well (it is stored off the loop too):

````diff
--- a/engine/tests/test_service.py
+++ b/engine/tests/test_service.py
@@ -450,7 +450,7 @@
     monkeypatch.setattr(service.asyncio, "to_thread", spy)
     pid = await svc.project()
     await svc.source(pid)
-    assert seen == ["_parse_stored"]
+    assert seen == ["put", "_parse_stored"]  # M19: the upload is stored off the loop too
 
 
 class _DownApp:
````

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_storage_calls.py tests/test_service.py -k "storage_call or event_loop or off_the_loop" --no-cov -q`
Expected: `ImportError: cannot import name 'storage_call' from 'corelata.storage'`.

- [ ] **Step 3: `storage_call`**

````diff
--- a/engine/corelata/storage.py
+++ b/engine/corelata/storage.py
@@ -4,13 +4,14 @@
 outside the storage root is reachable. Every call blocks: callers on the event loop run them in
 `asyncio.to_thread`."""
 
+import asyncio
 import contextlib
 import os
 import re
 import shutil
 import tempfile
 import uuid
-from collections.abc import Iterator
+from collections.abc import Callable, Iterator
 from contextlib import AbstractContextManager
 from pathlib import Path, PurePosixPath
 from typing import Any, Protocol
@@ -34,6 +35,27 @@
     def list_keys(self, prefix: str) -> list[str]: ...
 
     def check_writable(self) -> None: ...
+
+
+async def storage_call[T](fn: Callable[..., T], *args: Any) -> T:
+    """`fn(*args)` (a Storage method) in a thread, off the event loop: on the hosted demo each
+    call is a request to S3. It is waited for to its end even when the awaiting task is cancelled
+    meanwhile, and the cancellation is raised after it, so a cleanup that follows (a
+    `delete_prefix` in an `except BaseException`) never runs beside the `put` it undoes, and no
+    cancellation can stop a cleanup half way (R-M15-3, R-M19-4)."""
+    call = asyncio.ensure_future(asyncio.to_thread(fn, *args))
+    cancelled: asyncio.CancelledError | None = None
+    while not call.done():
+        try:
+            await asyncio.shield(call)
+        except asyncio.CancelledError as e:
+            cancelled = e  # the thread cannot be stopped: wait for it, then pass this on
+        except Exception:  # noqa: BLE001 - the call's own error, raised by result() below
+            pass
+    if cancelled is not None:
+        call.exception()  # retrieved: a failure of the call is not reported as unhandled
+        raise cancelled
+    return call.result()
 
 
 _UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
````

- [ ] **Step 4: The call sites (R-M19-4's list)**

````diff
--- a/engine/corelata/service.py
+++ b/engine/corelata/service.py
@@ -38,7 +38,7 @@
     Usage,
 )
 from corelata.standards.loader import pack_hash
-from corelata.storage import Storage, StorageError, display_name, safe_filename
+from corelata.storage import Storage, StorageError, display_name, safe_filename, storage_call
 from corelata.store import discoveries, records, runs
 from corelata.store.db import Database, error_reason
 from corelata.store.models import Project, ReviewEvent, Run, SourceRow, utcnow
@@ -273,7 +273,7 @@
     prefix = f"projects/{project_id}/sources/{source_id}/"
     key = prefix + safe_filename(name)
     try:
-        storage.put(key, data)
+        await storage_call(storage.put, key, data)
         parsed = await asyncio.to_thread(_parse_stored, storage, key, coglossa_export)
         parsed[0] = parsed[0].model_copy(update={"name": name})
         ids: list[uuid.UUID] = []
@@ -289,7 +289,7 @@
                 ids.append(row.id)
     except BaseException:
         with contextlib.suppress(StorageError):  # nothing points at the file
-            storage.delete_prefix(prefix)
+            await storage_call(storage.delete_prefix, prefix)
         raise
     return ids
 
@@ -349,7 +349,7 @@
 
     try:
         if key is not None:
-            storage.put(key, reference)
+            await storage_call(storage.put, key, reference)
         if session is not None:
             await insert(session)
         else:
@@ -358,7 +358,7 @@
     except BaseException:
         if key is not None:
             with contextlib.suppress(StorageError):
-                storage.delete_prefix(f"runs/{run_id}/")
+                await storage_call(storage.delete_prefix, f"runs/{run_id}/")
         raise
     return run_id
 
@@ -546,7 +546,11 @@
                     f"run {run_id} was already returned; its rerun is {earlier.child_run_id}. "
                     "Return that run to iterate again"
                 )
-            reference = storage.get(run.docx_reference_key) if run.docx_reference_key else None
+            reference = (
+                await storage_call(storage.get, run.docx_reference_key)
+                if run.docx_reference_key
+                else None
+            )
             guidance = f"{run.extra_guidance}\nReviewer note: {note.strip()}".strip()
             child = await _create_run(
                 db,
@@ -573,11 +577,11 @@
             await _store_review_state(s, run_id)
     except BaseException:
         # Nothing committed, so the database has nothing to undo. The rerun's copy of the
-        # reference document goes with plain file calls: no await, so no CancelledError, can
-        # stop it half way (R-M15-3).
+        # reference document goes in a thread that storage_call waits for even when cancelled,
+        # so no CancelledError can stop it half way (R-M15-3, R-M19-4).
         if child is not None:
             with contextlib.suppress(StorageError):
-                storage.delete_prefix(f"runs/{child}/")
+                await storage_call(storage.delete_prefix, f"runs/{child}/")
         raise
     await _defer_run(db, queue, child)
     return child
@@ -701,7 +705,7 @@
         row = next((r for r in await runs.list_exports(s, run_id) if r.name == name), None)
     if row is None:
         return None
-    return await asyncio.to_thread(storage.get, row.storage_key)
+    return await storage_call(storage.get, row.storage_key)
 
 
 async def get_run_record(db: Database, run_id: uuid.UUID) -> RunRecord:
@@ -713,7 +717,9 @@
     """The DOCX reference the run was queued with, or None when its profile names none."""
     async with db.session() as s:
         run = await runs.get_run(s, run_id)
-    return storage.get(run.docx_reference_key) if run.docx_reference_key else None
+    if not run.docx_reference_key:
+        return None
+    return await storage_call(storage.get, run.docx_reference_key)
 
 
 # ---------------------------------------------------------------- discovery (spec §7.1)
````

````diff
--- a/engine/corelata/worker/execute.py
+++ b/engine/corelata/worker/execute.py
@@ -9,7 +9,7 @@
 import contextlib
 import logging
 import uuid
-from collections.abc import Iterator
+from collections.abc import AsyncIterator
 from dataclasses import dataclass
 from datetime import datetime
 from pathlib import Path
@@ -42,7 +42,7 @@
 from corelata.stages.context import StageError
 from corelata.standards.loader import PackError
 from corelata.standards.schema import ResolvedPack
-from corelata.storage import Storage, StorageError
+from corelata.storage import Storage, StorageError, storage_call
 from corelata.store import discoveries, records, runs
 from corelata.store.db import Database
 from corelata.store.models import Run, utcnow
@@ -196,13 +196,20 @@
     return [k for k in storage.list_keys(prefix) if k not in keep]
 
 
-@contextlib.contextmanager
-def _reference(storage: Storage, key: str | None) -> Iterator[Path | None]:
+@contextlib.asynccontextmanager
+async def _reference(storage: Storage, key: str | None) -> AsyncIterator[Path | None]:
+    """The run's stored reference document as a local file. Fetching it (a download from S3 on
+    the hosted demo) runs off the event loop; the local copy is removed on the way out, a file
+    operation that needs no thread (R-M19-5)."""
     if key is None:
         yield None
         return
-    with storage.local_file(key) as path:
+    stored = storage.local_file(key)
+    path = await storage_call(stored.__enter__)
+    try:
         yield path
+    finally:
+        stored.__exit__(None, None, None)
 
 
 def _render(record: RunRecord, pack: ResolvedPack) -> tuple[dict[str, bytes], str | None]:
@@ -280,14 +287,14 @@
         # The dead attempt's files: its rows are gone (clear_trace), its files must follow, but
         # never the reference document, which the new attempt renders with.
         keep = {inputs.docx_reference_key} if inputs.docx_reference_key else set()
-        for key in _stray_files(svc.storage, f"runs/{run_id}/", keep):
+        for key in await storage_call(_stray_files, svc.storage, f"runs/{run_id}/", keep):
             with contextlib.suppress(StorageError):
-                svc.storage.delete_prefix(key)
+                await storage_call(svc.storage.delete_prefix, key)
     observer = DbObserver(svc.db, run_id, svc.call_log())
     phase = "failed"
     try:
         pack = ResolvedPack.model_validate(inputs.pack_snapshot)
-        with _reference(svc.storage, inputs.docx_reference_key) as reference:
+        async with _reference(svc.storage, inputs.docx_reference_key) as reference:
             pack.docx_reference_path = reference
             record = await run_report(
                 svc.cfg,
@@ -326,7 +333,7 @@
                 run.export_error = export_error
                 for name, data in files.items():
                     key = f"runs/{run_id}/{name}"
-                    svc.storage.put(key, data)
+                    await storage_call(svc.storage.put, key, data)
                     await runs.add_export(s, run_id, name, key, data)
                 await runs.notify_run(s, run_id)
                 await reruns_ended(s, [run_id])  # every outcome is terminal (R-M15-2)
````

````diff
--- a/engine/corelata/doctor.py
+++ b/engine/corelata/doctor.py
@@ -40,7 +40,7 @@
 from corelata.stages.audit import auditor_payload
 from corelata.stages.audit_schema import audit_output_type, to_audit_output
 from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN, PackError, list_packs
-from corelata.storage import StorageError, build_storage, describe_storage
+from corelata.storage import StorageError, build_storage, describe_storage, storage_call
 from corelata.store.db import redact
 from corelata.store.migrate import connect_error, migration_state
 from corelata.worker.execute import DB_ERRORS
@@ -206,7 +206,8 @@
     checks.append(_guard("pack names", lambda: _pack_names(cfg)))
     checks += await _backends(cfg, probe, backends_factory)
     checks.append(await _aguard("database", lambda: _database(cfg)))
-    checks.append(_guard("storage", lambda: _storage(cfg)))
+    # off the event loop: the API runs doctor for Settings, and S3 is a network call
+    checks.append(await storage_call(_guard, "storage", lambda: _storage(cfg)))
     checks.append(await _aguard("coglossa", lambda: _coglossa(cfg, probe, coglossa_transport)))
     return DoctorReport.of(checks)
 
````

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_storage_calls.py tests/test_service.py tests/test_return.py tests/worker tests/test_doctor.py --no-cov -q`
Expected: PASS. `test_service_and_worker_storage_calls_run_off_the_event_loop` sees `put`, `get`, `local_file`, `delete_prefix` and `list_keys` and none on the loop; the M15 return tests (`tests/test_return.py`) and the M17 worker tests pass unchanged.

- [ ] **Step 6: The gates**

Run: `make test-engine` (expected 1017 passed), `make lint`.

- [ ] **Step 7: Commit**

```bash
git -C <repo> add engine/corelata/storage.py engine/corelata/service.py engine/corelata/worker/execute.py engine/corelata/doctor.py engine/tests/test_storage_calls.py engine/tests/test_service.py
git -C <repo> commit -F "$SCRATCH/m19-t2-msg.txt"   # "fix(engine): storage calls off the event loop, waited for when cancelled (CRL-42)" + the two lines
```

---

### Task 3: The proxy secret (copied from Coglossa)

**Files:**
- Create (copied, renamed and adapted; given whole): `api/corelata_api/proxy.py`, `api/tests/test_proxy.py`
- Modify: `engine/corelata/config.py` (`AuthConfig.proxy_secret_env`, `validate_config`), `engine/corelata/doctor.py` (`_hosted`), `api/corelata_api/app.py` (`create_app`)
- Test: `api/tests/test_proxy.py`, `engine/tests/test_config.py`, `engine/tests/test_doctor.py`

**Interfaces:**
- Consumes: nothing beyond Task 2.
- Produces: `AuthConfig.proxy_secret_env: str | None = None`; `corelata_api.proxy.PROXY_SECRET_HEADER = "X-Corelata-Proxy-Secret"`, `OPEN_PATHS = frozenset({"/api/health"})`, `ProxySecretMiddleware(app, secret)`; `corelata.doctor._hosted(cfg) -> list[DoctorCheck]` (Task 4 adds its `worker` line).

- [ ] **Step 1: Write the failing tests**

`api/tests/test_proxy.py`, whole (Coglossa's, with `/api/system/info` for `/api/me`, no teams, and the forged-user test of Review Focus 3):

````python
"""M19 (spec §12.1): auth.proxy_secret_env and ProxySecretMiddleware, copied from Coglossa."""

import asyncio
import json

import pytest

from corelata_api.proxy import PROXY_SECRET_HEADER, ProxySecretMiddleware
from tests.conftest import set_run_state, start_run

SECRET = "s3cret-" * 5
AUTH = {"mode": "trusted_header", "proxy_secret_env": "CORELATA_PROXY_SECRET"}
SIGNED_IN = {"X-Remote-User": "ana"}
WITH_SECRET = {**SIGNED_IN, PROXY_SECRET_HEADER: SECRET}
REFUSED = {"detail": "this address only answers requests from the Corelata sign-in proxy"}


@pytest.fixture
def secret_env(monkeypatch):
    monkeypatch.setenv("CORELATA_PROXY_SECRET", SECRET)


async def test_requests_without_the_secret_are_refused(secret_env, make_api, tmp_path):
    web_dir = tmp_path / "dist"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<title>Corelata</title>", encoding="utf-8")
    async with make_api(auth=AUTH, api={"web_dir": str(web_dir), "progress_poll_s": 0.02}) as api:
        client = api.client
        missing = await client.get("/api/system/info", headers=SIGNED_IN)
        assert missing.status_code == 401 and missing.json() == REFUSED
        wrong_secret = {**SIGNED_IN, PROXY_SECRET_HEADER: "x"}
        wrong = await client.get("/api/system/info", headers=wrong_secret)
        assert wrong.status_code == 401
        ok = await client.get("/api/system/info", headers=WITH_SECRET)
        assert ok.status_code == 200 and ok.json()["user"] == "ana"
        assert (await client.get("/api/health")).status_code == 200
        assert (await client.get("/")).status_code == 401
        assert (await client.get("/", headers={PROXY_SECRET_HEADER: SECRET})).status_code == 200


async def test_a_forged_user_without_the_secret_reaches_nothing(secret_env, make_api):
    """Review Focus 3: a caller holding the Modal token Coglossa shares (spec §23.5) but not
    Corelata's own secret gets nothing, whatever user it claims, and changes nothing."""
    async with make_api(auth=AUTH) as api:
        forged = {"X-Remote-User": "people-first", "Modal-Key": "wk", "Modal-Secret": "ws"}
        for method, path in [
            ("GET", "/api/projects"),
            ("POST", "/api/projects"),
            ("GET", "/api/openapi.json"),
            ("GET", "/api/system/doctor"),
        ]:
            response = await api.client.request(method, path, headers=forged, json={"name": "x"})
            assert (response.status_code, response.json()) == (401, REFUSED), (method, path)
        listed = await api.client.get("/api/projects", headers=WITH_SECRET)
        assert listed.json() == []  # the refused POST created nothing


async def test_the_progress_stream_still_streams(secret_env, make_api):
    async with make_api(auth=AUTH) as api:
        api.client.headers.update(WITH_SECRET)
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "completed")
        refused = await api.client.get(
            f"/api/runs/{run['run_id']}/events", headers={PROXY_SECRET_HEADER: ""}
        )
        assert refused.status_code == 401
        async with asyncio.timeout(5):
            response = await api.client.get(f"/api/runs/{run['run_id']}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    data = next(line for line in response.text.splitlines() if line.startswith("data: "))
    assert json.loads(data[len("data: ") :])["state"] == "completed"


async def test_the_middleware_passes_chunks_on_as_they_come():
    """httpx's in-process transport collects whole bodies, so check the streaming at the ASGI
    level: the first chunk must reach the client while the app is still producing the rest."""
    release = asyncio.Event()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await release.wait()
        await send({"type": "http.response.body", "body": b"last", "more_body": False})

    sent = []
    first = asyncio.Event()

    async def send(message):
        sent.append(message)
        if message.get("body") == b"first":
            first.set()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "path": "/api/runs/x/events",
        "headers": [(PROXY_SECRET_HEADER.lower().encode(), SECRET.encode())],
    }
    task = asyncio.create_task(ProxySecretMiddleware(app, SECRET)(scope, receive, send))
    async with asyncio.timeout(5):
        await first.wait()
    assert not task.done()  # still streaming
    release.set()
    await task
    assert [m.get("body") for m in sent[1:]] == [b"first", b"last"]


async def test_other_protocols_pass_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    await ProxySecretMiddleware(app, SECRET)({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]


async def test_without_the_setting_nothing_changes(api):
    response = await api.client.get("/api/system/info")
    assert response.status_code == 200 and response.json()["user"] is None
````

````diff
--- a/engine/tests/test_config.py
+++ b/engine/tests/test_config.py
@@ -313,3 +313,24 @@
     )
     assert s3.storage.kind == "s3" and s3.storage.bucket == "bkt" and issues == []
     assert config_hash(s3) == config_hash(local)  # storage is operational
+
+
+# M19: auth.proxy_secret_env (copied from Coglossa, spec §12.1)
+
+
+def test_proxy_secret_is_off_by_default(make_config):
+    assert make_config().auth.proxy_secret_env is None
+
+
+def test_proxy_secret_env_must_be_set(tmp_path, monkeypatch):
+    monkeypatch.delenv("CORELATA_PROXY_SECRET", raising=False)
+    path = _write(tmp_path, {**BASE_CONFIG, "auth": {"proxy_secret_env": "CORELATA_PROXY_SECRET"}})
+    with pytest.raises(ConfigError, match="auth: environment variable CORELATA_PROXY_SECRET"):
+        load_config(path)
+    monkeypatch.setenv("CORELATA_PROXY_SECRET", "")  # empty is as good as unset
+    with pytest.raises(ConfigError, match="CORELATA_PROXY_SECRET is not set"):
+        load_config(path)
+    monkeypatch.setenv("CORELATA_PROXY_SECRET", "s" * 32)
+    cfg, _ = load_config(path)
+    assert cfg.auth.proxy_secret_env == "CORELATA_PROXY_SECRET"
+    assert config_hash(cfg) == config_hash(load_config(_write(tmp_path, BASE_CONFIG))[0])
````

````diff
--- a/engine/tests/test_doctor.py
+++ b/engine/tests/test_doctor.py
@@ -1194,6 +1194,19 @@
     assert check.fix == "fix storage (bucket, endpoint_url, keys)"
 
 
+async def test_the_proxy_secret_line_only_when_it_is_set(tmp_path, server, monkeypatch):
+    plain = _by_name(await run_doctor(_config(tmp_path, server.base_url), probe=False))
+    assert "auth" not in plain
+    monkeypatch.setenv("CORELATA_PROXY_SECRET", "s" * 32)
+    path = _config(tmp_path, server.base_url, auth={"proxy_secret_env": "CORELATA_PROXY_SECRET"})
+    check = _by_name(await run_doctor(path, probe=False))["auth"]
+    assert check.status is CheckStatus.PASS
+    assert check.message == (
+        "requests without the X-Corelata-Proxy-Secret header (CORELATA_PROXY_SECRET) are "
+        "refused, /api/health excepted"
+    )
+
+
 async def test_local_storage_names_its_path(tmp_path, server):
     report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
     check = _by_name(report)["storage"]
````

- [ ] **Step 2: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_proxy.py --no-cov -q`
Expected: `ModuleNotFoundError: No module named 'corelata_api.proxy'`. And `cd engine && uv run pytest tests/test_config.py -k proxy --no-cov -q`: FAIL with `extra_forbidden` on `auth.proxy_secret_env`.

- [ ] **Step 3: The setting, the middleware, the doctor line**

````diff
--- a/engine/corelata/config.py
+++ b/engine/corelata/config.py
@@ -206,6 +206,10 @@
     # the proxy's own sign-out page: the web app's header shows "Sign out" and posts there
     # (copied from Coglossa, M18 spec §7.3); unset, no Sign out is shown
     logout_url: str | None = None
+    # A secret the authenticating proxy adds to every request (header X-Corelata-Proxy-Secret);
+    # requests without it are refused, /api/health excepted. For an API whose address is
+    # reachable without the proxy, such as the hosted demo's (copied from Coglossa, M19).
+    proxy_secret_env: str | None = None
 
     @field_validator("header")
     @classmethod
@@ -311,6 +315,8 @@
         for var in (cfg.storage.access_key_id_env, cfg.storage.secret_access_key_env):
             if not os.environ.get(var):
                 add("error", f"storage: environment variable {var} is not set")
+    if cfg.auth.proxy_secret_env and not os.environ.get(cfg.auth.proxy_secret_env):
+        add("error", f"auth: environment variable {cfg.auth.proxy_secret_env} is not set")
     return issues
 
 
````

`api/corelata_api/proxy.py`, whole:

````python
"""Refuse requests that did not come through the authenticating proxy (the hosted demo's front
door, M19 spec §12.1; copied from Coglossa). A pure ASGI middleware, not BaseHTTPMiddleware, so
streamed responses (the progress events) pass through unbuffered."""

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

PROXY_SECRET_HEADER = "X-Corelata-Proxy-Secret"
OPEN_PATHS = frozenset({"/api/health"})  # liveness checks never carry the secret


class ProxySecretMiddleware:
    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self._secret = secret.encode()
        self._header = PROXY_SECRET_HEADER.lower().encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        given = next((v for k, v in scope["headers"] if k == self._header), b"")
        if hmac.compare_digest(given, self._secret):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "this address only answers requests from the Corelata sign-in proxy"},
            status_code=401,
        )
        await response(scope, receive, send)
````

````diff
--- a/api/corelata_api/app.py
+++ b/api/corelata_api/app.py
@@ -4,6 +4,7 @@
 import asyncio
 import contextlib
 import logging
+import os
 from collections.abc import AsyncIterator, Callable
 from contextlib import AbstractAsyncContextManager
 from pathlib import Path
@@ -27,6 +28,7 @@
 from corelata_api.errors import ErrorBody, install_error_handlers
 from corelata_api.pack_index import PackIndex
 from corelata_api.progress_feed import ProgressFeed
+from corelata_api.proxy import ProxySecretMiddleware
 from corelata_api.render_cache import RenderCache
 from corelata_api.routes import ROUTERS
 from corelata_api.run_listener import Connect, RunListener, listen_connection
@@ -131,6 +133,9 @@
         redoc_url=None,
     )
     install_error_handlers(app)
+    if cfg.auth.proxy_secret_env:
+        # validate_config refused an unset variable, so the value is there
+        app.add_middleware(ProxySecretMiddleware, secret=os.environ[cfg.auth.proxy_secret_env])
     app.include_router(health)
     protected = APIRouter(
         prefix="/api",
````

````diff
--- a/engine/corelata/doctor.py
+++ b/engine/corelata/doctor.py
@@ -209,7 +209,25 @@
     # off the event loop: the API runs doctor for Settings, and S3 is a network call
     checks.append(await storage_call(_guard, "storage", lambda: _storage(cfg)))
     checks.append(await _aguard("coglossa", lambda: _coglossa(cfg, probe, coglossa_transport)))
+    checks += _hosted(cfg)
     return DoctorReport.of(checks)
+
+
+def _hosted(cfg: CorelataConfig) -> list[DoctorCheck]:
+    """The hosted demo's settings (M19), each a line only when it is set. validate_config has
+    already failed the config check for a variable that is not set; the kick URL is never called
+    here, since a call would start a worker."""
+    checks = []
+    if cfg.auth.proxy_secret_env:
+        checks.append(
+            _check(
+                "auth",
+                CheckStatus.PASS,
+                f"requests without the X-Corelata-Proxy-Secret header ({cfg.auth.proxy_secret_env})"
+                " are refused, /api/health excepted",
+            )
+        )
+    return checks
 
 
 async def _coglossa(
````

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_proxy.py tests/test_app.py tests/test_system.py --no-cov -q` and `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_config.py tests/test_doctor.py --no-cov -q`
Expected: PASS.

- [ ] **Step 5: The gates**

Run: `make test-engine` (1020 passed), `make test-api` (180 passed), `make lint`, `make schema` then `git -C <repo> status --short schema web/src/api` (expected: nothing; no API model changed).

- [ ] **Step 6: Commit**

```bash
git -C <repo> add engine/corelata/config.py engine/corelata/doctor.py api/corelata_api/proxy.py api/corelata_api/app.py api/tests/test_proxy.py engine/tests/test_config.py engine/tests/test_doctor.py
git -C <repo> commit -F "$SCRATCH/m19-t3-msg.txt"   # "feat(api): refuse requests without the front door's proxy secret (CRL-42)" + the two lines
```

---

### Task 4: The kick (copied from Coglossa, priority passed through)

**Files:**
- Create (copied, renamed and adapted; given whole): `engine/corelata/worker/kick.py`
- Copy from Coglossa (with the patch below): `engine/tests/worker/test_kick.py` (Coglossa's is `engine/tests/test_kick.py`; Corelata keeps worker tests under `tests/worker/`)
- Create: `api/tests/test_kick.py`
- Modify: `engine/corelata/config.py` (`WorkerConfig`, `env_headers`, `validate_config`), `engine/corelata/doctor.py` (`_hosted`), `api/corelata_api/app.py` (the lifespan)
- Test: those three, `engine/tests/test_config.py`, `engine/tests/test_doctor.py`

**Interfaces:**
- Consumes: Task 3's `_hosted`.
- Produces: `WorkerConfig.kick_url: str | None`, `kick_token_env: str | None`, `extra_headers_env: dict[str, str]`; `corelata.config.env_headers(names) -> dict[str, str]`; `corelata.worker.kick.HttpKicker(url, token, *, min_interval_s=2.0, timeout_s=5.0, extra_headers=None, transport=None, clock=time.monotonic)` with `kick()`, `drain()`, `aclose()`, `url`, `token`; `KickingQueue(inner, kicker)` with `defer(task, *, lock=None, priority=0, **kwargs)`, `inner`, `kicker`; `build_kicker(cfg: WorkerConfig) -> HttpKicker | None`.

- [ ] **Step 1: Write the failing tests**

Copy `$COGLOSSA/engine/tests/test_kick.py` to `engine/tests/worker/test_kick.py`, run the rename on it, then apply (Corelata's two priority tests at the end):

````diff
--- a/engine/tests/worker/test_kick.py
+++ b/engine/tests/worker/test_kick.py
@@ -160,3 +160,38 @@
     kicker = build_kicker(cfg)
     assert kicker is not None and kicker._client.headers["modal-key"] == "wk-1"
     assert "authorization" not in kicker._client.headers
+
+
+# Corelata's own (spec §12.1): priority passes through, so a discovery still goes first.
+
+
+async def test_the_queue_passes_the_priority_through():
+    seen, transport = _recorder()
+    kicker = HttpKicker("https://k/", None, transport=transport, min_interval_s=0)
+    inner = RecordingQueue()
+    queue = KickingQueue(inner, kicker)
+    await queue.defer("corelata.discover", lock="discovery:1", priority=1, discovery_id="1")
+    await queue.defer("corelata.run", lock="run:1", run_id="1")
+    assert [(j.task, j.priority) for j in inner.jobs] == [
+        ("corelata.discover", 1),
+        ("corelata.run", 0),
+    ]
+    await kicker.drain()
+    assert len(seen) == 2
+    await kicker.aclose()
+
+
+async def test_a_discovery_queued_through_the_service_keeps_its_priority(db, tmp_path):
+    from corelata import service
+    from corelata.storage import LocalStorage
+
+    seen, transport = _recorder()
+    kicker = HttpKicker("https://k/", None, transport=transport)
+    inner = RecordingQueue()
+    pid = await service.create_project(db, "p")
+    sid = (await service.add_source(db, LocalStorage(tmp_path), pid, "a.txt", b"The port grew."))[0]
+    await service.start_discovery(db, KickingQueue(inner, kicker), pid, [sid])
+    assert [j.priority for j in inner.jobs] == [service.DISCOVERY_PRIORITY]
+    await kicker.drain()
+    assert len(seen) == 1
+    await kicker.aclose()
````

`api/tests/test_kick.py`, whole:

````python
"""M19 (spec §12.1): with worker.kick_url set, every job the API queues also kicks a worker."""

from corelata.worker.kick import KickingQueue

from tests.conftest import start_run


async def test_the_queue_kicks_a_worker_only_when_configured(make_api, monkeypatch):
    async with make_api() as plain:
        assert not isinstance(plain.app.state.ctx.queue, KickingQueue)
    monkeypatch.setenv("KICK_TOKEN", "t")
    # port 9 refuses at once: the kick fails, is logged, and the request is not held up
    worker = {"kick_url": "http://127.0.0.1:9/", "kick_token_env": "KICK_TOKEN"}
    async with make_api(worker=worker) as api:
        queue = api.app.state.ctx.queue
        assert isinstance(queue, KickingQueue) and queue.kicker.token == "t"
        assert queue.inner is api.queue
        run = await start_run(api)  # 202: the kick's failure never reaches the caller
        assert [j.kwargs for j in api.queue.jobs] == [{"run_id": run["run_id"]}]
        await queue.kicker.drain()
    assert queue.kicker._client.is_closed  # closed with the app
````

````diff
--- a/engine/tests/test_config.py
+++ b/engine/tests/test_config.py
@@ -334,3 +334,42 @@
     cfg, _ = load_config(path)
     assert cfg.auth.proxy_secret_env == "CORELATA_PROXY_SECRET"
     assert config_hash(cfg) == config_hash(load_config(_write(tmp_path, BASE_CONFIG))[0])
+
+
+# M19: worker.kick_url, kick_token_env, extra_headers_env (copied from Coglossa, spec §12.1)
+
+
+def test_the_kick_is_off_by_default_and_its_url_must_be_http(make_config):
+    worker = make_config().worker
+    assert (worker.kick_url, worker.kick_token_env, worker.extra_headers_env) == (None, None, {})
+    assert make_config(worker={"kick_url": "https://k/x"}).worker.kick_url == "https://k/x"
+    with pytest.raises(ValidationError, match="must be an http:// or https:// URL"):
+        make_config(worker={"kick_url": "ftp://k/x"})
+
+
+def test_extra_header_names_must_be_http_tokens(make_config):
+    with pytest.raises(ValidationError, match="'Modal Key' is not an HTTP header name"):
+        make_config(worker={"extra_headers_env": {"Modal Key": "K"}})
+
+
+def test_the_kick_variables_must_be_set(tmp_path, monkeypatch):
+    monkeypatch.setenv("KICK_TOKEN", "t")
+    monkeypatch.setenv("PLATFORM_KEY", "k")
+    monkeypatch.delenv("PLATFORM_SECRET", raising=False)
+    worker = {
+        "kick_url": "https://k/",
+        "kick_token_env": "KICK_TOKEN",
+        "extra_headers_env": {"Modal-Key": "PLATFORM_KEY", "Modal-Secret": "PLATFORM_SECRET"},
+    }
+    path = _write(tmp_path, {**BASE_CONFIG, "worker": worker})
+    with pytest.raises(ConfigError, match="worker: environment variable PLATFORM_SECRET") as e:
+        load_config(path)
+    assert "PLATFORM_KEY" not in str(e.value) and "KICK_TOKEN" not in str(e.value)
+    monkeypatch.delenv("KICK_TOKEN")
+    with pytest.raises(ConfigError, match="KICK_TOKEN is not set .and 1 more problem"):
+        load_config(path)
+    monkeypatch.setenv("KICK_TOKEN", "t")
+    monkeypatch.setenv("PLATFORM_SECRET", "s")
+    cfg, _ = load_config(path)
+    assert cfg.worker.extra_headers_env == worker["extra_headers_env"]
+    assert config_hash(cfg) == config_hash(load_config(_write(tmp_path, BASE_CONFIG))[0])
````

````diff
--- a/engine/tests/test_doctor.py
+++ b/engine/tests/test_doctor.py
@@ -1207,6 +1207,16 @@
     )
 
 
+async def test_the_worker_line_only_with_a_kick_url_which_is_never_called(tmp_path, server):
+    plain = _by_name(await run_doctor(_config(tmp_path, server.base_url), probe=False))
+    assert "worker" not in plain
+    # an address nothing answers: the line passes without a request (a kick starts a worker)
+    path = _config(tmp_path, server.base_url, worker={"kick_url": "https://kick.invalid/"})
+    check = _by_name(await run_doctor(path))["worker"]
+    assert check.status is CheckStatus.PASS
+    assert check.message == "kicks https://kick.invalid/ when a job is queued"
+
+
 async def test_local_storage_names_its_path(tmp_path, server):
     report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
     check = _by_name(report)["storage"]
````

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_kick.py --no-cov -q`
Expected: `ModuleNotFoundError: No module named 'corelata.worker.kick'`.

- [ ] **Step 3: The settings, the kicker, the lifespan, the doctor line**

````diff
--- a/engine/corelata/config.py
+++ b/engine/corelata/config.py
@@ -184,6 +184,34 @@
     # the start limit: a discovery the worker has not claimed this long after it was created
     # (the worker stopped, or busy with runs) is failed the same way (R-M17-26)
     discovery_start_deadline_s: float = Field(3600.0, ge=60)
+    # POSTed after each queued job, so an on-demand worker starts (the hosted demo, copied from
+    # Coglossa, M19); unset: an always-on worker polls the queue
+    kick_url: str | None = None
+    kick_token_env: str | None = None  # sent as "Authorization: Bearer <value>"
+    # more headers for the kick, each {header name: name of the variable holding its value},
+    # e.g. a hosting platform's own access token
+    extra_headers_env: dict[str, str] = Field(default_factory=dict)
+
+    @field_validator("kick_url")
+    @classmethod
+    def _http_url(cls, value: str | None) -> str | None:
+        if value is not None and not value.startswith(("http://", "https://")):
+            raise ValueError("must be an http:// or https:// URL")
+        return value
+
+    @field_validator("extra_headers_env")
+    @classmethod
+    def _header_names(cls, value: dict[str, str]) -> dict[str, str]:
+        for name in value:
+            if not _HTTP_TOKEN.fullmatch(name):
+                raise ValueError(f"{name!r} is not an HTTP header name: {_HEADER_NAME_HELP}")
+        return value
+
+
+def env_headers(names: dict[str, str]) -> dict[str, str]:
+    """{header: variable name} to {header: the variable's value}; validate_config has made
+    sure each variable is set."""
+    return {header: os.environ.get(var, "") for header, var in names.items()}
 
 
 class ApiConfig(_Strict):
@@ -195,6 +223,7 @@
 
 
 _HTTP_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
+_HEADER_NAME_HELP = "letters, digits and !#$%&'*+-.^_`|~, without spaces (e.g. Modal-Key)"
 
 
 class AuthConfig(_Strict):
@@ -317,6 +346,9 @@
                 add("error", f"storage: environment variable {var} is not set")
     if cfg.auth.proxy_secret_env and not os.environ.get(cfg.auth.proxy_secret_env):
         add("error", f"auth: environment variable {cfg.auth.proxy_secret_env} is not set")
+    for var in [cfg.worker.kick_token_env, *cfg.worker.extra_headers_env.values()]:
+        if var and not os.environ.get(var):
+            add("error", f"worker: environment variable {var} is not set")
     return issues
 
 
````

`engine/corelata/worker/kick.py`, whole:

````python
"""Starting an on-demand worker (the hosted demo, M19 spec §12.1; copied from Coglossa). After a
job is queued the API posts to `worker.kick_url`; the POST runs in the background and a failure
is only logged, because the cron also starts workers (spec §13.5)."""

import asyncio
import logging
import os
import time
from collections.abc import Callable, Mapping

import httpx

from corelata.config import WorkerConfig, env_headers
from corelata.service import JobQueue

log = logging.getLogger("corelata.worker")


class HttpKicker:
    def __init__(
        self,
        url: str,
        token: str | None,
        *,
        min_interval_s: float = 2.0,
        timeout_s: float = 5.0,
        extra_headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.token = token
        self._min_interval = min_interval_s
        self._clock = clock
        self._last: float | None = None
        self._pending: set[asyncio.Task[None]] = set()
        headers = dict(extra_headers or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(timeout=timeout_s, headers=headers, transport=transport)

    def kick(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._min_interval:
            return  # one worker start covers jobs queued moments apart
        self._last = now
        task = asyncio.get_running_loop().create_task(self._post())
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _post(self) -> None:
        try:
            response = await self._client.post(self.url)
            response.raise_for_status()
        except Exception as e:  # kick never raises: a bad URL (InvalidURL) is not an HTTPError
            log.warning("worker kick failed: %s", " ".join(f"{type(e).__name__}: {e}".split()))

    async def drain(self) -> None:
        await asyncio.gather(*self._pending, return_exceptions=True)

    async def aclose(self) -> None:
        # kicks are best-effort (the cron is the backstop): do not hold shutdown for them
        pending = list(self._pending)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self._client.aclose()


class KickingQueue:
    """A JobQueue that kicks a worker after each job it queues. Corelata passes `priority`
    through (a discovery is fetched ahead of waiting runs, R-M17-29)."""

    def __init__(self, inner: JobQueue, kicker: HttpKicker) -> None:
        self.inner = inner
        self.kicker = kicker

    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None:
        await self.inner.defer(task, lock=lock, priority=priority, **kwargs)
        self.kicker.kick()


def build_kicker(cfg: WorkerConfig) -> HttpKicker | None:
    if cfg.kick_url is None:
        return None
    token = os.environ.get(cfg.kick_token_env) if cfg.kick_token_env else None
    return HttpKicker(cfg.kick_url, token, extra_headers=env_headers(cfg.extra_headers_env))
````

````diff
--- a/api/corelata_api/app.py
+++ b/api/corelata_api/app.py
@@ -21,6 +21,7 @@
 from corelata.store.db import Database, database_url
 from corelata.version import build_version
 from corelata.worker.app import ProcrastinateQueue, open_app
+from corelata.worker.kick import KickingQueue, build_kicker
 from fastapi import APIRouter, Depends, FastAPI, Request
 
 from corelata_api.auth import current_user
@@ -99,6 +100,10 @@
         listener = asyncio.create_task(RunListener(listener_connect(db.url), feed).run())
         try:
             async with open_queue(db.url) as queue:
+                # the hosted demo: each queued job also starts an on-demand worker (M19)
+                kicker = build_kicker(cfg.worker)
+                if kicker is not None:
+                    queue = KickingQueue(queue, kicker)
                 app.state.ctx = ApiContext(
                     cfg=cfg,
                     config_path=config_path,
@@ -115,7 +120,11 @@
                     progress=feed,
                     packs=PackIndex(cfg.standards.packs_dir),
                 )
-                yield
+                try:
+                    yield
+                finally:
+                    if kicker is not None:
+                        await kicker.aclose()
         finally:
             try:
                 await stop_listener(listener)
````

````diff
--- a/engine/corelata/doctor.py
+++ b/engine/corelata/doctor.py
@@ -218,6 +218,10 @@
     already failed the config check for a variable that is not set; the kick URL is never called
     here, since a call would start a worker."""
     checks = []
+    if cfg.worker.kick_url:
+        checks.append(
+            _check("worker", CheckStatus.PASS, f"kicks {cfg.worker.kick_url} when a job is queued")
+        )
     if cfg.auth.proxy_secret_env:
         checks.append(
             _check(
````

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_kick.py tests/test_config.py tests/test_doctor.py --no-cov -q` and `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_kick.py tests/test_app.py --no-cov -q`
Expected: PASS (`tests/worker/test_kick.py` collects 13).

- [ ] **Step 5: The gates**

Run: `make test-engine` (1037 passed), `make test-api` (181 passed), `make lint`.

- [ ] **Step 6: Commit**

```bash
git -C <repo> add engine/corelata/config.py engine/corelata/doctor.py engine/corelata/worker/kick.py api/corelata_api/app.py engine/tests/worker/test_kick.py api/tests/test_kick.py engine/tests/test_config.py engine/tests/test_doctor.py
git -C <repo> commit -F "$SCRATCH/m19-t4-msg.txt"   # "feat: kick an on-demand worker after each queued job (CRL-42)" + the two lines
```

---

### Task 5: The queue's status, the cron pass and the purge pass

**Files:**
- Modify: `engine/corelata/worker/app.py`
- Create: `engine/tests/worker/test_on_demand.py`

**Interfaces:**
- Consumes: the existing `sweep_orphans`, `expire_discoveries`, `purge_closed_jobs`, `ORPHAN_GRACE_S`, `_PENDING_SQL`, `open_app`, `QUEUE`.
- Produces: `corelata.worker.app.QueueStatus(due, stalled, live_worker)` with `has_work`, `needs_worker`; `async queue_status(url: str, stalled_after_s: float) -> QueueStatus`; `async needs_worker(url, stalled_after_s) -> bool`; `async cron_pass(cfg: CorelataConfig) -> bool`; `async purge_pass(cfg: CorelataConfig) -> int`. Task 6's `worker`, `cron` and `purge` call them.

- [ ] **Step 1: Write the failing tests**

`engine/tests/worker/test_on_demand.py`, whole (the first five are Coglossa's, on Corelata's helpers):

````python
"""M19 (spec §12.1, §13.5): what the hosted demo's on-demand worker, cron and purge read and do,
on a real Postgres. queue_status and needs_worker are copied from Coglossa with their tests;
cron_pass and purge_pass are Corelata's."""

import dataclasses
from datetime import timedelta

from sqlalchemy import text

from corelata import service
from corelata.schema import DiscoveryState, RunState
from corelata.store.db import Database
from corelata.store.models import utcnow
from corelata.worker import app as worker_app
from corelata.worker.app import (
    ORPHAN_GRACE_S,
    ProcrastinateQueue,
    QueueStatus,
    cron_pass,
    needs_worker,
    open_app,
    purge_pass,
    queue_status,
    run_worker,
)
from corelata.worker.sweep import ORPHAN_ERROR
from tests.conftest import build_config
from tests.worker.conftest import make_services, submit


async def _register_worker(db, *, heartbeat_age_s=0):
    async with db.engine.begin() as conn:
        worker_id = (
            await conn.execute(text("SELECT worker_id FROM procrastinate_register_worker_v1()"))
        ).scalar_one()
        await conn.execute(
            text(
                "UPDATE procrastinate_workers"
                " SET last_heartbeat = now() - make_interval(secs => :a) WHERE id = :w"
            ),
            {"a": heartbeat_age_s, "w": worker_id},
        )
    return worker_id


async def _defer_run(pg_url, run_id="1"):
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(
            service.TASK_RUN, lock=f"run:{run_id}", run_id=run_id
        )


async def test_an_empty_queue_needs_no_worker(db, pg_url):
    assert await queue_status(pg_url, 60) == QueueStatus(
        due=False, stalled=False, live_worker=False
    )
    assert not await needs_worker(pg_url, 60)


async def test_a_due_job_without_a_live_worker_needs_one(db, pg_url):
    await _defer_run(pg_url)
    await _register_worker(db, heartbeat_age_s=600)  # a dead worker's row is not a live one
    status = await queue_status(pg_url, 60)
    assert (status.due, status.live_worker, status.has_work) == (True, False, True)
    assert await needs_worker(pg_url, 60)


async def test_a_live_worker_fetches_due_jobs_itself(db, pg_url):
    await _defer_run(pg_url)
    await _register_worker(db)
    status = await queue_status(pg_url, 60)
    assert (status.due, status.live_worker, status.has_work) == (True, True, True)
    assert not await needs_worker(pg_url, 60)


async def test_a_stalled_job_needs_a_worker(db, pg_url):
    await _defer_run(pg_url)
    dead = await _register_worker(db, heartbeat_age_s=600)
    await _register_worker(db)  # even with another worker alive: someone must re-queue it
    async with db.engine.begin() as conn:
        await conn.execute(
            text("UPDATE procrastinate_jobs SET status = 'doing', worker_id = :w"), {"w": dead}
        )
    status = await queue_status(pg_url, 60)
    assert (status.due, status.stalled, status.has_work) == (False, True, True)
    assert await needs_worker(pg_url, 60)


async def test_a_job_running_on_a_live_worker_needs_none(db, pg_url):
    await _defer_run(pg_url)
    live = await _register_worker(db)
    async with db.engine.begin() as conn:
        await conn.execute(
            text("UPDATE procrastinate_jobs SET status = 'doing', worker_id = :w"), {"w": live}
        )
    status = await queue_status(pg_url, 60)
    assert not status.has_work and not status.needs_worker


def _cfg(monkeypatch, pg_url, **worker):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    return build_config(worker={"stalled_after_s": 120, **worker})


async def test_cron_pass_starts_a_worker_for_a_run_whose_kick_was_lost(
    db, pg_url, fake_backend, tmp_path, monkeypatch
):
    """Review Focus 1: a run queued while its kick failed (the placeholder URL of the first
    deploy, a 5xx, a timeout) still gets a worker from the next cron tick."""
    cfg = _cfg(monkeypatch, pg_url)
    assert not await cron_pass(cfg)  # nothing queued: no worker, no Modal bill
    svc = make_services(db, fake_backend, tmp_path)
    async with open_app(pg_url) as opened:
        run_id = await submit(dataclasses.replace(svc, queue=ProcrastinateQueue(opened)))
    assert await cron_pass(cfg)
    assert (await service.run_progress(db, run_id)).state is RunState.CREATED  # left alone


async def test_cron_pass_ends_orphaned_runs_and_expired_discoveries(
    db, pg_url, fake_backend, tmp_path, monkeypatch
):
    cfg = _cfg(monkeypatch, pg_url, discovery_start_deadline_s=600)
    svc = make_services(db, fake_backend, tmp_path)
    orphan = await submit(svc)  # an in-memory queue: the run has no job in Postgres
    pid = (await service.run_progress(db, orphan)).project_id
    sources = [s.id for s in await service.list_sources(db, pid)]
    async with open_app(pg_url) as opened:
        waiting = await service.start_discovery(db, ProcrastinateQueue(opened), pid, sources)
    long_ago = utcnow() - timedelta(seconds=max(ORPHAN_GRACE_S, 600) + 60)
    async with db.engine.begin() as conn:
        await conn.execute(text("UPDATE run SET created_at = :t"), {"t": long_ago})
        await conn.execute(text("UPDATE discovery SET created_at = :t"), {"t": long_ago})
    assert await cron_pass(cfg)  # the discovery's job is still due, so a worker is wanted
    progress = await service.run_progress(db, orphan)
    assert progress.state is RunState.FAILED and progress.error == ORPHAN_ERROR.format(what="run")
    view = await service.get_discovery(db, waiting)
    assert view.state is DiscoveryState.FAILED
    assert view.error == service.discovery_start_error(600)


async def test_cron_pass_closes_its_database(db, pg_url, monkeypatch):
    disposed = []
    real = Database.dispose

    async def dispose(self):
        disposed.append(self.url)
        await real(self)

    monkeypatch.setattr(Database, "dispose", dispose)
    await cron_pass(_cfg(monkeypatch, pg_url))
    await purge_pass(_cfg(monkeypatch, pg_url))
    assert disposed == [pg_url, pg_url]


async def test_purge_pass_deletes_closed_jobs_older_than_the_retention(db, pg_url, monkeypatch):
    await _defer_run(pg_url, "old")
    await _defer_run(pg_url, "new")
    async with db.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE procrastinate_jobs SET status = 'failed', scheduled_at = now() - "
                "make_interval(days => CASE WHEN lock = 'run:old' THEN 40 ELSE 1 END)"
            )
        )
    assert await purge_pass(_cfg(monkeypatch, pg_url, job_retention_days=30)) == 1
    async with db.engine.connect() as conn:
        left = (await conn.execute(text("SELECT lock FROM procrastinate_jobs"))).scalars().all()
    assert left == ["run:new"]


async def test_an_idle_burst_worker_leaves_nothing_for_the_cron(
    db, pg_url, fake_backend, tmp_path, monkeypatch
):
    """A burst worker started on an empty queue (a late kick) defers procrastinate's periodic
    jobs, runs them and exits; it leaves no due job, so the cron does not start another one
    every five minutes (spec §10.2: nobody using it, Modal bills nothing)."""
    cfg = _cfg(monkeypatch, pg_url)
    svc = make_services(db, fake_backend, tmp_path)

    async def factory(cfg, queue):
        return dataclasses.replace(svc, db=Database(pg_url), queue=queue)

    await run_worker(cfg, burst=True, install_signal_handlers=False, services_factory=factory)
    assert not await needs_worker(pg_url, cfg.worker.stalled_after_s)
    assert not await cron_pass(cfg)
    assert worker_app.QUEUE == "corelata"
````

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_on_demand.py --no-cov -q`
Expected: `ImportError: cannot import name 'QueueStatus' from 'corelata.worker.app'`.

- [ ] **Step 3: The functions**

````diff
--- a/engine/corelata/worker/app.py
+++ b/engine/corelata/worker/app.py
@@ -6,6 +6,7 @@
 import contextlib
 import logging
 from collections.abc import AsyncIterator, Awaitable, Callable
+from dataclasses import dataclass
 from typing import Any
 
 import procrastinate
@@ -204,6 +205,82 @@
 """
 
 
+@dataclass(frozen=True)
+class QueueStatus:
+    """What an on-demand worker would find (the hosted demo, copied from Coglossa): jobs it could
+    run now, jobs left 'doing' by a worker that stopped sending heartbeats, and whether a worker
+    is alive."""
+
+    due: bool
+    stalled: bool
+    live_worker: bool
+
+    @property
+    def has_work(self) -> bool:
+        return self.due or self.stalled
+
+    @property
+    def needs_worker(self) -> bool:
+        # a live worker fetches due jobs itself; stalled jobs need a pass that re-queues them
+        return self.stalled or (self.due and not self.live_worker)
+
+
+# procrastinate's own heartbeat table; every worker registers there while it runs
+_LIVE_WORKERS_SQL = """
+SELECT count(*) AS live
+  FROM procrastinate_workers
+ WHERE last_heartbeat >= now() - make_interval(secs => %(seconds)s)
+"""
+
+
+async def queue_status(url: str, stalled_after_s: float) -> QueueStatus:
+    async with open_app(url) as opened:
+        pending = await opened.connector.execute_query_one_async(_PENDING_SQL, queue=QUEUE)
+        live = await opened.connector.execute_query_one_async(
+            _LIVE_WORKERS_SQL, seconds=stalled_after_s
+        )
+        stalled = await opened.job_manager.get_stalled_jobs(
+            queue=QUEUE, seconds_since_heartbeat=stalled_after_s
+        )
+    return QueueStatus(
+        due=bool(pending["due"]), stalled=bool(stalled), live_worker=bool(live["live"])
+    )
+
+
+async def needs_worker(url: str, stalled_after_s: float) -> bool:
+    """Whether the on-demand cron should start a worker: jobs are due and no worker is alive
+    to fetch them, or a dead worker left jobs stalled."""
+    return (await queue_status(url, stalled_after_s)).needs_worker
+
+
+async def cron_pass(cfg: CorelataConfig) -> bool:
+    """The hosted demo's cron, every 5 minutes (spec §13.5): the minute tasks a long-running
+    worker would run (fail orphaned runs and discoveries, then the discoveries past a deadline),
+    run directly against the database, since a burst worker is rarely alive at those minutes;
+    then whether to start a worker (`needs_worker`). Returns that answer (R-M19-9)."""
+    url = database_url(cfg)
+    db = Database(url)
+    try:
+        await sweep_orphans(db, grace_s=ORPHAN_GRACE_S)
+        await expire_discoveries(
+            db,
+            start_deadline_s=cfg.worker.discovery_start_deadline_s,
+            deadline_s=cfg.worker.discovery_deadline_s,
+        )
+    finally:
+        await db.dispose()
+    return await needs_worker(url, cfg.worker.stalled_after_s)
+
+
+async def purge_pass(cfg: CorelataConfig) -> int:
+    """The hosted demo's daily purge (spec §13.5): closed jobs older than the retention."""
+    db = Database(database_url(cfg))
+    try:
+        return await purge_closed_jobs(db, retention_days=cfg.worker.job_retention_days)
+    finally:
+        await db.dispose()
+
+
 async def _queue_settled(opened: procrastinate.App, stalled_after_s: float) -> bool:
     row = await opened.connector.execute_query_one_async(_PENDING_SQL, queue=QUEUE)
     if row["due"]:
````

- [ ] **Step 4: Run the tests to see them pass**

Run: the command of Step 2. Expected: 10 passed, including `test_an_idle_burst_worker_leaves_nothing_for_the_cron` (a burst worker started on an empty queue defers procrastinate's periodic jobs, runs them and leaves nothing due, so an idle demo starts no worker every 5 minutes).

- [ ] **Step 5: The gates**

Run: `make test-engine` (1047 passed, 98.50% in the scratch copy), `make lint`.

- [ ] **Step 6: Commit**

```bash
git -C <repo> add engine/corelata/worker/app.py engine/tests/worker/test_on_demand.py
git -C <repo> commit -F "$SCRATCH/m19-t5-msg.txt"   # "feat(worker): queue status, cron and purge passes for an on-demand worker (CRL-42)" + the two lines
```

---

### Task 6: The Modal app, its settings, the hosted config, start clean

**Files:**
- Copy from Coglossa and rename: `deploy/hosted/modal/conftest.py`, `deploy/hosted/modal/requirements.txt` (unchanged after the rename), `deploy/hosted/modal/check_app.py` (with the patch below). Not copied: `upload_weights.py`, `coglossa.hosted.yaml`.
- Create (whole): `deploy/hosted/corelata.hosted.yaml`, `deploy/hosted/modal/settings.py`, `deploy/hosted/modal/app.py`, `deploy/hosted/modal/test_settings.py`, `deploy/hosted/modal/start_clean.py`, `deploy/hosted/modal/test_start_clean.py`

**Interfaces:**
- Consumes: Tasks 1, 3 and 4's config (`S3StorageConfig`, `auth.proxy_secret_env`, the kick settings); Task 1's `S3Storage`, `list_keys`, `delete_prefix`; Task 5's `queue_status`, `cron_pass`, `purge_pass`; the existing `service.list_projects`, `corelata migrate`, `corelata doctor`, `corelata run --project`.
- Produces: `settings.HOSTED_TEMPLATE`, `EXAMPLE_PROJECT = "Example: Varna port"`, `EXAMPLE_SOURCE`, `STATEMENT`, `repo_root()`, `render_config()`, `check_kick()`, `seed_command(names) -> list[str] | None`; `app.APP_NAME = "corelata"`, `API_LABEL = "corelata-api"`, `KICK_LABEL = "corelata-kick"` and the eight functions; `start_clean.DATABASE`, `BUCKET`, `check_url()`, `tables()`, `clear_database(conn) -> int`, `clear_bucket(storage) -> int`, `main(argv) -> int`. Task 8's smoke test imports `settings.EXAMPLE_PROJECT`.

- [ ] **Step 1: Copy what is Coglossa's**

```bash
mkdir -p deploy/hosted/modal
cp "$COGLOSSA/deploy/hosted/modal/conftest.py" "$COGLOSSA/deploy/hosted/modal/requirements.txt" "$COGLOSSA/deploy/hosted/modal/check_app.py" deploy/hosted/modal/
python3 "$SCRATCH/rename.py" deploy/hosted/modal
```

- [ ] **Step 2: Write the failing tests**

`deploy/hosted/modal/test_settings.py`, whole (Coglossa's render and kick tests, Corelata's config and seed tests):

````python
import re
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from settings import (
    EXAMPLE_PROJECT,
    EXAMPLE_SOURCE,
    HERE,
    HOSTED_TEMPLATE,
    STATEMENT,
    check_kick,
    render_config,
    repo_root,
    seed_command,
)

ENV = {
    "CORELATA_S3_ENDPOINT": "https://ref.storage.supabase.co/storage/v1/s3",
    "CORELATA_S3_REGION": "ca-central-1",
    "CORELATA_KICK_URL": "https://ws--corelata-kick.modal.run",
}
SECRETS = [
    "OPENROUTER_API_KEY",
    "CORELATA_S3_ACCESS_KEY_ID",
    "CORELATA_S3_SECRET_ACCESS_KEY",
    "CORELATA_KICK_TOKEN",
    "CORELATA_PROXY_SECRET",
    "CORELATA_MODAL_KEY",
    "CORELATA_MODAL_SECRET",
]
SPEC = HERE.parents[2] / "docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md"


def test_render_fills_every_placeholder(tmp_path):
    out = render_config(HOSTED_TEMPLATE, tmp_path / "c.yaml", ENV)
    text = out.read_text(encoding="utf-8")
    assert "${" not in text
    data = yaml.safe_load(text)
    assert data["worker"]["kick_url"] == ENV["CORELATA_KICK_URL"]
    assert data["storage"]["endpoint_url"] == ENV["CORELATA_S3_ENDPOINT"]
    assert data["storage"]["region"] == "ca-central-1"


@pytest.mark.parametrize("missing", sorted(ENV))
def test_a_missing_value_names_the_variable(tmp_path, missing):
    with pytest.raises(KeyError, match=missing):
        render_config(
            HOSTED_TEMPLATE, tmp_path / "c.yaml", {k: v for k, v in ENV.items() if k != missing}
        )


def test_the_hosted_config_is_the_specs(tmp_path):
    """spec §14, the block under its heading, as data (comments aside)."""
    section = SPEC.read_text(encoding="utf-8").split("## 14. The hosted config", 1)[1]
    block = re.search(r"```yaml\n(.*?)```", section, re.S)
    assert block is not None
    assert yaml.safe_load(HOSTED_TEMPLATE.read_text(encoding="utf-8")) == yaml.safe_load(
        block.group(1)
    )


def test_the_rendered_config_is_valid(tmp_path, monkeypatch):
    corelata_config = pytest.importorskip("corelata.config")
    for var in SECRETS:
        monkeypatch.setenv(var, "x" * 32)
    cfg, issues = corelata_config.load_config(render_config(HOSTED_TEMPLATE, tmp_path / "c.yaml", ENV))
    assert [i for i in issues if i.level == "error"] == []
    assert (cfg.storage.kind, cfg.storage.bucket) == ("s3", "corelata-files")
    assert cfg.worker.extra_headers_env == {
        "Modal-Key": "CORELATA_MODAL_KEY",
        "Modal-Secret": "CORELATA_MODAL_SECRET",
    }
    # spec §13.4: a burst worker's limits
    worker = cfg.worker
    assert (worker.stalled_after_s, worker.discovery_start_deadline_s, worker.concurrency) == (
        120,
        600,
        4,
    )
    assert worker.discovery_deadline_s == 600
    # spec §13.1, §13.3, §23.6: the pooler's LISTEN path, Vercel's body limit
    assert (cfg.api.max_upload_mb, cfg.api.progress_poll_s, cfg.api.web_dir) == (4, 1.0, None)
    assert (cfg.auth.mode, cfg.auth.proxy_secret_env, cfg.auth.logout_url) == (
        "trusted_header",
        "CORELATA_PROXY_SECRET",
        "/logout",
    )
    assert cfg.integrations.coglossa is None and cfg.standards.packs_dir is None
    roles = dict(cfg.roles.all_roles())
    assert roles["auditor"] != roles["writer"]  # a different family checks the standards
    assert cfg.models[roles["auditor"]].name == "google/gemini-2.5-flash"


def test_the_rendered_config_needs_every_secret(tmp_path, monkeypatch):
    corelata_config = pytest.importorskip("corelata.config")
    for var in SECRETS:
        monkeypatch.setenv(var, "x" * 32)
    path = render_config(HOSTED_TEMPLATE, tmp_path / "c.yaml", ENV)
    for var in SECRETS:
        monkeypatch.delenv(var)
        with pytest.raises(corelata_config.ConfigError, match=var):
            corelata_config.load_config(path)
        monkeypatch.setenv(var, "x" * 32)


def test_check_kick():
    assert check_kick("Bearer abc", "abc")
    assert not check_kick("Bearer abd", "abc")
    assert not check_kick("abc", "abc")
    assert not check_kick(None, "abc")
    assert not check_kick("", "")  # no empty-token bypass of the "Bearer " prefix


def test_the_kick_endpoint_signature_works_under_fastapi():
    # Same signature style as kick() in app.py: a Header parameter resolvable in module globals.
    web = FastAPI()

    @web.post("/")
    def kick(authorization: str | None = Header(None)):
        if not check_kick(authorization, "tok"):
            return JSONResponse({"detail": "wrong kick token"}, status_code=401)
        return {"spawned": True}

    client = TestClient(web)
    right = client.post("/", headers={"Authorization": "Bearer tok"})
    assert (right.status_code, right.json()) == (200, {"spawned": True})
    assert client.post("/", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/").status_code == 401


def test_repo_root_locally_and_in_a_container():
    assert repo_root(HERE / "app.py", local=True) == HERE.parents[2]
    assert (repo_root(HERE / "app.py", local=True) / "engine" / "pyproject.toml").is_file()
    # Modal mounts app.py at /root/app.py: there is no repository around it
    assert repo_root("/root/app.py", local=False) == Path("/")


def test_seed_runs_only_when_the_example_is_missing():
    """Review Focus 5: a redeploy, or a second `modal run …::seed`, never writes a second
    example report (spec §13.6)."""
    command = seed_command(["Black Sea"])
    assert command == [
        "corelata",
        "run",
        "--project",
        EXAMPLE_PROJECT,
        "--statement",
        STATEMENT,
        EXAMPLE_SOURCE,
    ]
    assert seed_command([]) == command
    assert seed_command(["Black Sea", EXAMPLE_PROJECT]) is None
    assert seed_command(iter([EXAMPLE_PROJECT])) is None


def test_the_seed_uses_the_specs_statement_and_the_example_the_image_carries():
    assert EXAMPLE_PROJECT == "Example: Varna port"
    spec = " ".join(SPEC.read_text(encoding="utf-8").split())
    assert f'STATEMENT is a constant in `app.py`: "{STATEMENT}"' in spec
    assert (HERE.parents[2] / "docs" / "examples" / Path(EXAMPLE_SOURCE).name).is_file()
````

`deploy/hosted/modal/test_start_clean.py`, whole:

````python
"""Review Focus 4: starting the demo clean never touches Coglossa's database or bucket, which
share the Supabase project (spec §23.1). Runs in the engine's environment (CI `hosted-modal`)."""

import pytest

import start_clean

CORELATA_URL = "postgresql://postgres.ref:pw@aws-1-ca-central-1.pooler.supabase.com:5432/corelata?sslmode=require"


@pytest.mark.parametrize(
    "url",
    [
        CORELATA_URL.replace("/corelata?", "/postgres?"),  # the project's default: Coglossa's
        CORELATA_URL.replace("/corelata?", "/coglossa?"),
        CORELATA_URL.replace("/corelata?", "/corelata_old?"),
        CORELATA_URL.replace("/corelata?", "?"),  # no database at all
    ],
)
def test_any_database_but_corelata_is_refused(url):
    with pytest.raises(SystemExit, match="refusing: CORELATA_DATABASE_URL names the database"):
        start_clean.check_url(url)


def test_the_corelata_database_is_accepted():
    start_clean.check_url(CORELATA_URL)


class FakeConnection:
    def __init__(self, database: str) -> None:
        self.database = database
        self.statements: list[str] = []
        self.committed = False

    def execute(self, statement: str):
        self.statements.append(statement)
        return self

    def fetchone(self):
        return (self.database,)

    def commit(self) -> None:
        self.committed = True


def test_a_connection_to_another_database_truncates_nothing():
    conn = FakeConnection("postgres")
    with pytest.raises(SystemExit, match="refusing: connected to the database 'postgres'"):
        start_clean.clear_database(conn)
    assert conn.statements == ["SELECT current_database()"] and not conn.committed


def test_the_corelata_database_loses_its_rows_and_keeps_its_schema():
    conn = FakeConnection("corelata")
    assert start_clean.clear_database(conn) == len(start_clean.tables())
    truncate = conn.statements[1]
    assert truncate.startswith("TRUNCATE ") and truncate.endswith(" RESTART IDENTITY CASCADE")
    for table in ("project", "run", "source", "procrastinate_jobs", "procrastinate_workers"):
        assert f" {table}," in truncate or f" {table} " in truncate
    assert "alembic_version" not in truncate and conn.committed


@pytest.fixture
def buckets(monkeypatch):
    import boto3
    from moto import mock_aws

    monkeypatch.setenv("CORELATA_S3_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("CORELATA_S3_SECRET_ACCESS_KEY", "s")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        for bucket in ("corelata-files", "coglossa-files"):
            s3.create_bucket(Bucket=bucket)
            for key in ("projects/p/sources/s/a.txt", "runs/r/report.json"):
                s3.put_object(Bucket=bucket, Key=key, Body=b"x")
        yield s3


def _storage(bucket):
    from corelata.config import S3StorageConfig
    from corelata.storage import S3Storage

    return S3Storage(S3StorageConfig(kind="s3", bucket=bucket))


def test_the_bucket_is_emptied_and_coglossas_is_left_alone(buckets):
    assert start_clean.clear_bucket(_storage("corelata-files")) == 2
    assert buckets.list_objects_v2(Bucket="corelata-files").get("KeyCount") == 0
    assert buckets.list_objects_v2(Bucket="coglossa-files")["KeyCount"] == 2


def test_another_bucket_is_refused(buckets):
    with pytest.raises(SystemExit, match="refusing: the bucket is 'coglossa-files'"):
        start_clean.clear_bucket(_storage("coglossa-files"))
    assert buckets.list_objects_v2(Bucket="coglossa-files")["KeyCount"] == 2


def test_main_checks_before_it_connects(monkeypatch):
    for name in ("CORELATA_DATABASE_URL", "CORELATA_S3_ENDPOINT", "CORELATA_S3_REGION"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="CORELATA_DATABASE_URL, .* not set"):
        start_clean.main(["--yes"])
    monkeypatch.setenv("CORELATA_S3_ENDPOINT", "https://ref.storage.supabase.co/storage/v1/s3")
    monkeypatch.setenv("CORELATA_S3_REGION", "ca-central-1")
    monkeypatch.setenv("CORELATA_DATABASE_URL", CORELATA_URL.replace("/corelata?", "/postgres?"))
    with pytest.raises(SystemExit, match="refusing"):
        start_clean.main(["--yes"])
    monkeypatch.setenv("CORELATA_DATABASE_URL", CORELATA_URL)
    with pytest.raises(SystemExit, match="add --yes"):
        start_clean.main([])
````

- [ ] **Step 3: Run them to see them fail**

Run: `cd engine && CORELATA_FORBID_SKIP=1 uv run --with pyyaml --with fastapi --with httpx python -m pytest ../deploy/hosted/modal -q -p no:cacheprovider --no-cov --rootdir ../deploy/hosted/modal`
Expected: collection errors, `ModuleNotFoundError: No module named 'settings'` and `No module named 'start_clean'` (neither is written yet).

- [ ] **Step 4: The hosted config, the settings, the app, start clean**

`deploy/hosted/corelata.hosted.yaml`, whole (spec §14, R-M19-11):

````yaml
# Hosted demo (docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md).
# Placeholder values (dollar sign, braces, NAME) come from the Modal Secret corelata-hosted when a
# container starts (deploy/hosted/modal/settings.py); no secret is in this file.
# The config has no database pool-size setting; see README.md for the connection budget.
backends:
  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    max_concurrency: 4
    timeout_s: 300
models:
  writer-model:            # the gate, the writer and the editor: the bench pair (M12–M17)
    backend: openrouter
    name: openai/gpt-4.1-mini
    context_window: 128000
    structured_output: json_schema
    max_output_tokens: 8192
    temperature: 0.2
  auditor-model:           # a different family for the standards check (spec §4.4)
    backend: openrouter
    name: google/gemini-2.5-flash
    context_window: 128000
    structured_output: json_schema
    max_output_tokens: 8192
    temperature: 0.1
roles:
  gate:     { model: writer-model }
  writer:   { model: writer-model }
  conveyor: { model: writer-model }
  auditor:  { model: auditor-model }
  profiler: { model: writer-model }
standards:
  default_pack: icd203-base   # packs_dir unset: the base pack built into the engine
pipeline:
  max_iterations: 2
database:
  url_env: CORELATA_DATABASE_URL
storage:
  kind: s3
  endpoint_url: ${CORELATA_S3_ENDPOINT}
  region: ${CORELATA_S3_REGION}
  bucket: corelata-files
worker:
  concurrency: 4
  stalled_after_s: 120
  discovery_start_deadline_s: 600
  kick_url: ${CORELATA_KICK_URL}
  kick_token_env: CORELATA_KICK_TOKEN
  extra_headers_env: { Modal-Key: CORELATA_MODAL_KEY, Modal-Secret: CORELATA_MODAL_SECRET }
api:
  max_upload_mb: 4
  progress_poll_s: 1.0
auth:
  mode: trusted_header
  header: X-Remote-User
  proxy_secret_env: CORELATA_PROXY_SECRET
  logout_url: /logout
````

`deploy/hosted/modal/settings.py`, whole:

````python
"""Hosted demo settings shared by the Modal app and its tests; no Modal import here. Copied from
Coglossa's preview; the seed (spec §13.6) is Corelata's."""

import hmac
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
HOSTED_TEMPLATE = HERE.parent / "corelata.hosted.yaml"

# The example project the seed writes once (spec §13.6), from the file the image carries.
EXAMPLE_PROJECT = "Example: Varna port"
EXAMPLE_SOURCE = "/etc/corelata/examples/varna-port.txt"
STATEMENT = (
    "The port of Varna's 2025 container expansion, financed by a state bank, is already raising "
    "traffic; shippers and the port authority should plan for higher volumes."
)


def repo_root(app_file: str | Path, local: bool) -> Path:
    """The repository root, from deploy/hosted/modal/app.py. Inside a Modal container app.py
    is /root/app.py and nothing is read from the local tree (the image is already built), so
    any path will do there: "/" stands in for it."""
    return Path(app_file).resolve().parents[3] if local else Path("/")


def render_config(template: Path, out: Path, env: Mapping[str, str] = os.environ) -> Path:
    """The hosted config with ${NAME} filled from the environment (the Modal Secret). A
    missing value raises KeyError naming it, so the container fails at start, not mid-run."""
    out.write_text(Template(template.read_text(encoding="utf-8")).substitute(env), encoding="utf-8")
    return out


def check_kick(authorization: str | None, token: str) -> bool:
    """True when the Authorization header is exactly "Bearer <token>" (constant-time compare)."""
    return hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode())


def seed_command(project_names: Iterable[str]) -> list[str] | None:
    """The `corelata run` that queues the example report, or None when the example project
    already exists, so a redeploy never writes a second report (spec §13.6). The config comes
    from CORELATA_CONFIG, which the image sets."""
    if EXAMPLE_PROJECT in set(project_names):
        return None
    return ["corelata", "run", "--project", EXAMPLE_PROJECT, "--statement", STATEMENT, EXAMPLE_SOURCE]
````

`deploy/hosted/modal/app.py`, whole:

````python
"""Corelata hosted demo on Modal (spec §11, §12.2): the API, a burst worker, the kick, a cron, the
daily purge, and migrate, doctor and seed for the operator, all scaling to zero. Copied from
Coglossa's preview without the scorer. Deploy: modal deploy deploy/hosted/modal/app.py"""

import subprocess
from pathlib import Path

import modal
from fastapi import Header  # in the app image through the api's dependencies
from fastapi.responses import JSONResponse

from settings import EXAMPLE_SOURCE, HOSTED_TEMPLATE, check_kick, render_config, repo_root, seed_command

# A Modal container imports this file as /root/app.py, which has no repository around it.
REPO = repo_root(__file__, modal.is_local())
CONFIG = Path("/etc/corelata/corelata.hosted.yaml")  # the template, baked into the image
RENDERED = Path("/tmp/corelata.yaml")
IGNORE = [".venv", "**/__pycache__", "tests", "node_modules", "dist", "coverage", ".ruff_cache"]
APP_NAME = "corelata"
API_LABEL = "corelata-api"  # the web endpoint URLs are https://<workspace>--<label>.modal.run
KICK_LABEL = "corelata-kick"

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("corelata-hosted")

app_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("uv==0.13.0")
    .add_local_dir(REPO / "engine", "/src/engine", copy=True, ignore=IGNORE)
    .add_local_dir(REPO / "api", "/src/api", copy=True, ignore=IGNORE)
    .run_commands(
        # the locked dependencies, then the two projects, into the system Python Modal runs
        # --extra s3: boto3 for Supabase Storage (the air-gapped app image leaves it out)
        "cd /src/api && uv export --frozen --no-dev --extra s3 --no-emit-project --no-hashes"
        " | grep -v '^-e ' > /tmp/req.txt",
        "uv pip install --system -r /tmp/req.txt /src/engine /src/api",
    )
    .add_local_file(HOSTED_TEMPLATE, str(CONFIG), copy=True)
    .add_local_file(REPO / "docs" / "examples" / "varna-port.txt", EXAMPLE_SOURCE, copy=True)
    .env({"CORELATA_CONFIG": str(RENDERED)})
    .add_local_python_source("settings")  # not copied: must stay the last step
)


def _config():
    from corelata.config import load_config

    render_config(CONFIG, RENDERED)
    cfg, _ = load_config(RENDERED)
    return cfg


# Every web endpoint requires Modal proxy auth (Modal-Key/Modal-Secret headers): a request
# without them is refused by Modal and never starts a container. One API container: the
# database connection budget in README.md assumes it, and it holds the one LISTEN connection.
@app.function(
    image=app_image, secrets=[secret], cpu=1.0, memory=2048, scaledown_window=600, max_containers=1
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app(label=API_LABEL, requires_proxy_auth=True)
def api():
    from corelata_api.app import create_app

    return create_app(_config(), RENDERED)


@app.function(image=app_image, secrets=[secret], cpu=2.0, memory=4096, timeout=86400, max_containers=2)
def worker():
    import asyncio

    from corelata.store.db import database_url
    from corelata.worker.app import queue_status, run_worker

    cfg = _config()
    status = asyncio.run(queue_status(database_url(cfg), cfg.worker.stalled_after_s))
    if not status.has_work:
        return  # a late kick or a second spawn: exit at once
    asyncio.run(run_worker(cfg, burst=True, install_signal_handlers=False))


@app.function(image=app_image, secrets=[secret], cpu=0.25)
@modal.fastapi_endpoint(method="POST", label=KICK_LABEL, requires_proxy_auth=True)
def kick(authorization: str | None = Header(None)):
    import os

    if not check_kick(authorization, os.environ["CORELATA_KICK_TOKEN"]):
        return JSONResponse({"detail": "wrong kick token"}, status_code=401)
    worker.spawn()
    return {"spawned": True}


@app.function(image=app_image, secrets=[secret], cpu=0.25, schedule=modal.Period(minutes=5))
def cron():
    """The minute tasks a long-running worker would run (orphaned runs and discoveries, the
    discovery deadlines), then a worker when a job is waiting and none is alive (one queued as a
    worker decided to exit, a failed kick, a retry whose backoff has passed), or when a worker
    that died left jobs stalled (spec §13.5)."""
    import asyncio

    from corelata.worker.app import cron_pass

    if asyncio.run(cron_pass(_config())):
        worker.spawn()


@app.function(image=app_image, secrets=[secret], cpu=0.25, schedule=modal.Cron("17 3 * * *"))
def purge():
    """Closed jobs older than worker.job_retention_days, daily (spec §13.5)."""
    import asyncio

    from corelata.worker.app import purge_pass

    asyncio.run(purge_pass(_config()))


@app.function(image=app_image, secrets=[secret], timeout=900)
def migrate():
    render_config(CONFIG, RENDERED)
    subprocess.run(["corelata", "migrate"], check=True)


@app.function(image=app_image, secrets=[secret], timeout=900)
def doctor():
    render_config(CONFIG, RENDERED)
    subprocess.run(["corelata", "doctor"], check=False)


@app.function(image=app_image, secrets=[secret], timeout=900)
def seed():
    """Queue the example report once (spec §13.6), then start the deployed app's worker. A
    function spawned from `modal run` belongs to that run's short-lived app and would stop with
    it, so the worker is looked up by name (R-M19-12); the cron would start one within 5
    minutes anyway."""
    import asyncio

    from corelata import service
    from corelata.store.db import Database, database_url

    async def project_names() -> list[str]:
        db = Database(database_url(cfg))
        try:
            return [p.name for p in await service.list_projects(db)]
        finally:
            await db.dispose()

    cfg = _config()
    command = seed_command(asyncio.run(project_names()))
    if command is None:
        print("the example project exists: nothing to seed")
        return
    subprocess.run(command, check=True)
    modal.Function.from_name(APP_NAME, "worker").spawn()
````

`deploy/hosted/modal/start_clean.py`, whole:

````python
"""Start the hosted demo clean (spec §17, §23.1): empty Corelata's tables in the database
`corelata` and its files in the bucket `corelata-files`, then run the seed again.

Coglossa's preview lives in the same Supabase project, with its own database and its bucket
`coglossa-files`. This script touches neither: it refuses a database URL that does not name
`corelata`, checks again on the open connection, and only ever addresses `corelata-files`. The
schema and its migrations stay; only rows and files go.

Run it from engine/ with the hosted values in the environment (nothing is printed but counts):
    set -a; . ~/.config/corelata/hosted.env; set +a
    uv run --extra s3 python ../deploy/hosted/modal/start_clean.py --yes
    uv run --with-requirements ../deploy/hosted/modal/requirements.txt \
        modal run ../deploy/hosted/modal/app.py::seed
"""

import argparse
import os
import sys
from typing import Any

DATABASE = "corelata"
BUCKET = "corelata-files"
KEY_SPACES = ("projects", "runs")  # every stored key starts with one (corelata.service)


def check_url(url: str) -> None:
    """Refuse (SystemExit) a database URL that names any database but `corelata`."""
    from sqlalchemy.engine import make_url

    name = make_url(url).database
    if name != DATABASE:
        sys.exit(f"refusing: CORELATA_DATABASE_URL names the database {name!r}, not {DATABASE!r}")


def tables() -> list[str]:
    """Corelata's tables and procrastinate's, never alembic_version (the schema stays)."""
    from corelata.store.models import Base
    from corelata.testing.postgres import PROCRASTINATE_TABLES

    return [t.name for t in Base.metadata.sorted_tables] + list(PROCRASTINATE_TABLES)


def clear_database(conn: Any) -> int:
    """TRUNCATE every table on an open psycopg connection, after checking it is connected to
    `corelata`; returns how many tables were emptied."""
    current = conn.execute("SELECT current_database()").fetchone()[0]
    if current != DATABASE:
        sys.exit(f"refusing: connected to the database {current!r}, not {DATABASE!r}")
    names = tables()
    conn.execute(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE")
    conn.commit()
    return len(names)


def clear_bucket(storage: Any) -> int:
    """Delete every stored file of `corelata-files` (an S3Storage for it); returns the count."""
    if storage.cfg.bucket != BUCKET:
        sys.exit(f"refusing: the bucket is {storage.cfg.bucket!r}, not {BUCKET!r}")
    count = 0
    for space in KEY_SPACES:
        count += len(storage.list_keys(space))
        storage.delete_prefix(space)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--yes", action="store_true", help="really delete the demo's data")
    args = parser.parse_args(argv)
    names = ["CORELATA_DATABASE_URL", "CORELATA_S3_ENDPOINT", "CORELATA_S3_REGION"]
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"{', '.join(missing)} not set: export ~/.config/corelata/hosted.env first")
    url = os.environ["CORELATA_DATABASE_URL"]
    check_url(url)
    if not args.yes:
        sys.exit(f"this empties the database {DATABASE!r} and the bucket {BUCKET!r}: add --yes")

    import psycopg

    from corelata.config import S3StorageConfig
    from corelata.storage import S3Storage
    from corelata.store.db import to_libpq_url

    with psycopg.connect(to_libpq_url(url), connect_timeout=10) as conn:
        emptied = clear_database(conn)
    storage = S3Storage(
        S3StorageConfig(
            kind="s3",
            endpoint_url=os.environ["CORELATA_S3_ENDPOINT"],
            region=os.environ["CORELATA_S3_REGION"],
            bucket=BUCKET,
        )
    )
    files = clear_bucket(storage)
    print(f"emptied {emptied} tables in {DATABASE} and {files} files in {BUCKET}; now run the seed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
````

`deploy/hosted/modal/check_app.py`: the patch on the renamed copy (eight functions, `APP_NAME` checked):

````diff
--- a/deploy/hosted/modal/check_app.py
+++ b/deploy/hosted/modal/check_app.py
@@ -19,8 +19,8 @@
 
 import app  # noqa: E402
 
-FUNCTIONS = ["api", "cron", "doctor", "kick", "migrate", "scorer", "worker"]
-EXPECTED_LABELS = {"API_LABEL": "corelata-api", "KICK_LABEL": "corelata-kick", "SCORER_LABEL": "corelata-scorer"}
+FUNCTIONS = ["api", "cron", "doctor", "kick", "migrate", "purge", "seed", "worker"]
+EXPECTED_LABELS = {"APP_NAME": "corelata", "API_LABEL": "corelata-api", "KICK_LABEL": "corelata-kick"}
 
 
 with warnings.catch_warnings():
@@ -30,7 +30,7 @@
 problems = []
 if functions != FUNCTIONS:
     problems.append(f"functions {functions}, expected {FUNCTIONS}")
-labels = {"API_LABEL": app.API_LABEL, "KICK_LABEL": app.KICK_LABEL, "SCORER_LABEL": app.SCORER_LABEL}
+labels = {"APP_NAME": app.APP_NAME, "API_LABEL": app.API_LABEL, "KICK_LABEL": app.KICK_LABEL}
 if labels != EXPECTED_LABELS:
     problems.append(f"labels {labels}, expected {EXPECTED_LABELS}")
 
````

- [ ] **Step 5: Run the tests to see them pass**

Run: the command of Step 3. Expected: 22 passed (one `StarletteDeprecationWarning` from the overlay's FastAPI test client is shown, not an error: this directory has no `filterwarnings` setting). Then `uv run --no-project --with-requirements deploy/hosted/modal/requirements.txt python deploy/hosted/modal/check_app.py` from the repository root. Expected: its last line is `['api', 'cron', 'doctor', 'kick', 'migrate', 'purge', 'seed', 'worker']` (modal 1.6.2 prints a deprecation notice for `App.registered_functions` first, as on Coglossa). This installs the Modal client from PyPI and imports the app; it contacts no Modal service.

- [ ] **Step 6: The gates**

Run: `make test-engine` (1047: nothing under `engine/` changed), `make lint`.

- [ ] **Step 7: Commit**

```bash
git -C <repo> add deploy/hosted/corelata.hosted.yaml deploy/hosted/modal/app.py deploy/hosted/modal/settings.py deploy/hosted/modal/check_app.py deploy/hosted/modal/conftest.py deploy/hosted/modal/requirements.txt deploy/hosted/modal/test_settings.py deploy/hosted/modal/start_clean.py deploy/hosted/modal/test_start_clean.py
git -C <repo> commit -F "$SCRATCH/m19-t6-msg.txt"   # "feat(hosted): the Modal app, the hosted config and start clean (CRL-42)" + the two lines
```

---

### Task 7: The Vercel front door

**Files:**
- Copy from Coglossa and rename (unchanged after the rename): `deploy/hosted/vercel/build.sh`, `package.json`, `pnpm-lock.yaml` (not renamed: the script skips it), `tsconfig.json`, `vitest.config.ts`, `.vercelignore`, `.gitignore`, `lib/auth.test.ts`, `lib/add-user.test.ts`, `lib/imports.test.ts`
- Copy, rename and patch: `deploy/hosted/vercel/middleware.ts`, `lib/route.ts`, `lib/auth.ts`, `lib/route.test.ts`, `vercel.json`, `static/login.html`, `deploy/hosted/add-user.mjs`
- Create: `deploy/hosted/vercel/lib/site.test.ts`

**Interfaces:**
- Consumes: `docs/operator-guide.md`'s sample policy line, `web/src/styles/tokens.css`, `web/dist` (through `build.sh`).
- Produces: the site the controller deploys: `SESSION_COOKIE = "crl_session"`; env `CORELATA_USERS`, `CORELATA_SESSION_SECRET`, `CORELATA_API_ORIGIN`, `CORELATA_PROXY_SECRET`, `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET`; forwarded headers `x-remote-user`, `x-remote-groups`, `x-corelata-proxy-secret`, `modal-key`, `modal-secret`.

- [ ] **Step 1: Copy and rename**

```bash
mkdir -p deploy/hosted
cp -R "$COGLOSSA/deploy/hosted/vercel" deploy/hosted/vercel
cp "$COGLOSSA/deploy/hosted/add-user.mjs" deploy/hosted/add-user.mjs
rm -rf deploy/hosted/vercel/node_modules deploy/hosted/vercel/public deploy/hosted/vercel/coverage
python3 "$SCRATCH/rename.py" deploy/hosted/vercel
python3 "$SCRATCH/rename.py" deploy/hosted/add-user.mjs
```

- [ ] **Step 2: Write the failing tests**

`deploy/hosted/vercel/lib/site.test.ts`, whole:

````ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Corelata's checks on the site's static files (spec §12.2): the policy every page is served
// with, and the sign-in page's colours.
const HERE = join(__dirname, "..");
const REPO = join(HERE, "..", "..", "..");
const read = (path: string) => readFileSync(path, "utf8");

describe("vercel.json", () => {
  const config = JSON.parse(read(join(HERE, "vercel.json"))) as {
    headers: { source: string; headers: { key: string; value: string }[] }[];
  };

  it("sends the operator guide's sample Content-Security-Policy on every path, word for word", () => {
    // The guide's nginx line, which api/tests/test_csp_proxy.py pins for the e2e proxy too.
    const guide = read(join(REPO, "docs", "operator-guide.md"));
    const sample = /add_header Content-Security-Policy "([^"]+)" always;/.exec(guide)?.[1];
    expect(sample).toBeTruthy();
    const everyPath = config.headers.filter((h) => h.source === "/(.*)");
    expect(everyPath).toHaveLength(1);
    const policies = everyPath[0].headers.filter((h) => h.key === "Content-Security-Policy");
    expect(policies.map((h) => h.value)).toEqual([sample]);
  });
});

describe("login.html", () => {
  // Every --name: value pair of a :root[data-theme="…"] block, in order.
  const theme = (css: string, which: "light" | "dark") => {
    const start = css.indexOf(`:root[data-theme="${which}"]`);
    const block = css.slice(start, css.indexOf("}", start));
    return Object.fromEntries([...block.matchAll(/(--[a-z-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
  };
  const login = read(join(HERE, "static", "login.html"));
  const tokens = read(join(REPO, "web", "src", "styles", "tokens.css"));

  it.each(["light", "dark"] as const)("uses the web app's %s colours", (which) => {
    const used = theme(login, which);
    expect(Object.keys(used).length).toBeGreaterThanOrEqual(8);
    const app = theme(tokens, which);
    for (const [name, value] of Object.entries(used)) expect([name, app[name]]).toEqual([name, value]);
  });

  it("is Corelata's and keeps the theme under Corelata's key", () => {
    expect(login).toContain("<h1>Corelata</h1>");
    expect(login).toContain('localStorage.getItem("corelata.theme")');
  });
});
````

`lib/route.test.ts`: Corelata's two login tests:

````diff
--- a/deploy/hosted/vercel/lib/route.test.ts
+++ b/deploy/hosted/vercel/lib/route.test.ts
@@ -299,3 +299,32 @@
     expect(e.failDelayMs).toBe(1000);
   });
 });
+
+describe("Corelata's logins (spec §23.3)", () => {
+  it("signs in people-first with an account line copied from Coglossa's, groups and all", async () => {
+    const hash = await hashPassword("shared", { iterations: 1000 });
+    const line = JSON.stringify({ "people-first": { hash, groups: ["demo"] } });
+    const e = { ...(await env()), users: readEnv({ CORELATA_USERS: line }).users };
+    const body = new URLSearchParams({ name: "people-first", password: "shared" });
+    const login = await decide(
+      new Request("https://p.example/login", { method: "POST", body }),
+      e,
+      NOW,
+    );
+    if (login.kind !== "redirect" || !login.setCookie) throw new Error(login.kind);
+    const cookie = login.setCookie.split(";")[0];
+    expect(cookie.startsWith(`${SESSION_COOKIE}=`)).toBe(true);
+    const call = await decide(
+      new Request("https://p.example/api/system/info", { headers: { cookie } }),
+      e,
+      NOW,
+    );
+    if (call.kind !== "forward") throw new Error(call.kind);
+    expect(call.headers.get("x-remote-user")).toBe("people-first");
+    expect(call.url).toBe("https://ws--corelata-api.modal.run/api/system/info");
+  });
+
+  it("names its cookie crl_session, apart from Coglossa's cg_session", () => {
+    expect(SESSION_COOKIE).toBe("crl_session");
+  });
+});
````

- [ ] **Step 3: Run them to see them fail**

Run: `cd deploy/hosted/vercel && pnpm install --frozen-lockfile && pnpm exec vitest run lib/site.test.ts`
Expected: the policy test FAILS (`config.headers` is undefined: Coglossa's `vercel.json` sends no headers); the sign-in page's tests already pass after the rename (M18 copied the same colour values), and so do the two new route tests (the rename already gives `crl_session`). They stay to pin the copy.

- [ ] **Step 4: The front door's changes**

````diff
--- a/deploy/hosted/vercel/vercel.json
+++ b/deploy/hosted/vercel/vercel.json
@@ -3,6 +3,17 @@
   "buildCommand": "",
   "outputDirectory": "public",
   "cleanUrls": false,
+  "headers": [
+    {
+      "source": "/(.*)",
+      "headers": [
+        {
+          "key": "Content-Security-Policy",
+          "value": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'"
+        }
+      ]
+    }
+  ],
   "rewrites": [
     { "source": "/login", "destination": "/login.html" },
     { "source": "/((?!api/|assets/).*)", "destination": "/index.html" }
````

````diff
--- a/deploy/hosted/vercel/lib/auth.ts
+++ b/deploy/hosted/vercel/lib/auth.ts
@@ -1,4 +1,4 @@
-/** Sign-in for the hosted preview (spec §5): PBKDF2 password hashes and HMAC-signed session
+/** Sign-in for the hosted demo (copied from Coglossa's front door, spec §12.2): PBKDF2 password hashes and HMAC-signed session
  * cookies, using WebCrypto only, so it runs in Vercel Routing Middleware. */
 
 const enc = new TextEncoder();
@@ -55,10 +55,13 @@
 export const isValidName = (name: string): boolean =>
   /^[\x21-\x7e]([\x20-\x7e]*[\x21-\x7e])?$/.test(name);
 
-/** A user of the front door: a password hash and the groups passed on to Corelata (CGL-26). */
+/** A user of the front door: a password hash and groups. Accounts keep Coglossa's shape, so
+ * one CORELATA_USERS line can be copied from Coglossa's; Corelata has no roles and ignores the
+ * groups, but the front door still strips and sets x-remote-groups (spec §12.2). */
 export type Account = { hash: string; groups: string[] };
 
-// A Corelata team name (corelata.people.TEAM_NAME_PATTERN): no commas, so the header splits.
+// Coglossa's team name pattern (coglossa.people.TEAM_NAME_PATTERN): no commas, so the header
+// splits.
 export const GROUP_NAME = /^[A-Za-z0-9._-](?:[A-Za-z0-9._ -]{0,62}[A-Za-z0-9._-])?$/;
 
 function account(value: unknown): Account | null {
````

````diff
--- a/deploy/hosted/vercel/lib/route.ts
+++ b/deploy/hosted/vercel/lib/route.ts
@@ -1,4 +1,4 @@
-/** Routing for the front door (spec §3, §5). Pure: middleware.ts turns a Decision into a
+/** Routing for the front door (copied from Coglossa, spec §12.2). Pure: middleware.ts turns a Decision into a
  * response. */
 import {
   type Account,
@@ -119,8 +119,7 @@
   return forward(request, url, { name: user, groups: env.users.get(user)!.groups }, env);
 }
 
-/** The /api rewrite. Spike S1 (plan Task 8) decides whether this stays a header-adding
- * rewrite; its fallback is a streaming proxy function, swapped in here. */
+/** The /api rewrite: the client's identity and proxy headers replaced by the front door's. */
 export function forward(
   request: Request,
   url: URL,
````

````diff
--- a/deploy/hosted/vercel/middleware.ts
+++ b/deploy/hosted/vercel/middleware.ts
@@ -16,7 +16,7 @@
     case "unauthorized":
       return Response.json({ detail: "signed out: sign in again" }, { status: 401 });
     case "misconfigured":
-      return new Response("Corelata preview is not configured.", { status: 503 });
+      return new Response("The Corelata demo is not configured.", { status: 503 });
     case "forbidden":
       return new Response("Cross-site request refused.", { status: 403 });
     case "forward":
````

````diff
--- a/deploy/hosted/vercel/static/login.html
+++ b/deploy/hosted/vercel/static/login.html
@@ -3,7 +3,7 @@
 <head>
 <meta charset="utf-8">
 <meta name="viewport" content="width=device-width, initial-scale=1">
-<title>Corelata — Sign in</title>
+<title>Sign in – Corelata</title>
 <script>
   (function () {
     var c = "system";
@@ -15,6 +15,7 @@
   })();
 </script>
 <style>
+  /* The colours are web/src/styles/tokens.css's (M18); lib/site.test.ts checks they match. */
   :root, :root[data-theme="light"] {
     color-scheme: light;
     --bg: #faf8f5; --surface: #ffffff; --border-strong: #8a8378; --text: #1f2328;
````

````diff
--- a/deploy/hosted/add-user.mjs
+++ b/deploy/hosted/add-user.mjs
@@ -11,7 +11,7 @@
   console.error("usage: node --experimental-strip-types deploy/hosted/add-user.mjs <name> [--groups a,b]");
   process.exit(2);
 }
-// CGL-26: the groups the front door passes to Corelata (teams, or corelata-admins)
+// Groups are kept for Coglossa's account shape (Corelata ignores them, spec §12.2)
 const groups = (list ?? "").split(",").map((g) => g.trim()).filter((g) => g !== "");
 if (!groups.every((g) => GROUP_NAME.test(g))) {
   console.error("group names: letters, digits, spaces, '.', '_' or '-' (1-64 characters)");
````

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd deploy/hosted/vercel && pnpm typecheck && pnpm test`
Expected: 50 passed in 5 files; coverage 99.28 / 99.15 / 100 / 100% (thresholds 95). Then `deploy/hosted/vercel/build.sh` from the repository root: it builds `web/` and writes `deploy/hosted/vercel/public/` with `index.html`, `login.html`, `theme-init.js` and `assets/` (ignored by `deploy/hosted/vercel/.gitignore`; remove it after).

- [ ] **Step 6: Commit**

```bash
git -C <repo> add deploy/hosted/vercel deploy/hosted/add-user.mjs
git -C <repo> status --short deploy/hosted/vercel   # node_modules, public, coverage must not be listed
git -C <repo> commit -F "$SCRATCH/m19-t7-msg.txt"   # "feat(hosted): the Vercel front door, with the guide's CSP (CRL-42)" + the two lines
```

---

### Task 8: The smoke test, CI and the deploy workflow

**Files:**
- Copy, rename and patch: `deploy/hosted/smoke.py`, `deploy/hosted/test_smoke.py`
- Create: `.github/workflows/hosted.yml`
- Modify: `.github/workflows/ci.yml`, `.github/dependabot.yml`, `Makefile` (`deploy-check`)

**Interfaces:**
- Consumes: Task 6's `settings.EXAMPLE_PROJECT` and the two test directories; Task 7's `package.json` scripts (`typecheck`, `test`).
- Produces: `smoke.run_checks(site, api_origin, user, password, modal_auth, transport=None) -> list[tuple[str, bool, str]]` (six checks), `smoke.EXAMPLE_PROJECT`; CI jobs `hosted-web`, `hosted-modal`; the `hosted` workflow.

- [ ] **Step 1: Copy, rename, write the failing tests**

```bash
cp "$COGLOSSA/deploy/hosted/smoke.py" "$COGLOSSA/deploy/hosted/test_smoke.py" deploy/hosted/
python3 "$SCRATCH/rename.py" deploy/hosted/smoke.py
python3 "$SCRATCH/rename.py" deploy/hosted/test_smoke.py
```

````diff
--- a/deploy/hosted/test_smoke.py
+++ b/deploy/hosted/test_smoke.py
@@ -13,7 +13,7 @@
 
 def make_transport(
     login_location="/", api_me_status=401, health_status=200, me_user="ci", no_token_status=401,
-    modal_auth_on=True,
+    modal_auth_on=True, projects=None,
 ):
     def handler(request: httpx.Request) -> httpx.Response:
         host, path = request.url.host, request.url.path
@@ -24,15 +24,21 @@
             if login_location == "/":
                 headers["set-cookie"] = "crl_session=abc; Path=/; HttpOnly"
             return httpx.Response(303, headers=headers)
-        if host == "site.test" and path == "/api/me":
-            if "crl_session=abc" in request.headers.get("cookie", ""):
+        signed_in = "crl_session=abc" in request.headers.get("cookie", "")
+        if host == "site.test" and path == "/api/system/info":
+            if signed_in:
                 return httpx.Response(200, json={"user": me_user, "logout_url": "/logout"})
             return httpx.Response(401)
+        if host == "site.test" and path == "/api/projects":
+            if not signed_in:
+                return httpx.Response(401)
+            names = [smoke.EXAMPLE_PROJECT] if projects is None else projects
+            return httpx.Response(200, json=[{"id": str(i), "name": n} for i, n in enumerate(names)])
         if host == "api.test":  # Modal proxy auth, in front of the API
             given = (request.headers.get("modal-key"), request.headers.get("modal-secret"))
             if modal_auth_on and given != ("wk-1", "ws-1"):
                 return httpx.Response(no_token_status)
-        if host == "api.test" and path == "/api/me":
+        if host == "api.test" and path == "/api/system/info":
             return httpx.Response(api_me_status)
         if host == "api.test" and path == "/api/health":
             return httpx.Response(health_status)
@@ -54,7 +60,7 @@
 
 def test_all_checks_pass(capsys):
     results = run(make_transport())
-    assert len(results) == 5 and all(ok for _, ok, _ in results)
+    assert len(results) == 6 and all(ok for _, ok, _ in results)
 
 
 def test_modal_may_refuse_with_403(capsys):
@@ -69,18 +75,18 @@
 
 
 def test_check_3_fails_when_modal_proxy_auth_is_off():
-    # Without Modal's proxy auth the API still answers a tokenless /api/me with 401 (its own
+    # Without Modal's proxy auth the API still answers a tokenless /api/system/info with 401 (its own
     # proxy-secret check), which must not pass for Modal's refusal.
     results = run(make_transport(modal_auth_on=False))
     assert not results[2][1] and "without the Modal token (HTTP 200)" in results[2][2]
 
 
-def test_main_exits_zero_with_five_ok_lines(capsys, monkeypatch, smoke_env):
+def test_main_exits_zero_with_six_ok_lines(capsys, monkeypatch, smoke_env):
     monkeypatch.setattr(smoke, "_transport", make_transport())
     code = smoke.main(["--site", SITE, "--api-origin", API, "--user", "ci"])
     out = capsys.readouterr().out.splitlines()
     assert code == 0
-    assert len([line for line in out if line.startswith("ok")]) == 5
+    assert len([line for line in out if line.startswith("ok")]) == 6
 
 
 def test_api_answering_without_secret_fails(capsys, monkeypatch, smoke_env):
@@ -121,3 +127,38 @@
     SEEN.clear()
     run(make_transport())
     assert ("GET", "site.test", "/") not in SEEN
+
+
+# Corelata's check 6: the seed's example project, through the site.
+
+
+def test_a_missing_example_project_fails_check_six():
+    results = run(make_transport(projects=["Black Sea"]))
+    assert results[5] == (
+        "the example project exists",
+        False,
+        "HTTP 200, 1 project(s), no 'Example: Varna port'",
+    )
+    assert all(ok for _, ok, _ in results[:5])
+
+
+def test_check_six_reads_the_projects_with_the_session():
+    SEEN.clear()
+    results = run(make_transport(projects=["Black Sea", smoke.EXAMPLE_PROJECT]))
+    assert results[5] == ("the example project exists", True, "HTTP 200, 2 project(s)")
+    assert ("GET", "site.test", "/api/projects") in SEEN
+
+
+def test_check_six_fails_when_signed_out():
+    results = run(make_transport(login_location="/login?failed=1"))
+    assert not results[0][1] and not results[5][1] and "HTTP 401" in results[5][2]
+
+
+def test_the_smoke_tests_name_matches_the_seeds():
+    import sys
+    from pathlib import Path
+
+    sys.path.insert(0, str(Path(__file__).parent / "modal"))
+    import settings
+
+    assert smoke.EXAMPLE_PROJECT == settings.EXAMPLE_PROJECT
````

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run --with pyyaml --with fastapi --with httpx python -m pytest ../deploy/hosted/test_smoke.py -q -p no:cacheprovider --no-cov --rootdir ../deploy/hosted/modal`
Expected: FAIL (`AttributeError: module 'smoke' has no attribute 'EXAMPLE_PROJECT'`; five results where six are expected).

- [ ] **Step 3: The smoke test**

````diff
--- a/deploy/hosted/smoke.py
+++ b/deploy/hosted/smoke.py
@@ -1,4 +1,4 @@
-"""Smoke test for the hosted preview.
+"""Smoke test for the hosted demo (spec §19; copied from Coglossa).
 
 Usage: CORELATA_SMOKE_PASSWORD=... CORELATA_MODAL_KEY=... CORELATA_MODAL_SECRET=... \
            python smoke.py --site URL --api-origin URL --user NAME
@@ -8,7 +8,8 @@
 workspace proxy-auth token (Modal-Key/Modal-Secret) with 401 or 403, before the API runs.
 Check 3 asks for the health check without the token, which the API itself would answer
 200. Checks 4 and 5 send the token, so they reach the API: check 4 then proves the API's own
-proxy-secret check, and check 5 that the health check answers.
+proxy-secret check, and check 5 that the health check answers. Check 6 (Corelata's) finds
+the example project the seed writes, through the site.
 """
 
 import argparse
@@ -16,6 +17,8 @@
 import sys
 
 import httpx
+
+EXAMPLE_PROJECT = "Example: Varna port"  # settings.EXAMPLE_PROJECT
 
 # Tests replace this with an httpx.MockTransport.
 _transport = None
@@ -48,9 +51,11 @@
             ok, detail = False, f"request failed: {exc}"
         results.append(("sign in through the front door", ok, detail))
 
-        # 2. The session works through the proxy.
+        # 2. The session works through the proxy (Corelata has no /api/me: system/info names
+        # the user).
+        cookie = {"Cookie": f"crl_session={session or ''}"}
         try:
-            r = client.get(f"{site}/api/me", headers={"Cookie": f"crl_session={session or ''}"})
+            r = client.get(f"{site}/api/system/info", headers=cookie)
             body = r.json() if r.status_code == 200 else {}
             got = body.get("user") if isinstance(body, dict) else None
             ok = r.status_code == 200 and got == user
@@ -76,7 +81,7 @@
 
         # 4. Past Modal, the API refuses callers without the proxy secret.
         try:
-            r = client.get(f"{api_origin}/api/me", headers=modal_auth)
+            r = client.get(f"{api_origin}/api/system/info", headers=modal_auth)
             ok = r.status_code == 401
             detail = (
                 "HTTP 401"
@@ -94,6 +99,17 @@
         except httpx.HTTPError as exc:
             ok, detail = False, f"request failed: {exc}"
         results.append(("the API health check answers", ok, detail))
+
+        # 6. The seed's example project is there, through the site (spec §13.6).
+        try:
+            r = client.get(f"{site}/api/projects", headers=cookie)
+            body = r.json() if r.status_code == 200 else []
+            names = [p.get("name") for p in body] if isinstance(body, list) else []
+            ok = EXAMPLE_PROJECT in names
+            detail = f"HTTP {r.status_code}, {len(names)} project(s)" + ("" if ok else f", no {EXAMPLE_PROJECT!r}")
+        except (httpx.HTTPError, ValueError, AttributeError) as exc:
+            ok, detail = False, f"request failed: {exc}"
+        results.append(("the example project exists", ok, detail))
     return results
 
 
````

- [ ] **Step 4: CI, the deploy workflow, Dependabot, shellcheck**

````diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -133,6 +133,46 @@
     steps:
       - uses: actions/checkout@v7
       - run: make deploy-check
+  hosted-web:
+    # The hosted demo's front door (deploy/hosted/vercel, M19): Vitest at 95 % and tsc.
+    runs-on: ubuntu-24.04
+    timeout-minutes: 10
+    defaults:
+      run:
+        working-directory: deploy/hosted/vercel
+    steps:
+      - uses: actions/checkout@v7
+      - uses: pnpm/action-setup@v6
+        with:
+          package_json_file: deploy/hosted/vercel/package.json
+      - uses: actions/setup-node@v7
+        with:
+          node-version: "22"
+          cache: pnpm
+          cache-dependency-path: deploy/hosted/vercel/pnpm-lock.yaml
+      - run: pnpm install --frozen-lockfile
+      - run: pnpm typecheck
+      - run: pnpm test
+  hosted-modal:
+    # The hosted demo's Modal app without a Modal account (M19): the settings, start-clean and
+    # smoke tests in the engine's environment, so corelata.config is importable and the rendered
+    # config is checked instead of skipped (CORELATA_FORBID_SKIP, see conftest.py; --no-cov:
+    # the engine's coverage gate is not for these files); then the app's import and functions.
+    runs-on: ubuntu-24.04
+    timeout-minutes: 10
+    steps:
+      - uses: actions/checkout@v7
+      - uses: astral-sh/setup-uv@v7
+        with:
+          python-version: "3.12"
+      - run: uv sync --all-groups
+        working-directory: engine
+      - run: >-
+          CORELATA_FORBID_SKIP=1 uv run --with pyyaml --with fastapi --with httpx
+          python -m pytest ../deploy/hosted/modal ../deploy/hosted/test_smoke.py
+          -q -p no:cacheprovider --no-cov --rootdir ../deploy/hosted/modal
+        working-directory: engine
+      - run: uv run --no-project --with-requirements deploy/hosted/modal/requirements.txt python deploy/hosted/modal/check_app.py
   airgap:
     # Pull requests only: a push to main is a merged pull request that already passed, and the
     # release workflow runs the same test again before it publishes a bundle.
@@ -151,7 +191,7 @@
     # (airgap runs on pull requests only), red when any job failed or was cancelled.
     runs-on: ${{ vars.RUNS_ON && fromJSON(vars.RUNS_ON) || 'ubuntu-24.04' }}
     timeout-minutes: 5
-    needs: [engine, api, web, e2e, deploy, airgap]
+    needs: [engine, api, web, e2e, deploy, hosted-web, hosted-modal, airgap]
     if: always()
     concurrency:
       group: ci-status-${{ github.event.pull_request.number || github.ref }}
````

`.github/workflows/hosted.yml`, whole:

````yaml
name: hosted
# The hosted demo (deploy/hosted/README.md; copied from Coglossa). Deploys after `ci` passes on a
# push to main, or by hand; skips with a notice until the owner adds MODAL_TOKEN_ID and
# VERCEL_TOKEN (until then the controller deploys by hand, spec §23.5).
on:
  workflow_run:
    workflows: [ci]
    types: [completed]
    branches: [main]
  workflow_dispatch:
concurrency: { group: hosted-deploy, cancel-in-progress: false }
permissions:
  contents: read
jobs:
  deploy:
    # A fork PR from a branch named main also matches the branches filter, so require a push from this repo.
    if: >-
      github.event_name == 'workflow_dispatch' || (
      github.event.workflow_run.conclusion == 'success' &&
      github.event.workflow_run.event == 'push' &&
      github.event.workflow_run.head_repository.full_name == github.repository)
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    env:
      MODAL_TOKEN_ID: ${{ secrets.MODAL_TOKEN_ID }}
      MODAL_TOKEN_SECRET: ${{ secrets.MODAL_TOKEN_SECRET }}
      VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
      VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
      VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}
      CORELATA_SMOKE_PASSWORD: ${{ secrets.CORELATA_SMOKE_PASSWORD }}
      # the Modal workspace proxy-auth token: the smoke test reaches the API with it
      CORELATA_MODAL_KEY: ${{ secrets.CORELATA_MODAL_KEY }}
      CORELATA_MODAL_SECRET: ${{ secrets.CORELATA_MODAL_SECRET }}
      SITE_URL: ${{ vars.CORELATA_SITE_URL }}
      API_ORIGIN: ${{ vars.CORELATA_API_ORIGIN }}
    steps:
      - name: skip without deploy secrets
        id: gate
        run: |
          if [ -z "$MODAL_TOKEN_ID" ] || [ -z "$VERCEL_TOKEN" ]; then
            echo "::notice::hosted deploy skipped: MODAL_TOKEN_ID or VERCEL_TOKEN is not set"
            echo "run=false" >> "$GITHUB_OUTPUT"
          else
            echo "run=true" >> "$GITHUB_OUTPUT"
          fi
      - if: steps.gate.outputs.run == 'true'
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: ${{ github.event.workflow_run.head_sha || github.sha }}
      - if: steps.gate.outputs.run == 'true'
        uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7.6.0
        with:
          python-version: "3.12"
      - if: steps.gate.outputs.run == 'true'
        name: deploy the backend
        # migrations first: the new code never runs against the old schema; the seed last
        run: |
          uv run --with-requirements deploy/hosted/modal/requirements.txt modal run deploy/hosted/modal/app.py::migrate
          uv run --with-requirements deploy/hosted/modal/requirements.txt modal deploy deploy/hosted/modal/app.py
          uv run --with-requirements deploy/hosted/modal/requirements.txt modal run deploy/hosted/modal/app.py::seed
      - if: steps.gate.outputs.run == 'true'
        uses: pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86 # v6.0.10
        with:
          package_json_file: deploy/hosted/vercel/package.json
      - if: steps.gate.outputs.run == 'true'
        uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with:
          node-version: "22"
      - if: steps.gate.outputs.run == 'true'
        name: deploy the front door
        run: |
          deploy/hosted/vercel/build.sh
          cd deploy/hosted/vercel
          npx --yes vercel@61.1.0 deploy --prod --yes --token "$VERCEL_TOKEN"
      - if: steps.gate.outputs.run == 'true' && env.CORELATA_SMOKE_PASSWORD != '' && env.SITE_URL != '' && env.API_ORIGIN != ''
        name: smoke test
        run: uv run --with httpx python deploy/hosted/smoke.py --site "$SITE_URL" --api-origin "$API_ORIGIN" --user ci
````

````diff
--- a/.github/dependabot.yml
+++ b/.github/dependabot.yml
@@ -75,3 +75,37 @@
       actions:
         patterns:
           - "*"
+
+  # The hosted demo (M19, copied from Coglossa): the front door and the Modal image's pins.
+  - package-ecosystem: "npm"
+    directory: "/deploy/hosted/vercel"
+    schedule:
+      interval: "weekly"
+      day: "monday"
+    open-pull-requests-limit: 5
+    rebase-strategy: "auto"
+    labels: ["dependencies", "javascript"]
+    groups:
+      minor-and-patch:
+        update-types:
+          - "minor"
+          - "patch"
+    ignore:
+      - dependency-name: "@types/node"
+        update-types: ["version-update:semver-major"]
+      - dependency-name: "typescript"
+        update-types: ["version-update:semver-major"]
+
+  - package-ecosystem: "pip"
+    directory: "/deploy/hosted/modal"
+    schedule:
+      interval: "weekly"
+      day: "monday"
+    open-pull-requests-limit: 3
+    rebase-strategy: "auto"
+    labels: ["dependencies", "python"]
+    groups:
+      minor-and-patch:
+        update-types:
+          - "minor"
+          - "patch"
````

````diff
--- a/Makefile
+++ b/Makefile
@@ -66,7 +66,7 @@
 SHELLCHECK := docker run --rm -v "$(CURDIR):/mnt" -w /mnt koalaman/shellcheck:v0.10.0
 
 deploy-check:
-	$(SHELLCHECK) deploy/*.sh deploy/tests/*.sh
+	$(SHELLCHECK) deploy/*.sh deploy/tests/*.sh deploy/hosted/vercel/*.sh
 	deploy/tests/test-install.sh
 	deploy/tests/test-restore.sh
 	python3 deploy/tests/check_compose.py
````

- [ ] **Step 5: Run everything CI will run**

Run, from `engine/`: `CORELATA_FORBID_SKIP=1 uv run --with pyyaml --with fastapi --with httpx python -m pytest ../deploy/hosted/modal ../deploy/hosted/test_smoke.py -q -p no:cacheprovider --no-cov --rootdir ../deploy/hosted/modal` (expected 37 passed); from the root: `uv run --no-project --with-requirements deploy/hosted/modal/requirements.txt python deploy/hosted/modal/check_app.py`; `cd deploy/hosted/vercel && pnpm typecheck && pnpm test`; `make deploy-check` (shellcheck now covers `deploy/hosted/vercel/build.sh`); `actionlint .github/workflows/ci.yml .github/workflows/hosted.yml` if actionlint is installed (it is clean on the scratch copy).

- [ ] **Step 6: Commit**

```bash
git -C <repo> add deploy/hosted/smoke.py deploy/hosted/test_smoke.py .github/workflows/ci.yml .github/workflows/hosted.yml .github/dependabot.yml Makefile
git -C <repo> commit -F "$SCRATCH/m19-t8-msg.txt"   # "ci: hosted-web, hosted-modal and the hosted deploy workflow (CRL-42)" + the two lines
```

Pushing this commit runs `hosted-web` and `hosted-modal` on the pull request; `ci-status` must be green with them. `hosted.yml` runs only after `ci` on `main` or by hand, and skips with a notice while the repository has no `MODAL_TOKEN_ID` or `VERCEL_TOKEN`.

---

### Task 9: Docs

**Files:**
- Create (whole): `deploy/hosted/README.md`, `docs/m19-followups.md`
- Modify: `docs/operator-guide.md` (a note in section 5 that the hosted settings are optional and off), `README.md` (an M19 section)

**Interfaces:**
- Consumes: every task's rulings and divergences.
- Produces: the runbook the controller follows with the last section, and the follow-ups file the controller completes with S1's result.

- [ ] **Step 1: The hosted README**

`deploy/hosted/README.md`, whole:

````markdown
# Corelata hosted demo

A hosted, password-protected Corelata for demonstrations, built like Coglossa's preview: Vercel is
the front door, Modal runs the backend and scales to zero, Supabase holds the data, and OpenRouter
serves the language models. The design is Part B of
`docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md` (with its §23
amendments); the M19 plan's "Provisioning and deploy" section is the step list the controller
followed. The air-gapped install is in `docs/operator-guide.md` and is unaffected by anything here:
everything in this directory is optional and off unless a config turns it on.

## What runs where

| Part | Runs | Cost when idle |
|---|---|---|
| Vercel project `corelata-demo` (`deploy/hosted/vercel`, team `bonham-technologies`) | always | already paid (Pro) |
| Supabase: database `corelata` and bucket `corelata-files` in Coglossa's project `coglossa-preview` | always | nothing new |
| Modal `api`, `worker`, `kick` | on demand | $0 (inside the workspace's included credit) |
| Modal `cron` (every 5 min), `purge` (daily, 03:17 UTC) | a few seconds of CPU | cents per month |
| OpenRouter | per token | $0 |

The Modal app is `corelata`. Its web endpoints are `https://<workspace>--corelata-api.modal.run`
and `https://<workspace>--corelata-kick.modal.run`. Both require Modal proxy auth: a request
without the workspace's proxy-auth token (headers `Modal-Key` and `Modal-Secret`) is refused by
Modal and starts no container. The token is Coglossa's, shared by the workspace, so the API also
checks Corelata's own proxy secret (`X-Corelata-Proxy-Secret`) and the kick its own bearer token:
Coglossa's front door, which holds the same Modal token, cannot use Corelata's API.

| Function | What it does |
|---|---|
| `api` | the REST API (one container, 1 CPU); listens for progress through the session pooler while awake |
| `worker` | a burst worker: drains the queue, then exits (2 CPU, at most 2 containers) |
| `kick` | starts a worker; the API posts to it after each queued job |
| `cron` | every 5 minutes: fails orphaned runs and discoveries past their limits, then starts a worker if a job waits with none alive, or a dead worker left jobs stalled |
| `purge` | daily: deletes closed jobs older than `worker.job_retention_days` |
| `migrate`, `doctor`, `seed` | run by hand (`modal run deploy/hosted/modal/app.py::<name>`) |

## Coglossa's data is never touched

Corelata shares Coglossa's Supabase project, but not its data. Corelata uses only the database
`corelata` (the pooler URL's path is `/corelata`) and the bucket `corelata-files`. Coglossa's
database and the bucket `coglossa-files` are never read, written, emptied or dropped by anything
here. Do not use the Supabase dashboard's SQL editor or the Supabase connector for Corelata's
data: they run on the project's default database, which is Coglossa's. Use
`deploy/hosted/modal/start_clean.py`, which refuses any other database or bucket.

## Secrets

The values live in `~/.config/corelata/hosted.env` (mode 600, never committed or printed). No
secret is in this repository; `corelata.hosted.yaml` names the variables, and the account-specific
URLs and the region are filled in from the Modal Secret when a container starts.

| Variable | Lives in | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | Modal Secret | The existing key (`CORELATA_OPENROUTER_KEY`), with its $25 credit limit |
| `CORELATA_DATABASE_URL` | Modal Secret | The session-pooler URL (port 5432) with path `/corelata` and `?sslmode=require` |
| `CORELATA_S3_ACCESS_KEY_ID`, `CORELATA_S3_SECRET_ACCESS_KEY` | Modal Secret | The project's Storage S3 keys (Coglossa's, project-wide; server side only) |
| `CORELATA_S3_ENDPOINT`, `CORELATA_S3_REGION` | Modal Secret | `https://<ref>.storage.supabase.co/storage/v1/s3`, `ca-central-1` |
| `CORELATA_PROXY_SECRET` | Modal Secret and Vercel env | 32 random bytes, Corelata's own; the same value in both |
| `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET` | Modal Secret and Vercel env | The workspace proxy-auth token (`wk-…`, `ws-…`), Coglossa's |
| `CORELATA_KICK_TOKEN` | Modal Secret | 32 random bytes |
| `CORELATA_KICK_URL` | Modal Secret | The deployed `corelata-kick` URL |
| `CORELATA_SESSION_SECRET`, `CORELATA_USERS`, `CORELATA_API_ORIGIN` | Vercel env | |
| `CORELATA_SMOKE_PASSWORD` | `hosted.env` | The `ci` login's password, for the smoke test |

"Modal Secret" is `corelata-hosted`, which every function reads.

## Logins

`CORELATA_USERS` is one JSON object: `{"name": "pbkdf2_sha256$…", …}` or, as Coglossa writes
them, `{"name": {"hash": "…", "groups": [...]}}`. Corelata has no roles and ignores the groups.

- `people-first`: the demo team's shared login. Its line is Coglossa's (the same hash), so one
  password works on both demos.
- `ci`: the smoke test's login.

To add someone: `node --experimental-strip-types deploy/hosted/add-user.mjs <name>` (Node 22.6 or
later) asks for a password and prints the line to add. Names must be printable ASCII. The hashes
contain `$`: put the whole value in single quotes in a shell.

## Deploying

The controller deploys by hand from its own machine, as Coglossa's preview is deployed. Run the
Modal commands from the repository root with a Modal client pinned to the image's version:
`uv tool install modal --with-requirements deploy/hosted/modal/requirements.txt` (after a
Dependabot bump of that file, run it again with `--force`).

1. `modal run deploy/hosted/modal/app.py::migrate` (migrations only move forward).
2. `modal deploy deploy/hosted/modal/app.py`.
3. `modal run deploy/hosted/modal/app.py::seed`: queues the example report ("Example: Varna
   port") when that project does not exist yet, then starts the deployed worker. It does nothing
   on a database that already has it.
4. The front door: `deploy/hosted/vercel/build.sh`, then from `deploy/hosted/vercel`,
   `npx --yes vercel@61.1.0 deploy --prod --yes --scope bonham-technologies`. The project's Root
   Directory stays empty; `.vercelignore` keeps the built `public/` in the upload.
5. The smoke test (six checks: sign-in, the session through the proxy, Modal's refusal without
   its token, the API's refusal without the proxy secret, health, the example project):
   `CORELATA_SMOKE_PASSWORD=… CORELATA_MODAL_KEY=… CORELATA_MODAL_SECRET=… uv run --with httpx python deploy/hosted/smoke.py --site <site> --api-origin <api> --user ci`

`.github/workflows/hosted.yml` does the same on a push to `main` after `ci` passes, once the owner
adds its tokens (`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`,
`VERCEL_PROJECT_ID`, `CORELATA_SMOKE_PASSWORD`, `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET`,
and the variables `CORELATA_SITE_URL`, `CORELATA_API_ORIGIN`). Without `MODAL_TOKEN_ID` and
`VERCEL_TOKEN` it skips with a notice. Running it by hand (`workflow_dispatch`) deploys the
dispatched ref with no CI gate.

## Progress, uploads and the stream

- The API keeps one `LISTEN` connection on the session pooler while it is awake (spike S2: 10 of
  10 notifications, worst 0.117 s). While the connection is down the feed reads every
  `api.progress_poll_s` (1 s) instead.
- The progress stream sends `retry: 3000`, the current state at once, a comment every 15 s and
  ends after the terminal event. Spike S1 measured how Vercel treats a long stream on this
  project; the result and the case that applies are recorded in `docs/m19-followups.md`. If
  Vercel ends a stream, the browser reconnects after 3 s and the first event carries the current
  state; if a reconnect fails, the page reads the run every 3 s.
- Uploads are capped at 4 MB (`api.max_upload_mb: 4`): Vercel refuses request bodies over about
  4.5 MB with its own 413.

## Checks and operations

- `modal run deploy/hosted/modal/app.py::doctor` checks the config, the models, the database, the
  bucket, the kick URL (named, never called) and the proxy secret.
- Rollback: deploy an earlier commit. Migrations only move forward.
- Backups: Supabase's daily database backups. The bucket has none, which is acceptable for a demo.
- Logs: Modal (one day on the Starter plan) and Vercel.
- CI imports the Modal app without an account (`deploy/hosted/modal/check_app.py`) and runs the
  settings, start-clean and smoke tests (`hosted-modal`), and the front door's Vitest and `tsc`
  (`hosted-web`).
- Every signed-in person sees every project; the demo fills up. To start clean, empty Corelata's
  tables and files, then seed again (from `engine/`):

  ```
  set -a; . ~/.config/corelata/hosted.env; set +a
  uv run --extra s3 python ../deploy/hosted/modal/start_clean.py --yes
  cd .. && modal run deploy/hosted/modal/app.py::seed
  ```

- Teardown, only on the owner's word: `modal app stop corelata`; `DROP DATABASE corelata WITH
  (FORCE)` (Postgres cannot drop the database a session is connected to, so this one statement
  runs from a session on the project's `postgres` database and changes nothing in it); delete
  the bucket `corelata-files` (Storage, that bucket only); remove the Vercel project
  `corelata-demo`.

## Revoking access

A session is tied to the user's name.
- To sign one person out, remove them from `CORELATA_USERS`. Their cookie is refused on the next
  request.
- To sign everyone out, rotate `CORELATA_SESSION_SECRET`.

Redeploy the Vercel project after changing either variable.

## Costs and spending limits

All three are set before the URL is shared.
- OpenRouter: the key's $25 credit limit.
- Modal: the workspace budget, shared with Coglossa's GPU scorer; Corelata adds only CPU time.
- `api.max_upload_mb: 4`.

An open browser tab on a report being written keeps the API container awake (about $0.05/hour).

## Database connections

The pooler and the project's connection limit are shared with Coglossa's preview. Corelata runs
one API container (`max_containers=1`: a SQLAlchemy pool, the job queue's pool and the `LISTEN`
connection) and at most two workers (`max_containers=2`). The config has no pool-size setting;
Coglossa's README sets the session pooler's Pool Size to 40 for the project.
````

- [ ] **Step 2: The follow-ups**

`docs/m19-followups.md`, whole (the divergences, this plan's rulings, the spec deviations, S1's place, the follow-ups):

````markdown
# M19 follow-ups

M19 (CRL-42): the hosted demo. Spec Part B (§10 to §22) with its §23 amendments; plan
`docs/superpowers/plans/2026-10-20-m19-hosted-demo.md`.

## Divergences from Coglossa

Copied from Coglossa at 72dd055 and renamed (`COGLOSSA_` to `CORELATA_`, `coglossa` to
`corelata`, the cookie `cg_session` to `crl_session`). Every other change:

- `storage.py`: `S3Storage.list_keys` added (Corelata's `Storage` protocol has it; the worker
  clears a restarted run's stale exports with it); `check_key` shared by both stores, as in
  Coglossa. `storage_call` is Corelata's (R-M19-4). **Backport candidate:** Coglossa's service
  still calls storage on the event loop.
- `config.py`: no `scorer` section, so `env_headers` and the header-name check live with
  `WorkerConfig`; `S3StorageConfig`'s key variables are `CORELATA_S3_*`.
- `doctor.py`: the `worker` line (kick URL, never called) as Coglossa's; the `auth` line for the
  proxy secret is Corelata's; the storage check runs off the event loop.
- `worker/kick.py`: `KickingQueue.defer` passes `priority` through (R-M17-29).
- `worker/app.py`: `queue_status` and `needs_worker` as Coglossa's; `cron_pass` and
  `purge_pass` are Corelata's (Coglossa has no periodic tasks to stand in for).
- `api/proxy.py`: header `X-Corelata-Proxy-Secret`; the message names Corelata.
- `deploy/hosted/modal/app.py`: no `scorer`, scorer image, weights Volume or
  `upload_weights.py`; adds `purge`, `seed` and the example source in the image; `api.web_dir`
  unset; `cron` calls `cron_pass`.
- `settings.py`: the seed's constants and `seed_command` (R-M19-12).
- `check_app.py`: the eight functions, and `APP_NAME` checked with the labels.
- `test_settings.py`: Corelata's config, the spec §14 comparison, the seed tests.
- `start_clean.py`, `test_start_clean.py`: Corelata's (R-M19-13).
- `corelata.hosted.yaml`: spec §14's config (R-M19-11); no `groups_header`, scorer or
  translation roles.
- `vercel/lib/auth.ts`, `route.ts`: comments only; groups are kept for Coglossa's account shape
  and ignored by Corelata. `route.test.ts` adds two tests (`people-first` with Coglossa's line,
  the cookie name).
- `vercel/middleware.ts`: "The Corelata demo is not configured."
- `vercel/vercel.json`: the operator guide's sample `Content-Security-Policy` on every path;
  `lib/site.test.ts` (Corelata's) checks it word for word and checks the sign-in page's colours
  against `web/src/styles/tokens.css`.
- `vercel/static/login.html`: title "Sign in – Corelata" (§3.4's pattern), key `corelata.theme`,
  a comment naming the colour check.
- `add-user.mjs`: the usage names `CORELATA_USERS`; the groups comment.
- `smoke.py`: checks 2 and 4 read `/api/system/info` (Corelata has no `/api/me`); check 6 finds
  the example project. `test_smoke.py` runs in CI (`hosted-modal`); Coglossa's runs nowhere.
  **Backport candidate.**
- `README.md`: Corelata's names, the shared Supabase project, the seed, start clean.
- `.github/workflows/hosted.yml`: the seed after the deploy; `ubuntu-24.04` and a 30-minute
  limit (Corelata's runner rule).
- CI `hosted-modal`: `python -m pytest` under `uv run --with` (the bare `pytest` resolved to the
  project's own environment, without the overlay, on macOS), and `--no-project` for
  `check_app.py`. **Backport candidate.**
- `deploy/tests/check-app-image.sh`: the image must not carry `boto3`. **Backport candidate.**

## Rulings

From the plan; rulings made during execution go in the next section.

- **R-M19-1 (owner decisions, spec §23).** Coglossa's Supabase project with Corelata's own
  database `corelata` and bucket `corelata-files`; the existing OpenRouter key; the logins
  `people-first` and `ci`; the `*.vercel.app` address of `corelata-demo`; deployed by hand.
- **R-M19-2 (spike S2 passed).** The API listens through the session pooler;
  `api.progress_poll_s` stays 1.0; no fallback and no self-`NOTIFY` follow-up. S2's second half
  is part of the final acceptance.
- **R-M19-3 (off by default).** Every new setting is in an operational section (`storage`,
  `worker`, `auth`), so `config_hash` is unchanged, and unset means today's behaviour.
- **R-M19-4 (storage off the event loop).** Every storage call on an event-loop path goes
  through `corelata.storage.storage_call`, which runs it in a thread and waits for the thread even
  when the caller is cancelled, then raises the cancellation. So a cleanup in `except
  BaseException` never runs beside the `put` it undoes, and no cancellation stops it half way,
  which is what R-M15-3 had from a plain call. Call sites: `service.add_source` (put, the cleanup),
  `_create_run` (put, the cleanup), `review_run` (the reference's get, the cleanup),
  `stored_export`, `reference_document`, `worker.execute.execute_run` (stale files' listing and
  deletes, the reference download, the exports' puts) and doctor's storage check. Not moved:
  startup (`build_services`, the API's lifespan, `corelata-api`'s checks) and the CLI.
- **R-M19-5 (the reference document in the worker).** `_reference` is an async context manager:
  the download runs in a thread, the temporary copy is removed on the loop.
- **R-M19-6 (`S3Storage.list_keys`).** Sorted keys under the prefix, without the configured
  `storage.prefix`, as `LocalStorage` gives them; paginated; a failure is "cannot list <prefix>".
- **R-M19-7 (doctor).** `storage` names `s3://bucket[/prefix] [at endpoint]` and its fix; a
  `worker` line only with `kick_url` (never called); an `auth` line only with
  `proxy_secret_env`. Both always pass: an unset variable already fails the config check.
- **R-M19-8 (the kick in the API).** The lifespan wraps the queue in `KickingQueue` when
  `worker.kick_url` is set and closes the kicker before the queue; a kick never holds up a
  request or raises.
- **R-M19-9 (the cron and the purge).** `cron_pass(cfg)` runs `sweep_orphans` and
  `expire_discoveries`, then answers `needs_worker`; `purge_pass(cfg)` runs `purge_closed_jobs`.
  Both live in the engine with Postgres tests; the Modal functions only call them.
- **R-M19-10 (the proxy secret).** `X-Corelata-Proxy-Secret`, constant-time compare, only
  `/api/health` open, a pure ASGI middleware so streams pass unbuffered.
- **R-M19-11 (the hosted config).** Spec §14 as data (a test compares them); its first comment
  says "placeholder values" instead of `${NAME}`, which `string.Template` would try to fill.
- **R-M19-12 (the seed).** `settings.seed_command` decides; `EXAMPLE_PROJECT`, `EXAMPLE_SOURCE`
  and `STATEMENT` live in `settings.py` (importable without Modal, so CI tests them) and
  `app.py` imports them. It spawns the deployed app's worker by name, because a function spawned
  from `modal run` belongs to that run's short-lived app.
- **R-M19-13 (start clean).** `deploy/hosted/modal/start_clean.py` refuses a URL that does not
  name `corelata`, checks `current_database()` again, truncates Corelata's and procrastinate's
  tables (not `alembic_version`) and deletes the files under `projects/` and `runs/` of
  `corelata-files` only. A script, not a ninth Modal function.
- **R-M19-14 (the front door).** Copied; cookie `crl_session`; the CSP in `vercel.json`, checked
  against the guide; the sign-in page's colours checked against `tokens.css`.
- **R-M19-15 (the smoke test).** Six checks; `/api/system/info` for checks 2 and 4; the example
  project for check 6; its tests run in `hosted-modal`.
- **R-M19-16 (CI).** `hosted-web` and `hosted-modal` on `ubuntu-24.04` with `ci.yml`'s action
  tags, on every run (each takes about a minute), and `ci-status` needs them; `hosted.yml` keeps
  Coglossa's SHA pins (it holds the deploy secrets).
- **R-M19-17 (lockfiles).** `uv lock` in `engine` and `api` adds `boto3` and its dependencies
  (and `moto`'s in the engine's dev group) and nothing else; uv 0.13 rewrites the lock format
  revision from 3 to 5, which the image's uv 0.13.0 reads (checked by building the image).
- **R-M19-18 (version).** Stays 0.1.7; the controller cuts the next one after the acceptance.
- **R-M19-19 (deploy checks).** `make deploy-check` shellchecks `deploy/hosted/vercel/*.sh`;
  Dependabot watches `deploy/hosted/vercel` (npm) and `deploy/hosted/modal` (pip).
- **R-M19-20 (provisioning).** The controller provisions and deploys by the plan's
  "Provisioning and deploy" section; it is not an implementer task.

## Spec deviations

- §13.6 puts `STATEMENT` in `app.py`; it is in `settings.py` and imported there (R-M19-12).
- §14's comment line about `${NAME}` (R-M19-11).

## Rulings during execution

None yet.

## Spike S1 (Vercel stream length)

Run by the controller during provisioning on `corelata-demo` (spec §23.7). Record here: the
date, how long the stream stayed open, how it ended (the terminal event, or cut at about 120 s),
whether the reconnect's first event carried the current state, and which §13.2 case
`deploy/hosted/README.md` now describes.

## Follow-ups

- **Deploy on push (spec §23.5).** `hosted.yml` skips until the owner creates a Modal token and a
  Vercel token for CI and the controller sets the repository secrets and variables listed in
  `deploy/hosted/README.md`. Until then the controller deploys by hand.
- **CLAUDE.md's gate list** names the CI jobs; add `hosted-web` and `hosted-modal` when it is next
  edited.
- **Backports to Coglossa:** `storage_call` and the storage calls off the loop, the
  `check-app-image.sh` boto3 check, `test_smoke.py` in CI, `python -m pytest` in `hosted-modal`.
- **A warm API** (about $15/month) if the first request after idle (about 5 s) bothers a demo.
- **Uploads over 4 MB** need a direct-to-storage upload (spec §20).
````

- [ ] **Step 3: The operator guide and the README**

````diff
--- a/docs/operator-guide.md
+++ b/docs/operator-guide.md
@@ -393,6 +393,17 @@
 one) and adds it to the project like an uploaded export, passing the signed-in user's name along
 when `auth` is `trusted_header`. The containers must be able to reach `base_url`; Corelata and Coglossa are separate Compose projects, so a service name such as `coglossa-api` does not resolve from Corelata's containers unless you join them to a shared network. Use the host's address or `host.docker.internal:<port>` (the port Coglossa publishes) instead. Without this
 section the import answers that the integration is not configured. An unset key variable is refused when the configuration loads, so the API and worker do not start until it is set. `corelata doctor` reports an empty key variable, a key Coglossa rejects, and an unreachable or wrong URL.
+
+### Settings for the hosted demo only
+
+The configuration also accepts a few settings that only Bonham's hosted demonstration uses
+(`deploy/hosted/`, not part of the bundle): `storage.kind: s3` with a `bucket`,
+`worker.kick_url`, `worker.kick_token_env` and `worker.extra_headers_env`, and
+`auth.proxy_secret_env`. Every one is off unless set, and none is needed here: leave them out.
+Files stay on the `storage.path` volume, the worker runs all the time, and your reverse proxy is
+the only way in. The app image carries no S3 client, so `storage.kind: s3` stops the API and the
+worker at start on this install ("S3 storage needs the s3 extra") rather than storing files
+anywhere else.
 
 ### Applying changes
 
````

````diff
--- a/README.md
+++ b/README.md
@@ -381,6 +381,28 @@
 stylesheet but `tokens.css` holds a raw colour, and the behaviour M9 to M17 pinned is unchanged. The
 rulings, the divergences from Coglossa and the fixes still to come are in `docs/m18-followups.md`.
 
+## M19: a hosted demo
+
+CRL-42. A password-protected Corelata on the internet for demonstrations, built like Coglossa's
+preview so one runbook serves both: a Vercel front door (`deploy/hosted/vercel`: the web app, a
+sign-in page and middleware that checks a signed session cookie, then forwards `/api/*` to Modal
+with the user's name, Corelata's proxy secret and Modal's proxy-auth token), a Modal app
+(`deploy/hosted/modal/app.py`: the API, a burst worker started by a kick after each queued job, a
+cron every 5 minutes and a daily purge, all scaling to zero; `migrate`, `doctor` and `seed` by
+hand), Supabase (the database `corelata` and the bucket `corelata-files`, in Coglossa's project;
+Coglossa's data is never touched) and OpenRouter (`gpt-4.1-mini` writes, `gemini-2.5-flash`
+checks the standards). The seed writes one example report ("Example: Varna port") the first time.
+The engine and API gain what the demo needs, each off unless configured: `storage.kind: s3`, every
+storage call off the event loop (a cancelled call is waited for, so a cleanup never races it),
+`worker.kick_url`, `auth.proxy_secret_env` and its middleware, and the cron's `cron_pass` and
+`purge_pass`. The air-gapped install is unchanged: the app image carries no S3 client
+(`check-app-image.sh` checks), and the bundle, `install.sh` and the `airgap` job are as before. CI
+adds `hosted-web` (the front door's Vitest at 95 % and `tsc`) and `hosted-modal` (the settings,
+start-clean and smoke tests, and the Modal app's import without an account);
+`.github/workflows/hosted.yml` deploys on push once the owner adds its tokens, and until then the
+demo is deployed by hand. `deploy/hosted/README.md` is the runbook; the rulings, the divergences
+from Coglossa and the follow-ups are in `docs/m19-followups.md`.
+
 ## Development
 
     make db-up && make lint && make test   # Postgres 16 in Docker; ruff and pytest for engine and api; Vitest for web
````

- [ ] **Step 4: Check the docs the tests read**

Run: `cd api && uv run pytest tests/test_csp_proxy.py --no-cov -q` (the guide's sample policy is untouched) and `cd deploy/hosted/vercel && pnpm exec vitest run lib/site.test.ts` (it reads the same line). Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C <repo> add deploy/hosted/README.md docs/m19-followups.md docs/operator-guide.md README.md
git -C <repo> commit -F "$SCRATCH/m19-t9-msg.txt"   # "docs: the hosted demo's runbook and M19 follow-ups (CRL-42)" + the two lines
```

---

## Provisioning and deploy (the controller carries this out; not an implementer task)

This replaces spec §16 (R-M19-20). It runs after the implementation branch's whole-branch review, from a clean checkout of that branch (a rehearsal before the merge) or of `main` after it. **[SECRET]** marks each step that writes a secret, and where to. No step prints a secret: no `set -x`, no `cat`, `env` or `echo` of a value; commands that would print one send their output to `/dev/null`. Supabase is not contacted by any step but the deployed app itself and `start_clean.py`: the database `corelata` and the bucket `corelata-files` already exist (spec §23.1).

1. **Tools.** From the repository root: `uv tool install modal --with-requirements deploy/hosted/modal/requirements.txt` (`--force` if it is installed at another version); `modal profile current` names `mrbonha`'s workspace; `npx --yes vercel@61.1.0 whoami` names the signed-in Vercel user. Set `SCRATCH` to the session scratchpad's `m19/` directory.
2. **[SECRET → `~/.config/corelata/hosted.env`, mode 600]** Run `python3 "$SCRATCH/make_hosted_env.py"` (the controller's script from the planning session; it refuses to overwrite an existing file, opens the new one `O_EXCL` with mode 600 and prints key names only). It reads `~/.config/coglossa/preview.env` (the pooler URL, rewritten to path `/corelata` with `sslmode=require`; the S3 key pair, endpoint and region; the Modal proxy-auth token as `CORELATA_MODAL_KEY` and `CORELATA_MODAL_SECRET`), `~/.config/corelata/openrouter.env` (`CORELATA_OPENROUTER_KEY`, written as `OPENROUTER_API_KEY`) and Coglossa's login files (`people-first`'s hash and `ci`'s hash and password, written as `CORELATA_USERS` and `CORELATA_SMOKE_PASSWORD`), and generates `CORELATA_PROXY_SECRET`, `CORELATA_KICK_TOKEN` and `CORELATA_SESSION_SECRET` (`secrets.token_urlsafe(32)` each, new for Corelata). It leaves `CORELATA_KICK_URL`, `CORELATA_API_ORIGIN` and `CORELATA_SITE_URL` empty. Check: `stat -f %Lp ~/.config/corelata/hosted.env` prints `600`; `grep -c '^CORELATA_\|^OPENROUTER_' ~/.config/corelata/hosted.env` prints `16`.
3. **Load the values** into the shell that runs the next steps, without printing them: `set -a; . ~/.config/corelata/hosted.env; set +a`. After any step that edits `hosted.env`, load it again.
4. **[SECRET → Modal Secret `corelata-hosted`]** Create the Secret with a placeholder kick URL:
   ```bash
   modal secret create corelata-hosted \
     OPENROUTER_API_KEY="$OPENROUTER_API_KEY" CORELATA_DATABASE_URL="$CORELATA_DATABASE_URL" \
     CORELATA_S3_ACCESS_KEY_ID="$CORELATA_S3_ACCESS_KEY_ID" CORELATA_S3_SECRET_ACCESS_KEY="$CORELATA_S3_SECRET_ACCESS_KEY" \
     CORELATA_S3_ENDPOINT="$CORELATA_S3_ENDPOINT" CORELATA_S3_REGION="$CORELATA_S3_REGION" \
     CORELATA_PROXY_SECRET="$CORELATA_PROXY_SECRET" CORELATA_KICK_TOKEN="$CORELATA_KICK_TOKEN" \
     CORELATA_MODAL_KEY="$CORELATA_MODAL_KEY" CORELATA_MODAL_SECRET="$CORELATA_MODAL_SECRET" \
     CORELATA_KICK_URL=https://placeholder.invalid >/dev/null
   ```
   `modal secret list` shows `corelata-hosted` beside Coglossa's; nothing of Coglossa's is changed.
5. **Migrate** (spike S3's first half): `modal run deploy/hosted/modal/app.py::migrate`. Expected: the image builds and `corelata migrate` exits 0; the database `corelata` is then at revision 0006 (step 8 shows it).
6. **First deploy:** `modal deploy deploy/hosted/modal/app.py`. It prints the URLs of `corelata-api` and `corelata-kick`. **[SECRET → `hosted.env`]** Write them as `CORELATA_API_ORIGIN` and `CORELATA_KICK_URL` (edit the two empty lines in place, for example with a small Python script that rewrites only those keys; never by echoing the file), then load it again.
7. **[SECRET → Modal Secret]** Repeat step 4's command with `--force` after `create` and `CORELATA_KICK_URL="$CORELATA_KICK_URL"`, then `modal deploy deploy/hosted/modal/app.py` again, so the API kicks the real endpoint.
8. **Doctor:** `modal run deploy/hosted/modal/app.py::doctor`. Expected PASS on `config`, `prompts`, `pack`, `pack names`, `backend openrouter` and every `model …` line (the probes reach OpenRouter), `database` ("… at revision 0006", the password redacted), `storage` ("s3://corelata-files at <the project's S3 endpoint> is writable"), `coglossa` ("integrations.coglossa not configured"), `worker` ("kicks https://…--corelata-kick.modal.run when a job is queued") and `auth`. Any FAIL stops the deploy: fix what it names and repeat from the step that set it.
9. **Seed:** `modal run deploy/hosted/modal/app.py::seed`. Expected: "run <id> queued in project 'Example: Varna port'", and a worker starts (Modal's dashboard shows the `worker` function running). Run it a second time: "the example project exists: nothing to seed" (Review Focus 5).
10. **The Vercel project.** From `deploy/hosted/vercel`: `npx --yes vercel@61.1.0 project add corelata-demo --scope bonham-technologies`, then `npx --yes vercel@61.1.0 link --yes --project corelata-demo --scope bonham-technologies` (it writes `.vercel/`, which `.gitignore` excludes). Leave the project's Root Directory empty: the CLI deploys from this directory. In the dashboard, set Deployment Protection as on Coglossa's preview project, so the production address is public (the front door's own sign-in protects it).
11. **[SECRET → Vercel env, production]** From `deploy/hosted/vercel`, in bash (the values come from the loaded `hosted.env`; `printf` passes each on stdin, so none reaches the terminal or the process list):
    ```bash
    for name in CORELATA_API_ORIGIN CORELATA_PROXY_SECRET CORELATA_MODAL_KEY CORELATA_MODAL_SECRET CORELATA_SESSION_SECRET CORELATA_USERS; do
      printf '%s' "${!name}" | npx --yes vercel@61.1.0 env add "$name" production --scope bonham-technologies >/dev/null
    done
    ```
12. **Deploy the front door:** `deploy/hosted/vercel/build.sh`, then from `deploy/hosted/vercel`: `npx --yes vercel@61.1.0 deploy --prod --yes --scope bonham-technologies`. **[SECRET → `hosted.env`]** Write the production address it prints (`https://corelata-demo….vercel.app`) as `CORELATA_SITE_URL`; load it again. Remove `deploy/hosted/vercel/public` afterwards.
13. **The site's headers:** `curl -sI "$CORELATA_SITE_URL/login"` answers 200 with `content-security-policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'`; `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' "$CORELATA_SITE_URL/"` prints `303 …/login`. A 401 from Vercel's own sign-in means step 10's Deployment Protection is still on.
14. **Smoke test:** `uv run --with httpx python deploy/hosted/smoke.py --site "$CORELATA_SITE_URL" --api-origin "$CORELATA_API_ORIGIN" --user ci` (it reads `CORELATA_SMOKE_PASSWORD`, `CORELATA_MODAL_KEY` and `CORELATA_MODAL_SECRET` from the environment). Expected: six `ok` lines.
15. **Spike S1, the stream through Vercel (spec §13.2, §23.7).** Sign in as `ci` with a cookie jar in the scratchpad: `curl -s -c "$SCRATCH/s1.jar" -o /dev/null -d name=ci --data-urlencode "password=$CORELATA_SMOKE_PASSWORD" "$CORELATA_SITE_URL/login"`. Read the example project's id from `GET /api/projects` and its source's id from `GET /api/projects/<id>/sources` (with `-b "$SCRATCH/s1.jar"`), then start a run: `POST /api/runs` with `{"project_id": …, "source_ids": [<the source>], "value_statement": "<the seed's statement>", "max_iterations": 10}` (no `Origin` header, which the front door's CSRF check allows). Hold its stream with timestamps for up to 6 minutes: `timeout 360 curl -N -s -b "$SCRATCH/s1.jar" "$CORELATA_SITE_URL/api/runs/<run>/events" | while IFS= read -r line; do printf '%s %s\n' "$(date +%T)" "$line"; done | tee "$SCRATCH/s1.log"`. Record:
    - the stream ended with the terminal event after more than 125 s: Vercel's limit is an idle limit, and the 15 s comments keep the stream open (case 1);
    - it was cut near 120 s before the terminal event: Vercel caps a response's length (case 2). Open the stream again at once: its first `data:` line must carry the run's current state;
    - the run ended within 125 s: inconclusive. Repeat with a run that waits for a slot: queue nine runs at once on the example source (8 worker slots: `concurrency` 4 × `max_containers` 2) and hold the last one's stream. That costs nine small reports on OpenRouter.

    Write the result in `docs/m19-followups.md` ("Spike S1") and the case into `deploy/hosted/README.md` ("Progress, uploads and the stream"), and commit both on the branch with the two attribution lines.
16. **Spike S2's second half:** `modal app logs corelata` (or the dashboard's `api` logs) shows "progress listener connected" after the API started. For the S1 run, compare each `event: progress` line's time in `s1.log` with each stage's `finished_at` in `GET /api/runs/<run>`: each change shows within 2 s (allowing for the machine clock's offset, `sntp -K /dev/null time.apple.com` shows it).
17. **Doctor and the real bench against the hosted config (spec §14).** Render the config into the scratchpad from the loaded values (it holds no secret, only account URLs; never commit it): from `engine/`, `uv run --extra s3 python -c "import sys, pathlib; sys.path.insert(0, '../deploy/hosted/modal'); from settings import HOSTED_TEMPLATE, render_config; render_config(HOSTED_TEMPLATE, pathlib.Path(sys.argv[1]))" "$SCRATCH/corelata.hosted.rendered.yaml"`. Then `uv run --extra s3 corelata doctor --config "$SCRATCH/corelata.hosted.rendered.yaml"` (the same lines as step 8) and `uv run --extra s3 corelata bench --scenarios real --config "$SCRATCH/corelata.hosted.rendered.yaml"`. Post both tables on CRL-42 (the M17 numbers for this pair were 8/8, 8/8, 4/4).
18. **The manual end-to-end check (spec §19, as `people-first`):** sign in as `people-first`; open the example report; create a project and upload `docs/examples/varna-port.txt`; Suggest value; write the report; watch the steps change (each within 2 s); review it; return it with a note; the revised report completes; download the DOCX; sign out. Then sign in to Coglossa's preview with the same name and password (one password, both demos). Record each step's result in the implementation PR.
19. **Spending limits** (spec §17), before the URL is shared: `python3 "$SCRATCH/or_key_info.py"` shows the key's $25 limit and its usage; the owner confirms the Modal workspace budget (shared with Coglossa's scorer); `GET /api/system/info` through the site reports `max_upload_mb: 4`.
20. **Hand over:** send the owner the site URL and the `people-first` login (its password is Coglossa's). The URL is shared only after the owner has tried it and said yes. The deploy-on-push follow-up (`docs/m19-followups.md`) waits on the owner's CI tokens.

To start clean later: `deploy/hosted/README.md`, "Checks and operations" (`start_clean.py`, then the seed). Teardown is the owner's call only.

## Final verification (what the planner checked on the scratch copy)

The plan was checked on a scratch copy of the branch at 37a8b43 (`$SCRATCH/repo`, with a pristine copy beside it), against the dev Postgres; databases the suites created were dropped by their fixtures, and one throwaway database for the TRUNCATE check was dropped after it.

- Baseline before any change: engine 979 passed (98.47%), api 174 (99.69%).
- After Tasks 1 to 5: engine 1047 passed (98.50%), api 181 passed (99.70%); `ruff check` and `ruff format --check` clean in both.
- Task 6: `hosted-modal`'s pytest 22 passed with `CORELATA_FORBID_SKIP=1`; `check_app.py` lists the eight functions and imports the app as a container does; `start_clean.tables()`'s TRUNCATE ran on a throwaway migrated database and left `alembic_version` at 0006.
- Task 7: the front door's Vitest 50 passed in 5 files (99.28 / 99.15 / 100 / 100%), `tsc` clean, `pnpm install --frozen-lockfile` with Coglossa's lock unchanged; `build.sh` built `public/` with `index.html`, `login.html`, `theme-init.js` and `assets/`.
- Task 8: `hosted-modal`'s full command 37 passed; `make deploy-check` passed in full (shellcheck v0.10.0 now on `deploy/hosted/vercel/*.sh` too, the install and restore tests, `check_compose`); `actionlint` clean on `ci.yml` and `hosted.yml`.
- `make schema`'s two exports into a temporary directory equal the committed `schema/` (no API model changed).
- `make image-app` on the scratch copy (the new locks, uv 0.13.0 in the image): `check-app-image.sh` passed, including the new "no boto3" check.
- The blocks of this plan, applied in task order to a fresh copy of 37a8b43 (with the copies renamed and the two `uv.lock` files from `uv lock`), rebuild the scratch copy byte for byte.
- Not checked here: anything that needs Modal, Vercel, Supabase or OpenRouter (the controller's, in the section above), `make e2e` and the web suite (no `web/` change), and `make airgap-test` (CI's `airgap` job runs it on the pull request).
