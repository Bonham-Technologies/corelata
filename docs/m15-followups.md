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
  in its Global Constraints. Number new ones from R-M15-23.
- **R-M15-19 (Task 1 review).** The `review_run` docstring was narrowed: an interrupted return
  leaves nothing behind unless its commit landed; a rerun left without a queued job (a
  cancellation during `_defer_run`) stays CREATED and spends the return until the orphan sweep
  fails it, which frees the return; the 0005 data test gained a completed-rerun-then-accept case
  and a gate-rejected case.
- **R-M15-20 (Task 4 review).** The Review screen tests pin that a typed note survives Cancel and
  reopening, a null stored note opens empty, and a second return re-locks the parent's actions.
- **R-M15-21 (whole-branch and docs reviews).** The Review page re-reads the run after a refused
  review (409 or 503), so a stale freed page locks; the orphan sweep recomputes each affected
  parent in its own savepoint (`reruns_ended(..., tolerate=True)`), logging and skipping one that
  cannot be recomputed; doctor says "request failed on the repair turn" and gives the generic fix
  when the repair request is rejected; a Hypothesis test keeps migration 0005's decision function
  equal to `service._review_state`; a worker test pins that a gate-rejected rerun frees its
  parent; the operator guide gained the 0.1.3 upgrade paragraph, the queued-rerun wording and
  rewrapped lines, and the README no longer says `install.sh` runs doctor.
- **R-M15-22 (live rehearsal).** A Review page opened before any decision does not poll (nothing
  is pending, R-M15-11), and the app turns `refetchOnWindowFocus` off globally, so a page left
  open while another reviewer returned the report kept offering both actions until reloaded.
  `useRun` now refetches on window focus (the run query only; the app default stays off), so
  switching to the tab shows the decision and, after a failed rerun, its outcome. A page that
  stays focused the whole time still learns only when its user acts (a refused return re-reads
  it, R-M15-21). Cost: one run read per focus.

## Should fix soon

- None.

## Later

- A `CancelledError` (or a lost connection) during the COMMIT round trip of a return whose commit
  in fact landed makes `review_run` delete the rerun's reference-document copy; that rerun then
  fails at its DOCX render and frees the report again. Rare; the report can be returned once more.
- A return now holds the parent's row lock while it reads and copies the reference document (a
  small local file); a slow storage volume would hold other reviews of the same run that long.
- ~~A Review page left open on a returned run reads `GET /api/runs/{id}` every 3 s until the rerun
  ends; a progress stream that stays open for a completed run whose rerun is live would replace
  the poll if many reviewers keep such pages open.~~ — CRL-77
- The parent of a manual rerun (`POST /runs` with `parent_run_id`, after a gate rejection) is
  announced and its `review_state` recomputed when that rerun ends, which changes nothing; a
  check that the parent has a `return` event pointing at the run would save the write.
- `corelata review --return` on the CLI says nothing about a rerun that failed; `corelata status
  <parent>` shows the stored decision only in `--json`.
- `review_event.child_run_id` is `ON DELETE SET NULL`: deleting a single rerun row would turn its
  return into a null-child return that counts as in flight forever (409 on every later return). No
  path deletes a single run today (project deletion cascades to the parent too); any future
  run-delete feature must free or delete the event.
- A non-database exception from `service.reruns_ended` (for example a corrupt stored review event)
  would roll back the rerun's own terminal write and send it through `_fail_run`; consistent with
  the other writes in those transactions. The orphan sweep now isolates each parent in a
  savepoint (R-M15-21), so one bad parent no longer stalls it; the worker's own transactions
  still fail as a unit.
- ~~`engine/tests/worker/test_rerun_end.py`'s `broken` monkeypatch depends on the observer's call
  order to reach `_fail_run`'s fallback; a comment or a narrower patch would make it robust.~~ — **closed in M16** (CRL-37). — CRL-37
- Doctor's WARN fix text promises that a structured call "may cost a second request"; the probe's
  byte-identity test compares the repair messages only (the run's own byte identity rests on the
  agent tests).
- ~~`restore.sh` removes psql's temporary stderr file explicitly; a signal during the query leaks one
  empty file (a trap would need chaining with the later `trap restart EXIT`).~~ — **closed in M16** (CRL-37). — CRL-37
