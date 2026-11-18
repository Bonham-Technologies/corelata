# Corelata hosted demo

A hosted, password-protected Corelata for demonstrations, built like Coglossa's preview: Vercel is
the front door, Modal runs the backend and scales to zero, Supabase holds the data, and OpenRouter
serves the language models. The design is Part B of
`docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md` (with its §23
amendments); the M19 plan's "Provisioning and deploy" section is the step list the controller
followed. The air-gapped install is in `docs/operator-guide.md` and is unaffected by anything here:
everything in this directory is optional and off unless a config turns it on.

The demo's address is `https://corelata-demo.vercel.app`, the Vercel project `corelata-demo`'s
own address (no custom domain). Two logins exist: `people-first` (the demo team's) and `ci` (the smoke test's).

The demo stays out of search results (CRL-98): the front door's middleware (`lib/respond.ts`) sends
`X-Robots-Tag: noindex, nofollow` on every response, and `/robots.txt` (`static/robots.txt`, open
signed out) disallows everything. The public site under `site/` sends neither.

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
Coglossa's front door, which holds the same Modal token, cannot use Corelata's API. Both checks
fail closed: an empty secret or token refuses everything (only `/api/health` is open), and a
websocket without the secret is closed.

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
here. Every Modal function that touches the database refuses, before connecting, any URL whose
effective database (as libpq reads it, so `?dbname=`, `service=` and the like count) is not
exactly `corelata`. Do not use the Supabase dashboard's SQL editor or the Supabase connector for
Corelata's data: they run on the project's default database, which is Coglossa's. Use
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
| `CORELATA_KICK_URL` | Modal Secret | The deployed `corelata-kick` URL (no user name or password in it) |
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
3. `modal run deploy/hosted/modal/app.py::doctor`: the config, the models, the database and the
   storage; any FAIL fails the run, so fix what it names and repeat from the step that set it.
4. `modal run deploy/hosted/modal/app.py::seed`: queues the example report ("Example: Varna
   port") when that project does not exist yet, then starts the deployed worker. It does nothing
   on a database that already has it.
5. The front door: `deploy/hosted/vercel/build.sh`, then from `deploy/hosted/vercel`,
   `npx --yes vercel@61.1.0 deploy --prod --yes --scope bonham-technologies`. The project's Root
   Directory stays empty; `.vercelignore` keeps the built `public/` in the upload.
6. The smoke test (six checks: sign-in, the session through the proxy, Modal's refusal without
   its token, the API's refusal without the proxy secret, health, the example project):
   `CORELATA_SMOKE_PASSWORD=… CORELATA_MODAL_KEY=… CORELATA_MODAL_SECRET=… uv run --with httpx python deploy/hosted/smoke.py --site <site> --api-origin <api> --user ci`

`.github/workflows/hosted.yml` does the same on a push to `main` after `ci` passes, once the owner
adds its tokens (`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`,
`VERCEL_PROJECT_ID`, `CORELATA_SMOKE_PASSWORD`, `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET`,
and the variables `CORELATA_SITE_URL`, `CORELATA_API_ORIGIN`). The tokens are secrets of the
`hosted` Environment (Settings, Environments), which has the owner as its required reviewer, so
each deploy waits for the owner's approval; keep no copy at repository level, where any workflow
could read it. GitHub creates the Environment without protection the first time a job names it,
so add the reviewer before the tokens. Without `MODAL_TOKEN_ID` and `VERCEL_TOKEN` it skips with
a notice. If the deploy ran but a smoke input is missing, it ends with a warning naming the
missing input (never its value). Running it by hand
(`workflow_dispatch`) deploys the dispatched ref with no CI gate, and only from `main`.

## Progress, uploads and the stream

- The API keeps one `LISTEN` connection on the session pooler while it is awake (spike S2: 10 of
  10 notifications, worst 0.117 s). While the connection is down the feed reads every
  `api.progress_poll_s` (1 s) instead.
- The progress stream sends `retry: 3000`, the current state at once, a comment every 15 s and
  ends after the terminal event. Spike S1 (2026-10-21, `docs/m19-followups.md`) held streams
  through Vercel for 40 s and 104 s, one of them idle for about 65 s on keep-alive comments alone,
  and Vercel cut neither; whether it caps a stream past 120 s is unmeasured, because a report
  finishes in about 40 s when a worker slot is free. Both cases are handled: if Vercel ends a
  stream, the browser reconnects after 3 s and the first event carries the current state; if a
  reconnect fails, the page reads the run every 3 s.
- Measured on the live demo (spike S2's second half): each stage change reaches the browser
  about 2 s after the stage before it ends.
- Uploads are capped at 4 MB (`api.max_upload_mb: 4`): Vercel refuses request bodies over about
  4.5 MB with its own 413.

## Checks and operations

- `modal run deploy/hosted/modal/app.py::doctor` checks the config, the models, the database, the
  bucket, the kick URL (named, never called) and the proxy secret. It exits non-zero on any
  failure.
- Rollback: deploy an earlier commit. Migrations only move forward.
- Backups: Supabase's daily database backups. The bucket has none, which is acceptable for a demo.
- Logs: Modal (one day on the Starter plan) and Vercel.
- CI (`ci.yml`, on every pull request and every push to `main`; both jobs feed `ci-status`)
  imports the Modal app without an account (`deploy/hosted/modal/check_app.py`) and runs the
  settings, start-clean and smoke tests (`hosted-modal`), and the front door's Vitest and `tsc`
  (`hosted-web`). To run them locally:

  ```
  # hosted-web
  cd deploy/hosted/vercel && pnpm install --frozen-lockfile && pnpm typecheck && pnpm test

  # hosted-modal (from engine/, after `uv sync --all-groups`; pins as in ci.yml)
  CORELATA_FORBID_SKIP=1 uv run --with pyyaml==6.0.3 --with fastapi==0.162.0 --with httpx \
    python -m pytest ../deploy/hosted/modal ../deploy/hosted/test_smoke.py \
    -q -p no:cacheprovider --no-cov --rootdir ../deploy/hosted/modal
  cd .. && uv run --no-project --with-requirements deploy/hosted/modal/requirements.txt \
    python deploy/hosted/modal/check_app.py
  ```
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
