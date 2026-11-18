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
  `WorkerConfig`; `S3StorageConfig`'s key variables are `CORELATA_S3_*`. Fail-closed settings
  (R-M19-21, R-M19-22): `auth.proxy_secret_env` and `worker.kick_token_env` set to an empty string
  are validation errors (Coglossa reads an empty name as "off" or accepts it), and
  `worker.kick_url` with userinfo (`user:pass@`) is a validation error. **Backport candidate.**
- `doctor.py`: the `worker` line (kick URL, never called) as Coglossa's; the `auth` line for the
  proxy secret is Corelata's; the storage check runs off the event loop.
- `worker/kick.py`: `KickingQueue.defer` passes `priority` through (R-M17-29), so a discovery still
  goes first. Coglossa's has no priority; two extra tests.
- `worker/app.py`: `queue_status` and `needs_worker` as Coglossa's; `cron_pass` and
  `purge_pass` are Corelata's (Coglossa has no periodic tasks to stand in for).
- `api/proxy.py`: header `X-Corelata-Proxy-Secret`; the message names Corelata. **Fails closed
  (R-M19-21)**, unlike Coglossa's `ProxySecretMiddleware`, which passes every non-http scope
  (websockets included) and compares a missing header to an empty secret: only `lifespan` passes
  unchecked; a websocket without the secret is closed with code 1008 before the app sees it; any
  other scope type is dropped; an empty configured secret refuses everything but `/api/health`
  (exact match). **Backport candidate.**
- `api/app.py`: the lifespan closes the kicker's HTTP client if building the API context fails
  (R-M19-22), and closes the kicker before the queue on shutdown. **Backport candidate.**
- `deploy/hosted/modal/app.py`: no `scorer`, scorer image, weights Volume or
  `upload_weights.py`; adds `purge`, `seed` and the example source in the image; `api.web_dir`
  unset; `cron` calls `cron_pass`. **Database guard (R-M19-23):** a `_render()` helper runs
  `settings.check_database_url` on `CORELATA_DATABASE_URL` before the config is rendered, and
  `_config()` (api, worker, cron, purge, seed), `migrate` and `doctor` all go through it before
  any connection. `kick` refuses an empty token (`check_kick` returns False for `Bearer ` with
  nothing after it; an unset token gives 401, not a 500). `doctor` and `seed` run their command
  with `check=True`, so a non-zero exit fails the Modal function. **Backport candidates:** the
  kick's empty-token refusal and the doctor's non-zero exit.
- `settings.py`: the seed's constants and `seed_command` (R-M19-12); `check_database_url` (R-M19-23):
  the effective database is read with libpq's own parser (`to_libpq_url`, then
  `psycopg.conninfo.conninfo_to_dict`) and must be exactly `corelata`; any `service`, and any
  `options` that mention dbname, database or search_path, are refused (CRL-52 tightened this to
  any `options` at all, and to `PGOPTIONS` or `PGSERVICE` in the environment). This replaces Coglossa's
  path-only check, which a `?dbname=` or `service=` query would defeat. Coglossa's own database
  is in the same Supabase project, so this is Corelata's data-safety rule.
- `check_app.py`: the eight functions, and `APP_NAME` checked with the labels; the functions are
  found by scanning `app.py`'s globals for `modal.Function` (R-M19-24), not with
  `App.registered_functions`, which modal 1.6.2 deprecates and 1.7.0 removes. **Backport
  candidate.**
- `test_settings.py`: Corelata's config, the spec §14 comparison, the seed tests, the database
  guard and kick tests.
- `start_clean.py`, `test_start_clean.py`: Corelata's (R-M19-13); `check_url` calls
  `check_database_url`, and the `current_database()` re-check stays.
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
  limit (Corelata's runner rule). **Hardening (R-M19-24):** a final step warns
  (`::warning::deployed, but the smoke test did not run; missing: ...`) naming the unset smoke
  inputs, never their values; a manual dispatch deploys only from `refs/heads/main`; the checkout
  uses `persist-credentials: false`. **Backport candidate**: Coglossa's workflow has all three
  gaps.
- CI `hosted-modal`: `python -m pytest` under `uv run --with` (the bare `pytest` resolved to the
  project's own environment, without the overlay, on macOS), and `--no-project` for
  `check_app.py`. **Backport candidate.** **Pinned overlay (R-M19-24):** the overlay is pinned to
  `requirements.txt` (`pyyaml==6.0.3`, `fastapi==0.143.2`), and pytest runs with `-W error` and
  one ignore, Starlette's "Using `httpx` with `starlette.testclient` is deprecated" notice
  (fastapi's `fastapi.testclient` emits it whenever httpx, not httpx2, is installed, and httpx is
  what `smoke.py` and its tests need). Any other warning fails the job. **Backport candidate.**
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

Each came from a review; the fix round that applied it is committed on the branch.

- **R-M19-21 (the proxy secret fails closed; Task 3).** Only `lifespan` passes the middleware
  unchecked. An `http` request without the secret gets the 401, except exactly `/api/health`. A
  `websocket` without it is closed with code 1008 and the app is never called; any other scope type is dropped. An empty configured secret refuses every request
  but `/api/health`. `auth.proxy_secret_env: ""` is a configuration error, not "off". Tests pin
  lookalike paths. Reason: the Modal proxy token is Coglossa's,
  so this secret is the only thing that keeps Coglossa's front door out of Corelata's API.
  Divergence from Coglossa; **backport candidate.**
- **R-M19-22 (the kick settings fail closed; Task 4, extends R-M19-21).** `worker.kick_token_env`
  empty is a validation error (Coglossa accepts it, which would make `Bearer ` a valid token);
  `worker.kick_url` must be `http(s)` without userinfo (a URL with `user:pass@` would put a
  credential in a config file and a log); the API's lifespan closes the kicker's HTTP client when
  building the API context fails (test `test_a_failed_start_closes_the_kicker`). Divergence from
  Coglossa; **backport candidate.**
- **R-M19-23 (the hosted parts refuse any database but `corelata`; Task 6).** The Supabase project
  is shared with Coglossa, so a wrong URL must fail before a connection. `check_database_url` reads
  the effective `dbname` with libpq's parser and requires exactly `corelata` (and refuses `service`
  and `options` naming dbname, database or search_path; since CRL-52, any `options`, `PGOPTIONS`
  or `PGSERVICE`); every Modal function that touches the
  database, `migrate` and `doctor` included, calls it first (`_render()`); `start_clean.check_url`
  calls it too and keeps its `current_database()` re-check. The kick refuses an empty token. Modal
  `doctor` and `seed` fail when the command exits non-zero (`check=True`), so a FAIL in the doctor
  is no longer a green Modal run. Divergence from Coglossa's path-only check; the **kick and
  doctor parts are backport candidates** (the database guard is Corelata's own rule, since
  Coglossa's app owns the project's default database).
- **R-M19-24 (hosted.yml hardening, a pinned and strict `hosted-modal`, and `check_app`; Task 8).**
  `hosted.yml` warns when the smoke inputs are missing after a deploy, deploys a manual dispatch
  only from `refs/heads/main`, and checks out with `persist-credentials: false`. `hosted-modal`
  pins `fastapi` and `pyyaml` in its overlay to the versions in `requirements.txt` (`httpx` stays
  unpinned; it is not in that file) and runs pytest with `-W error`, allowing only Starlette's
  httpx notice. `check_app.py` finds the functions by scanning for `modal.Function` instead of the
  deprecated `App.registered_functions` (removed in modal 1.7.0). **Backport candidate**: Coglossa has all of these gaps.

## Spike S1 (Vercel stream length)

Run by the controller on 2026-10-21 on `corelata-demo` (spec §23.7), signed in as `ci`, with the
stream read through `https://corelata-demo.vercel.app`.

- One report alone: the stream stayed open 40 s and ended with the terminal event.
- Nine reports queued at once (eight worker slots), holding the last one's stream: it stayed
  open 103.6 s, about 65 s of it idle with only the 15 s `: keep-alive` comments (four of them),
  and ended with the terminal event. Vercel did not cut it.
- **Ruling R-M19-25: inconclusive on a hard cap past 120 s, recorded as measured.** No stream
  lasted past 120 s: a report finishes in about 40 s when a slot is free, so a stream that long
  needs more than one queue's worth of waiting. An idle limit, if Vercel has one, is longer than
  65 s. Both §13.2 cases are already handled (the browser reconnects after `retry: 3000` and the
  first event carries the current state), so the README describes both. Queueing 17 reports to
  push past 120 s was judged not worth the clutter on the demo.

## Spike S2, second half (stage changes through the site)

Measured on the same runs (2026-10-21):

- The API's `LISTEN "corelata_run"` session was open on the `corelata` database through the
  session pooler (`pg_stat_activity`), so progress came from notifications, not polling.
- Each stage change reached the browser 1.6 to 2.2 s after the previous stage's `finished_at`
  (the machine clock was 0.12 s off, by `sntp`). The `completed` event came about 3.3 s after the
  run's `finished_at`: the run's exports are uploaded to S3 after `finished_at` is stamped and
  before the commit that notifies, so the page says "ready" when the downloads exist.

## Acceptance on the live demo (2026-10-21)

- `modal run …::doctor`, and `corelata doctor` against the rendered hosted config from the
  controller's machine: 13 PASS each (config, prompts, pack, pack names, OpenRouter with both
  models, both models' structured output, the auditor schema, the `corelata` database at 0006,
  `s3://corelata-files` writable, coglossa not configured, the kick URL, the proxy secret).
- `smoke.py`: six `ok`.
- `corelata bench --scenarios real` with the hosted models (on a throwaway local database and
  local storage, so the demo's data stayed clean): full 6/8, gate 7/8, rule failures 3/3, no
  errors. Repeated three times each: `mixed-relevance-sources` 3/3 (the first miss was variance);
  `conflicting-rail-figures` gate-rejected 3/3, as at M15 and M16 (it passed once at M17). The
  prompts, pipeline, schemas and bench are unchanged since v0.1.6, so this is the scenario's known
  borderline, not a regression.
- The manual end-to-end check as `people-first` (a Playwright script on the live site, the
  password read from the owner's file): sign in; the example report opens; a new project and an
  upload of `varna-port.txt`; Suggest value (12.6 s and 24.8 s on two tries); the report ready in
  35 s and 66 s, each step shown as it changed; review; the DOCX downloads (40 KB); Return with a
  note, and the revised report follows the note; sign out (then `/api/projects` answers 401); the
  same name and password sign in on Coglossa's preview. Every request stayed on the site's origin.
- OpenRouter: M19's checks used $0.58 of the key's $25 limit.
- The demo data was then cleared with `start_clean.py` (database `corelata` and bucket
  `corelata-files` only; Coglossa's bucket was checked unchanged) and the example seeded again.

## Test counts

The plan expected engine 1047, api 181 and `hosted-modal` 37. The real counts at the end of
Task 8 are engine 1056, api 190, `hosted-modal` 45 and the front door's Vitest 50 (unchanged from
the plan). The difference is the fix rounds: R-M19-21 and R-M19-22 added engine and api tests
(the proxy, the kick settings, the kicker closed on a failed start), and R-M19-23 and R-M19-24
added `hosted-modal` tests (the database guard, the kick's empty token, `run_cli`'s exit status,
`check_app`). Task 9 changes only documents.

## Follow-ups

- **Deploy on push (spec §23.5).** `hosted.yml` skips until the owner creates a Modal token and a
  Vercel token for CI and the controller sets the repository secrets and variables listed in
  `deploy/hosted/README.md`. Until then the controller deploys by hand. — CRL-44
- ~~**CLAUDE.md's gate list** names the CI jobs; add `hosted-web` and `hosted-modal` when it is next
  edited.~~ — CRL-61
- **Backports to Coglossa:** `storage_call` and the storage calls off the loop, the
  `check-app-image.sh` boto3 check, `test_smoke.py` in CI, `python -m pytest` in `hosted-modal`,
  and R-M19-21, R-M19-22, R-M19-23 (the kick's empty-token refusal and the doctor's exit status)
  and R-M19-24.
- **A warm API** (about $15/month) if the first request after idle (about 5 s) bothers a demo.
- **Uploads over 4 MB** need a direct-to-storage upload (spec §20).
- **Starting and returning a report are slow on the demo** (found in the live check). Through the
  site, `POST /api/runs` answered about every 4.1 s when nine were sent one after another, and a
  Return took 8.5 s from the click to the revised report's page. Meanwhile the Return dialog's
  buttons are disabled (`busy`), so nothing is sent twice, but the button keeps saying "Return".
  Two parts: profile `service.start_run` and `review_run` on the hosted stack (Modal us-east, the
  pooler and Storage in ca-central-1: connection checkouts with `pool_pre_ping`, the pack and
  config snapshots, the reference document's S3 get and put) and cut what is slow; and show
  "Returning…" / "Starting…" on the pending button.
  CRL-43 (2026-10-30) did the second part: the pending buttons read "Starting…", "Accepting…",
  "Returning…" and "Stopping…". A local profile against the dev database found nothing to cut in
  the service itself: `start_run` sends 3 statements on one connection checkout in about 30 ms,
  and a return 12 statements on one checkout in about 30 ms, both before the queue's defer (the
  worker kick runs in the background). That is with the base pack, which has no reference
  document: a pack with one adds a storage put to every start and a get and a put to every
  return (S3 in ca-central-1 on the hosted stack), which the local profile cannot measure.
  Otherwise the 4.1 s and 8.5 s are spent outside these
  functions' own work, on the hosted path: connection setup through the pooler from us-east, the
  defer's own connection, or the Vercel-to-Modal hop. Profiling that needs the hosted stack. — CRL-43, CRL-66

### Should fix soon

Parked minors that touch the guard or a safety property; none breaks an invariant today.

- **`check_database_url`, dashed `options` (Task 6). Fixed by CRL-52.** ~~The `options` filter was a
  substring match, so `-c search-path=...` and `--search-path=...` passed it (Postgres maps `-` to
  `_`).~~ It could not change the database, so the `corelata` invariant held. The guard now refuses
  any non-empty `options` (the demo needs none). — CRL-52
- **`check_database_url`, libpq environment fallbacks (Task 6). Fixed by CRL-52.** ~~`PGOPTIONS` and
  `PGSERVICE` are read by libpq at connect time and the guard read only the URL.~~ It now refuses
  when either is set in the environment. — CRL-52
- **Unknown ASGI scope (Task 3).** ~~The proxy middleware reads `scope['headers']` before it checks
  the scope type, so an unknown scope type raises `KeyError` (still closed).~~ uvicorn sends only
  `http`, `websocket` and `lifespan`.
  CRL-57 (2026-11-08) fixed it: any other scope type is refused before its headers are read,
  even with the secret, and logged at warning. — CRL-57
- **No server-side session revocation (Task 7).** Inherited from Coglossa: a cookie stays valid
  until it expires or `CORELATA_SESSION_SECRET` rotates; removing a user from `CORELATA_USERS`
  does refuse their cookie on the next request.
- **Concurrent or half-failed seeds (Task 6).** `seed` is run by hand by one controller; two at
  once, or a retry after a half-failed run, is not guarded.

### Later

- **Stale-export sweep (Task 2).** The sweep at a restarted run's start is interruptible; the
  next restart sweeps again.
- **S3 `get` mid-stream (Task 1).** A non-botocore error part-way through a download is not
  mapped to a storage error (a faithful copy of Coglossa).
- **`check-app-image.sh` and python's PATH (Task 1).** The image check passed; the PATH it finds
  python on is worth pinning when the script is next edited.
- **A test's wait readability (Task 2).** The wait in the storage test is hard to read.
- **Thin API kick test (Task 4).** `api/tests/test_kick.py` is thin; the engine's timed test
  covers the behaviour.
- **`queue_status` reads (Task 5).** It makes three reads without a snapshot; the next cron tick
  corrects any skew. An unrelated `QUEUE` assert in the cron tests could be removed.
- **Duplicated table list (Task 6).** `start_clean`'s table list is copied from
  `corelata.testing`; import it instead.
- **Tests of copies (Task 6).** Some `hosted-modal` tests exercise copies of `kick` and of
  `app.py` logic, not the Modal functions themselves.
- **Starlette warning noise (Task 6, Task 8).** `-W error` allows one Starlette notice; drop the
  ignore when fastapi's testclient stops importing httpx.
- **Long lines (Tasks 6, 7, 8).** A 146-character docstring line in `start_clean.py`, two long
  comment lines in the front door's TypeScript and long lines in `hosted.yml` come verbatim from
  the briefs and sit outside ruff's scope.
- **Copied tests (Task 7).** ~~The front door's tests still carry Coglossa's `CGL-26` and
  `corelata-admins` names.~~ — **closed** (CRL-60: neutral names, no ticket key). — CRL-60
- **CSP test (Task 7).** `lib/site.test.ts` checks only the `/(.*)` block of `vercel.json`.
- **No recorded red run (Tasks 4, 5, 6, 8).** The reports give pass counts but not the failing
  run before each fix; the tests were checked against the fix by review.
- **Spec prose in a test (final review).** `test_settings.py` requires the spec's sentence about
  `STATEMENT`; pin the statement text alone, or match §13.6's quoted string by regex.
- **Sign-in font (final review).** ~~`login.html` names "Noto Sans" but loads no font, so it renders in
  `system-ui`; drop the name or inline the font-face.~~ — **closed** (CRL-60: the name is dropped, and
  `lib/site.test.ts` fails if the page names a font the web app bundles without loading it). — CRL-60
- **boto3 default session (final review). Done, CRL-59.** ~~Doctor's storage check creates a client on boto3's default
  session from a worker thread; use `boto3.session.Session().client(...)`.~~ — CRL-59
- **Doctor probe leftovers (final review). Done, CRL-59** (doctor warns naming the key; `start_clean` sweeps the root probes). ~~`start_clean` sweeps `projects/` and `runs/` only; a
  `.corelata-check-<hex>` probe whose delete failed stays in the bucket's root.~~ — CRL-59
