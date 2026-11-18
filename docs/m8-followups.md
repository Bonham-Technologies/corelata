# M8 follow-ups

## Divergences from Coglossa

- `LocalStorage.delete_prefix` prunes emptied parents and `list_keys` lists a prefix — **backport** (CGL-18).
- The worker's nightly `purge_closed_jobs` task and the `(args->>'run_id')` index — **backport** (Coglossa has the same sweep and the same accumulation).
- `_logo_runs` keeps any run child that holds a picture — Coglossa has no header marking.

## Spec deviations

- §7.2/§10.1: a completed run can be returned once (R-M8-1); the spec now states it. M15 re-reads it: one live or completed return (R-M15-1, spec §10.1 M15 amendment).
- §12: `restore.sh` refuses foreign schemas without an override flag (R-M8-5).

## Should fix soon

- ~~`review_run` writes a placeholder event before the child exists; a crash between the two leaves a `return` event with `child_run_id` null. The orphan sweep could clear such events.~~ — **closed in M15** (CRL-34): the return, its rerun and the decision commit in one transaction; migration 0005 deleted the placeholders left behind (R-M15-12, R-M15-13). — CRL-34
- ~~`review_run`: the child and the `return` event are separate transactions; a failed `set_review_child` leaves a CREATED child with a parent link, and a failed queue leaves a FAILED child and uses up the run's one return (fix: one transaction, with `_create_run` taking an outer session).~~ — **closed in M15** (CRL-34): one transaction, and a rerun that failed frees the return (R-M15-1). — CRL-34
- A partial unique index on the review event table `(run_id) WHERE action = 'return'` would enforce one return per run in the database (defence in depth; the run's row lock does it today). — **dropped in M15**: a run may now hold several return events, one of them live (R-M15-1); the row lock keeps it to one.
- `writer_overflow` does not reserve the gate-cited units' tokens: cited units of forced-digest sources count against `writer_unit_budget_tokens`, so the writer's cut can withhold non-digested units, and a run whose cited units alone exceed the budget leaves a non-digested source invisible (M2 amendment). Reserve cited tokens in the overflow rule.
- The Coglossa fetch still runs inside the request (30 s); a slow Coglossa holds the API worker.
- The Coglossa cap bounds memory, not time: httpx's timeout is per operation, so a slow-drip body can outlast 30 s. Add an overall deadline.
- ~~`service.review_run` cleans up in `except BaseException`; a `CancelledError` can interrupt the cleanup await (shield it or narrow to `Exception`).~~ — **closed in M15** (CRL-34): nothing is left to clean up in the database; the reference copy goes with synchronous file calls (R-M15-12). — CRL-34
- `restore.sh` could offer `--allow-schemas` for sites that knowingly keep an extra schema.
- Scenario fixtures for conveyor-routed findings and added-rule profiles still need a steerable synthetic auditor.

## Later

- Tests to add: a `procrastinate_periodic_defers` row referencing a purged job (the purge deletes defers first; the FK has no cascade).
- Tests to add: a multi-chunk oversized Coglossa body, proving the read stops early.
- Tests to add: doctor `coglossa` non-200 and `InvalidURL` branches.
- Tests to add: a bare `w:object` header logo.
- Tests to add: `code == 2` for the CLI missing-file case.
- `purge_closed_jobs` never purges a job with neither `scheduled_at` nor events (the safe direction; such rows would accumulate if procrastinate ever stopped writing events).
- Migration 0003 creates its indexes without `IF NOT EXISTS`; a hand-created index of the same name would fail the install-time migrate.
- ~~`restore.sh` keeps `2>/dev/null` on the schema query, so psql's own error is hidden behind the die message.~~ — **closed in M15** (CRL-36). — CRL-36
- Pin `postgres:16-alpine` by digest across `bundle.sh`, `check-bundle.sh` and the compose files.
