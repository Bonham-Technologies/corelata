# M5 follow-ups

## Divergences from Coglossa

- `deploy/` copied without the scorer (image, service, GPU overlay, weights, `--gpu`), the
  language tiers (`tiers.yaml`) and FLORES/bench; `install.sh` takes no options.
- The base pack ships as `config/packs.example/` and is copied to `config/packs/` once by
  `install.sh` (Coglossa has no customer-editable directory of this kind).
- The app image carries `/opt/corelata/examples/` (the sample source) for the demo and the
  smoke test; `.dockerignore` allows `docs/examples/`.
- `migrate` runs `corelata migrate` (Coglossa: `coglossa db upgrade`); `worker.stop_grace_period`
  is 5m (Coglossa: 2m) because a Corelata stage is a model call of minutes.
- `smoke.py` drives Corelata's flow (project, source upload, run, exports, trace) and its
  `check` mode also starts a new run after an upgrade or restore.
- `airgap-test.sh` adds a pack-edit-survives-upgrade step and an invalid-config step; it drops
  the tiers and bench steps.
- `check-app-image.sh` checks Corelata's package data (migrations, prompt templates, the
  report template, the base pack, the vendored Coglossa export schema).
- `docker build --provenance=false` in `bundle.sh` and the Makefile: buildx attestations made
  `docker save` emit a manifest list — **backport**.
- The stub tests use `if grep ...; then fail` instead of Coglossa's `grep -q ... && fail`. Both
  fire on a match; on no match the `&&` form's non-zero status is exempt from `set -e`, but as the
  last command of a function it still fails the function. The `if` form is clearer and avoids
  that pitfall — optional backport.
- The postgres healthcheck is `pg_isready -h 127.0.0.1 ...` so it cannot succeed against initdb's
  socket-only temporary server — Coglossa backport candidate.
- `check_compose.py` asserts `not services["api"].get("command")` (Compose emits `command: null`
  for a merged service).

## Spec deviations

- §12: recorded in the spec (`config/packs.example`, `examples/`, `VERSION`, version derivation,
  5m grace, no GPU overlay, no release workflow).
- The operator guide's housekeeping SQL differs from the plan's draft: it matches
  `COALESCE(scheduled_at, last event)` and clears `procrastinate_periodic_defers` first. The
  plan's version would never match ordinary jobs and would violate the foreign key.

## Should fix soon

- `/api/health` and the web footer show `corelata.__version__` (0.1.0), not the bundle version;
  a `VERSION` build-arg read at runtime would align them (Coglossa has the same gap — **backport**) — **closed in M7** (`CORELATA_BUILD_VERSION`, BORG-35).
- ~~`restore.sh` drops the whole `public` schema; it assumes everything Corelata and procrastinate
  create lives there (true today). A future extension schema would need the script changed.~~ — **closed in M8** (CRL-7) — CRL-7
- ~~`backup.sh` reads the files volume through a one-shot `worker` container; a very large volume
  is streamed through `docker compose run`, which is slow on some hosts.~~ — **documented in M8** (CRL-7; not changed) — CRL-7
- The air-gap test takes about 13 minutes locally (10-15 expected) and about 5 GB; ~~CI runs it on
  every push and PR.~~ — CRL-5
- `bundle.sh` refuses a dirty tree without `--allow-dirty`; CI's airgap job passes
  `--allow-dirty` through `airgap-test.sh`.
- ~~Closed procrastinate job copies (failed, cancelled, aborted; the worker deletes succeeded ones) accumulate; the guide gives a `DELETE` for housekeeping, nothing
  runs it automatically. The SQL is exercised by the air-gap test (step 6b), which plants an old and a
  recent failed job, runs the guide's statement and checks that runs and exports are intact.~~ — **closed in M8** (CRL-10) — CRL-10
- The `postgres:16-alpine` image is pinned by tag, not digest.
- ~~`check-bundle.sh`'s `diff -r` against the repo pack should exclude `__pycache__`.~~ — **closed in M15** (CRL-36). — CRL-36
- ~~The restore stub test checks the stop/SQL/files/up ordering loosely and the rc-3 path is
  untested (as in Coglossa).~~ — **closed in M8** (CRL-7) — CRL-7
- ~~The stub test's one-exec-call assertion joins log lines rather than counting calls.~~ — **closed in M8** (CRL-7) — CRL-7
- Raw `docker compose` demo commands need `CORELATA_DB_PASSWORD`; the guide says so, but the
  header comment of `compose.demo.yaml` does not. — **closed**, verified 2026-10-18: `deploy/compose.demo.yaml` line 4 names `CORELATA_DB_PASSWORD`.
- `check_compose.py` has a formatting slip (`,"api uses...`). — **closed**, verified 2026-10-18: `deploy/tests/check_compose.py` line 57 is clean.

## Later

- ~~A release workflow that builds the bundle on a tag and publishes the tar, `.sha256` and
  manifest~~ — **closed in M7** (`.github/workflows/release.yml`, CRL-5); the `airgap` CI job now
  runs on pull requests only, the release workflow runs it again before publishing. — CRL-5
- Compose resource limits once a customer host profile is known.
- M6 added one package-data path (`bench/scenarios/`) to `check-app-image.sh`; no other packaging change.
