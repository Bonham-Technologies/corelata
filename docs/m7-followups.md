# M7 follow-ups

## Divergences from Coglossa

- `corelata.version.build_version` / `CORELATA_BUILD_VERSION` baked into the image: Coglossa has
  the same gap (`/api/health` shows the package version) — **backport** (CGL-18).
- The report frame bridge (`frameBridge.ts`) has no Coglossa counterpart; Coglossa's review view
  renders in the page.

## Spec deviations

- §6.8: `pack diff` takes `--profile-left`/`--profile-right` rather than a `name@profile`
  syntax; a side may be a pack directory or a run directory (recorded in the spec).
- §10.3: the frame is `srcdoc` + `sandbox="allow-scripts"`, not same-origin (recorded).

## Should fix soon

- `pack diff` prints added rules with `[severity, checkability]` only; a `--full` flag could print
  the whole rule.
- `pack diff` compares resolved packs, so two directories that resolve the same way (through
  different `extends` chains) show no difference; that is the intended meaning of "same pack".
- `bench --concurrency` shares one `tallies` dict across runs; safe today because scoring has no
  `await`, and noted here so a future async scorer does not break it.
- `profile extract` still has no digest pass for a single report longer than the whole budget.
- `run_bench` uses `asyncio.gather`; an exception raised outside a run's `try` (in `score_run`
  or a trace write) does not cancel the sibling runs before the backends close. `asyncio.TaskGroup`
  (Python 3.12 is the floor) would give structured cancellation.
- A partial `bench.json` is only recognisable by its run counts (`summary.runs`, scenarios with
  `runs: []`); a `complete`/`interrupted` marker would make it explicit (schema change).
- `_write_report` leaves `bench.json.tmp` behind if `os.replace` raises; the next write overwrites
  it, and `bench.json` is never half-written.
- ~~The in-frame bridge script runs in an opaque origin; a `<meta http-equiv="Content-Security-Policy">`
  inside the `srcdoc` (the bridge by hash, `connect-src 'none'`) would be the next hardening step.
  A site reverse proxy that sends a CSP without `'unsafe-inline'` would block the bridge.~~ — **closed in M9** (CRL-16) — CRL-16
- `RunRecord.corelata_version` and `BenchReport.corelata_version` still record the package version,
  not the build version (a trace-format decision; `/api/health` and friends report the build).
- `check-app-image.sh` matches the version label in `corelata --version` output by substring; the
  exact `CORELATA_BUILD_VERSION` equality check beside it carries the real assertion.

## Later

- ~~Scenarios written for real models (needs its own ticket, after the deployment dry run BORG-34).~~ — **closed in M12** (CRL-28: `engine/corelata/bench/scenarios-real/`, `corelata bench --scenarios real`) — CRL-28
- ~~A release workflow~~ — **closed** (`.github/workflows/release.yml`, CRL-5). The tag must equal the
  package version; `postgres:16-alpine` is still pinned by tag, not digest. — CRL-5
