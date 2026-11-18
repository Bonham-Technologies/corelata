# Contributing to Corelata

Thanks for helping! This guide covers setup and what a pull request needs. `CLAUDE.md` holds the
layout, gates and conventions in more detail; the design is in
`docs/superpowers/specs/2026-10-12-corelata-v1-design.md`.

## Setup

Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm 10, Docker (for the dev
Postgres and the deploy checks).

```bash
cd engine && uv sync --all-groups && cd ..
cd api && uv sync --all-groups && cd ..
cd web && pnpm install --frozen-lockfile && cd ..
make db-up                                  # Postgres 16 on 127.0.0.1:55433
cd engine && uv run corelata fake-openai &  # a synthetic model for smoke tests
cp engine/corelata.example.yaml engine/corelata.yaml
```

## Before you open a PR

```bash
make lint
make test
make e2e
make deploy-check
make schema && git status --short schema web/src/api/schema.d.ts   # empty unless you changed a model
```

- Keep PRs focused; follow the existing code style (ruff, eslint and prettier enforce most of it).
- Add or update tests for behaviour changes; the engine and API keep 95% branch coverage and the
  web app 95% on every Vitest threshold. A change to what a run does gets a scenario fixture.
- Conventional-commit style titles (`feat:`, `fix:`, `docs:`, `chore:`) with the Jira key
  (`CRL-n`) when there is one.
- `main` is protected: open a pull request, wait for the `ci-status` check to pass, and
  squash-merge. The remote branch is deleted on merge.
- Before a release, run `corelata doctor` and `corelata bench --scenarios real` against a real
  model server; the synthetic model cannot produce a real server's failures.

## Developer Certificate of Origin

Every commit needs a `Signed-off-by: Name <email>` line with the same name and email as the
commit's author; `git commit -s` adds it from your git config. The sign-off certifies the
[Developer Certificate of Origin](https://developercertificate.org/). The DCO check on each
pull request enforces it for every contributor who is not a verified member of the
Bonham-Technologies organisation. `git commit --amend -s` signs off the last commit, and
`git rebase --signoff HEAD~N` the last N. Contributions are accepted under the Apache License 2.0
(see `LICENSE`).

## Notes

- The first customer is air-gapped. Nothing in the engine, API or web app may reach the network
  except the model servers named in `corelata.yaml` and the configured Coglossa instance.
- Never commit `deploy/.env`, `deploy/config/corelata.yaml` or any model-server key.
