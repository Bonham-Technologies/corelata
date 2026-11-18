# M4a follow-ups

## Divergences from Coglossa

- Package `corelata_api`, script `corelata-api`, title `Corelata`, logger `corelata.api`, env
  `CORELATA_CONFIG`; the 401 message names Corelata.
- `errors.py`: Corelata's exceptions (`TraceError` → 404, `PackError` → 422,
  `CoglossaFetchError` → its own status); no `code` field on conflicts (nothing sets one yet).
- `routes/`: Coglossa's translation routes replaced by spec §10.1; the SSE stream, `read_upload`,
  `content_disposition` and the SPA mount are copied. `content_disposition(filename, *, inline=False)`
  gained an `inline=` flag (HTML and Markdown display in the browser) — **backport** candidate.
- `conftest.py`: `Api` carries the `db` handle and `make_api` takes `coglossa_transport`; the
  in-test worker (`complete_queued`) replaces Coglossa's seeded runs.
- `test_app.py`: the protected-route 401 test builds its route list from `app.openapi()["paths"]`
  plus `GET /api/openapi.json`, because fastapi 0.143 keeps nested routers lazy and `app.routes`
  has no leaf routes — **backport** candidate.
- The worker's periodic `corelata.sweep_orphans` task is new; Coglossa has the same gap
  (runs stranded when a job ends `failed` or is never queued) — **backport**.

## Spec deviations

- §10.1 route prefix `/api`; `GET /api/system/info`, `GET /api/runs`, `GET /api/runs/{id}/exports/{name}`
  added; `RunTrace` shape; review response; 409 for an unconfigured Coglossa integration
  (recorded in the spec by Task 11).
- §11: the listening address is a CLI flag, not `api.host`/`api.port`.
- §5.3 / §11 `integrations.coglossa.api_key_env`: sent as `Authorization: Bearer`; the caller's
  identity is forwarded as `X-Remote-User` (Coglossa's trusted header). Coglossa itself has no
  bearer auth today; the key is for a proxy in front of it. Confirm with the customer's layout.
- The plan's draft-profile test needed `standards.default_pack` set to the customer pack, because
  `POST /runs` has no pack field (profiles resolve under the default pack).

## Should fix soon

- ~~A rejected `add_source` (unparseable upload or Coglossa export) leaves an empty
  `projects/<id>/sources` directory in storage; `delete_prefix` removes only the source's own
  directory.~~ — **closed in M8** (CRL-6) — CRL-6
- ~~Starlette spools the whole multipart body before `read_upload` applies `api.max_upload_mb`; put
  a body-size limit on the reverse proxy too.~~ — the upload route answers 413 from
  `Content-Length` before parsing — CRL-88; ~~a chunked request is still spooled before it is
  measured~~ — the route counts the body as it is read and answers the same 413 at the limit —
  CRL-104
- ~~The sweep's `args->>'run_id'` lookup has no index on `procrastinate_jobs` (a scan per candidate
  row; fine while job history is small).~~ — **closed in M8** (CRL-10) — CRL-10
- ~~Pack directory names must match `^[a-z0-9][a-z0-9-]*$` to be reachable through
  `/api/packs/{name}`; the listing shows them regardless.~~ — **closed in M9** (CRL-16) — CRL-16
- ~~`GET /api/runs/{id}/report?with_claim_ids=1&format=docx` re-renders through a temporary file
  on every call.~~ — **closed in M9** (CRL-9) — CRL-9
- The SPA catch-all is GET-only (`HEAD /` answers 405).
- ~~The report routes load the full `RunRecord` (all model-call bodies) per request, and
  `with_claim_ids=1` re-renders `trace.json` too (`render_outputs` always emits it): check the
  state via `run_progress` and render only the requested file later.~~ — **closed in M9** (CRL-9) — CRL-9
- The api test package is named `tests` like `engine/tests`, which the engine's editable install
  also puts on `sys.path` (works because pytest prepends `api/`); rename one side later.
- ~~An invalid `integrations.coglossa.base_url` raises `httpx.InvalidURL` (not an `HTTPError`) at
  fetch time, so the route answers 500.~~ — **closed in M8** (CRL-11) — CRL-11
- ~~An unset `api_key_env` variable silently sends no key.~~ — **closed in M8** (CRL-11) — CRL-11
- ~~The doctor does not check the Coglossa integration.~~ — **closed in M8** (CRL-11) — CRL-11
- ~~The fetched Coglossa export body has no size cap (trusted peer).~~ — **closed in M8** (CRL-11) — CRL-11
- ~~The 503 body carries the driver's `error_reason` text (host and port, never the password; the
  CLI does the same).~~ — CRL-86
- ~~`GET /api/runs/{id}/events` polls the database every `api.progress_poll_s` per open stream
  (fine for a handful of analysts; LISTEN/NOTIFY later).~~ — **closed in M9** (CRL-8) — CRL-8
- ~~`GET /api/packs/*` reads the pack directories on every call (two directory scans).~~ — **closed in M9** (CRL-8) — CRL-8
- ~~`read_upload` holds the whole upload in memory (≤ `api.max_upload_mb`), as Coglossa does.~~ — CRL-73
- The sweep has no retry-window gap: procrastinate's retry sets the job back to `todo` with a
  future `scheduled_at`, so a pending retry is never swept.
- `POST /api/projects/{id}/sources/from-coglossa` fetches inside the request (30 s timeout);
  a slow Coglossa holds the request that long.
- No `DELETE` routes (spec §15: no delete path in v1); Coglossa's delete-with-confirm pattern
  is the template when one is wanted.

## Later

- M4b: delivered (`web/`); the client is generated from `schema/openapi.json`, the stream is
  closed on terminal/`deleted`, `GET /api/system/info` drives the Coglossa button and the footer,
  `api/devstack.py` runs the Playwright stack.
- M5: delivered (deploy/).
