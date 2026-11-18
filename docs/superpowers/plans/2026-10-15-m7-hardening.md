# M7 Post-v1 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six follow-ups filed after v1 shipped (Jira BORG-35, BORG-36, BORG-40, BORG-41, BORG-42, BORG-43): the version an operator sees matches the bundle, `corelata pack diff` exists, the Sources tab shows each source's hash, the report frame no longer shares the page's origin, the bench survives Ctrl-C and can run scenarios concurrently, and the profile extractor allocates its budget by report length and warns on a name collision.

**Architecture:** Six independent changes, each small, each with its own tests, touching the engine, the API, the web app and `deploy/`. Nothing changes the run pipeline, the database schema or the pack format. Generated artifacts (`schema/*.schema.json`, `schema/openapi.json`, `web/src/api/schema.d.ts`) are regenerated with `make schema` in the task that changes a model and committed with it; CI fails on a stale copy.

**Tech Stack:** Python 3.12, pydantic 2, argparse, FastAPI, pytest; React 19, TypeScript, Vitest + jsdom 26, Playwright; Docker, bash.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §6.6 (snapshot), §6.8 (CLI: `corelata pack diff <a> <b>`), §10.3 (Sources tab "list with kinds, hashes"; the report frame), §12 (versions), §13 (`corelata bench`), §14 M6 row. The tickets' text is in Jira (BORG-35, 36, 40, 41, 42, 43) and in `docs/m4b-followups.md`, `docs/m5-followups.md`, `docs/m6-followups.md`.

## Global Constraints

- 95% branch coverage for the engine and api packages (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest thresholds 95% lines, branches, functions and statements (`web/vite.config.ts`).
- Strict pydantic (`extra="forbid"`) for everything a customer edits; models Corelata writes (reports, diffs) are plain `BaseModel`.
- CLI exit codes (`cli.py` header): 0 ok, 1 failed, 2 usage or config error, 3 completed with findings open / disagreements / differences, 130 interrupted.
- Generated files are never edited by hand: after a model change run `make schema` (engine schemas, `schema/openapi.json`, `web/src/api/schema.d.ts`) and commit the result; `engine/tests/schema/test_export.py` and `api/tests/test_openapi.py` and the CI `web` job check staleness.
- Nothing under `deploy/` changes except where Task 1 says (`app.Dockerfile`, `check-app-image.sh`, `airgap-test.sh`).
- The engine's `tests` package imports helpers as `from tests.standards.test_loader import write_pack`; the API's tests import `from tests.conftest import ...`.
- Commit messages end with the two attribution lines the session uses; write them to a file and `git commit -F FILE`. Never `git stash`.
- Run the engine suite with `cd engine && uv run pytest`, the API suite with `make test-api` (needs the dev Postgres: `make db-up`), the web suite with `cd web && pnpm test`, the journeys with `make e2e`. Do not run the Vitest and pytest suites at the same time.

## Review Focus

1. **An image built with `--build-arg VERSION=1.2.0` must report `1.2.0` from `/api/health`, `/api/system/info` and `corelata --version`, while a source checkout with no such variable keeps reporting the package version.** Pinned in Task 1 (`test_build_version_comes_from_the_image_environment`, `test_health_and_info_report_the_build_version`, the `check-app-image.sh` label check and the air-gap health check).
2. **`pack diff` given a run directory compares the run's snapshot, not whatever the pack directory holds today**; given an unknown name or a directory without `trace.json` or `pack.yaml` it exits 1 with the loader's message, never a traceback. Pinned in Task 2 (`test_pack_diff_against_a_run_snapshot`, `test_pack_diff_errors`).
3. **A report whose HTML carried a script must not run it in the page's origin**: the frame has `sandbox="allow-scripts"` and no `allow-same-origin`, the page acts only on messages whose `source` is the frame's window and whose shape it knows, and a link inside the report navigates nothing. Pinned in Task 4 (`ignores messages from other windows and malformed data`, `makes links inert`).
4. **Ctrl-C half-way through a bench must leave a `bench.json` holding every run that finished**, and the command must exit 130 saying where the partial report is. Pinned in Task 5 (`test_bench_json_is_written_after_every_run`, `test_bench_interrupted_keeps_the_partial_report_and_exits_130`).
5. **With `--concurrency 3` the report must list scenarios in command-line order and runs by repeat number regardless of which finished first**, and a run that errors must still not stop the others. Pinned in Task 5 (`test_concurrency_overlaps_runs_and_keeps_the_order`).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/version.py` | `build_version()`, `version_line()`: which version Corelata reports. |
| `engine/corelata/standards/diff.py` | `PackDiff`, `diff_packs`, `format_diff`: pure functions over two `ResolvedPack`s. |
| `engine/corelata/standards/loader.py` | adds `chain_profiles(name, packs_dir)`. |
| `engine/corelata/trace.py` | `SourceSummary.sha256`. |
| `engine/corelata/bench/run.py` | concurrency, `store_io`, `bench.json` after every run. |
| `engine/corelata/bench/text.py` | two columns `agree` and `outcome`. |
| `engine/corelata/schema/export.py` | `SERIALIZED`: schemas exported in serialization mode. |
| `engine/corelata/profiler.py` | `_shares`: water-filling budget split in `read_examples`. |
| `engine/corelata/cli.py` | `--version` text, `pack diff`, bench flags and interrupt handling, the profile-name warning. |
| `api/corelata_api/app.py`, `api/corelata_api/routes/system.py` | report `build_version()`. |
| `deploy/docker/app.Dockerfile`, `deploy/tests/check-app-image.sh`, `deploy/tests/airgap-test.sh` | bake and check the build version. |
| `web/src/pages/review/frameBridge.ts` | the script that runs inside the report frame and the `srcdoc` builder. |
| `web/src/pages/review/ReportFrame.tsx` | the sandboxed frame and the message channel. |
| `web/src/pages/review/SourcesTab.tsx` | the SHA-256 column. |
| `schema/*.schema.json`, `schema/openapi.json`, `web/src/api/schema.d.ts` | regenerated by `make schema` (Tasks 3 and 5). |
| `engine/tests/test_version.py`, `engine/tests/standards/test_diff.py`, `engine/tests/test_cli.py`, `engine/tests/test_trace.py`, `engine/tests/bench/test_run.py`, `engine/tests/bench/test_text.py`, `engine/tests/test_cli_bench.py`, `engine/tests/schema/test_export.py`, `engine/tests/test_profiler.py`, `engine/tests/test_cli_profile.py`, `engine/tests/standards/test_loader.py`, `api/tests/test_app.py`, `web/src/pages/review/*.test.ts(x)`, `web/src/test/fixtures.ts` | tests. |
| `README.md`, `docs/operator-guide.md`, `docs/m7-followups.md`, `docs/m1-followups.md`, `docs/m4b-followups.md`, `docs/m5-followups.md`, `docs/m6-followups.md`, spec amendments | docs. |

---

### Task 1: Report the bundle version (BORG-35)

`VERSION`, the image label and `manifest.json` carry the bundle version, while `/api/health`, `/api/system/info`, the web footer and `corelata --version` show the package version `corelata.__version__` (0.1.0). The image bakes the build version into `CORELATA_BUILD_VERSION`; everything the operator sees reads it, falling back to the package version in a source checkout.

**Files:**
- Create: `engine/corelata/version.py`
- Modify: `engine/corelata/cli.py:62` (`--version`)
- Modify: `api/corelata_api/app.py:1,48-51`, `api/corelata_api/routes/system.py:5,27-31`
- Modify: `deploy/docker/app.Dockerfile:40-41`, `deploy/tests/check-app-image.sh:11,25-26`, `deploy/tests/airgap-test.sh:75-77`
- Modify: `docs/operator-guide.md:568-571`, `docs/superpowers/specs/2026-10-12-corelata-v1-design.md:453-454`, `docs/m5-followups.md:40-41`
- Test: `engine/tests/test_version.py`, `engine/tests/test_cli.py:39-42`, `api/tests/test_app.py`

**Interfaces:**
- Produces: `corelata.version.build_version(environ: Mapping[str, str] | None = None) -> str`; `corelata.version.version_line(environ=None) -> str`; `corelata.version.BUILD_VERSION_ENV = "CORELATA_BUILD_VERSION"`.

- [ ] **Step 1: Write the failing engine tests**

Append to `engine/tests/test_version.py`:

```python
from corelata.version import BUILD_VERSION_ENV, build_version, version_line


def test_build_version_falls_back_to_the_package_version():
    assert BUILD_VERSION_ENV == "CORELATA_BUILD_VERSION"
    assert build_version({}) == corelata.__version__
    assert build_version({BUILD_VERSION_ENV: "   "}) == corelata.__version__
    assert version_line({}) == f"corelata {corelata.__version__}"


def test_build_version_comes_from_the_image_environment(monkeypatch):
    monkeypatch.setenv(BUILD_VERSION_ENV, " 1.2.0-g1234abc ")
    assert build_version() == "1.2.0-g1234abc"
    assert version_line() == f"corelata {corelata.__version__} (build 1.2.0-g1234abc)"
    assert version_line({BUILD_VERSION_ENV: corelata.__version__}) == f"corelata {corelata.__version__}"
```

Replace `test_version` in `engine/tests/test_cli.py:39-42` with:

```python
def test_version(capsys, monkeypatch):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and __version__ in capsys.readouterr().out
    monkeypatch.setenv("CORELATA_BUILD_VERSION", "9.9.9")
    with pytest.raises(SystemExit):
        main(["--version"])
    assert f"corelata {__version__} (build 9.9.9)" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/test_version.py tests/test_cli.py::test_version -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.version'`.

- [ ] **Step 3: Create `engine/corelata/version.py`**

```python
"""Which version Corelata reports (spec §12). `__version__` is the Python package's; the bundle
that ships it may carry another (the git tag, or `<package>-g<sha>` between releases), baked into
the image as CORELATA_BUILD_VERSION by deploy/docker/app.Dockerfile. Health, system/info, the web
footer and `corelata --version` report the build version when there is one, so what an operator
sees agrees with VERSION, the image label and manifest.json."""

import os
from collections.abc import Mapping

from corelata import __version__

BUILD_VERSION_ENV = "CORELATA_BUILD_VERSION"


def build_version(environ: Mapping[str, str] | None = None) -> str:
    """The bundle version when the image carries one, else the package version."""
    env = os.environ if environ is None else environ
    return env.get(BUILD_VERSION_ENV, "").strip() or __version__


def version_line(environ: Mapping[str, str] | None = None) -> str:
    """`corelata 0.1.0`, or `corelata 0.1.0 (build 1.2.0)` when the build differs."""
    build = build_version(environ)
    if build == __version__:
        return f"corelata {__version__}"
    return f"corelata {__version__} (build {build})"
```

In `engine/corelata/cli.py` add `from corelata.version import version_line` to the imports (after `from corelata.trace import (...)`) and change line 62 to:

```python
    parser.add_argument("--version", action="version", version=version_line())
```

- [ ] **Step 4: Run the engine tests**

Run: `cd engine && uv run pytest tests/test_version.py tests/test_cli.py::test_version -q`
Expected: PASS.

- [ ] **Step 5: Write the failing API test**

Append to `api/tests/test_app.py` (after `test_auth_none_has_no_user`):

```python
async def test_health_and_info_report_the_build_version(make_api, monkeypatch):
    """The image bakes the bundle version into CORELATA_BUILD_VERSION (spec §12); without it the
    package version stands, which the two tests above pin."""
    monkeypatch.setenv("CORELATA_BUILD_VERSION", "1.2.0-gabcdef0")
    async with make_api() as api:
        health = await api.client.get("/api/health")
        info = await api.client.get("/api/system/info")
    assert health.json() == {"status": "ok", "version": "1.2.0-gabcdef0"}
    assert info.json()["version"] == "1.2.0-gabcdef0"
```

Run: `make test-api` (or `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_app.py -q -k build_version`)
Expected: FAIL, the version is `0.1.0`.

- [ ] **Step 6: Make the API read the build version**

`api/corelata_api/app.py`: add `from corelata.version import build_version` to the imports and change `get_health`:

```python
@health.get("/health")
async def get_health() -> dict[str, str]:
    """Liveness: answers without the database and without a signed-in user. The version is the
    bundle's when the image carries one (spec §12)."""
    return {"status": "ok", "version": build_version()}
```

Keep `FastAPI(title="Corelata", version=corelata.__version__, ...)` as it is: the OpenAPI document describes the package.

`api/corelata_api/routes/system.py`: replace `import corelata` with `from corelata.version import build_version` and set `version=build_version(),` in `get_info`.

Run: `make test-api`
Expected: PASS (the two existing version assertions still hold: no variable in the test environment).

- [ ] **Step 7: Bake the version into the image and check it**

`deploy/docker/app.Dockerfile`, the `ENV` line of the final stage (lines 40-41) becomes:

```dockerfile
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CORELATA_CONFIG=/etc/corelata/corelata.yaml CORELATA_BUILD_VERSION=${VERSION}
```

`deploy/tests/check-app-image.sh`: move the `label=` lines (25-26) up to directly after the `run corelata --version | grep -q '^corelata '` line (11) and add one check after them:

```bash
label=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$image")
[ -n "$label" ] || die "the org.opencontainers.image.version label is empty"
run corelata --version | grep -qF "$label" || die "corelata --version does not carry the image version ($label)"
[ "$(run sh -c 'echo $CORELATA_BUILD_VERSION')" = "$label" ] || die "CORELATA_BUILD_VERSION must equal the image version label"
```

`deploy/tests/airgap-test.sh`, step 6, after `compose exec -T api corelata doctor` (line 76) add:

```bash
health=$(api_py "import json, urllib.request
print(json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health'))['version'])")
[ "$health" = "$version" ] || die "/api/health reports '$health'; the bundle is '$version'"
echo "health reports the bundle version $health"
```

Run: `make deploy-check` (shellcheck and the stub tests) and `make image-app` (builds `corelata/app:dev` and runs `check-app-image.sh`).
Expected: both pass; `check-app-image.sh` prints `ok: corelata/app:dev`. (`make airgap-test` runs in CI; run it locally only if Docker and 15 minutes are at hand.)

- [ ] **Step 8: Docs**

`docs/operator-guide.md:568-571` becomes:

```markdown
- **Versions.** `VERSION`, the image's `org.opencontainers.image.version` label
  (`docker image inspect corelata/app:<version>`), `manifest.json`, `GET /api/health`, the footer
  of the web app and `corelata --version` all carry the bundle's version. The Python package
  inside has its own version (`corelata --version` prints both when they differ).
```

Spec §12, replace the sentence fragment `/api/health and the web footer show the package version, the image label, VERSION and manifest.json the bundle version.` with: `the image bakes the version into CORELATA_BUILD_VERSION, so /api/health, /api/system/info, the web footer and corelata --version report the bundle version (M7); a source checkout reports the package version.`

`docs/m5-followups.md:40-41`: append ` — **closed in M7** (`CORELATA_BUILD_VERSION`, BORG-35).` to the item.

- [ ] **Step 9: Lint and commit**

Run: `cd engine && uv run ruff check . && uv run ruff format --check . && cd ../api && uv run ruff check . && uv run ruff format --check .`

```bash
git add engine/corelata/version.py engine/corelata/cli.py engine/tests/test_version.py engine/tests/test_cli.py api/corelata_api/app.py api/corelata_api/routes/system.py api/tests/test_app.py deploy/docker/app.Dockerfile deploy/tests/check-app-image.sh deploy/tests/airgap-test.sh docs/operator-guide.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/m5-followups.md
git commit -F /path/to/message   # "feat: report the bundle version from health, system/info and --version (BORG-35)"
```

---

### Task 2: `corelata pack diff` (BORG-36)

Spec §6.8 names `corelata pack diff <a> <b>`; it has been open since M1. Each side is a pack name (with an optional profile), a pack directory, or a run directory whose `trace.json` holds the pack snapshot (§6.6). The operator guide's "merge a newer base pack by hand with `diff -r`" becomes this command.

**Files:**
- Create: `engine/corelata/standards/diff.py`
- Modify: `engine/corelata/cli.py:128-137` (parser), `cli.py:426-453` (`_pack`), imports
- Modify: `docs/operator-guide.md:510-515`, `docs/m1-followups.md:38`, `docs/m6-followups.md` ("Later"), spec §6.8
- Test: `engine/tests/standards/test_diff.py`, `engine/tests/test_cli.py`

**Interfaces:**
- Consumes: `ResolvedPack` (`corelata.standards.schema`), `load_pack`, `PackError` (`corelata.standards.loader`), `_load_run(run_dir) -> (RunRecord, ResolvedPack)` and `TraceError` (already in `cli.py`).
- Produces: `diff_packs(left: ResolvedPack, right: ResolvedPack, *, left_name: str, right_name: str) -> PackDiff`; `format_diff(diff: PackDiff) -> str`; `PackDiff.empty: bool`.

- [ ] **Step 1: Write the failing unit tests**

Create `engine/tests/standards/test_diff.py`:

```python
import json

from corelata.standards.diff import PackDiff, diff_packs, format_diff
from corelata.standards.loader import load_pack
from tests.standards.test_loader import LEXICON, RULE, TEMPLATE, write_pack

RULE2 = {**RULE, "id": "test.r.2", "title": "Second rule", "severity": "minor"}
PROFILE = {
    "name": "team",
    "extends": "base",
    "rules": {
        "disable": ["test.r.2"],
        "override": [{"id": "test.r.1", "severity": "blocking", "text": "Stricter."}],
        "add": [{**RULE, "id": "team.r.1", "title": "House rule"}],
    },
    "template": {"key_judgments": {"min": 1, "max": 3}},
    "tone": "Lead with the judgment.",
    "format": {"heading_style": "numbered"},
    "lexicon": {"handling_markings": ["UNCLASSIFIED//FOUO"]},
}


def _packs(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE, RULE2], profiles={"team": PROFILE})
    base = load_pack("base", packs_dir=tmp_path)
    team = load_pack("base", packs_dir=tmp_path, profile="team")
    return base, team


def test_identical_packs_have_an_empty_diff(tmp_path):
    base, _ = _packs(tmp_path)
    diff = diff_packs(base, base, left_name="a", right_name="b")
    assert diff.empty
    assert diff.model_dump(exclude={"left", "right"}) == {
        "identity": [],
        "rules_added": [],
        "rules_removed": [],
        "rules_changed": [],
        "template": [],
        "lexicon": [],
        "tone_changed": False,
        "format": [],
    }
    assert format_diff(diff) == "pack diff: a -> b\nno differences\n"


def test_profile_changes_are_listed_by_kind(tmp_path):
    base, team = _packs(tmp_path)
    diff = diff_packs(base, team, left_name="base", right_name="base@team")
    assert not diff.empty
    assert [c.model_dump() for c in diff.identity] == [
        {"field": "profile", "before": None, "after": "team"}
    ]
    assert diff.rules_added == ["team.r.1"] and diff.rules_removed == ["test.r.2"]
    assert [r.id for r in diff.rules_changed] == ["test.r.1"]
    assert [c.model_dump() for c in diff.rules_changed[0].changes] == [
        {"field": "severity", "before": "major", "after": "blocking"},
        {"field": "text", "before": RULE["text"], "after": "Stricter."},
    ]
    assert [c.model_dump() for c in diff.template] == [
        {"field": "key_judgments.max", "before": 5, "after": 3}
    ]
    assert [c.model_dump() for c in diff.lexicon] == [
        {"field": "handling_markings added", "before": None, "after": ["UNCLASSIFIED//FOUO"]}
    ]
    assert diff.tone_changed
    assert [c.model_dump() for c in diff.format] == [
        {"field": "heading_style", "before": "plain", "after": "numbered"}
    ]
    text = format_diff(diff, left=base, right=team)
    assert "profile: None -> team" in text
    assert "rules added (1):\n  team.r.1  House rule [major, verifiable]" in text
    assert "rules removed (1):\n  test.r.2  Second rule [minor, verifiable]" in text
    assert "rules changed (1):\n  test.r.1:\n    severity: major -> blocking" in text
    assert "template:\n  key_judgments.max: 5 -> 3" in text
    assert "lexicon:\n  handling_markings added: ['UNCLASSIFIED//FOUO']" in text
    assert "tone changed" in text
    assert "format:\n  heading_style: plain -> numbered" in text
    PackDiff.model_validate_json(diff.model_dump_json())  # round trip


def test_lexicon_terms_are_keyed_by_term_and_versions_by_identity(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    lexicon = {
        **LEXICON,
        "likelihood": [{"term": "likely", "low": 55, "high": 85}, {"term": "unlikely", "low": 20, "high": 45}],
        "confidence_definitions": {**LEXICON["confidence_definitions"], "high": "Changed."},
        "source_descriptors": ["press report"],
    }
    write_pack(tmp_path, "other", rules=[RULE], lexicon=lexicon, template=TEMPLATE)
    left = load_pack("base", packs_dir=tmp_path)
    right = load_pack("other", packs_dir=tmp_path)
    diff = diff_packs(left, right, left_name="base", right_name="other")
    assert [c.field for c in diff.identity] == ["name"]
    assert [c.model_dump() for c in diff.lexicon] == [
        {"field": "confidence_definitions.high", "before": LEXICON["confidence_definitions"]["high"], "after": "Changed."},
        {"field": "likelihood[likely].high", "before": 80, "after": 85},
        {"field": "likelihood[unlikely]", "before": None, "after": {"term": "unlikely", "low": 20, "high": 45}},
        {"field": "source_descriptors removed", "before": ["open-source report"], "after": None},
        {"field": "source_descriptors added", "before": None, "after": ["press report"]},
    ]
    assert json.loads(diff.model_dump_json())["lexicon"][2]["after"]["term"] == "unlikely"
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/standards/test_diff.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.standards.diff'`.

- [ ] **Step 3: Create `engine/corelata/standards/diff.py`**

```python
"""`corelata pack diff` (spec §6.8): what changed between two resolved packs. Pure functions over
`ResolvedPack`; the CLI turns names, directories and run snapshots into packs first. Lists of
scalars diff as sets (added, removed); lists of objects keyed by `id` or `term` diff per key."""

from typing import Any

from pydantic import BaseModel

from corelata.standards.schema import ResolvedPack, Rule


class FieldChange(BaseModel):
    field: str
    before: Any
    after: Any


class RuleChange(BaseModel):
    id: str
    changes: list[FieldChange]


class PackDiff(BaseModel):
    left: str  # how each side was named on the command line
    right: str
    identity: list[FieldChange]  # name, version, profile
    rules_added: list[str]
    rules_removed: list[str]
    rules_changed: list[RuleChange]
    template: list[FieldChange]
    lexicon: list[FieldChange]
    tone_changed: bool
    format: list[FieldChange]

    @property
    def empty(self) -> bool:
        return not (
            self.identity
            or self.rules_added
            or self.rules_removed
            or self.rules_changed
            or self.template
            or self.lexicon
            or self.tone_changed
            or self.format
        )


def _list_key(items: list[Any]) -> str | None:
    """The key that names every object in a list of dicts (`id`, then `term`), else None."""
    if not items or not all(isinstance(x, dict) for x in items):
        return None
    for key in ("id", "term"):
        if all(key in x for x in items):
            return key
    return None


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _diff_values(path: str, a: Any, b: Any, out: list[FieldChange]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            _diff_values(_join(path, key), a.get(key), b.get(key), out)
        return
    if isinstance(a, list) and isinstance(b, list):
        key = _list_key(a + b)
        if key is not None:
            left = {x[key]: x for x in a}
            right = {x[key]: x for x in b}
            for k in sorted(set(left) | set(right)):
                _diff_values(f"{path}[{k}]", left.get(k), right.get(k), out)
            return
        removed = [x for x in a if x not in b]
        added = [x for x in b if x not in a]
        if removed:
            out.append(FieldChange(field=f"{path} removed", before=removed, after=None))
        if added:
            out.append(FieldChange(field=f"{path} added", before=None, after=added))
        return
    out.append(FieldChange(field=path, before=a, after=b))


def _changes(a: BaseModel, b: BaseModel) -> list[FieldChange]:
    out: list[FieldChange] = []
    _diff_values("", a.model_dump(mode="json"), b.model_dump(mode="json"), out)
    return out


def diff_packs(
    left: ResolvedPack, right: ResolvedPack, *, left_name: str, right_name: str
) -> PackDiff:
    identity: list[FieldChange] = []
    for field in ("name", "version", "profile"):
        a, b = getattr(left, field), getattr(right, field)
        if a != b:
            identity.append(FieldChange(field=field, before=a, after=b))
    rules_a = {r.id: r for r in left.rules}
    rules_b = {r.id: r for r in right.rules}
    changed = []
    for rule_id in sorted(set(rules_a) & set(rules_b)):
        changes = _changes(rules_a[rule_id], rules_b[rule_id])
        if changes:
            changed.append(RuleChange(id=rule_id, changes=changes))
    return PackDiff(
        left=left_name,
        right=right_name,
        identity=identity,
        rules_added=sorted(set(rules_b) - set(rules_a)),
        rules_removed=sorted(set(rules_a) - set(rules_b)),
        rules_changed=changed,
        template=_changes(left.template, right.template),
        lexicon=_changes(left.lexicon, right.lexicon),
        tone_changed=left.tone != right.tone,
        format=_changes(left.format, right.format),
    )


def _rule_line(rule: Rule) -> str:
    return f"  {rule.id}  {rule.title} [{rule.severity.value}, {rule.checkability.value}]"


def format_diff(diff: PackDiff, *, left: ResolvedPack | None = None, right: ResolvedPack | None = None) -> str:
    """The terminal rendering. `left`/`right` let added and removed rules show their title."""
    out = [f"pack diff: {diff.left} -> {diff.right}"]
    if diff.empty:
        return "\n".join([*out, "no differences"]) + "\n"
    for c in diff.identity:
        out.append(f"{c.field}: {c.before} -> {c.after}")
    out.append(f"rules added ({len(diff.rules_added)}):")
    for rule_id in diff.rules_added:
        out.append(_rule_line(right.rule(rule_id)) if right is not None else f"  {rule_id}")
    out.append(f"rules removed ({len(diff.rules_removed)}):")
    for rule_id in diff.rules_removed:
        out.append(_rule_line(left.rule(rule_id)) if left is not None else f"  {rule_id}")
    out.append(f"rules changed ({len(diff.rules_changed)}):")
    for rc in diff.rules_changed:
        out.append(f"  {rc.id}:")
        out += [f"    {c.field}: {c.before} -> {c.after}" for c in rc.changes]
    for title, changes in (("template", diff.template), ("lexicon", diff.lexicon), ("format", diff.format)):
        if changes:
            out.append(f"{title}:")
            out += [f"  {c.field}: {c.before} -> {c.after}" for c in changes]
    if diff.tone_changed:
        out.append("tone changed")
    return "\n".join(out) + "\n"
```

Fix the test's expectations to this output shape where they name titles: `format_diff(diff, left=base, right=team)` in `test_profile_changes_are_listed_by_kind` (pass both packs; the `[major, verifiable]` suffix comes from the rule). `ruff format` will re-wrap the long signature; let it.

- [ ] **Step 4: Run the unit tests**

Run: `cd engine && uv run pytest tests/standards/test_diff.py -q`
Expected: PASS. If `_diff_values` orders `lexicon` changes differently from the third test, fix the implementation, not the test: dict keys sort alphabetically (`confidence_definitions` < `likelihood` < `source_descriptors`), and within `source_descriptors` removed comes before added.

- [ ] **Step 5: Write the failing CLI tests**

Append to `engine/tests/test_cli.py`:

```python
def test_pack_diff_names_profiles_and_directories(capsys, tmp_path):
    from tests.standards.test_diff import PROFILE, RULE2
    from tests.standards.test_loader import RULE, write_pack

    packs = tmp_path / "packs"
    write_pack(packs, "base", rules=[RULE, RULE2], profiles={"team": PROFILE})
    assert main(["pack", "diff", "icd203-base", "icd203-base"]) == 0
    assert capsys.readouterr().out == "pack diff: icd203-base -> icd203-base\nno differences\n"
    rc = main(["pack", "diff", "base", "base", "--profile-right", "team", "--packs-dir", str(packs)])
    out = capsys.readouterr().out
    assert rc == 3 and "profile: None -> team" in out and "team.r.1  House rule" in out
    rc = main(["pack", "diff", str(packs / "base"), "base", "--packs-dir", str(packs), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and data["left"] == str(packs / "base") and data["rules_added"] == []


def test_pack_diff_against_a_run_snapshot(config_path, inputs, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["run", *inputs, "--statement", STATEMENT, "--out", str(out), "--config", str(config_path)]) == 0
    capsys.readouterr()
    assert main(["pack", "diff", str(out), "icd203-base"]) == 0
    assert "no differences" in capsys.readouterr().out
    assert main(["pack", "diff", str(out / "trace.json"), "icd203-base", "--profile-left", "x"]) == 2
    assert "carries its own profile" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "text"),
    [
        (["pack", "diff", "nope", "icd203-base"], "not found"),
        (["pack", "diff", "icd203-base", "icd203-base", "--profile-right", "ghost"], "profile 'ghost'"),
    ],
)
def test_pack_diff_errors(capsys, tmp_path, argv, text):
    assert main(argv) == 1
    assert text in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["pack", "diff", str(empty), "icd203-base"]) == 1
    assert "not found" in capsys.readouterr().err
```

`STATEMENT`, `config_path` and `inputs` already exist in `test_cli.py` (the `test_run_clean` test uses them; check the exact constant name of the statement at the top of the file and use it).

Run: `cd engine && uv run pytest tests/test_cli.py -q -k pack_diff`
Expected: FAIL with argparse `invalid choice: 'diff'` (exit 2 raised as SystemExit).

- [ ] **Step 6: Add the command**

In `build_parser`, after the `for name, help_ in (...)` loop that builds `validate` and `show`, add:

```python
    d = pack_sub.add_parser("diff", help="compare two packs, profiles or run snapshots")
    for side in ("left", "right"):
        d.add_argument(
            side, help="a pack name, a pack directory, or a run directory / trace.json (its snapshot)"
        )
    d.add_argument("--profile-left", help="profile to apply to the left pack name")
    d.add_argument("--profile-right", help="profile to apply to the right pack name")
    d.add_argument("--packs-dir", type=Path)
    d.add_argument("--config", type=Path)
    d.add_argument("--json", action="store_true", help="print the diff as JSON")
```

Imports: `from corelata.standards.diff import diff_packs, format_diff`.

In `_pack`, after the `validate` branch and before the `show` code, add the dispatch, and add the two helpers below `_pack`:

```python
    if args.pack_command == "diff":
        return _pack_diff(args, packs_dir)
```

```python
def _pack_side(spec: str, profile: str | None, packs_dir: Path | None) -> ResolvedPack:
    """A pack name (with an optional profile), a pack directory, or a run directory / trace.json
    whose snapshot is the pack a run actually used (spec §6.6)."""
    path = Path(spec)
    run_dir = path.parent if path.is_file() and path.name == "trace.json" else path
    if (run_dir / "trace.json").is_file():
        if profile is not None:
            raise ConfigError(f"{spec} is a run snapshot; it carries its own profile")
        return _load_run(run_dir)[1]
    if (path / "pack.yaml").is_file():
        return load_pack(path.name, packs_dir=path.parent, profile=profile, allow_draft=True)
    return load_pack(spec, packs_dir=packs_dir, profile=profile, allow_draft=True)


def _pack_diff(args: argparse.Namespace, packs_dir: Path | None) -> int:
    try:
        left = _pack_side(args.left, args.profile_left, packs_dir)
        right = _pack_side(args.right, args.profile_right, packs_dir)
    except ConfigError as e:
        return _usage(str(e))
    except (PackError, TraceError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED
    diff = diff_packs(left, right, left_name=args.left, right_name=args.right)
    if args.json:
        print(dump_json(diff.model_dump(mode="json")), end="")
    else:
        print(format_diff(diff, left=left, right=right), end="")
    return EXIT_OK if diff.empty else EXIT_FINDINGS_OPEN
```

A directory without `trace.json` or `pack.yaml` falls through to `load_pack(spec, ...)`, whose message says the name was not found.

- [ ] **Step 7: Run the CLI tests and the whole engine suite**

Run: `cd engine && uv run pytest tests/test_cli.py -q -k pack_diff && uv run pytest -q`
Expected: PASS, coverage above 95%.

- [ ] **Step 8: Docs**

`docs/operator-guide.md:510-515`: replace the `diff -r` paragraph and code block with:

```markdown
**New rules in a newer base pack.** The bundle ships its base pack in `config/packs.example/`,
which the installer never copies over your own. See what changed, then merge by hand:

```sh
docker compose exec api corelata pack diff /etc/corelata/packs/icd203-base /opt/corelata/packs.example/icd203-base
```

(On the host: `corelata pack diff config/packs/icd203-base config/packs.example/icd203-base` from a
checkout.) Exit 0 means the two are the same, 3 that they differ; `--json` gives the diff as data.
The same command compares a pack with a profile (`--profile-right team-east`) or with the pack a
run actually used (`corelata pack diff /data/files/runs/<id> icd203-base`): the run directory's
`trace.json` carries the snapshot.
```

Check the container paths before writing them: `compose.yaml` mounts `config/` read-only; find where `config/packs` and `config/packs.example` appear inside the containers (`grep -n packs deploy/compose.yaml deploy/install.sh docs/operator-guide.md`) and use those paths; if `packs.example` is not mounted, drop the in-container example and keep the host form only.

`docs/m1-followups.md:38` → `` - `corelata pack diff` (§6.8) — **closed in M7** (BORG-36) ``. `docs/m6-followups.md`, the "Later" item → same note. Spec §6.8, append to the M6 amendment: `*M7 amendment:* `corelata pack diff <left> <right> [--profile-left <p>] [--profile-right <p>] [--packs-dir <dir>] [--json]`; a side is a pack name, a pack directory or a run directory (its snapshot); exit 0 same, 3 different, 1 a side did not load.`

- [ ] **Step 9: Lint and commit**

```bash
cd engine && uv run ruff check . && uv run ruff format --check .
git add engine/corelata/standards/diff.py engine/corelata/cli.py engine/tests/standards/test_diff.py engine/tests/test_cli.py docs/operator-guide.md docs/m1-followups.md docs/m6-followups.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -F /path/to/message   # "feat: corelata pack diff compares packs, profiles and run snapshots (BORG-36)"
```

---

### Task 3: Per-source hash in the trace summary and the Sources tab (BORG-40)

Spec §10.3 lists "hashes" for the Sources tab. `Source.sha256` exists on every run record; `SourceSummary` just does not copy it.

**Files:**
- Modify: `engine/corelata/trace.py:29-36,182-193`
- Modify: `engine/tests/test_trace.py:26-35`
- Regenerate: `schema/trace-summary.schema.json`, `schema/run-trace.schema.json`, `schema/openapi.json`, `web/src/api/schema.d.ts` (`make schema`)
- Modify: `web/src/pages/review/SourcesTab.tsx`, `web/src/test/fixtures.ts:236-255`
- Modify: `docs/m4b-followups.md:35-37,46`, spec §10.3 M4b amendment
- Test: `engine/tests/test_trace.py`, `web/src/pages/review/SourcesTab.test.tsx`

**Interfaces:**
- Produces: `SourceSummary.sha256: str` (64 hex characters; the upload's SHA-256, the same value as the project's `SourceView.sha256`).

- [ ] **Step 1: Write the failing engine test**

In `engine/tests/test_trace.py`, `test_summarize_clean_run`, change the expected source dict to:

```python
    assert [x.model_dump() for x in s.sources] == [
        {
            "id": "src1",
            "name": "src1.txt",
            "kind": "file",
            "format": "txt",
            "sha256": rec.sources[0].sha256,
            "units": 3,
            "digested": False,
            "coglossa_run_id": None,
        }
    ]
    assert len(s.sources[0].sha256) == 64
```

Run: `cd engine && uv run pytest tests/test_trace.py::test_summarize_clean_run -q`
Expected: FAIL (`sha256` missing from the dump).

- [ ] **Step 2: Add the field**

`engine/corelata/trace.py`, `SourceSummary`:

```python
class SourceSummary(BaseModel):
    id: str
    name: str
    kind: SourceKind
    format: str
    sha256: str  # of the uploaded bytes: joins the run to the project's source list (spec §10.3)
    units: int
    digested: bool
    coglossa_run_id: str | None
```

and in `summarize`, add `sha256=s.sha256,` after `format=s.format,`.

Run: `cd engine && uv run pytest tests/test_trace.py -q`
Expected: PASS; `tests/schema/test_export.py::test_committed_schema_matches_models` now FAILS ("trace-summary.schema.json is stale").

- [ ] **Step 3: Regenerate the schemas and the web client**

Run: `make schema` (from the repo root; needs `uv` and `pnpm`).
Expected: `schema/trace-summary.schema.json`, `schema/run-trace.schema.json`, `schema/openapi.json` and `web/src/api/schema.d.ts` change; `git diff --stat` shows those four files. `SourceSummary` in `schema.d.ts` gains `sha256: string`.

Run: `cd engine && uv run pytest tests/schema -q && cd ../api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_openapi.py -q`
Expected: PASS.

- [ ] **Step 4: Write the failing web test**

In `web/src/test/fixtures.ts`, add `sha256: "a".repeat(64),` to the first trace-summary source (after `format: "txt",`) and `sha256: "c".repeat(64),` to the second (after `format: "coglossa",`).

In `web/src/pages/review/SourcesTab.test.tsx`, first test, after `expect(rows[0]).toHaveTextContent("3 units");` add:

```tsx
  expect(rows[0]).toHaveTextContent("aaaaaaaaaaaa");
  expect(within(rows[0]!).getByTitle("a".repeat(64))).toHaveTextContent("aaaaaaaaaaaa");
  expect(rows[1]).toHaveTextContent("cccccccccccc");
  expect(within(table).getByRole("columnheader", { name: "SHA-256" })).toBeInTheDocument();
```

Run: `cd web && pnpm test -- SourcesTab`
Expected: FAIL (no SHA-256 column).

- [ ] **Step 5: Show the hash**

`web/src/pages/review/SourcesTab.tsx`: add `<th>SHA-256</th>` after `<th>Kind</th>` in the header, and after the kind cell add:

```tsx
              <td>
                <code title={s.sha256}>{s.sha256.slice(0, 12)}</code>
              </td>
```

Run: `cd web && pnpm test -- SourcesTab && pnpm lint`
Expected: PASS.

- [ ] **Step 6: Docs and the full suites**

`docs/m4b-followups.md:35-37` (the §10.3 Sources tab deviation): append ` **Closed in M7:** `SourceSummary.sha256` is shown in a SHA-256 column (BORG-40).` `docs/m4b-followups.md:46`: append ` — **closed in M7**.` Spec §10.3 M4b amendments: append the sentence `The Sources tab shows each source's SHA-256 (M7).`

Run: `cd engine && uv run pytest -q` then `cd web && pnpm test`.
Expected: PASS with the coverage gates met.

- [ ] **Step 7: Commit**

```bash
git add engine/corelata/trace.py engine/tests/test_trace.py schema/ web/src/api/schema.d.ts web/src/pages/review/SourcesTab.tsx web/src/pages/review/SourcesTab.test.tsx web/src/test/fixtures.ts docs/m4b-followups.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -F /path/to/message   # "feat: show each source's SHA-256 in the trace summary and the Sources tab (BORG-40)"
```

---

### Task 4: An origin-less report frame (BORG-41)

`ReportFrame` writes the report with `document.write` into a frame that shares the page's origin (`sandbox="allow-same-origin"`). The renderer autoescapes, so this is safe today, but a report that ever carried hostile HTML would run in the page's origin. The frame moves to `srcdoc` with `sandbox="allow-scripts"` only; a small script inside the frame (the bridge) posts the clicked claim to the page and applies the highlight the page asks for. Links inside the report become inert. The journey test in `web/e2e/journey.spec.ts:57-62` already exercises the real frame (click a claim, expect `.corelata-highlight`) and must keep passing; jsdom does not load `srcdoc`, so the Vitest tests drive the two halves separately.

**Files:**
- Create: `web/src/pages/review/frameBridge.ts`, `web/src/pages/review/frameBridge.test.ts`
- Rewrite: `web/src/pages/review/ReportFrame.tsx`, `web/src/pages/review/ReportFrame.test.tsx`
- Modify: `web/src/pages/review/ReviewPage.test.tsx:97-105`
- Modify: `docs/m4b-followups.md:47-50,66`, spec §10.3 M4b amendment
- Test: the three Vitest files above; `make e2e`

**Interfaces:**
- Produces: `installFrameBridge(doc, post, listen, css)`, `bridgeScript(): string`, `withBridge(html: string): string`, types `FrameToHost`, `HostToFrame`, `HIGHLIGHT_CSS`.
- Message protocol: frame → page `{type: "corelata:ready"}` once installed, `{type: "corelata:select", claim}` on a click; page → frame `{type: "corelata:highlight", claim: string | null, scroll: boolean}`.

- [ ] **Step 1: Write the failing bridge tests**

Create `web/src/pages/review/frameBridge.test.ts`:

```ts
import { reportHtml } from "../../test/fixtures";
import {
  HIGHLIGHT_CSS,
  bridgeScript,
  installFrameBridge,
  withBridge,
  type FrameToHost,
  type HostToFrame,
} from "./frameBridge";

function install(html = reportHtml) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const posted: FrameToHost[] = [];
  let handler: ((message: HostToFrame) => void) | undefined;
  installFrameBridge(doc, (m) => posted.push(m), (h) => (handler = h), HIGHLIGHT_CSS);
  const click = (el: Element) =>
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  return { doc, posted, send: (m: unknown) => handler!(m as HostToFrame), click };
}

it("adds the highlight stylesheet to the frame and reports ready", () => {
  const { doc, posted } = install();
  expect(doc.head.querySelector("style:last-of-type")?.textContent).toBe(HIGHLIGHT_CSS);
  expect(posted).toEqual([{ type: "corelata:ready" }]);
});

it("posts the first claim of a clicked cited element and nothing for an unclaimed one", () => {
  const { doc, posted, click } = install();
  click(doc.querySelector('li[data-claim-ids="c1 c3"]')!);
  click(doc.querySelector('p[data-claim-ids=""]')!);
  click(doc.querySelector("h1")!);
  expect(posted.slice(1)).toEqual([{ type: "corelata:select", claim: "c1" }]);
});

it("highlights the claim it is told to, scrolls only on request, and clears", () => {
  const { doc, send } = install();
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  send({ type: "corelata:highlight", claim: "c3", scroll: true });
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(1);
  expect(scroll).toHaveBeenCalledWith({ block: "center" });
  send({ type: "corelata:highlight", claim: "c1", scroll: false });
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(2);
  expect(scroll).toHaveBeenCalledTimes(1);
  send({ type: "corelata:highlight", claim: "c99", scroll: true });
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(0);
  expect(scroll).toHaveBeenCalledTimes(1);
  send({ type: "corelata:highlight", claim: null, scroll: true });
  send({ type: "something-else" });
  send(null);
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(0);
});

it("makes links inert", () => {
  const { doc, click } = install(
    reportHtml.replace("<article>", '<article><a href="https://example.test/x">out</a>'),
  );
  expect(click(doc.querySelector("a")!)).toBe(false); // preventDefault() was called
  expect(click(doc.querySelector("h1")!)).toBe(true);
});

it("serialises the installer into the document before </body>", () => {
  const script = bridgeScript();
  expect(script.startsWith("<script>")).toBe(true);
  expect(script).toContain("corelata:highlight");
  expect(script).toContain(JSON.stringify(HIGHLIGHT_CSS));
  expect(withBridge(reportHtml)).toContain(`${script}</body>`);
  expect(withBridge("<p>no body tag</p>")).toBe(`<p>no body tag</p>${script}`);
});
```

Run: `cd web && pnpm test -- frameBridge`
Expected: FAIL (module missing).

- [ ] **Step 2: Create `web/src/pages/review/frameBridge.ts`**

```ts
/** What runs inside the report frame. The frame is sandboxed without `allow-same-origin`
 * (spec §10.3, M7), so the page cannot reach into it and nothing in it can reach the page; this
 * bridge is the one channel. The frame posts the claim a reader clicked and says when it is
 * ready; the page posts the claim to highlight. */

export type FrameToHost = { type: "corelata:ready" } | { type: "corelata:select"; claim: string };
export type HostToFrame = { type: "corelata:highlight"; claim: string | null; scroll: boolean };

export const HIGHLIGHT_CSS =
  ".corelata-highlight { background: #fff3b0; color: #1a1a1a; outline: 2px solid #e0a800; outline-offset: 2px; }";

/** Installed inside the frame. Self-contained on purpose: `bridgeScript()` serialises it with
 * `Function.prototype.toString`, so its body may not reference anything outside itself. */
export function installFrameBridge(
  doc: Document,
  post: (message: FrameToHost) => void,
  listen: (handler: (message: HostToFrame) => void) => void,
  css: string,
): void {
  const style = doc.createElement("style");
  style.textContent = css;
  doc.head.appendChild(style);
  doc.addEventListener("click", (event) => {
    const target = event.target as Element | null;
    if (target?.closest("a[href]")) event.preventDefault(); // a report's links navigate nothing
    const cited = target?.closest("[data-claim-ids]");
    const first = (cited?.getAttribute("data-claim-ids") ?? "").split(/\s+/).filter(Boolean)[0];
    if (first) post({ type: "corelata:select", claim: first });
  });
  listen((message) => {
    if (!message || message.type !== "corelata:highlight") return;
    for (const el of doc.querySelectorAll(".corelata-highlight"))
      el.classList.remove("corelata-highlight");
    if (!message.claim) return;
    const marked = doc.querySelectorAll(`[data-claim-ids~="${CSS.escape(message.claim)}"]`);
    for (const el of marked) el.classList.add("corelata-highlight");
    if (message.scroll) marked[0]?.scrollIntoView?.({ block: "center" });
  });
  post({ type: "corelata:ready" });
}

/** The `<script>` that installs the bridge: it talks to `parent` and trusts only `parent`. */
export function bridgeScript(): string {
  return (
    `<script>(${installFrameBridge.toString()})(document,` +
    ' function (m) { parent.postMessage(m, "*"); },' +
    ' function (h) { addEventListener("message", function (e) { if (e.source === parent) h(e.data); }); },' +
    ` ${JSON.stringify(HIGHLIGHT_CSS)});</script>`
  );
}

/** The report with the bridge appended inside `<body>` (or at the end when there is none). */
export function withBridge(html: string): string {
  const script = bridgeScript();
  const at = html.toLowerCase().lastIndexOf("</body>");
  return at === -1 ? html + script : html.slice(0, at) + script + html.slice(at);
}
```

Run: `cd web && pnpm test -- frameBridge`
Expected: PASS. If `Element.prototype.scrollIntoView = scroll` upsets TypeScript, cast: `(Element.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView = scroll;`.

- [ ] **Step 3: Write the failing ReportFrame tests**

Replace `web/src/pages/review/ReportFrame.test.tsx` with:

```tsx
import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { reportHtml } from "../../test/fixtures";
import { ReportFrame } from "./ReportFrame";

function Host({ initial = null, html = reportHtml }: { initial?: string | null; html?: string }) {
  const [claim, setClaim] = useState<string | null>(initial);
  return (
    <>
      <output aria-label="Selected">{claim ?? "none"}</output>
      <ReportFrame html={html} selectedClaim={claim} onSelectClaim={setClaim} />
    </>
  );
}

function frame(): HTMLIFrameElement {
  return screen.getByTitle("Report") as HTMLIFrameElement;
}

/** A message as the page receives it; `source` is read-only on a real event, so it is defined. */
function deliver(data: unknown, source: Window | null = frame().contentWindow) {
  const event = new MessageEvent("message", { data });
  Object.defineProperty(event, "source", { value: source });
  act(() => {
    window.dispatchEvent(event);
  });
}

const highlight = (claim: string | null, scroll: boolean) => ({
  type: "corelata:highlight",
  claim,
  scroll,
});

it("puts the report and the bridge into a scriptable frame with no origin", () => {
  render(<Host initial="c3" />);
  expect(frame()).toHaveAttribute("sandbox", "allow-scripts");
  const srcdoc = frame().getAttribute("srcdoc")!;
  expect(srcdoc).toContain("Varna Port Expansion");
  expect(srcdoc).toContain("corelata:highlight");
  expect(srcdoc.indexOf("<script>")).toBeLessThan(srcdoc.lastIndexOf("</body>"));
  expect(document.querySelector("style")).toBeNull(); // the report's stylesheet stays inside
});

it("sends the selection once the frame is ready, then on every change", () => {
  const { rerender } = render(<Host initial="c3" />);
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  expect(post).not.toHaveBeenCalled(); // nothing before the frame reports in
  deliver({ type: "corelata:ready" });
  expect(post).toHaveBeenLastCalledWith(highlight("c3", true), "*");
  deliver({ type: "corelata:select", claim: "c1" }); // a click inside the frame: no scroll
  expect(screen.getByLabelText("Selected")).toHaveTextContent("c1");
  expect(post).toHaveBeenLastCalledWith(highlight("c1", false), "*");
  deliver({ type: "corelata:select", claim: "c1" }); // the same claim again: nothing changes
  expect(post).toHaveBeenCalledTimes(2);
});

it("clears the highlight when the selection is cleared", () => {
  const { rerender } = render(
    <ReportFrame html={reportHtml} selectedClaim="c3" onSelectClaim={() => {}} />,
  );
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  deliver({ type: "corelata:ready" });
  rerender(<ReportFrame html={reportHtml} selectedClaim={null} onSelectClaim={() => {}} />);
  expect(post).toHaveBeenCalledTimes(2);
  expect(post).toHaveBeenLastCalledWith(highlight(null, true), "*");
});

it("re-sends the highlight after a new report loads", () => {
  const { rerender } = render(
    <ReportFrame html={reportHtml} selectedClaim="c3" onSelectClaim={() => {}} />,
  );
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  deliver({ type: "corelata:ready" });
  rerender(
    <ReportFrame html={reportHtml + "<!-- v2 -->"} selectedClaim="c3" onSelectClaim={() => {}} />,
  );
  expect(frame().getAttribute("srcdoc")).toContain("<!-- v2 -->");
  deliver({ type: "corelata:ready" }); // the reloaded frame's bridge reports in
  expect(post).toHaveBeenCalledTimes(2);
  expect(post).toHaveBeenLastCalledWith(highlight("c3", true), "*");
});

it("ignores messages from other windows and malformed data", () => {
  render(<Host />);
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  deliver({ type: "corelata:ready" }, window);
  deliver({ type: "corelata:select", claim: "c1" }, null);
  deliver(null);
  deliver("corelata:select");
  deliver({ type: "corelata:select", claim: 42 });
  expect(post).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Selected")).toHaveTextContent("none");
});
```

Run: `cd web && pnpm test -- ReportFrame`
Expected: FAIL (`sandbox` is still `allow-same-origin`, no `srcdoc`).

- [ ] **Step 4: Rewrite `web/src/pages/review/ReportFrame.tsx`**

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { type FrameToHost, type HostToFrame, withBridge } from "./frameBridge";

/** The rendered report (spec §9, claim ids on) in a sandboxed frame with no origin of its own:
 * its stylesheet stays inside, nothing in it can touch the page, and the bridge script in the
 * document is the only channel (M7). The page tells the frame which claim to highlight; the
 * frame tells the page which cited element a reader clicked. */
export function ReportFrame({
  html,
  selectedClaim,
  onSelectClaim,
}: {
  html: string;
  selectedClaim: string | null;
  onSelectClaim: (claimId: string) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const select = useRef(onSelectClaim);
  select.current = onSelectClaim;
  const fromFrame = useRef(false); // the last selection came from a click inside the frame
  const current = useRef(selectedClaim);
  current.current = selectedClaim;
  const [ready, setReady] = useState(0); // bumps each time a loaded frame's bridge reports in
  const srcdoc = useMemo(() => withBridge(html), [html]);

  useEffect(() => {
    const onMessage = (event: MessageEvent<FrameToHost | null>) => {
      if (!event.source || event.source !== frame.current?.contentWindow) return;
      const message = event.data;
      if (typeof message !== "object" || message === null) return;
      if (message.type === "corelata:ready") setReady((n) => n + 1);
      else if (message.type === "corelata:select" && typeof message.claim === "string") {
        fromFrame.current = message.claim !== current.current;
        select.current(message.claim);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // The highlight follows the selection, once there is a frame to tell.
  useEffect(() => {
    if (!ready) return;
    const message: HostToFrame = {
      type: "corelata:highlight",
      claim: selectedClaim,
      scroll: !fromFrame.current,
    };
    frame.current?.contentWindow?.postMessage(message, "*"); // the frame has no origin to name
    fromFrame.current = false;
  }, [selectedClaim, ready]);

  return (
    <iframe
      ref={frame}
      title="Report"
      className="report-frame"
      sandbox="allow-scripts"
      srcDoc={srcdoc}
    />
  );
}
```

Run: `cd web && pnpm test -- ReportFrame`
Expected: PASS. If `vi.spyOn(contentWindow, "postMessage")` fails because jsdom defines `postMessage` as non-configurable, replace the spy with `frame().contentWindow!.postMessage = vi.fn()` before `render` is impossible, so instead assign after render: `const post = vi.fn(); Object.defineProperty(frame().contentWindow, "postMessage", { value: post, configurable: true });`.

- [ ] **Step 5: Update the review-page test that clicked inside the frame**

`web/src/pages/review/ReviewPage.test.tsx:97-105` (the block from `const frame = ...` to the `act(...)` call) becomes:

```tsx
  const frame = (await screen.findByTitle("Report")) as HTMLIFrameElement;
  expect(frame.getAttribute("srcdoc")).toContain('p data-claim-ids="c1"');
  act(() => {
    const event = new MessageEvent("message", {
      data: { type: "corelata:select", claim: "c1" },
    });
    Object.defineProperty(event, "source", { value: frame.contentWindow });
    window.dispatchEvent(event);
  });
```

Remove the now-unused `doc` and `view` variables. Run: `cd web && pnpm test && pnpm lint`
Expected: PASS with coverage at or above 95% on every metric. Check `grep -rn "contentDocument" web/src` finds nothing outside tests that still relies on the old frame.

- [ ] **Step 6: Run the journeys**

Run: `make e2e` (builds the app, starts the dev stack on 8765, runs Playwright against the real browser, which does load `srcdoc`).
Expected: PASS, including `upload, suggest value, run, review, return and rerun`, where `frame.locator(".corelata-highlight").first()` becomes visible after a claim is clicked in the Claims list.

- [ ] **Step 7: Docs**

`docs/m4b-followups.md:47-50` (the `document.write` item) and line 66 (anchors): append ` — **closed in M7** (`srcdoc`, `sandbox="allow-scripts"`, a `postMessage` bridge; links inside the report are inert; BORG-41).` Spec §10.3 M4b amendments: replace `The report is shown in a same-origin frame written from` with `The report is shown in a sandboxed frame (`srcdoc`, scripts allowed, no origin of its own; M7) loaded from`, and append `A small script inside the frame relays clicks on cited elements to the page and applies the highlight the page asks for; links inside the report navigate nothing.`

- [ ] **Step 8: Commit**

```bash
git add web/src/pages/review/frameBridge.ts web/src/pages/review/frameBridge.test.ts web/src/pages/review/ReportFrame.tsx web/src/pages/review/ReportFrame.test.tsx web/src/pages/review/ReviewPage.test.tsx docs/m4b-followups.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -F /path/to/message   # "feat: show the report in an origin-less sandboxed frame with a message bridge (BORG-41)"
```

---

### Task 5: Bench: partial report, concurrency, stored model I/O, schema and table (BORG-42)

Five small changes to `corelata bench`: `bench.json` is written after every finished run (so Ctrl-C keeps what finished), `--concurrency N` runs up to N scenario runs at once (the backend's `max_concurrency` still bounds the server), `--store-io` keeps the model requests and responses in the traces, `Rate.ratio` appears in the exported schema, and the text table has separate `agree` and `outcome` columns.

**Files:**
- Modify: `engine/corelata/bench/run.py`, `engine/corelata/bench/text.py`, `engine/corelata/schema/export.py`, `engine/corelata/cli.py` (bench parser and `_bench`)
- Regenerate: `schema/bench-report.schema.json` (`make schema`)
- Modify: `README.md` (M6 section), `docs/operator-guide.md:402-416`, `docs/m6-followups.md`, spec §6.8 bench line
- Test: `engine/tests/bench/test_run.py`, `engine/tests/bench/test_text.py`, `engine/tests/schema/test_export.py`, `engine/tests/test_cli_bench.py`

**Interfaces:**
- Produces: `run_bench(..., concurrency: int = 1, store_io: bool = False, ...)` writes `out_dir / "bench.json"` itself after every run and at the end; the CLI no longer writes it. `corelata.schema.export.SERIALIZED: frozenset[str] = frozenset({"bench-report"})`.

- [ ] **Step 1: Write the failing schema and text tests**

Append to `engine/tests/schema/test_export.py`:

```python
def test_bench_report_schema_is_the_serialized_shape(tmp_path):
    """BenchReport is something Corelata writes and others read: its computed `ratio` must be in
    the schema, so that one model is exported in serialization mode."""
    export(tmp_path)
    schema = json.loads((tmp_path / "bench-report.schema.json").read_text())
    assert "ratio" in schema["$defs"]["Rate"]["properties"]
    report = json.loads((tmp_path / "report.schema.json").read_text())
    assert "claims" in report["properties"]  # the validation-mode exports are unchanged
```

In `engine/tests/bench/test_text.py`, `test_format_bench_lists_scenarios_summary_rules_and_mismatches`, after `assert len(table) == 3` add:

```python
    header = lines[4]
    assert "  agree  outcome" in header and "agree outcome" not in header
    assert table[0].split()[2] == "yes" and table[1].split()[2] == "no"
    assert table[2].split()[2] == "err" and "RuntimeError: boom" in table[2]
```

Run: `cd engine && uv run pytest tests/schema/test_export.py tests/bench/test_text.py -q`
Expected: FAIL on both new assertions.

- [ ] **Step 2: Schema mode and the table**

`engine/corelata/schema/export.py`: after `EXPORTED`, add and use:

```python
# Written by Corelata and read by others: computed fields (BenchReport's `Rate.ratio`) belong in
# the schema, which only serialization mode includes. Everything else is validated on input.
SERIALIZED: frozenset[str] = frozenset({"bench-report"})


def export(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in EXPORTED.items():
        path = out_dir / f"{name}.schema.json"
        mode = "serialization" if name in SERIALIZED else "validation"
        schema = model.model_json_schema(mode=mode)
        text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
        path.write_text(text + "\n", encoding="utf-8")
        written.append(path)
    return written
```

`engine/corelata/bench/text.py`: replace `_outcome` and the header/row lines:

```python
def _outcome(run: RunResult) -> tuple[str, str]:
    """The `agree` flag and the `outcome` text of a table row."""
    if not run.ok:
        return "err", run.error or ""
    state = run.state.value if run.state is not None else "?"
    status = f" {run.status.value}" if run.status is not None else ""
    return ("yes" if run.agree else "no"), f"{state}{status}"
```

```python
        f"{'scenario':<{width}}  {'run':>3}  {'agree':<5}  {'outcome':<24} {'time':>7}  "
        f"{'calls':>5}  {'tokens':>6}",
    ]
    for scenario in report.scenarios:
        for run in scenario.runs:
            agree, outcome = _outcome(run)
            lines.append(
                f"{scenario.name:<{width}}  {run.repeat:>3}  {agree:<5}  {outcome:<24} "
                f"{run.duration_s:>6.1f}s  {run.calls:>5}  {run.tokens_in + run.tokens_out:>6}"
            )
```

Run: `make schema` (regenerates `schema/bench-report.schema.json`; `git diff --stat` must show only that file under `schema/`), then `cd engine && uv run pytest tests/schema tests/bench/test_text.py -q`.
Expected: PASS.

- [ ] **Step 3: Write the failing run tests**

Append to `engine/tests/bench/test_run.py`:

```python
async def test_bench_json_is_written_after_every_run(make_config, monkeypatch, tmp_path):
    """Ctrl-C half-way must leave the runs that finished (spec §13, M7)."""
    scenarios = [
        load_scenario(SCENARIOS_DIR / "clean-single-source.yaml"),
        load_scenario(SCENARIOS_DIR / "gate-rejected.yaml"),
    ]
    real = scenarios_module.run_scenario
    seen: list[int] = []

    async def spying(scenario, cfg, **kw):
        partial = tmp_path / "bench.json"
        on_disk = BenchReport.model_validate_json(partial.read_text()) if partial.is_file() else None
        seen.append(on_disk.summary.runs if on_disk else 0)
        return await real(scenario, cfg, **kw)

    monkeypatch.setattr("corelata.bench.run.run_scenario", spying)
    report = await run_bench(
        make_config(),
        scenarios,
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        out_dir=tmp_path,
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
    )
    assert seen == [0, 1]  # before the first run nothing; before the second, one run on disk
    final = BenchReport.model_validate_json((tmp_path / "bench.json").read_text())
    assert final.summary.runs == 2 and final == report


async def test_concurrency_overlaps_runs_and_keeps_the_order(make_config, monkeypatch):
    names = ["gate-rejected", "clean-single-source", "clean-two-sources"]
    scenarios = [load_scenario(SCENARIOS_DIR / f"{n}.yaml") for n in names]
    real = scenarios_module.run_scenario
    in_flight, peak = [0], [0]
    started = asyncio.Event()

    async def overlapping(scenario, cfg, **kw):
        in_flight[0] += 1
        peak[0] = max(peak[0], in_flight[0])
        if in_flight[0] == 3:
            started.set()
        await started.wait()  # every run waits until all three are in flight
        try:
            return await real(scenario, cfg, **kw)
        finally:
            in_flight[0] -= 1

    monkeypatch.setattr("corelata.bench.run.run_scenario", overlapping)
    lines: list[str] = []
    report = await run_bench(
        make_config(),
        scenarios,
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        repeat=2,
        concurrency=3,
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
        progress=lines.append,
    )
    assert peak[0] == 3
    assert [s.name for s in report.scenarios] == names
    assert all([r.repeat for r in s.runs] == [1, 2] for s in report.scenarios)
    assert report.summary.runs == 6 and len(lines) == 6 and exit_code(report) == 0


async def test_store_io_keeps_the_model_text_in_the_traces(make_config, tmp_path):
    scenario = load_scenario(SCENARIOS_DIR / "gate-rejected.yaml")
    for store_io in (False, True):
        await run_bench(
            make_config(),
            [scenario],
            backends={"fake": FakeBackend(name="fake")},
            prompts=PromptLibrary(),
            store_io=store_io,
            out_dir=tmp_path / str(store_io),
            scenarios_dir=SCENARIOS_DIR,
            clock=_ticker(),
        )
    calls = {
        store_io: json.loads(
            (tmp_path / str(store_io) / scenario.name / "run-1" / "trace.json").read_text()
        )["calls"]
        for store_io in (False, True)
    }
    assert all(c["request"] is None and c["response"] is None for c in calls[False])
    assert all(c["request"] is not None and c["response"] is not None for c in calls[True])
```

Put `import asyncio` with the other imports at the top of the file (`BenchReport` is already imported there). Run: `cd engine && uv run pytest tests/bench/test_run.py -q`
Expected: FAIL (`concurrency`/`store_io` are unknown arguments; `bench.json` is not written by `run_bench`).

- [ ] **Step 4: Rewrite `run_bench`**

`engine/corelata/bench/run.py`: replace the module docstring's second sentence with "Runs execute up to `concurrency` at a time (default one; the backend's `max_concurrency` still bounds the server), and `bench.json` is rewritten after every finished run so an interrupted bench keeps what finished." Replace `run_bench` with:

```python
def _write_report(out_dir: Path, report: BenchReport) -> None:
    (out_dir / "bench.json").write_text(dump_json(report.model_dump(mode="json")), encoding="utf-8")


async def run_bench(
    cfg: CorelataConfig,
    scenarios: list[Scenario],
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    repeat: int = 1,
    concurrency: int = 1,
    store_io: bool = False,
    out_dir: Path | None = None,
    scenarios_dir: Path,
    now: Callable[[], datetime] = utcnow,
    clock: Callable[[], float] = time.monotonic,
    progress: Progress | None = None,
) -> BenchReport:
    started = now()
    bench_t0 = clock()
    tallies: dict[str, RuleTally] = {}
    runs: dict[str, list[RunResult]] = {s.name: [] for s in scenarios}
    if out_dir is not None:  # a re-run into the same directory leaves no stale traces
        for scenario in scenarios:
            for stale in (out_dir / scenario.name).glob("run-*"):
                shutil.rmtree(stale, ignore_errors=True)

    def report() -> BenchReport:
        results = [
            ScenarioResult(
                name=s.name,
                description=s.description,
                runs=sorted(runs[s.name], key=lambda r: r.repeat),
            )
            for s in scenarios
        ]
        return BenchReport(
            corelata_version=__version__,
            started_at=started,
            finished_at=now(),
            config_hash=config_hash(cfg),
            models={
                role: cfg.models[key].name or key
                for role, key in cfg.roles.all_roles()
                if role != "profiler"
            },
            scenarios_dir=str(scenarios_dir),
            repeat=repeat,
            scenarios=results,
            rules={rule_id: tallies[rule_id] for rule_id in sorted(tallies)},
            summary=summarize(results, duration_s=clock() - bench_t0),
        )

    gate = asyncio.Semaphore(concurrency)

    async def one(scenario: Scenario, k: int) -> None:
        async with gate:
            t0 = clock()
            try:
                record = await run_scenario(
                    scenario,
                    cfg,
                    backends=backends,
                    prompts=prompts,
                    log=CallLog(store_io=store_io),
                    now=now,
                )
            except Exception as e:  # noqa: BLE001 - one broken scenario must not end the bench
                result = error_result(
                    repeat=k,
                    error=" ".join(f"{type(e).__name__}: {e}".split()),
                    duration_s=clock() - t0,
                )
            else:
                result = score_run(
                    scenario, record, repeat=k, duration_s=clock() - t0, tallies=tallies
                )
                if out_dir is not None:
                    _write_trace(out_dir, scenario.name, k, dump_json(record.model_dump(mode="json")))
            runs[scenario.name].append(result)
            if out_dir is not None:
                _write_report(out_dir, report())
            if progress is not None:
                progress(f"{scenario.name} {k}/{repeat}: {_describe(result)}")

    await asyncio.gather(*(one(s, k) for s in scenarios for k in range(1, repeat + 1)))
    final = report()
    if out_dir is not None:
        _write_report(out_dir, final)
    return final
```

Add `import asyncio` to the imports. `score_run` and `summarize` have no `await`, so the shared `tallies` and `runs` are never touched by two runs at once.

Run: `cd engine && uv run pytest tests/bench -q`
Expected: PASS (including the existing `test_a_rerun_into_the_same_directory_leaves_no_stale_traces` and the order of `lines[0]` in `test_full_agreement_on_the_shipped_set`, which concurrency 1 preserves).

- [ ] **Step 5: Write the failing CLI tests**

Append to `engine/tests/test_cli_bench.py`:

```python
def test_bench_interrupted_keeps_the_partial_report_and_exits_130(
    config_path, tmp_path, capsys, monkeypatch
):
    from corelata import scenarios as scenarios_module

    real = scenarios_module.run_scenario

    async def interrupting(scenario, cfg, **kw):
        if scenario.name == "gate-rejected":
            raise KeyboardInterrupt
        return await real(scenario, cfg, **kw)

    monkeypatch.setattr("corelata.bench.run.run_scenario", interrupting)
    out = tmp_path / "bench"
    rc = main(
        ["bench", "--config", str(config_path), "--only", "clean-single-source", "--only",
         "gate-rejected", "--out", str(out)]
    )
    err = capsys.readouterr().err
    assert rc == 130 and f"interrupted; the partial report is {out / 'bench.json'}" in err
    report = BenchReport.model_validate_json((out / "bench.json").read_text())
    assert [(s.name, len(s.runs)) for s in report.scenarios] == [
        ("clean-single-source", 1),
        ("gate-rejected", 0),
    ]


def test_bench_interrupted_without_out_says_so(config_path, capsys, monkeypatch):
    async def interrupting(scenario, cfg, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr("corelata.bench.run.run_scenario", interrupting)
    rc = main(["bench", "--config", str(config_path), "--only", "clean-single-source"])
    assert rc == 130 and capsys.readouterr().err.strip().endswith("interrupted")


def test_bench_concurrency_and_store_io_flags(config_path, tmp_path, capsys):
    out = tmp_path / "bench"
    rc = main(
        ["bench", "--config", str(config_path), "--only", "clean-single-source", "--only",
         "gate-rejected", "--concurrency", "2", "--store-io", "--out", str(out)]
    )
    assert rc == 0, capsys.readouterr().err
    trace = json.loads((out / "gate-rejected" / "run-1" / "trace.json").read_text())
    assert all(c["request"] is not None for c in trace["calls"])
    assert main(["bench", "--config", str(config_path), "--concurrency", "0"]) == 2
    assert "--concurrency must be between 1 and 16" in capsys.readouterr().err
    assert main(["bench", "--config", str(config_path), "--concurrency", "17"]) == 2
```

Run: `cd engine && uv run pytest tests/test_cli_bench.py -q -k "interrupted or concurrency"`
Expected: FAIL (unknown flag; `interrupted` only).

- [ ] **Step 6: The CLI**

In `build_parser`, after the `--repeat` argument of `bench` add:

```python
    bench.add_argument(
        "--concurrency", type=int, default=1, help="scenario runs in flight at once (1-16)"
    )
    bench.add_argument(
        "--store-io", action="store_true", help="keep model requests and responses in the traces"
    )
```

In `_bench`: after the `--repeat` check add

```python
    if not 1 <= args.concurrency <= 16:
        return _usage("--concurrency must be between 1 and 16")
```

pass `concurrency=args.concurrency, store_io=args.store_io,` to `run_bench`, and replace the tail from `report = asyncio.run(go())` to the end with:

```python
    try:
        report = asyncio.run(go())
    except KeyboardInterrupt:
        where = f"; the partial report is {args.out / 'bench.json'}" if args.out is not None else ""
        print(f"interrupted{where}", file=sys.stderr)
        return EXIT_INTERRUPTED
    if args.json:
        print(dump_json(report.model_dump(mode="json")), end="")
    else:
        print(format_bench(report), end="")
    return bench_exit_code(report)
```

(`run_bench` now writes `bench.json`; the CLI no longer does.) If the interrupt test shows `asyncio.run` turning the `KeyboardInterrupt` raised inside the task into a `CancelledError` on this Python, catch `KeyboardInterrupt` inside `go()` instead: wrap the `await run_bench(...)` in `try/except KeyboardInterrupt: raise` is not enough; return a sentinel (`None`) from `go()` on `KeyboardInterrupt` and treat `None` as interrupted in `_bench`.

Run: `cd engine && uv run pytest tests/test_cli_bench.py -q && uv run pytest -q`
Expected: PASS, coverage above 95%.

- [ ] **Step 7: Docs**

README M6 paragraph on `bench`: after `--json` prints the report.` add: `--concurrency N` runs up to N scenario runs at once (the backend's `max_concurrency` still caps the server), `--store-io` keeps the model requests and responses in the traces for diagnosing a disagreement, and `bench.json` is rewritten after every finished run, so Ctrl-C keeps what finished.` `docs/operator-guide.md:408-409` code block: add a third line `docker compose exec api corelata bench --concurrency 4 --store-io --out /data/files/bench-$(date +%F)` and after the block one sentence: `An interrupted bench leaves a `bench.json` with the runs that finished.` `docs/m6-followups.md`: mark the `--concurrency`, `--store-io`, `Rate.ratio`, header and Ctrl-C items ` — **closed in M7** (BORG-42)`. Spec §6.8 M6 amendment bench line: insert `[--concurrency <n>] [--store-io]` after `[--repeat <n>]`.

- [ ] **Step 8: Lint and commit**

```bash
cd engine && uv run ruff check . && uv run ruff format --check .
git add engine/corelata/bench/run.py engine/corelata/bench/text.py engine/corelata/schema/export.py engine/corelata/cli.py schema/bench-report.schema.json engine/tests/bench/test_run.py engine/tests/bench/test_text.py engine/tests/schema/test_export.py engine/tests/test_cli_bench.py README.md docs/operator-guide.md docs/m6-followups.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -F /path/to/message   # "feat: bench keeps a partial report, runs concurrently and can store model I/O (BORG-42)"
```

---

### Task 6: Profile extractor: budget by report length, warn on a name collision (BORG-43)

`read_examples` cuts every report to an even share of the budget, so a long report loses its tail while short ones leave budget unused; the share now water-fills (short reports keep everything, the rest is split evenly among the long ones). `profile extract` says nothing when `--name` is already a profile in the extends chain; it warns.

**Files:**
- Modify: `engine/corelata/profiler.py:42-71`, `engine/corelata/standards/loader.py` (after `resolve_profile`), `engine/corelata/cli.py` (`_profile`)
- Modify: `README.md` (M6 section), `docs/operator-guide.md:238-250`, `docs/m6-followups.md`
- Test: `engine/tests/test_profiler.py`, `engine/tests/standards/test_loader.py`, `engine/tests/test_cli_profile.py`

**Interfaces:**
- Produces: `corelata.standards.loader.chain_profiles(name: str, packs_dir: Path | None = None) -> dict[str, str]` (profile name → the pack that defines it; the nearest pack in the chain wins, as `load_pack` resolves it); `corelata.profiler._shares(costs: list[int], budget: int) -> list[int]`.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/test_profiler.py`:

```python
from corelata.profiler import _shares


def test_shares_water_fill_the_budget():
    assert _shares([8, 200], 108) == [8, 100]  # the short report keeps all, the long one the rest
    assert _shares([50, 50, 50], 90) == [30, 30, 30]  # all long: an even split
    assert _shares([5, 5], 100) == [5, 5]  # budget to spare
    assert _shares([100], 0) == [1]  # never less than one token per report
    assert _shares([30, 10, 20], 45) == [18, 10, 17]  # order is kept; allotment goes by size


def test_read_examples_gives_long_reports_what_short_ones_leave(tmp_path):
    (tmp_path / "a.txt").write_text("\n\n".join(["x" * 10] * 2), encoding="utf-8")  # 2 x 4 tokens
    (tmp_path / "b.txt").write_text("\n\n".join(["y" * 25] * 20), encoding="utf-8")  # 20 x 10
    reports = read_examples(tmp_path, budget_tokens=108, bytes_per_token=2.5)
    assert [r.name for r in reports] == ["a.txt", "b.txt"]
    assert len(reports[0].units) == 2 and not reports[0].truncated
    assert len(reports[1].units) == 10 and reports[1].truncated  # 100 of the budget, not 54
```

Append to `engine/tests/standards/test_loader.py`:

```python
def test_chain_profiles_names_the_nearest_owner(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE], profiles={"shared": {"name": "shared", "extends": "base"}})
    write_pack(
        tmp_path,
        "derived",
        rules=[],
        extends="base",
        template=None,
        lexicon=None,
        profiles={
            "shared": {"name": "shared", "extends": "derived"},
            "own": {"name": "own", "extends": "derived", "draft": True},
        },
    )
    assert chain_profiles("base", packs_dir=tmp_path) == {"shared": "base"}
    assert chain_profiles("derived", packs_dir=tmp_path) == {"shared": "derived", "own": "derived"}
    with pytest.raises(PackError, match="not found"):
        chain_profiles("nope", packs_dir=tmp_path)
```

Add `chain_profiles` to the file's `from corelata.standards.loader import (...)`.

Append to `engine/tests/test_cli_profile.py`:

```python
def test_extract_warns_when_the_name_is_already_a_profile(config_path, examples, tmp_path, capsys):
    pack_dir = tmp_path / "packs" / "icd203-base"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", pack_dir)
    (pack_dir / "profiles").mkdir()
    (pack_dir / "profiles" / "team-east.yaml").write_text(
        "name: team-east\nextends: icd203-base\n", encoding="utf-8"
    )
    out = tmp_path / "team-east.yaml"
    rc = main(_extract_argv(config_path, examples, out, "--packs-dir", str(pack_dir.parent)))
    captured = capsys.readouterr()
    assert rc == 0 and out.is_file()
    assert (
        "warning: profile 'team-east' already exists in pack 'icd203-base'; "
        "a profile file of that name in its profiles/ directory would replace it" in captured.err
    )
    rc = main(_extract_argv(config_path, examples, tmp_path / "team-west.yaml", "--packs-dir", str(pack_dir.parent)))
    assert rc == 0 and "warning: profile" not in capsys.readouterr().err
```

Run: `cd engine && uv run pytest tests/test_profiler.py tests/standards/test_loader.py tests/test_cli_profile.py -q -k "shares or long_reports or chain_profiles or already_a_profile"`
Expected: FAIL (`_shares`, `chain_profiles` missing; no warning).

- [ ] **Step 2: The loader and the profiler**

`engine/corelata/standards/loader.py`, after `resolve_profile`:

```python
def chain_profiles(name: str, packs_dir: Path | None = None) -> dict[str, str]:
    """Profile name -> the pack in `name`'s chain that defines it, the way `load_pack` finds them:
    the nearest pack wins. `corelata profile extract` warns when a new draft would shadow one."""
    owners: dict[str, str] = {}
    for pack in _chain(name, packs_dir):  # base first, so a descendant overwrites
        for profile_name in pack.profiles:
            owners[profile_name] = pack.meta.name
    return owners
```

`engine/corelata/profiler.py`: add `_shares` above `read_examples` and use it:

```python
def _shares(costs: list[int], budget: int) -> list[int]:
    """Split `budget` tokens over reports of the given sizes: a report that fits keeps all of its
    tokens, the rest is divided evenly among the longer ones (water-filling), and every report
    gets at least one token so one unit always survives."""
    shares = [0] * len(costs)
    remaining = budget
    pending = len(costs)
    for i in sorted(range(len(costs)), key=lambda i: costs[i]):
        shares[i] = max(min(costs[i], remaining // pending), 1)
        remaining = max(remaining - shares[i], 0)
        pending -= 1
    return shares
```

In `read_examples`, replace `share = max(budget_tokens // len(files), 1)` and the loop with:

```python
    sources = [make_source(f"ex{i}", path) for i, path in enumerate(files, 1)]
    costs = [
        [estimate_tokens(unit.text, bytes_per_token) for unit in source.units]
        for source in sources
    ]
    shares = _shares([sum(c) for c in costs], budget_tokens)
    reports: list[ExampleReport] = []
    for path, source, unit_costs, share in zip(files, sources, costs, shares, strict=True):
        units: list[str] = []
        spent = 0
        for unit, cost in zip(source.units, unit_costs, strict=True):
            if units and spent + cost > share:
                break
            units.append(unit.text)
            spent += cost
        reports.append(ExampleReport(path.name, units, truncated=len(units) < len(source.units)))
    return reports
```

Update the docstring: "cut to a share of `budget_tokens` that favours long reports once the short ones are whole (at least one unit each)".

`engine/corelata/cli.py`, `_profile`: import `chain_profiles` from `corelata.standards.loader`, add `PackError` to the `except (ConfigError, IngestError, OSError)` tuple of the first `try`, and inside that `try`, after `packs_dir = ...`, add:

```python
        owners = chain_profiles(extends, packs_dir)
        if name in owners:
            print(
                f"warning: profile '{name}' already exists in pack '{owners[name]}'; a profile "
                "file of that name in its profiles/ directory would replace it",
                file=sys.stderr,
            )
```

Run: `cd engine && uv run pytest tests/test_profiler.py tests/standards/test_loader.py tests/test_cli_profile.py -q && uv run pytest -q`
Expected: PASS; `test_read_examples_in_name_order_within_budget` still passes (three equal reports split evenly as before).

- [ ] **Step 3: Docs**

README M6 `profile extract` paragraph: append `Long example reports get the budget the short ones leave, so a team's one long report is not cut to a third; the command warns when the profile name already exists in the pack it extends.` `docs/operator-guide.md`, the profile paragraph ending `without it an existing profile is never touched.`: append ` The command warns if the name is already a profile of the pack, since copying the draft into `profiles/` under that name would replace the team's approved one.` `docs/m6-followups.md`: mark the even-share, `--name` collision and web-select items ` — **closed in M7** (BORG-43; the select already disables drafts and labels them "(draft)")`.

- [ ] **Step 4: Lint and commit**

```bash
cd engine && uv run ruff check . && uv run ruff format --check .
git add engine/corelata/profiler.py engine/corelata/standards/loader.py engine/corelata/cli.py engine/tests/test_profiler.py engine/tests/standards/test_loader.py engine/tests/test_cli_profile.py README.md docs/operator-guide.md docs/m6-followups.md
git commit -F /path/to/message   # "feat: profile extract water-fills the example budget and warns on a name collision (BORG-43)"
```

---

### Task 7: README section and `docs/m7-followups.md`

**Files:**
- Modify: `README.md` (new section before `## Development`)
- Create: `docs/m7-followups.md`

- [ ] **Step 1: README**

Insert before `## Development`:

```markdown
## M7: hardening after v1

Six follow-ups from the first release (Jira BORG-35, 36, 40, 41, 42, 43): `/api/health`,
`/api/system/info`, the web footer and `corelata --version` report the bundle version the image
was built with (`CORELATA_BUILD_VERSION`); `corelata pack diff <left> <right>` compares packs,
profiles (`--profile-left/right`) and run snapshots (a run directory) and exits 3 on a
difference; the Sources tab shows each source's SHA-256; the report frame is sandboxed with no
origin of its own (`srcdoc`, `sandbox="allow-scripts"`, a `postMessage` bridge; links inside the
report are inert); `corelata bench` keeps a partial `bench.json` on Ctrl-C and takes
`--concurrency` and `--store-io`; `corelata profile extract` gives long example reports the budget
short ones leave and warns when the name is already a profile.
```

- [ ] **Step 2: `docs/m7-followups.md`**

```markdown
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

## Later

- Scenarios written for real models (BORG-42, after the deployment dry run BORG-34).
- A release workflow (BORG-44).
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/m7-followups.md
git commit -F /path/to/message   # "docs: README M7 section and follow-ups"
```

---

## Self-review

- **Spec coverage:** §6.8 `pack diff` → Task 2; §10.3 "hashes" → Task 3; §10.3 frame → Task 4; §12 versions → Task 1; §13 bench → Task 5; §4.4/§6.5 extractor → Task 6. The tickets' texts are each covered by one task.
- **Placeholders:** none; every step has its code or exact text. Task 2 Step 8 asks the implementer to verify two container paths before writing them, with the fallback stated.
- **Type consistency:** `build_version`/`version_line` (Task 1) used by `cli.py` and the API; `diff_packs(left, right, *, left_name, right_name)` and `format_diff(diff, *, left, right)` (Task 2) match the CLI calls; `SourceSummary.sha256: str` (Task 3) matches the fixture and the test; `FrameToHost`/`HostToFrame` (Task 4) match both sides; `run_bench(..., concurrency, store_io)` (Task 5) matches the CLI and tests; `chain_profiles` and `_shares` (Task 6) match their tests.
- **Review Focus:** each of the five lines names the test that pins it.
