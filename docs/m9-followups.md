# M9 follow-ups

## Divergences from Coglossa

- `ProgressFeed` (one poller per run for the SSE streams), `RenderCache` and `PackIndex` on the
  API context — **backport** (CGL-18): Coglossa's events route polls per stream the same way.
- `runs.get_run_brief` (deferred JSON columns for progress reads) — **backport**.

## Spec deviations

- §10.1: none; `review` on `GET /runs/{id}` and the caches are recorded as M9 amendments.

## Rulings during execution

- **R-M9-11**: `ProgressFeed` publishes to a stream only the result of a read that started after
  the stream joined, and only when it differs from what that stream last showed. The route reads
  the run fresh right before subscribing, so nothing stale is pushed and nothing is missed.

## Should fix soon

- ~~`ProgressFeed` polls; LISTEN/NOTIFY from the worker would make the stream event-driven and
  remove `api.progress_poll_s`.~~ — **closed in M14** (CRL-22: `RunListener`; `progress_poll_s` is now the fallback) — CRL-22
- ~~The frame's `style-src 'unsafe-inline'` could become a hash of the template's `<style>` plus a
  nonce on the bridge's style element.~~ — **closed in M14** (CRL-23) — CRL-23
- ~~The operator guide's sample proxy policy is a starting point, not a tested configuration; an
  e2e run behind a proxy that sets it would pin it.~~ — **closed in M14** (CRL-23: `api/csp_proxy.py`, `e2e/csp.spec.ts`) — CRL-23
- ~~`ReviewActions` still allows a return after an accept (the server allows it); decide whether an
  accepted report should be returnable.~~ — **closed in M16** (CRL-21: an accept is final; R-M16-1). — CRL-21

## Later

- ~~Offset or cursor paging for `GET /api/runs` once a project passes 500 runs.~~ — **closed in M14** (CRL-24) — CRL-24
- ~~Discovery polling never gives up on a stuck discovery; the worker's stalled-job sweep is what
  ends it. A client-side ceiling (stop after 10 minutes with a message) is a UX question.~~ — **closed in M16** (CRL-21: a 10-minute ceiling with a message; R-M16-2). — CRL-21
- ~~Discovery backoff (R-M9-9, 15 s cap) adds up to 15 s before a finished discovery is shown; a 5 s
  cap would bound load nearly as well (R-M9-12 kept 15 s; a UX question).~~ — **closed in M16** (CRL-21: 5 s; R-M16-3). — CRL-21

## Closed in M10

- ~~`RunProgress.review` is read from the review events on every progress call for a completed
  run (one indexed query); a `review_state` column on `run`, written by `review_run`, would make
  it free.~~ — **closed in M10** (CRL-17) — CRL-17
- ~~`pack_dirs_signature` stats every file under both pack directories on every `GET /api/packs`
  and every name check; a customer directory with hundreds of files turns that into a measurable
  cost. A debounce (re-stat at most once a second) would bound it.~~ — **closed in M10** (CRL-18) — CRL-18
- ~~Symlinked pack directories are listed by `list_packs` but not walked by `pack_dirs_signature`
  (`rglob` does not descend into symlinked directories), so edits inside such a pack never
  refresh the listing: `os.walk(followlinks=True)`, or document the limitation.~~ — **closed in
  M10** (CRL-18) — CRL-18
- ~~The doctor's fix text hard-codes the pack-name pattern, and the API's `max_length=100` is not
  checked by the doctor.~~ — **closed in M10** (CRL-18) — CRL-18
- ~~`RenderCache` is bounded by entry count (64), not bytes: add a byte budget.~~ — **closed in M10**
  (CRL-19) — CRL-19
- ~~Tests to add: `RenderCache` eviction under concurrent requests for 65 different runs.~~ —
  **closed in M10** (CRL-19) — CRL-19
- ~~Tests to add (T1): a failed claim-id render is not cached, and a DOCX claim-id render is; a
  claim-id cache miss reads the run twice (`run_progress`, then `load_record`).~~ — **closed in
  M10** (CRL-19) — CRL-19
- ~~Tests to add: `ProgressFeed` under a cancelled stream mid-`wait_for` (the `finally`
  unsubscribes; a direct test would pin it).~~ — **closed in M10** (CRL-20) — CRL-20
- ~~Tests to add (T2): the API-level two-stream test does not prove sharing; count `run_progress`
  calls during the overlap.~~ — **closed in M10** (CRL-20) — CRL-20
- ~~Tests to add (T5): `setNote("")` after a return has no assertion, so the m4b "note persists"
  item is closed without a test.~~ — **closed in M10** (CRL-20) — CRL-20
- ~~Tests to add (T6): no test for the 500-run ceiling note or the per-project reset; the AuditTab
  loading test uses a real 80 ms delay.~~ — **closed in M10** (CRL-20) — CRL-20
- ~~Tests to add (T8): `withBridge`'s head regex does not match `<head lang="...">` (the meta then
  goes before `<!DOCTYPE>`; safe in srcdoc, untested).~~ — **closed in M10** (CRL-20) — CRL-20
