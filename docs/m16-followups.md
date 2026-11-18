# M16 follow-ups

## Divergences from Coglossa

- `restore.sh`'s single `on_exit` trap and the `corelata-restore.XXXXXX` temporary file —
  **backport** with CGL-18 (Coglossa's restore script has the same late `trap restart EXIT`).
- `corelata_api.app.stop_listener` — Corelata only (Coglossa's API has no LISTEN task).
- `OpenAICompatBackend`'s "model server unreachable (<url>)" — **backport candidate**: Coglossa's
  adapter formats transport errors the same way.
- `web/src/test/setup.ts` failing a test on an unmocked request — **backport candidate** for
  Coglossa's web tests.
- The accept-is-final rule, the discovery ceiling and the discovery in the URL — Corelata only.

## Spec deviations

- None. §10.1 and §10.3 carry M16 amendments.

## Rulings during execution

- How the plan applied R-M16-1 to R-M16-13, and the rulings it added (R-M16-14 to R-M16-24), are
  in its Global Constraints. Number new ones from R-M16-25.

## Should fix soon

- None.

## Later

- ~~The ceiling's message no longer promises a sweep (R-M16-18): the sweep fails a discovery only
  when its job is gone; a discovery whose worker died is re-queued after `worker.stalled_after_s`
  (900 s by default) and runs again, and nothing sweeps while no worker runs. A per-discovery
  deadline in the worker would let the screen say how a stuck discovery will end.~~ — **closed in M17** (CRL-38: `worker.discovery_deadline_s`; R-M17-1). — CRL-38
- The discovery's age falls back to the browser's clock when an answer has no `Date` header (a
  proxy that strips it); a skewed workstation behind such a proxy is back to the client clock.
- ~~The New run screen keeps the discovery in the URL but not the chosen sources: a reload selects
  every source again (as before M16), so a discovery made on a subset shows next to a full
  selection.~~ — **closed in M17** (CRL-40). — CRL-40
- ~~`received_until`'s deadline branch (the loop ends because the time is up between two
  notifications) has no test of its own; the timeout case is covered by an empty read.~~ — **closed in M17** (CRL-40). — CRL-40
- An accept is final for the run; a report accepted by mistake needs a new run. An "undo
  accept" (with an audit event) would be a product decision.
- ~~A model `base_url` with a query string cannot work: httpx joins the request path into the
  query, giving `http://h/v1?key=abc/chat/completions`. Config validation could reject a
  `base_url` with a query or a fragment.~~ — **closed in M17** (CRL-39). — CRL-39
- ~~The return-race test's lock-wait poll counts any lock waiter in the database
  (`engine/tests/test_return.py`, `_until_a_session_waits_for_a_lock`). Filter it on the holder's
  pid if tests ever run in parallel against one database.~~ — **closed in M17** (CRL-40). — CRL-40
- ~~The `NewRunPage` race test waits a fixed 300 ms for a write that must not happen.~~ — **closed in M17** (CRL-40). — CRL-40
- The development CSP proxy prints `repr(e)` to stderr when its upstream does not answer, which
  could include a URL embedded in an exception message. This is development only.
