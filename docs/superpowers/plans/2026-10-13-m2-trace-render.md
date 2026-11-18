# Corelata M2: Trace, HTML/DOCX Rendering and Scenario Fixtures — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver spec §14 M2: a documented trace export, HTML and DOCX renders alongside Markdown (all three carrying the open-findings appendix), `corelata report` and `corelata trace` commands that work from a run directory alone, and scenario fixtures that pin the pipeline's behaviour against the fake model — plus the three M1 carry-overs that M3 depends on (sorted pack hash, chunked digests, writer unit budget).

**Architecture:** A renderer-neutral *outline* (`render/outline.py`) becomes the single place that knows section order, heading numbering, source lines and the appendix; Markdown is refactored onto it and HTML (jinja2, autoescaped, self-contained) and DOCX (python-docx, optional reference document) are written against it, so the three outputs cannot drift. A `trace` module answers the review-screen questions (timeline, findings by iteration, claim provenance, draft diff) as pure functions of `RunRecord`, and the CLI gains `report` and `trace` subcommands that read `trace.json`. A `scenarios` module loads YAML fixtures (sources + statement + expectations), runs them through `run_report`, and reports mismatches; M6's `bench` will reuse it against real models.

**Tech Stack:** Python 3.12, uv, pydantic v2, jinja2, python-docx 1.2, lxml (tests only, for parsing HTML), pyyaml, pytest + pytest-asyncio + hypothesis. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §5.4 (digests), §6.5/§6.6 (profile format, snapshot), §7.4 (context budgets; amended by Task 10), §7.5 (error ladder), §8.4 (trace invariants), §9 (rendering), §10.2 (CLI), §13 (golden tests, scenario fixtures), §14 (M2 row). M1 follow-ups: `docs/m1-followups.md`.

**Working directory for every command below:** `engine/` (the package root with `pyproject.toml`). Paths in **Files:** blocks are relative to the repository root.

## Global Constraints

- Python `>=3.12`; `uv` for everything (`uv run pytest`, `uv run ruff ...`). Dependencies stay exactly those in `engine/pyproject.toml`; no `jsonschema`, no `cssselect`, no HTML-to-PDF.
- `pytest` runs with `--cov=corelata --cov-branch --cov-fail-under=95` and `filterwarnings = error`; every task leaves the whole suite green and coverage at or above 95%. `uv run ruff check .` and `uv run ruff format --check .` clean (line length 100, rules E F I B UP SIM).
- Renderers are pure functions of `Report` + `ResolvedPack` + `list[Source]` (+ open findings, + an optional reference path for DOCX): no clock, no randomness, no network, no file writes. Two calls with the same inputs give byte-identical output.
- Rendered HTML is self-contained: no `<link>`, `<script src>`, `@import`, `url(` or `http(s)://` anywhere in the output. The customer opens it on an air-gapped network.
- Production modules never import `corelata.testing` (the single sanctioned exception is `cli.py` importing `corelata.testing.fake_openai` for the `fake-openai` subcommand). Scenario running lives in `corelata/scenarios.py`, a production module, because `corelata bench` (M6) will call it.
- Trace invariants (spec §8.4) hold unchanged. Invariant 5 in its M2 form: every rendered export is derivable from `trace.json` alone — `corelata report` proves it.
- Section copy, verbatim: "Key judgments", "Scope note", "Sources", "Alternatives considered", "Gaps and indicators"; appendix heading "Audit findings open at delivery". Numbered style prefixes `N. `.
- Every intentional change to a module copied from Coglossa is recorded in `docs/m2-followups.md` under **Divergences from Coglossa** (none are expected in M2; record it if one happens).
- Exit codes are unchanged: 0 completed clean, 3 findings open, 4 gate rejected, 1 failed, 2 usage or config error, 130 interrupted. New subcommands use 0 / 1 / 2 only.
- Commits: conventional prefix (`feat:`, `refactor:`, `test:`, `docs:`, `fix:`), one task per commit unless a step says otherwise, ending with the attribution lines the session supplies.

## Review Focus

1. Report text containing `<`, `&`, `"` or a `<script>` tag — HTML must escape it, Markdown and DOCX must keep it literal. (Tests in Task 2 and Task 4.)
2. A profile `docx_reference` that is missing or is not a `.docx` — `pack validate` reports an error and `load_pack` raises `PackError` with the profile name and path; nothing fails later at render time. (Task 3.)
3. `corelata report` or `corelata trace` pointed at a directory without `trace.json`, at a corrupt file, or at a gate-rejected run with no report — exit 2 with a one-line message, never a traceback. (Task 6.)
4. A report whose alternatives, gaps or analysis list is empty — every renderer emits the heading with no items and no exception. (Task 1, 2, 4.)
5. A scenario file with an unknown key, or one expecting a rule id the pack does not have — a message naming the file and the key, not a `KeyError` inside `compare`. (Task 8.)
6. A single source unit larger than the digest chunk budget — the run fails fast at `ingesting`, naming the source and the unit's locator, before any model call. (Task 9.)

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/render/outline.py` (new) | Renderer-neutral block list: `Marking`, `Title`, `Heading`, `Para`, `Bullets`/`Item`; `build_outline()`; `source_line()`, `finding_line()` |
| `engine/corelata/render/markdown.py` (modify) | `render_markdown()` walks the outline; output unchanged from M1 |
| `engine/corelata/render/html.py` + `render/templates/report.html.j2` (new) | `render_html()`; autoescaped jinja2; inline CSS; `data-claim-ids` on paragraphs and items |
| `engine/corelata/render/docx.py` (new) | `render_docx()`; neutral default or profile reference; `RenderError` |
| `engine/corelata/render/__init__.py` (modify) | re-exports |
| `engine/corelata/standards/schema.py`, `loader.py` (modify) | `ResolvedPack.docx_reference_path` (excluded from dump/hash); reference resolution and existence check in `load_pack`; key-sorted `pack_hash` |
| `engine/corelata/trace.py` (new) | `TraceSummary`, `summarize()`, `claim_provenance()`, `draft_changes()`, `delivered_open_findings()`, `load_record()`, `format_summary()`, `TraceError` |
| `engine/corelata/cli.py` (modify) | `run` writes `report.html` and `report.docx`; new `report` and `trace` subcommands |
| `engine/corelata/scenarios.py` (new) + `engine/tests/fixtures/scenarios/*.yaml` | `Scenario` model, `load_scenario(s)`, `scenario_sources()`, `run_scenario()`, `compare()`, `ScenarioError` |
| `engine/corelata/ingest/units.py` (modify) | `source_from_paragraphs()` (production home for what `testing/sources.text_source` did) |
| `engine/corelata/stages/digest.py`, `pipeline.py`, `config.py` (modify) | `digest_chunk_tokens`; `chunk_units()`; per-unit oversize check; budget sanity check at ingesting |
| `engine/corelata/stages/write.py`, `config.py` (modify) | `writer_unit_budget_tokens`; `select_writer_units()` |
| `engine/tests/conftest.py` (modify) | shared `run` fixture (moved from `test_pipeline.py`) |
| `engine/tests/render/fixtures.py`, `tests/render/golden/*` (new) | shared fixture report; byte goldens for md and html |
| `schema/*.schema.json` (regenerate), `docs/trace-format.md` (new), `docs/m2-followups.md` (new), `README.md`, `engine/corelata.example.yaml`, spec §7.4/§11 (modify) | documentation |

---

### Task 1: Render outline, and Markdown on top of it

**Files:**
- Create: `engine/corelata/render/outline.py`
- Create: `engine/tests/render/fixtures.py`
- Create: `engine/tests/render/test_outline.py`
- Create: `engine/tests/render/golden/varna.md` (written by the first test run, then committed)
- Modify: `engine/corelata/render/markdown.py` (whole file)
- Modify: `engine/corelata/render/__init__.py`
- Keep green, unchanged: `engine/tests/render/test_markdown.py`

**Interfaces:**
- Consumes: `Report`, `Source`, `SourceKind`, `SourceEntry`, `Finding` from `corelata.schema`; `ResolvedPack` (`.template.section_order`, `.format.heading_style`) from `corelata.standards.schema`.
- Produces (used by Tasks 2 and 4):
  - `build_outline(report: Report, pack: ResolvedPack, sources: list[Source], *, open_findings: list[Finding] | None = None) -> list[Block]`
  - block dataclasses `Marking(text)`, `Title(text)`, `Heading(text, number: int | None)` with `.label`, `Para(text, claim_ids: tuple[str, ...])`, `Bullets(items: tuple[Item, ...], role: str)`, `Item(text, lead: str, claim_ids: tuple[str, ...])`; every block class has a `kind: ClassVar[str]` in {"marking", "title", "heading", "para", "bullets"}.
  - constants `SECTION_TITLES: dict[str, str]`, `APPENDIX_TITLE = "Audit findings open at delivery"`.
  - `render_markdown(...)` signature unchanged from M1.
  - test helpers in `tests/render/fixtures.py`: `PACK`, `NUMBERED`, `SOURCES`, `make_report(**metadata)`, `make_finding(recommendation=...)`, `empty_lists_report()`, and in `tests/render/test_outline.py`: `check_golden(name, text)`.

- [ ] **Step 1: Write the shared render fixture module**

Create `engine/tests/render/fixtures.py`:

```python
"""One fixture report, source list and finding shared by every renderer test."""

from corelata.schema import (
    Alternative,
    BlockKind,
    Claim,
    ClaimKind,
    Confidence,
    Finding,
    FindingOut,
    KeyJudgment,
    Paragraph,
    Report,
    ReportMetadata,
    Section,
    Source,
    SourceEntry,
    SourceKind,
    SourceUnit,
    Verdict,
)
from corelata.standards.loader import load_pack

PACK = load_pack("icd203-base")
NUMBERED = PACK.model_copy(
    update={"format": PACK.format.model_copy(update={"heading_style": "numbered"})}
)

SOURCES = [
    Source(
        id="src1",
        kind=SourceKind.FILE,
        name="a.txt",
        format="txt",
        sha256="abcdef0123456789" * 4,
        units=[
            SourceUnit(id="u1", text="Grew 40 percent.", locator="para 1", kind=BlockKind.PARAGRAPH)
        ],
    ),
    Source(
        id="src2",
        kind=SourceKind.COGLOSSA_EXPORT,
        name="b.json",
        format="coglossa",
        sha256="ff" * 32,
        provenance={"coglossa_run_id": "run-42"},
        units=[],
    ),
]


def make_report(**metadata) -> Report:
    return Report(
        title="Varna port",
        handling_marking="UNCLASSIFIED",
        key_judgments=[
            KeyJudgment(text="Capacity grew.", confidence=Confidence.MODERATE, claim_ids=["c1"])
        ],
        scope_note="Two sources.",
        sources=[
            SourceEntry(
                source_id="src1", descriptor="open-source report", reliability_note="Current."
            ),
            SourceEntry(
                source_id="src2", descriptor="translated document", reliability_note="Tier B."
            ),
        ],
        analysis=[
            Section(
                heading="Capacity",
                paragraphs=[Paragraph(text="Grew 40 percent.", claim_ids=["c1"])],
            )
        ],
        alternatives=[Alternative(hypothesis="Flat.", assessment="Unlikely.")],
        gaps_and_indicators=["Customs data."],
        claims=[Claim(id="c1", text="Grew.", kind=ClaimKind.FACT, evidence=["src1/u1"])],
        metadata=ReportMetadata(pack_name="icd203-base", pack_hash="h", **metadata),
    )


def make_finding(recommendation: str = "Cite or remove.") -> Finding:
    return Finding(
        **FindingOut(
            rule_id="icd203.tc.8",
            verdict=Verdict.FAIL,
            evidence="c9 has no evidence",
            recommendation=recommendation,
        ).model_dump(),
        severity="blocking",
        route_to="writer",
        iteration=2,
    )


def empty_lists_report() -> Report:
    """Headings with nothing under them must not break any renderer (Review Focus 4)."""
    r = make_report()
    return r.model_copy(update={"analysis": [], "alternatives": [], "gaps_and_indicators": []})
```

- [ ] **Step 2: Write the failing outline tests**

Create `engine/tests/render/test_outline.py`:

```python
from pathlib import Path

from corelata.render.markdown import render_markdown
from corelata.render.outline import (
    APPENDIX_TITLE,
    Bullets,
    Heading,
    Item,
    Marking,
    Para,
    Title,
    build_outline,
    finding_line,
    source_line,
)
from corelata.schema import SourceEntry
from tests.render.fixtures import (
    NUMBERED,
    PACK,
    SOURCES,
    empty_lists_report,
    make_finding,
    make_report,
)

GOLDEN = Path(__file__).parent / "golden"


def check_golden(name: str, text: str) -> None:
    """First run writes the golden; review the file, then commit it. Later runs compare."""
    path = GOLDEN / name
    if not path.is_file():
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


def test_outline_follows_template_order_with_marking_top_and_bottom():
    blocks = build_outline(make_report(), PACK, SOURCES)
    assert blocks[0] == Marking("UNCLASSIFIED") and blocks[-1] == Marking("UNCLASSIFIED")
    assert [b.kind for b in blocks] == [
        "marking",
        "title",
        "heading",
        "bullets",
        "heading",
        "para",
        "heading",
        "bullets",
        "heading",
        "para",
        "heading",
        "bullets",
        "heading",
        "bullets",
        "marking",
    ]
    assert blocks[1] == Title("Varna port")
    headings = [b for b in blocks if isinstance(b, Heading)]
    assert [h.label for h in headings] == [
        "Key judgments",
        "Scope note",
        "Sources",
        "Capacity",
        "Alternatives considered",
        "Gaps and indicators",
    ]
    assert all(h.number is None for h in headings)
    kj = blocks[3]
    assert isinstance(kj, Bullets) and kj.role == "key_judgments"
    assert kj.items == (Item("Capacity grew.", "Moderate confidence.", ("c1",)),)
    assert blocks[5] == Para("Two sources.")
    assert blocks[9] == Para("Grew 40 percent.", ("c1",))
    alts = blocks[11]
    assert alts.items == (Item("Unlikely.", "Flat.", ()),) and alts.role == "alternatives"
    assert blocks[13].items == (Item("Customs data."),) and blocks[13].role == "gaps"


def test_outline_numbers_headings_and_appends_open_findings():
    blocks = build_outline(
        make_report(), NUMBERED, SOURCES, open_findings=[make_finding(), make_finding("")]
    )
    labels = [b.label for b in blocks if isinstance(b, Heading)]
    assert labels[:2] == ["1. Key judgments", "2. Scope note"]
    assert labels[3] == "4. Capacity"
    assert labels[-1] == APPENDIX_TITLE  # the appendix is never numbered
    findings = blocks[-2]
    assert isinstance(findings, Bullets) and findings.role == "findings"
    assert findings.items == (
        Item("icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."),
        Item("icd203.tc.8 (blocking): c9 has no evidence"),
    )
    assert blocks[-1] == Marking("UNCLASSIFIED")


def test_outline_without_open_findings_has_no_appendix():
    blocks = build_outline(make_report(), PACK, SOURCES, open_findings=[])
    assert all(not (isinstance(b, Heading) and b.text == APPENDIX_TITLE) for b in blocks)


def test_source_lines():
    entry = SourceEntry(source_id="src1", descriptor="open-source report", reliability_note="Now.")
    assert source_line(entry, SOURCES[0]) == "a.txt — open-source report; Now. (sha256 abcdef01)"
    cog = SourceEntry(source_id="src2", descriptor="translated document")
    assert (
        source_line(cog, SOURCES[1])
        == "b.json — translated document (sha256 ffffffff; Coglossa run run-42)"
    )
    missing = SourceEntry(source_id="src9", descriptor="social media post")
    assert source_line(missing, None) == "src9 — social media post (sha256 unknown)"
    no_run = SOURCES[1].model_copy(update={"provenance": {}})
    assert source_line(cog, no_run).endswith("Coglossa run unknown)")


def test_finding_line_with_and_without_recommendation():
    assert finding_line(make_finding()) == (
        "icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."
    )
    assert finding_line(make_finding("")) == "icd203.tc.8 (blocking): c9 has no evidence"


def test_empty_lists_keep_headings_with_no_items():
    blocks = build_outline(empty_lists_report(), PACK, SOURCES)
    labels = [b.label for b in blocks if isinstance(b, Heading)]
    assert labels == [
        "Key judgments",
        "Scope note",
        "Sources",
        "Alternatives considered",
        "Gaps and indicators",
    ]
    empties = [b for b in blocks if isinstance(b, Bullets) and b.items == ()]
    assert [b.role for b in empties] == ["alternatives", "gaps"]


def test_unknown_section_names_are_ignored():
    pack = PACK.model_copy(
        update={
            "template": PACK.template.model_copy(
                update={"section_order": ["title", "annex_z", "key_judgments"]}
            )
        }
    )
    blocks = build_outline(make_report(), pack, SOURCES)
    assert [b.kind for b in blocks] == ["marking", "title", "heading", "bullets", "marking"]


def test_markdown_golden_and_determinism():
    md = render_markdown(
        make_report(status="findings_open", open_findings=["icd203.tc.8@2"]),
        NUMBERED,
        SOURCES,
        with_claim_ids=True,
        open_findings=[make_finding()],
    )
    check_golden("varna.md", md)
    assert render_markdown(make_report(), PACK, SOURCES) == render_markdown(
        make_report(), PACK, SOURCES
    )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/render/test_outline.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.render.outline'`

- [ ] **Step 4: Write the outline module**

Create `engine/corelata/render/outline.py`:

```python
"""A renderer-neutral outline of a report (spec §9): the one place that knows section order,
heading numbering, how a source line reads and how the open-findings appendix is laid out.
Markdown, HTML and DOCX walk this outline, so the three outputs cannot drift apart."""

from dataclasses import dataclass
from typing import ClassVar

from corelata.schema import Finding, Report, Source, SourceEntry, SourceKind
from corelata.standards.schema import ResolvedPack

SECTION_TITLES = {
    "key_judgments": "Key judgments",
    "scope_note": "Scope note",
    "sources": "Sources",
    "alternatives": "Alternatives considered",
    "gaps_and_indicators": "Gaps and indicators",
}
APPENDIX_TITLE = "Audit findings open at delivery"


@dataclass(frozen=True)
class Marking:
    kind: ClassVar[str] = "marking"
    text: str


@dataclass(frozen=True)
class Title:
    kind: ClassVar[str] = "title"
    text: str


@dataclass(frozen=True)
class Heading:
    kind: ClassVar[str] = "heading"
    text: str
    number: int | None = None

    @property
    def label(self) -> str:
        return f"{self.number}. {self.text}" if self.number is not None else self.text


@dataclass(frozen=True)
class Para:
    kind: ClassVar[str] = "para"
    text: str
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Item:
    text: str
    lead: str = ""  # bold lead-in: "Moderate confidence." or an alternative's hypothesis
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Bullets:
    kind: ClassVar[str] = "bullets"
    items: tuple[Item, ...]
    role: str = "list"  # key_judgments | sources | alternatives | gaps | findings


Block = Marking | Title | Heading | Para | Bullets


def source_line(entry: SourceEntry, source: Source | None) -> str:
    name = source.name if source else entry.source_id
    extra = f"sha256 {source.sha256[:8]}" if source else "sha256 unknown"
    if source and source.kind is SourceKind.COGLOSSA_EXPORT:
        extra += f"; Coglossa run {source.provenance.get('coglossa_run_id', 'unknown')}"
    note = f"; {entry.reliability_note}" if entry.reliability_note else ""
    return f"{name} — {entry.descriptor}{note} ({extra})"


def finding_line(f: Finding) -> str:
    rec = f" — {f.recommendation}" if f.recommendation else ""
    return f"{f.rule_id} ({f.severity}): {f.evidence}{rec}"


def build_outline(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    open_findings: list[Finding] | None = None,
) -> list[Block]:
    """Blocks in reading order. `handling_marking` in the template is honoured by the marking
    blocks at top and bottom; a section name this version does not know is skipped."""
    numbered = pack.format.heading_style == "numbered"
    by_id = {s.id: s for s in sources}
    out: list[Block] = [Marking(report.handling_marking)]
    counter = 0

    def heading(text: str) -> Heading:
        nonlocal counter
        counter += 1
        return Heading(text, counter if numbered else None)

    for section in pack.template.section_order:
        if section == "title":
            out.append(Title(report.title))
        elif section == "key_judgments":
            out.append(heading(SECTION_TITLES[section]))
            items = tuple(
                Item(kj.text, f"{kj.confidence.value.capitalize()} confidence.", tuple(kj.claim_ids))
                for kj in report.key_judgments
            )
            out.append(Bullets(items, "key_judgments"))
        elif section == "scope_note":
            out.append(heading(SECTION_TITLES[section]))
            out.append(Para(report.scope_note))
        elif section == "sources":
            out.append(heading(SECTION_TITLES[section]))
            items = tuple(Item(source_line(e, by_id.get(e.source_id))) for e in report.sources)
            out.append(Bullets(items, "sources"))
        elif section == "analysis":
            for sec in report.analysis:
                out.append(heading(sec.heading))
                out.extend(Para(p.text, tuple(p.claim_ids)) for p in sec.paragraphs)
        elif section == "alternatives":
            out.append(heading(SECTION_TITLES[section]))
            items = tuple(
                Item(a.assessment, a.hypothesis, tuple(a.claim_ids)) for a in report.alternatives
            )
            out.append(Bullets(items, "alternatives"))
        elif section == "gaps_and_indicators":
            out.append(heading(SECTION_TITLES[section]))
            out.append(Bullets(tuple(Item(g) for g in report.gaps_and_indicators), "gaps"))
    if open_findings:
        out.append(Heading(APPENDIX_TITLE))
        out.append(Bullets(tuple(Item(finding_line(f)) for f in open_findings), "findings"))
    out.append(Marking(report.handling_marking))
    return out
```

- [ ] **Step 5: Rewrite the Markdown renderer on the outline**

Replace the whole of `engine/corelata/render/markdown.py` with:

```python
"""Markdown render of a Report: a pure function of report, resolved pack and sources (spec §9).
The layout comes from `render.outline`; this module only knows Markdown syntax."""

from corelata.render.outline import Bullets, Heading, Marking, Para, Title, build_outline
from corelata.schema import Finding, Report, Source
from corelata.standards.schema import ResolvedPack


def _ids(claim_ids: tuple[str, ...], on: bool) -> str:
    return f" ^[{', '.join(claim_ids)}]" if on and claim_ids else ""


def render_markdown(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    with_claim_ids: bool = False,
    open_findings: list[Finding] | None = None,
) -> str:
    out: list[str] = []
    for block in build_outline(report, pack, sources, open_findings=open_findings):
        match block:
            case Marking(text):
                out += [text, ""]
            case Title(text):
                out += [f"# {text}", ""]
            case Heading():
                out += [f"## {block.label}", ""]
            case Para(text, claim_ids):
                out += [f"{text}{_ids(claim_ids, with_claim_ids)}", ""]
            case Bullets(items):
                for item in items:
                    lead = f"**{item.lead}** " if item.lead else ""
                    out.append(f"- {lead}{item.text}{_ids(item.claim_ids, with_claim_ids)}")
                out.append("")
    return "\n".join(out).rstrip() + "\n"
```

Replace `engine/corelata/render/__init__.py` with:

```python
"""Renderers: pure functions of Report + resolved pack + sources (spec §9)."""

from corelata.render.markdown import render_markdown
from corelata.render.outline import build_outline

__all__ = ["build_outline", "render_markdown"]
```

(Tasks 2 and 4 add `render_html` and `render_docx` here.)

- [ ] **Step 6: Run the render suite**

Run: `uv run pytest tests/render -q --no-cov`
Expected: all pass, including the unchanged `tests/render/test_markdown.py`, whose two tests pin M1's exact output. The golden `tests/render/golden/varna.md` is written on this first run. Open it and confirm it reads, in order: `UNCLASSIFIED`, `# Varna port`, `## 1. Key judgments`, `- **Moderate confidence.** Capacity grew. ^[c1]`, `## 2. Scope note`, `Two sources.`, `## 3. Sources`, the two source lines, `## 4. Capacity`, `Grew 40 percent. ^[c1]`, `## 5. Alternatives considered`, `- **Flat.** Unlikely.`, `## 6. Gaps and indicators`, `- Customs data.`, `## Audit findings open at delivery`, `- icd203.tc.8 (blocking): c9 has no evidence — Cite or remove.`, `UNCLASSIFIED`. If anything differs, the renderer is wrong, not the golden: fix the code, delete the golden, rerun.

- [ ] **Step 7: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all tests pass; coverage ≥ 95%.

- [ ] **Step 8: Commit**

Stage `corelata/render/` and `tests/render/` (including the new golden) and commit with message `refactor(render): renderer-neutral outline; Markdown walks it`.

### Task 2: HTML renderer

**Files:**
- Create: `engine/corelata/render/html.py`
- Create: `engine/corelata/render/templates/report.html.j2`
- Create: `engine/tests/render/test_html.py`
- Create: `engine/tests/render/golden/varna.html` (written by the first test run, then committed)
- Modify: `engine/corelata/render/__init__.py` (add `render_html`)
- Modify: `engine/pyproject.toml` (`[tool.hatch.build.targets.wheel] artifacts` gains `"corelata/render/templates/**/*.j2"`)

**Interfaces:**
- Consumes: `build_outline`, block classes and `APPENDIX_TITLE` from Task 1.
- Produces: `render_html(report: Report, pack: ResolvedPack, sources: list[Source], *, with_claim_ids: bool = False, open_findings: list[Finding] | None = None) -> str`. Output contract (M4b's review screen relies on it): every `<p>` inside `<article>` that comes from a report paragraph and every `<li>` carries `data-claim-ids="c1 c2"` (space-separated, possibly empty); visible `<sup class="claim-ids">c1, c2</sup>` only when `with_claim_ids`; `<ul class="{role}">` per bullet list; `<section class="appendix">` around the open-findings appendix; `<p class="marking">` first and `<p class="marking bottom">` last inside `<article>`; `<footer class="meta">` with run id, pack name and hash, profile, status and iteration.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/render/test_html.py`:

```python
import re

from lxml import html as lxml_html

from corelata.render.html import render_html
from tests.render.fixtures import (
    NUMBERED,
    PACK,
    SOURCES,
    empty_lists_report,
    make_finding,
    make_report,
)
from tests.render.test_outline import check_golden


def _doc(text: str):
    return lxml_html.fromstring(text)


def test_html_structure_and_provenance_attributes():
    out = render_html(make_report(run_id="r1", status="clean"), PACK, SOURCES)
    assert out.startswith("<!DOCTYPE html>")
    doc = _doc(out)
    assert doc.xpath("//title/text()") == ["Varna port"]
    assert doc.xpath("//h1/text()") == ["Varna port"]
    assert doc.xpath("//article/section/h2/text()") == [
        "Key judgments",
        "Scope note",
        "Sources",
        "Capacity",
        "Alternatives considered",
        "Gaps and indicators",
    ]
    markings = doc.xpath("//article/p[contains(@class, 'marking')]")
    assert [m.text for m in markings] == ["UNCLASSIFIED", "UNCLASSIFIED"]
    assert markings[0].get("class") == "marking" and markings[1].get("class") == "marking bottom"
    assert doc.xpath("//ul[@class='key_judgments']/li/@data-claim-ids") == ["c1"]
    assert doc.xpath("//ul[@class='key_judgments']/li/strong/text()") == ["Moderate confidence."]
    assert doc.xpath("//section[h2='Capacity']/p/@data-claim-ids") == ["c1"]
    assert doc.xpath("//section[h2='Scope note']/p/@data-claim-ids") == [""]
    assert doc.xpath("//ul[@class='sources']/li/text()") == [
        "a.txt — open-source report; Current. (sha256 abcdef01)",
        "b.json — translated document; Tier B. (sha256 ffffffff; Coglossa run run-42)",
    ]
    assert doc.xpath("//sup") == []
    assert doc.xpath("//section[@class='appendix']") == []
    footer = doc.xpath("//footer[@class='meta']")[0].text_content()
    assert "run r1" in footer and "icd203-base" in footer and "clean" in footer


def test_html_claim_ids_numbering_and_appendix():
    out = render_html(
        make_report(status="findings_open", open_findings=["icd203.tc.8@2"]),
        NUMBERED,
        SOURCES,
        with_claim_ids=True,
        open_findings=[make_finding()],
    )
    doc = _doc(out)
    h2 = doc.xpath("//h2/text()")
    assert h2[0] == "1. Key judgments" and h2[3] == "4. Capacity"
    assert h2[-1] == "Audit findings open at delivery"
    assert doc.xpath("//sup[@class='claim-ids']/text()") == ["c1", "c1"]
    assert doc.xpath("//section[@class='appendix']/ul[@class='findings']/li/text()") == [
        "icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."
    ]
    check_golden("varna.html", out)


def test_html_is_self_contained():
    out = render_html(make_report(), PACK, SOURCES)
    assert not re.search(r"https?://|<link|<script|@import|url\(", out)
    assert "<style>" in out


def test_html_escapes_report_text():
    nasty = make_report().model_copy(
        update={"title": '<script>alert(1)</script> & "co"', "scope_note": "a < b & c"}
    )
    out = render_html(nasty, PACK, SOURCES)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; " in out
    assert "a &lt; b &amp; c" in out
    doc = _doc(out)
    assert doc.xpath("//h1/text()") == ['<script>alert(1)</script> & "co"']


def test_html_empty_lists_keep_headings():
    doc = _doc(render_html(empty_lists_report(), PACK, SOURCES))
    assert doc.xpath("//ul[@class='alternatives']") and doc.xpath("//ul[@class='alternatives']/li") == []
    assert doc.xpath("//ul[@class='gaps']/li") == []
    assert "Capacity" not in doc.xpath("//h2/text()")


def test_html_is_deterministic():
    a = render_html(make_report(), PACK, SOURCES)
    assert a == render_html(make_report(), PACK, SOURCES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/render/test_html.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.render.html'`

- [ ] **Step 3: Write the template**

Create `engine/corelata/render/templates/report.html.j2`:

```jinja
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ report.title }}</title>
<style>
:root { color-scheme: light dark; }
body.corelata-report { font-family: Georgia, "Times New Roman", serif; line-height: 1.5; max-width: 46rem; margin: 0 auto; padding: 1rem 1.25rem; }
.marking { text-align: center; font-family: system-ui, sans-serif; font-weight: 700; letter-spacing: .08em; border: 1px solid currentColor; padding: .25rem; margin: 0 0 1.5rem; }
.marking.bottom { margin: 2rem 0 0; }
h1 { font-size: 1.6rem; margin: 0 0 1rem; }
h2 { font-size: 1.15rem; margin: 1.5rem 0 .5rem; border-bottom: 1px solid rgba(128,128,128,.4); padding-bottom: .15rem; }
ul { padding-left: 1.25rem; }
li { margin: .3rem 0; }
sup.claim-ids { font-family: system-ui, sans-serif; font-size: .7em; margin-left: .15em; opacity: .7; }
section.appendix { border-top: 2px solid currentColor; margin-top: 2rem; padding-top: .5rem; }
footer.meta { font-family: system-ui, sans-serif; font-size: .8rem; opacity: .7; margin-top: 2rem; }
</style>
</head>
<body class="corelata-report">
{% macro ids(claim_ids) -%}
{% if with_claim_ids and claim_ids %}<sup class="claim-ids">{{ claim_ids | join(", ") }}</sup>{% endif %}
{%- endmacro %}
<article>
{% set ns = namespace(open=false) %}
{% for b in blocks %}
{% if b.kind == "marking" %}
{% if ns.open %}
</section>
{% set ns.open = false %}
{% endif %}
{% if loop.last %}
<p class="marking bottom">{{ b.text }}</p>
{% else %}
<p class="marking">{{ b.text }}</p>
{% endif %}
{% elif b.kind == "title" %}
<h1>{{ b.text }}</h1>
{% elif b.kind == "heading" %}
{% if ns.open %}
</section>
{% endif %}
{% set ns.open = true %}
{% if b.text == appendix_title %}
<section class="appendix">
{% else %}
<section>
{% endif %}
<h2>{{ b.label }}</h2>
{% elif b.kind == "para" %}
<p data-claim-ids="{{ b.claim_ids | join(' ') }}">{{ b.text }}{{ ids(b.claim_ids) }}</p>
{% elif b.kind == "bullets" %}
<ul class="{{ b.role }}">
{% for it in b.items %}
<li data-claim-ids="{{ it.claim_ids | join(' ') }}">{% if it.lead %}<strong>{{ it.lead }}</strong> {% endif %}{{ it.text }}{{ ids(it.claim_ids) }}</li>
{% endfor %}
</ul>
{% endif %}
{% endfor %}
</article>
<footer class="meta">Corelata run {{ meta.run_id or "-" }} · pack {{ meta.pack_name }} {{ meta.pack_hash }}{% if meta.profile %} · profile {{ meta.profile }}{% endif %} · status {{ meta.status.value if meta.status else "unknown" }} · iteration {{ meta.iteration }}</footer>
</body>
</html>
```

Notes for the implementer: the appendix test expects `//section[@class='appendix']/ul[@class='findings']/li/text()` to be exactly the finding line, so the `<li>` for an item without a lead must contain no leading space (the `{% if it.lead %}` block above produces none). Macro output and literal template text are not re-escaped; `b.text`, `it.lead`, `it.text`, `report.title` and `meta.*` are escaped by autoescape.

- [ ] **Step 4: Write the module**

Create `engine/corelata/render/html.py`:

```python
"""HTML render (spec §9): one self-contained file with inline CSS, nothing fetched from anywhere,
safe to open on an air-gapped network. Paragraphs and list items carry data-claim-ids so the
review screen can highlight provenance; the visible superscripts appear only on request."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from corelata.render.outline import APPENDIX_TITLE, build_outline
from corelata.schema import Finding, Report, Source
from corelata.standards.schema import ResolvedPack

_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render_html(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    with_claim_ids: bool = False,
    open_findings: list[Finding] | None = None,
) -> str:
    blocks = build_outline(report, pack, sources, open_findings=open_findings)
    return _ENV.get_template("report.html.j2").render(
        report=report,
        meta=report.metadata,
        blocks=blocks,
        with_claim_ids=with_claim_ids,
        appendix_title=APPENDIX_TITLE,
    )
```

Add `from corelata.render.html import render_html` and `"render_html"` to `engine/corelata/render/__init__.py`.

In `engine/pyproject.toml`, change the `artifacts` line to:

```toml
artifacts = ["corelata/standards/packs/**/*.yaml", "corelata/prompts/templates/**/*.j2", "corelata/render/templates/**/*.j2", "corelata/ingest/vendor/*.json"]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/render/test_html.py -q --no-cov`
Expected: 6 passed. The golden `tests/render/golden/varna.html` is written on this run; open it and read it top to bottom once: doctype, `<title>Varna port</title>`, a `<style>` block, `<article>` with the marking paragraph, `<h1>`, six numbered `<section>`s, an appendix section, the bottom marking, the footer. If the structure tests pass but the file looks wrong (stray blank lines are fine; missing sections are not), fix the template, delete the golden, rerun.

- [ ] **Step 6: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 7: Commit**

Stage `corelata/render/`, `tests/render/`, `pyproject.toml` and commit with message `feat(render): self-contained HTML render with provenance attributes`.

### Task 3: Pack loader — resolve `docx_reference`, key-sorted `pack_hash`

**Files:**
- Modify: `engine/corelata/standards/schema.py` (`ResolvedPack`)
- Modify: `engine/corelata/standards/loader.py` (`load_pack`, `pack_hash`, imports)
- Modify: `engine/tests/standards/test_loader.py` (append tests)
- Keep green: `engine/tests/standards/test_builtin_pack.py` (golden JSON must not change), `tests/standards/test_resolution_properties.py`

**Interfaces:**
- Consumes: `Profile.format.docx_reference: Path | None` (spec §6.5), `RawPack.path`.
- Produces: `ResolvedPack.docx_reference_path: Path | None` — absolute path of the profile's reference document, **excluded from `model_dump`, `model_dump_json`, the snapshot and the hash** (`Field(None, exclude=True)`); `None` when the profile names none or when the pack was rebuilt from a snapshot. Task 4 reads it; Task 6 passes it to `render_docx`. `pack_hash(pack)` now hashes a key-sorted compact JSON dump (16 hex chars as before).

Why excluded: the snapshot and hash must be identical on every machine that installs the same pack (spec §6.6), so no absolute path may enter them. M3 will store the reference bytes alongside the run; until then `corelata report` from a run directory renders DOCX with the neutral template unless the user passes `--docx-reference` (Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/standards/test_loader.py` (the file already imports `Path`, `pytest`, `yaml`, `PackError`, `load_pack`, `pack_hash`, `validate_pack`, and defines `RULE`, `TEMPLATE`, `LEXICON`, `write_pack`):

```python
from docx import Document

from corelata.standards.schema import ResolvedPack


def _profile_with_reference(ref: str) -> dict:
    return {"name": "east", "extends": "base", "format": {"docx_reference": ref}}


def test_docx_reference_resolves_relative_to_the_profile_pack(tmp_path):
    pack = write_pack(tmp_path, "base", rules=[RULE], profiles={"east": _profile_with_reference("templates/east.docx")})
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    resolved = load_pack("base", packs_dir=tmp_path, profile="east")
    assert resolved.docx_reference_path == (pack / "templates" / "east.docx").resolve()
    assert resolved.format.docx_reference == Path("templates/east.docx")
    dumped = resolved.model_dump(mode="json")
    assert "docx_reference_path" not in dumped
    assert "docx_reference_path" not in resolved.model_dump_json()
    assert ResolvedPack.model_validate(dumped).docx_reference_path is None
    without = load_pack("base", packs_dir=tmp_path)
    assert without.docx_reference_path is None


def test_docx_reference_absolute_path_is_kept(tmp_path):
    ref = tmp_path / "elsewhere.docx"
    Document().save(str(ref))
    write_pack(tmp_path, "base", rules=[RULE], profiles={"east": _profile_with_reference(str(ref))})
    assert load_pack("base", packs_dir=tmp_path, profile="east").docx_reference_path == ref.resolve()


@pytest.mark.parametrize(
    ("ref", "prepare"),
    [
        ("templates/missing.docx", lambda pack: None),
        ("templates/notes.txt", lambda pack: (pack / "templates" / "notes.txt").write_text("x")),
    ],
)
def test_docx_reference_must_be_an_existing_docx(tmp_path, ref, prepare):
    pack = write_pack(tmp_path, "base", rules=[RULE], profiles={"east": _profile_with_reference(ref)})
    (pack / "templates").mkdir()
    prepare(pack)
    with pytest.raises(PackError, match=f"profile 'east': docx_reference '{ref}' is not an existing .docx file"):
        load_pack("base", packs_dir=tmp_path, profile="east")
    issues = validate_pack("base", packs_dir=tmp_path)
    assert [i.level for i in issues] == ["error"] and "docx_reference" in issues[0].message


def test_pack_hash_ignores_dict_key_order_and_reference_path(tmp_path):
    pack = write_pack(tmp_path, "base", rules=[RULE])
    a = load_pack("base", packs_dir=tmp_path)
    flipped = dict(reversed(list(LEXICON["confidence_definitions"].items())))
    (pack / "lexicon.yaml").write_text(
        yaml.safe_dump({**LEXICON, "confidence_definitions": flipped}), encoding="utf-8"
    )
    b = load_pack("base", packs_dir=tmp_path)
    assert list(a.lexicon.confidence_definitions) != list(b.lexicon.confidence_definitions)
    assert pack_hash(a) == pack_hash(b) and len(pack_hash(a)) == 16
    c = a.model_copy(update={"docx_reference_path": tmp_path / "any.docx"})
    assert pack_hash(c) == pack_hash(a)
```

Put the two new imports (`from docx import Document`, `from corelata.standards.schema import ResolvedPack`) into the file's top import block; ruff will tell you if they are misplaced.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/standards/test_loader.py -q --no-cov -k "docx_reference or key_order"`
Expected: FAIL — `docx_reference_path` attribute missing / no `PackError` raised / hashes differ.

- [ ] **Step 3: Add the excluded field to `ResolvedPack`**

In `engine/corelata/standards/schema.py`, inside `class ResolvedPack(BaseModel)`, after `format: ProfileFormat` add:

```python
    # Where the profile's reference document lives on this machine. Excluded from every dump so
    # the snapshot and pack_hash stay identical across installs (spec §6.6); None when rebuilt
    # from a snapshot. Set by the loader, read by the DOCX renderer.
    docx_reference_path: Path | None = Field(None, exclude=True)
```

(`Path` and `Field` are already imported in that file.)

- [ ] **Step 4: Resolve and check the reference in `load_pack`; sort keys in `pack_hash`**

In `engine/corelata/standards/loader.py`:

Add `import json` to the imports.

Replace `load_pack` with:

```python
def load_pack(
    name: str,
    *,
    packs_dir: Path | None = None,
    profile: str | None = None,
    allow_draft: bool = False,
) -> ResolvedPack:
    chain = _chain(name, packs_dir)
    chosen: Profile | None = None
    owner: RawPack | None = None
    if profile is not None:
        for pack in reversed(chain):
            if profile in pack.profiles:
                chosen, owner = pack.profiles[profile], pack
                break
        if chosen is None:
            raise PackError(f"profile '{profile}' not found in pack '{name}' or its ancestors")
        if chosen.draft and not allow_draft:
            raise PackError(
                f"profile '{profile}' is a draft (draft: true); review it and remove the flag"
            )
    resolved = resolve(chain, chosen)
    if chosen is not None and owner is not None:
        resolved.docx_reference_path = _docx_reference_path(chosen, owner)
    return resolved


def _docx_reference_path(profile: Profile, owner: RawPack) -> Path | None:
    """The profile's reference document, absolute, verified to exist (Review Focus 2)."""
    ref = profile.format.docx_reference
    if ref is None:
        return None
    base = owner.path if owner.path is not None else Path.cwd()
    path = (ref if ref.is_absolute() else base / ref).resolve()
    if path.suffix.lower() != ".docx" or not path.is_file():
        raise PackError(
            f"profile '{profile.name}': docx_reference '{ref}' is not an existing .docx file"
        )
    return path
```

Replace `pack_hash` with:

```python
def pack_hash(pack: ResolvedPack) -> str:
    """SHA-256 (first 16 hex chars) of a key-sorted compact JSON dump: independent of YAML key
    order and of anything excluded from the dump, so the same pack hashes alike everywhere."""
    data = pack.model_dump(mode="json")
    dump = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/standards -q --no-cov`
Expected: all pass, including `test_builtin_pack_matches_golden` (the golden compares `model_dump_json()`, which the excluded field does not touch) and the hypothesis property tests.

- [ ] **Step 6: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 7: Commit**

Stage `corelata/standards/` and `tests/standards/` and commit with message `feat(standards): resolve profile docx_reference; key-sorted pack_hash`.

### Task 4: DOCX renderer

**Files:**
- Create: `engine/corelata/render/docx.py`
- Create: `engine/tests/render/test_docx.py`
- Modify: `engine/corelata/render/__init__.py` (add `render_docx`, `RenderError`)

**Interfaces:**
- Consumes: `build_outline` and block classes (Task 1); `ResolvedPack.docx_reference_path` (Task 3) is *not* read here — the caller passes `reference` explicitly so the renderer stays a pure function of its arguments.
- Produces: `render_docx(report: Report, pack: ResolvedPack, sources: list[Source], *, with_claim_ids: bool = False, open_findings: list[Finding] | None = None, reference: Path | None = None) -> bytes` and `class RenderError(ValueError)`. Structure contract: title → style `Heading 1`; every section heading and the appendix heading → `Heading 2`; paragraphs → `Normal`; bullet items → `List Bullet` with a bold lead run; claim ids as a trailing superscript run `" c1, c2"` only when `with_claim_ids`; handling marking centred and bold in the header and footer of every section; when a style is missing from the reference, headings fall back to a bold `Normal` run and bullets to a `Normal` paragraph starting with `"• "`; a reference's own body content is removed, its styles, headers/footers, numbering and page setup are kept.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/render/test_docx.py`:

```python
import io
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Pt

from corelata.render.docx import RenderError, render_docx
from tests.render.fixtures import (
    NUMBERED,
    PACK,
    SOURCES,
    empty_lists_report,
    make_finding,
    make_report,
)

H2 = [
    "Key judgments",
    "Scope note",
    "Sources",
    "Capacity",
    "Alternatives considered",
    "Gaps and indicators",
]


def _open(data: bytes):
    assert data[:2] == b"PK"
    return Document(io.BytesIO(data))


def _texts(doc, style: str) -> list[str]:
    return [p.text for p in doc.paragraphs if p.style.name == style]


def test_docx_structure_with_neutral_template():
    doc = _open(render_docx(make_report(), PACK, SOURCES))
    assert _texts(doc, "Heading 1") == ["Varna port"]
    assert _texts(doc, "Heading 2") == H2
    assert doc.paragraphs[0].style.name == "Heading 1"
    bullets = [p for p in doc.paragraphs if p.style.name == "List Bullet"]
    assert bullets[0].runs[0].text == "Moderate confidence. " and bullets[0].runs[0].bold
    assert bullets[0].text == "Moderate confidence. Capacity grew."
    assert [p.text for p in bullets[1:3]] == [
        "a.txt — open-source report; Current. (sha256 abcdef01)",
        "b.json — translated document; Tier B. (sha256 ffffffff; Coglossa run run-42)",
    ]
    assert "Grew 40 percent." in _texts(doc, "Normal")
    assert not any(r.font.superscript for p in doc.paragraphs for r in p.runs)
    section = doc.sections[0]
    assert section.header.paragraphs[0].text == "UNCLASSIFIED"
    assert section.footer.paragraphs[0].text == "UNCLASSIFIED"
    assert section.header.paragraphs[0].runs[0].bold
    assert doc.core_properties.title == "Varna port"


def test_docx_claim_ids_numbering_and_appendix():
    doc = _open(
        render_docx(
            make_report(status="findings_open", open_findings=["icd203.tc.8@2"]),
            NUMBERED,
            SOURCES,
            with_claim_ids=True,
            open_findings=[make_finding()],
        )
    )
    h2 = _texts(doc, "Heading 2")
    assert h2[0] == "1. Key judgments" and h2[3] == "4. Capacity"
    assert h2[-1] == "Audit findings open at delivery"
    sups = [r.text for p in doc.paragraphs for r in p.runs if r.font.superscript]
    assert sups == [" c1", " c1"]
    assert _texts(doc, "List Bullet")[-1] == (
        "icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."
    )


def test_docx_reference_supplies_styles_and_loses_its_body(tmp_path):
    ref = Document()
    ref.add_paragraph("OLD BODY TEXT")
    ref.styles["Heading 2"].font.size = Pt(20)
    ref.sections[0].header.paragraphs[0].text = "OLD HEADER"
    path = tmp_path / "ref.docx"
    ref.save(str(path))
    doc = _open(render_docx(make_report(), PACK, SOURCES, reference=path))
    assert all(p.text != "OLD BODY TEXT" for p in doc.paragraphs)
    assert doc.styles["Heading 2"].font.size == Pt(20)
    assert _texts(doc, "Heading 2") == H2
    assert doc.sections[0].header.paragraphs[0].text == "UNCLASSIFIED"


def test_docx_missing_styles_fall_back_to_normal(tmp_path):
    ref = Document()
    ref.styles["Heading 2"].delete()
    ref.styles["List Bullet"].delete()
    path = tmp_path / "bare.docx"
    ref.save(str(path))
    doc = _open(render_docx(make_report(), PACK, SOURCES, reference=path))
    assert _texts(doc, "Heading 2") == []
    normals = [p for p in doc.paragraphs if p.style.name == "Normal"]
    headings = [p for p in normals if p.text in H2]
    assert [p.text for p in headings] == H2 and all(p.runs[0].bold for p in headings)
    assert "• Moderate confidence. Capacity grew." in [p.text for p in normals]


@pytest.mark.parametrize("content", [b"not a zip", b""])
def test_docx_unreadable_reference_is_a_render_error(tmp_path, content):
    path = tmp_path / "bad.docx"
    path.write_bytes(content)
    with pytest.raises(RenderError, match="cannot open docx reference"):
        render_docx(make_report(), PACK, SOURCES, reference=path)
    with pytest.raises(RenderError, match="cannot open docx reference"):
        render_docx(make_report(), PACK, SOURCES, reference=tmp_path / "absent.docx")


def test_docx_keeps_text_literal_and_handles_empty_lists():
    nasty = make_report().model_copy(update={"title": '<b>&"x"'})
    doc = _open(render_docx(nasty, PACK, SOURCES))
    assert _texts(doc, "Heading 1") == ['<b>&"x"']
    doc = _open(render_docx(empty_lists_report(), PACK, SOURCES))
    assert _texts(doc, "Heading 2") == [h for h in H2 if h != "Capacity"]


def test_docx_is_deterministic():
    a = render_docx(make_report(), PACK, SOURCES)
    assert a == render_docx(make_report(), PACK, SOURCES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/render/test_docx.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.render.docx'`

- [ ] **Step 3: Write the module**

Create `engine/corelata/render/docx.py`:

```python
"""DOCX render (spec §9) with python-docx. A profile's reference document supplies styles,
headers, footers and page setup; otherwise python-docx's neutral default does. The reference's
own body content is dropped and the report appended, so a customer's template can carry a
logo in the header and the house heading styles without any text of its own leaking in."""

import io
from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from corelata.render.outline import Bullets, Heading, Marking, Para, Title, build_outline
from corelata.schema import Finding, Report, Source
from corelata.standards.schema import ResolvedPack


class RenderError(ValueError):
    """A render input the engine cannot use, e.g. an unreadable reference document."""


def _open(reference: Path | None) -> DocxDocument:
    if reference is None:
        return Document()
    try:
        doc = Document(str(reference))
    except (PackageNotFoundError, KeyError, ValueError, OSError) as e:
        raise RenderError(f"cannot open docx reference '{reference}': {e}") from e
    body = doc.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
    return doc


def _styled(doc: DocxDocument, style: str) -> Paragraph:
    """A paragraph in `style`, or a Normal one when the reference lacks that style."""
    try:
        return doc.add_paragraph(style=style)
    except KeyError:
        return doc.add_paragraph()


def _heading(doc: DocxDocument, text: str, level: int) -> None:
    style = f"Heading {level}"
    p = _styled(doc, style)
    run = p.add_run(text)
    if p.style.name != style:
        run.bold = True


def _ids(p: Paragraph, claim_ids: tuple[str, ...], on: bool) -> None:
    if on and claim_ids:
        p.add_run(" " + ", ".join(claim_ids)).font.superscript = True


def _mark(doc: DocxDocument, text: str) -> None:
    for section in doc.sections:
        for part in (section.header, section.footer):
            part.is_linked_to_previous = False
            p = part.paragraphs[0] if part.paragraphs else part.add_paragraph()
            p.text = ""
            p.add_run(text).bold = True
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def render_docx(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    with_claim_ids: bool = False,
    open_findings: list[Finding] | None = None,
    reference: Path | None = None,
) -> bytes:
    doc = _open(reference)
    doc.core_properties.title = report.title
    marked = False
    for block in build_outline(report, pack, sources, open_findings=open_findings):
        match block:
            case Marking(text):
                if not marked:  # the marking lives in the header and footer, set once
                    _mark(doc, text)
                    marked = True
            case Title(text):
                _heading(doc, text, 1)
            case Heading():
                _heading(doc, block.label, 2)
            case Para(text, claim_ids):
                p = doc.add_paragraph()
                p.add_run(text)
                _ids(p, claim_ids, with_claim_ids)
            case Bullets(items):
                for item in items:
                    p = _styled(doc, "List Bullet")
                    if p.style.name != "List Bullet":
                        p.add_run("• ")
                    if item.lead:
                        p.add_run(f"{item.lead} ").bold = True
                    p.add_run(item.text)
                    _ids(p, item.claim_ids, with_claim_ids)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
```

Add `from corelata.render.docx import RenderError, render_docx` and the two names to `__all__` in `engine/corelata/render/__init__.py`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/render/test_docx.py -q --no-cov`
Expected: 8 passed. If `test_docx_missing_styles_fall_back_to_normal` fails because `styles["List Bullet"]` does not exist in python-docx's default template, change the test to delete only `Heading 2` and assert only the heading fallback — and record in the report that the bullet fallback is covered by the `KeyError` branch being unreachable with the default template (then the branch needs `# pragma: no cover` with a comment, or a hand-built reference without that style). Do not silently drop the assertion.

- [ ] **Step 5: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 6: Commit**

Stage `corelata/render/` and `tests/render/` and commit with message `feat(render): DOCX render with optional profile reference document`.

### Task 5: Trace module — summary, provenance, draft diff, loading

**Files:**
- Create: `engine/corelata/trace.py`
- Create: `engine/tests/test_trace.py`
- Modify: `engine/tests/conftest.py` (move the `run` fixture here from `tests/test_pipeline.py`)
- Modify: `engine/tests/test_pipeline.py` (delete its local `run` fixture and the imports only it used; everything else unchanged)

**Interfaces:**
- Consumes: `RunRecord`, `ReportBody`, `Claim`, `Finding`, `GateVerdict`, `Usage`, `RunState`, `ReportStatus`, `SourceKind`, `Verdict` from `corelata.schema`; `open_findings` from `corelata.stages.audit`.
- Produces (Task 6 CLI and M4a API consume these):
  - `class TraceError(ValueError)`
  - `delivered_open_findings(record: RunRecord) -> list[Finding]` — the blocking/major failures of the **last** audit iteration (what the appendix lists)
  - `load_record(run_dir: Path) -> RunRecord` — reads `run_dir / "trace.json"`; `TraceError` for missing file, invalid JSON, or a record that fails validation
  - `summarize(record: RunRecord) -> TraceSummary`
  - `claim_provenance(record: RunRecord, claim_id: str) -> ClaimProvenance` — `TraceError` when the run has no report or the claim id is unknown
  - `draft_changes(prev: ReportBody, new: ReportBody) -> DraftChanges`
  - `format_summary(summary: TraceSummary) -> str` — the text `corelata trace` prints
  - pydantic models `SourceSummary`, `StageLine`, `IterationFindings`, `TraceSummary`, `EvidenceUnit`, `ClaimProvenance`, `DraftChanges` with the exact fields in Step 3.

- [ ] **Step 1: Move the `run` fixture into `tests/conftest.py`**

Append to `engine/tests/conftest.py`:

```python
from datetime import UTC, datetime

from corelata.pipeline import RunOptions, run_report
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT


@pytest.fixture
def run(make_config, fake_backend):
    """Execute a whole run in-process against the fake backend with a frozen clock."""

    async def _run(
        *sources, statement="Varna port capacity expansion matters to shippers", cfg=None, **opts
    ):
        cfg = cfg or make_config()
        sources = list(sources) or [text_source("src1", *PORT)]
        return await run_report(
            cfg,
            sources,
            RunOptions(value_statement=statement, **opts),
            backends={"fake": fake_backend},
            prompts=PromptLibrary(),
            log=CallLog(),
            now=lambda: datetime(2026, 10, 12, tzinfo=UTC),
        )

    return _run
```

Move the new imports into the top import block (`CallLog` and `PromptLibrary` are already imported there). In `engine/tests/test_pipeline.py`, delete the `run` fixture definition (the `@pytest.fixture def run(...)` block) and any import that becomes unused (`ruff check` reports them as F401; `datetime`/`UTC`, `text_source`, `PORT`, `RunOptions` may still be used by other tests in the file — remove only what ruff flags).

Run: `uv run pytest tests/test_pipeline.py -q --no-cov`
Expected: all pass as before.

- [ ] **Step 2: Write the failing tests**

Create `engine/tests/test_trace.py`:

```python
import json

import pytest

from corelata.schema import ReportStatus, RunState
from corelata.testing.sources import text_source
from corelata.trace import (
    TraceError,
    claim_provenance,
    delivered_open_findings,
    draft_changes,
    format_summary,
    load_record,
    summarize,
)
from tests.stages.conftest import PORT


async def test_summarize_clean_run(run):
    rec = await run(run_id="r1")
    s = summarize(rec)
    assert s.run_id == "r1" and s.state is RunState.COMPLETED and s.status is ReportStatus.CLEAN
    assert s.iterations == 0 and s.max_iterations == 2
    assert s.pack_name == "icd203-base" and s.pack_hash == rec.pack_hash and s.profile is None
    assert [x.model_dump() for x in s.sources] == [
        {
            "id": "src1",
            "name": "src1.txt",
            "kind": "file",
            "format": "txt",
            "units": 3,
            "digested": False,
            "coglossa_run_id": None,
        }
    ]
    assert s.gate is not None and s.gate.supported
    assert [(x.stage, x.iteration, x.ok, x.duration_ms) for x in s.stages] == [
        ("ingesting", 0, True, 0),
        ("gating", 0, True, 0),
        ("drafting", 0, True, 0),
        ("conveying", 0, True, 0),
        ("auditing", 0, True, 0),
        ("rendering", 0, True, 0),
    ]
    assert len(s.findings) == 1
    it0 = s.findings[0]
    assert it0.iteration == 0 and it0.failed == [] and it0.open == []
    assert it0.passed == 12 and it0.attested == 5 and it0.not_applicable == 0
    assert s.open_findings == [] and s.usage.calls == 4
    assert s.prompt_versions["writer"] == 1 and s.error is None


async def test_summarize_findings_loop_and_open_at_delivery(run):
    rec = await run(text_source("src1", *PORT, "UNSOURCED UNFIXABLE detail on Varna."))
    s = summarize(rec)
    assert s.status is ReportStatus.FINDINGS_OPEN and s.iterations == 2
    assert [f.iteration for f in s.findings] == [0, 1, 2]
    assert s.findings[0].failed == ["icd203.as.5", "icd203.tc.8", "icd206.src.2"]
    assert s.findings[0].open == ["icd203.as.5@0", "icd203.tc.8@0", "icd206.src.2@0"]
    assert [f.id for f in s.open_findings] == ["icd203.as.5@2", "icd203.tc.8@2", "icd206.src.2@2"]
    assert [f.id for f in delivered_open_findings(rec)] == [f.id for f in s.open_findings]
    text = format_summary(s)
    assert text.splitlines()[0] == (
        f"run {rec.run_id}: completed findings_open after 2 revision(s) (max 2)"
    )
    assert "  iteration 0: failed icd203.as.5, icd203.tc.8, icd206.src.2" in text
    assert "open at delivery:" in text and "icd203.tc.8@2 (blocking)" in text
    assert "usage: 10 calls" in text


async def test_summarize_gate_rejected_and_failed_runs(run, fake_backend):
    rejected = summarize(await run(statement="Lunar helium mining"))
    assert rejected.state is RunState.GATE_REJECTED and rejected.status is None
    assert rejected.findings == [] and rejected.open_findings == []
    assert delivered_open_findings(await run(statement="Lunar helium mining")) == []
    text = format_summary(rejected)
    assert text.splitlines()[0].endswith(": gate_rejected")
    assert "gate: not supported, insufficient" in text

    from corelata.llm.types import PermanentBackendError

    fake_backend.script("writer", PermanentBackendError("down"), PermanentBackendError("down"))
    failed = summarize(await run())
    assert failed.state is RunState.FAILED and "down" in failed.error
    assert [x.ok for x in failed.stages if x.stage == "drafting"] == [False, False]
    assert "drafting" in format_summary(failed) and "FAIL" in format_summary(failed)


async def test_claim_provenance(run):
    rec = await run(text_source("src1", *PORT), text_source("src2", "Rail links to Varna."))
    prov = claim_provenance(rec, "c0")
    assert prov.claim.id == "c0" and prov.claim.kind.value == "judgment"
    assert [e.model_dump() for e in prov.evidence] == [
        {
            "ref": "src1/u1",
            "source_id": "src1",
            "source_name": "src1.txt",
            "locator": "para 1",
            "text": PORT[0],
        }
    ]
    assert prov.cited_by == ["key_judgments[0]", "analysis[0].paragraphs[0]"]
    with pytest.raises(TraceError, match="unknown claim id 'zzz'"):
        claim_provenance(rec, "zzz")
    with pytest.raises(TraceError, match="has no report"):
        claim_provenance(await run(statement="Lunar helium mining"), "c0")


async def test_draft_changes_between_iterations(run):
    rec = await run(text_source("src1", *PORT, "UNSOURCED detail on Varna."))
    conveyed = [d.report for d in rec.drafts if d.role == "conveyor"]
    assert len(conveyed) == 2
    changes = draft_changes(conveyed[0], conveyed[1])
    assert changes.claims_removed == ["c99"] and changes.claims_added == []
    assert changes.claims_reworded == [] and not changes.title_changed
    assert not changes.key_judgments_changed and changes.sections_changed == ["Analysis"]
    reworded = conveyed[1].model_copy(
        update={
            "title": "New",
            "claims": [
                c.model_copy(update={"text": c.text + "!"}) if c.id == "c1" else c
                for c in conveyed[1].claims
            ],
        }
    )
    again = draft_changes(conveyed[1], reworded)
    assert again.title_changed and again.claims_reworded == ["c1"]
    assert again.sections_changed == []


async def test_load_record_roundtrip_and_errors(run, tmp_path):
    rec = await run(run_id="r9")
    (tmp_path / "trace.json").write_text(json.dumps(rec.model_dump(mode="json")))
    assert load_record(tmp_path).run_id == "r9"
    with pytest.raises(TraceError, match="no trace.json in"):
        load_record(tmp_path / "nowhere")
    (tmp_path / "trace.json").write_text("{not json")
    with pytest.raises(TraceError, match="trace.json is not valid JSON"):
        load_record(tmp_path)
    (tmp_path / "trace.json").write_text(json.dumps({"schema_version": "1", "run_id": "x"}))
    with pytest.raises(TraceError, match="trace.json is not a Corelata run record"):
        load_record(tmp_path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_trace.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.trace'`

- [ ] **Step 4: Write the module**

Create `engine/corelata/trace.py`:

```python
"""Read a run's trace and answer what the review screens ask (spec §10.3): what happened when,
what failed in which iteration, where a claim's evidence sits, how a draft changed between
iterations. Pure functions of RunRecord; the CLI calls them now and the API will from M4a."""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from corelata.schema import (
    Claim,
    Finding,
    GateVerdict,
    ReportBody,
    ReportStatus,
    RunRecord,
    RunState,
    SourceKind,
    Usage,
    Verdict,
)
from corelata.stages.audit import open_findings


class TraceError(ValueError):
    """A run directory or record the trace tools cannot use; the message says why."""


class SourceSummary(BaseModel):
    id: str
    name: str
    kind: SourceKind
    format: str
    units: int
    digested: bool
    coglossa_run_id: str | None


class StageLine(BaseModel):
    stage: str
    iteration: int
    ok: bool
    duration_ms: int
    error: str | None


class IterationFindings(BaseModel):
    iteration: int
    failed: list[str]  # rule ids with verdict fail, sorted
    open: list[str]  # finding ids that would loop (fail + blocking/major), sorted
    passed: int
    attested: int
    not_applicable: int


class TraceSummary(BaseModel):
    run_id: str
    state: RunState
    status: ReportStatus | None
    error: str | None
    value_statement: str
    pack_name: str
    pack_hash: str
    profile: str | None
    iterations: int
    max_iterations: int
    sources: list[SourceSummary]
    gate: GateVerdict | None
    stages: list[StageLine]
    findings: list[IterationFindings]
    open_findings: list[Finding]
    usage: Usage
    prompt_versions: dict[str, int]


class EvidenceUnit(BaseModel):
    ref: str
    source_id: str
    source_name: str
    locator: str
    text: str


class ClaimProvenance(BaseModel):
    claim: Claim
    evidence: list[EvidenceUnit]
    cited_by: list[str]  # "key_judgments[0]", "analysis[1].paragraphs[2]", "alternatives[0]"


class DraftChanges(BaseModel):
    title_changed: bool
    claims_added: list[str]
    claims_removed: list[str]
    claims_reworded: list[str]
    key_judgments_changed: bool
    sections_changed: list[str]  # headings whose paragraphs differ, or that appear/disappear


def delivered_open_findings(record: RunRecord) -> list[Finding]:
    """What the appendix lists: looping failures from the last audit iteration."""
    if record.report is None:
        return []
    return open_findings([f for f in record.findings if f.iteration == record.iterations])


def load_record(run_dir: Path) -> RunRecord:
    path = run_dir / "trace.json"
    if not path.is_file():
        raise TraceError(f"no trace.json in {run_dir}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise TraceError(f"{path}: trace.json is not valid JSON: {e}") from e
    try:
        return RunRecord.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "(top level)"
        raise TraceError(
            f"{path}: trace.json is not a Corelata run record ({where}: {first['msg']})"
        ) from e


def summarize(record: RunRecord) -> TraceSummary:
    digested = {d.source_id for d in record.digests}
    by_iteration: dict[int, list[Finding]] = {}
    for f in record.findings:
        by_iteration.setdefault(f.iteration, []).append(f)
    findings = [
        IterationFindings(
            iteration=it,
            failed=sorted(f.rule_id for f in fs if f.verdict is Verdict.FAIL),
            open=sorted(f.id for f in open_findings(fs)),
            passed=sum(f.verdict is Verdict.PASS for f in fs),
            attested=sum(f.verdict is Verdict.ATTESTED for f in fs),
            not_applicable=sum(f.verdict is Verdict.NOT_APPLICABLE for f in fs),
        )
        for it, fs in sorted(by_iteration.items())
    ]
    return TraceSummary(
        run_id=record.run_id,
        state=record.state,
        status=record.status,
        error=record.error,
        value_statement=record.value_statement,
        pack_name=record.pack_name,
        pack_hash=record.pack_hash,
        profile=record.profile,
        iterations=record.iterations,
        max_iterations=record.max_iterations,
        sources=[
            SourceSummary(
                id=s.id,
                name=s.name,
                kind=s.kind,
                format=s.format,
                units=len(s.units),
                digested=s.id in digested,
                coglossa_run_id=s.provenance.get("coglossa_run_id"),
            )
            for s in record.sources
        ],
        gate=record.gate,
        stages=[
            StageLine(
                stage=s.stage,
                iteration=s.iteration,
                ok=s.ok,
                duration_ms=int((s.finished_at - s.started_at).total_seconds() * 1000),
                error=s.error,
            )
            for s in record.stages
        ],
        findings=findings,
        open_findings=delivered_open_findings(record),
        usage=record.usage,
        prompt_versions=record.prompt_versions,
    )


def claim_provenance(record: RunRecord, claim_id: str) -> ClaimProvenance:
    if record.report is None:
        raise TraceError(f"run {record.run_id} has no report (state {record.state.value})")
    report = record.report
    claim = next((c for c in report.claims if c.id == claim_id), None)
    if claim is None:
        raise TraceError(f"unknown claim id '{claim_id}' in run {record.run_id}")
    units = {
        f"{s.id}/{u.id}": EvidenceUnit(
            ref=f"{s.id}/{u.id}", source_id=s.id, source_name=s.name, locator=u.locator, text=u.text
        )
        for s in record.sources
        for u in s.units
    }
    evidence = [units[r] for r in claim.evidence if r in units]
    cited_by = [f"key_judgments[{i}]" for i, kj in enumerate(report.key_judgments) if claim_id in kj.claim_ids]
    for si, section in enumerate(report.analysis):
        for pi, p in enumerate(section.paragraphs):
            if claim_id in p.claim_ids:
                cited_by.append(f"analysis[{si}].paragraphs[{pi}]")
    cited_by += [f"alternatives[{i}]" for i, a in enumerate(report.alternatives) if claim_id in a.claim_ids]
    return ClaimProvenance(claim=claim, evidence=evidence, cited_by=cited_by)


def draft_changes(prev: ReportBody, new: ReportBody) -> DraftChanges:
    before = {c.id: c for c in prev.claims}
    after = {c.id: c for c in new.claims}
    prev_sections = {s.heading: [p.model_dump() for p in s.paragraphs] for s in prev.analysis}
    new_sections = {s.heading: [p.model_dump() for p in s.paragraphs] for s in new.analysis}
    return DraftChanges(
        title_changed=prev.title != new.title,
        claims_added=sorted(set(after) - set(before)),
        claims_removed=sorted(set(before) - set(after)),
        claims_reworded=sorted(cid for cid in before.keys() & after.keys() if before[cid] != after[cid]),
        key_judgments_changed=[k.model_dump() for k in prev.key_judgments] != [k.model_dump() for k in new.key_judgments],
        sections_changed=sorted(h for h in prev_sections.keys() | new_sections.keys() if prev_sections.get(h) != new_sections.get(h)),
    )


def format_summary(s: TraceSummary) -> str:
    out: list[str] = []
    if s.state is RunState.COMPLETED and s.status is not None:
        out.append(
            f"run {s.run_id}: completed {s.status.value} after {s.iterations} revision(s) "
            f"(max {s.max_iterations})"
        )
    else:
        out.append(f"run {s.run_id}: {s.state.value}" + (f": {s.error}" if s.error else ""))
    out.append(f"pack: {s.pack_name}@{s.pack_hash}" + (f" profile {s.profile}" if s.profile else ""))
    out.append(f"statement: {s.value_statement}")
    out.append("sources:")
    for src in s.sources:
        extra = f", Coglossa run {src.coglossa_run_id}" if src.coglossa_run_id else ""
        extra += ", digested" if src.digested else ""
        out.append(f"  {src.id} {src.name} ({src.format}, {src.units} units{extra})")
    if s.gate is not None:
        supported = "supported" if s.gate.supported else "not supported"
        out.append(f"gate: {supported}, {s.gate.substance.value}; {' '.join(s.gate.reasons)}")
    out.append("stages:")
    for st in s.stages:
        flag = "ok  " if st.ok else "FAIL"
        err = f"  {st.error}" if st.error else ""
        out.append(f"  {st.stage:<11} it{st.iteration}  {flag} {st.duration_ms:>6} ms{err}")
    if s.findings:
        out.append("findings:")
        for it in s.findings:
            failed = ", ".join(it.failed) if it.failed else "none"
            out.append(
                f"  iteration {it.iteration}: failed {failed}; open {len(it.open)}; "
                f"passed {it.passed}; attested {it.attested}; n/a {it.not_applicable}"
            )
    if s.open_findings:
        out.append("open at delivery:")
        out += [f"  {f.id} ({f.severity}): {f.evidence}" for f in s.open_findings]
    by_role = "; ".join(
        f"{role} {u.get('calls', 0)} call(s), {u.get('tokens_in', 0)} in / {u.get('tokens_out', 0)} out"
        for role, u in sorted(s.usage.by_role.items())
    )
    out.append(
        f"usage: {s.usage.calls} calls, {s.usage.tokens_in} in / {s.usage.tokens_out} out tokens"
        + (f"; {by_role}" if by_role else "")
    )
    return "\n".join(out) + "\n"
```

(`Usage.by_role` inner keys are exactly `calls`, `tokens_in`, `tokens_out` — see `CallLog.usage()` in `corelata/llm/agent.py`.)

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_trace.py -q --no-cov`
Expected: 6 passed. If `it0.passed == 12 and it0.attested == 5` fails, count the base pack: 17 rules, 5 advisory (attested by the synthetic auditor), 12 verifiable (pass on a clean run) — fix the code, not the numbers, unless the pack has changed.

- [ ] **Step 6: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 7: Commit**

Stage `corelata/trace.py`, `tests/test_trace.py`, `tests/conftest.py`, `tests/test_pipeline.py` and commit with message `feat(trace): run summary, claim provenance, draft diff and trace loading`.

### Task 6: CLI — `run` writes HTML and DOCX; new `report` and `trace` subcommands

**Files:**
- Modify: `engine/corelata/cli.py`
- Modify: `engine/tests/test_cli.py` (adjust two existing assertions; append tests)
- Modify: `README.md` (M2 section)

**Interfaces:**
- Consumes: `render_html`, `render_docx`, `RenderError` (Tasks 2, 4); `ResolvedPack.docx_reference_path` (Task 3); `load_record`, `summarize`, `format_summary`, `claim_provenance`, `delivered_open_findings`, `TraceError` (Task 5).
- Produces:
  - `corelata run` output directory now holds `trace.json`, `gate.json`, `report.json`, `report.md`, `report.html`, `report.docx` (the last four only when there is a report). `--claim-ids` applies to `report.md` and `report.html`; `report.docx` from `run` never shows claim ids (spec §9: off for DOCX downloads). DOCX uses the pack's `docx_reference_path` when set.
  - `corelata report RUN_DIR --format {json,md,html,docx} [--claim-ids] [--out FILE] [--docx-reference FILE]` — re-renders from `trace.json` alone (invariant 5). Text formats go to stdout unless `--out`; `docx` requires `--out` (exit 2 otherwise). When the snapshot names a `docx_reference` and no `--docx-reference` is given, a note goes to stderr and the neutral template is used.
  - `corelata trace RUN_DIR [--json] [--claim CLAIM_ID]` — prints `format_summary`, or the `TraceSummary` JSON with `--json`, or the `ClaimProvenance` (text, or JSON with `--json`) with `--claim`.
  - Exit codes: `report`/`trace` return 0 on success, 2 for a bad directory, missing report, unknown claim, or bad arguments.
  - `OUTPUT_FILES` tuple extended; helper `render_outputs(record, pack, *, with_claim_ids) -> dict[str, str | bytes]` (name → content) shared by `run` and `report`.

- [ ] **Step 1: Adjust the two existing tests that enumerate output files**

In `engine/tests/test_cli.py`:

In `test_run_clean`, replace
```python
    assert names == {"report.md", "report.json", "trace.json", "gate.json"}
```
with
```python
    assert names == {"report.md", "report.html", "report.docx", "report.json", "trace.json", "gate.json"}
    html = (out / "report.html").read_text()
    assert html.startswith("<!DOCTYPE html>") and "<sup" not in html
    assert (out / "report.docx").read_bytes()[:2] == b"PK"
```

In `test_rerun_into_same_out_leaves_no_stale_files`, replace
```python
    all_four = {"report.md", "report.json", "trace.json", "gate.json"}
    assert {p.name for p in out.iterdir()} == all_four
```
with
```python
    all_six = {"report.md", "report.html", "report.docx", "report.json", "trace.json", "gate.json"}
    assert {p.name for p in out.iterdir()} == all_six
```

- [ ] **Step 2: Append the new tests**

Append to `engine/tests/test_cli.py`:

```python
STATEMENT = "Varna port capacity expansion matters to shippers"


@pytest.fixture
def run_dir(config_path, inputs, tmp_path) -> Path:
    out = tmp_path / "run"
    assert main(["run", *inputs, "--statement", STATEMENT, "--config", str(config_path), "--out", str(out)]) == 0
    return out


@pytest.fixture
def rejected_dir(config_path, inputs, tmp_path) -> Path:
    out = tmp_path / "rejected"
    code = main(["run", *inputs, "--statement", "Lunar helium mining", "--config", str(config_path), "--out", str(out)])
    assert code == 4
    return out


def test_run_claim_ids_apply_to_md_and_html_but_never_docx(config_path, inputs, tmp_path):
    out = tmp_path / "out"
    args = ["run", *inputs, "--statement", STATEMENT, "--config", str(config_path), "--out", str(out)]
    assert main([*args, "--claim-ids"]) == 0
    assert "^[c0]" in (out / "report.md").read_text()
    assert '<sup class="claim-ids">c0</sup>' in (out / "report.html").read_text()
    from docx import Document

    doc = Document(str(out / "report.docx"))
    assert not any(r.font.superscript for p in doc.paragraphs for r in p.runs)


def test_report_reproduces_the_run_outputs(run_dir, capsys, tmp_path):
    assert main(["report", str(run_dir), "--format", "md"]) == 0
    assert capsys.readouterr().out == (run_dir / "report.md").read_text()
    assert main(["report", str(run_dir), "--format", "html"]) == 0
    assert capsys.readouterr().out == (run_dir / "report.html").read_text()
    assert main(["report", str(run_dir), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads((run_dir / "report.json").read_text())
    target = tmp_path / "again.docx"
    assert main(["report", str(run_dir), "--format", "docx", "--out", str(target)]) == 0
    assert target.read_bytes() == (run_dir / "report.docx").read_bytes()
    assert main(["report", str(run_dir), "--format", "md", "--claim-ids", "--out", str(tmp_path / "ids.md")]) == 0
    assert "^[c0]" in (tmp_path / "ids.md").read_text()


def test_report_docx_needs_out_and_notes_unresolvable_reference(run_dir, capsys, tmp_path):
    assert main(["report", str(run_dir), "--format", "docx"]) == 2
    assert "--out" in capsys.readouterr().err
    trace = json.loads((run_dir / "trace.json").read_text())
    trace["pack_snapshot"]["format"]["docx_reference"] = "templates/east.docx"
    (run_dir / "trace.json").write_text(json.dumps(trace))
    target = tmp_path / "x.docx"
    assert main(["report", str(run_dir), "--format", "docx", "--out", str(target)]) == 0
    err = capsys.readouterr().err
    assert "docx_reference 'templates/east.docx'" in err and "--docx-reference" in err
    assert target.read_bytes()[:2] == b"PK"
    from docx import Document

    ref = tmp_path / "ref.docx"
    Document().save(str(ref))
    assert main(["report", str(run_dir), "--format", "docx", "--out", str(target), "--docx-reference", str(ref)]) == 0
    assert capsys.readouterr().err == ""
    (tmp_path / "bad.docx").write_text("nope")
    assert main(["report", str(run_dir), "--format", "docx", "--out", str(target), "--docx-reference", str(tmp_path / "bad.docx")]) == 2
    assert "cannot open docx reference" in capsys.readouterr().err


def test_report_and_trace_usage_errors(rejected_dir, tmp_path, capsys):
    assert main(["report", str(rejected_dir), "--format", "md"]) == 2
    assert "has no report (state gate_rejected)" in capsys.readouterr().err
    assert main(["report", str(tmp_path / "nowhere"), "--format", "md"]) == 2
    assert "no trace.json in" in capsys.readouterr().err
    assert main(["trace", str(tmp_path / "nowhere")]) == 2
    assert "no trace.json in" in capsys.readouterr().err
    (tmp_path / "corrupt").mkdir()
    (tmp_path / "corrupt" / "trace.json").write_text("{")
    assert main(["trace", str(tmp_path / "corrupt")]) == 2
    assert "not valid JSON" in capsys.readouterr().err
    assert main(["trace", str(rejected_dir)]) == 0
    out = capsys.readouterr().out
    assert ": gate_rejected" in out and "gate: not supported" in out


def test_trace_text_json_and_claim(run_dir, capsys):
    assert main(["trace", str(run_dir)]) == 0
    text = capsys.readouterr().out
    assert "completed clean after 0 revision(s)" in text and "stages:" in text
    assert main(["trace", str(run_dir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "completed" and [s["id"] for s in data["sources"]] == ["src1", "src2"]
    assert main(["trace", str(run_dir), "--claim", "c0"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("c0 (judgment):") and "src1/u1" in text and "para 1" in text
    assert "cited by: key_judgments[0], analysis[0].paragraphs[0]" in text
    assert main(["trace", str(run_dir), "--claim", "c0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["claim"]["id"] == "c0"
    assert main(["trace", str(run_dir), "--claim", "zzz"]) == 2
    assert "unknown claim id 'zzz'" in capsys.readouterr().err
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q --no-cov`
Expected: the two adjusted tests fail (only four files), the new ones fail with argparse `invalid choice: 'report'` / `'trace'` (SystemExit 2 — pytest reports them as errors or failures; either way red).

- [ ] **Step 4: Implement**

In `engine/corelata/cli.py`:

Replace the imports block's render/trace lines so it contains:

```python
from corelata.render.docx import RenderError, render_docx
from corelata.render.html import render_html
from corelata.render.markdown import render_markdown
from corelata.trace import (
    TraceError,
    claim_provenance,
    delivered_open_findings,
    format_summary,
    load_record,
    summarize,
)
```

and delete `from corelata.stages.audit import open_findings` (no longer used here).

Replace the `OUTPUT_FILES` line:

```python
OUTPUT_FILES = ("trace.json", "gate.json", "report.json", "report.md", "report.html", "report.docx")
REPORT_FORMATS = ("json", "md", "html", "docx")
```

In `build_parser`, after the `disc` subparser block add:

```python
    rep = sub.add_parser("report", help="re-render a finished run's report from its directory")
    rep.add_argument("run_dir", type=Path, help="a directory written by `corelata run`")
    rep.add_argument("--format", choices=REPORT_FORMATS, default="md")
    rep.add_argument("--claim-ids", action="store_true", help="show claim ids (md, html, docx)")
    rep.add_argument("--out", type=Path, help="write here instead of stdout (required for docx)")
    rep.add_argument(
        "--docx-reference", type=Path, help="reference .docx for styles (else the neutral built-in)"
    )

    tr = sub.add_parser("trace", help="summarise a run from its directory")
    tr.add_argument("run_dir", type=Path, help="a directory written by `corelata run`")
    tr.add_argument("--json", action="store_true", help="machine-readable output")
    tr.add_argument("--claim", help="show one claim's evidence units instead of the summary")
```

In `main`, before `return _fake_openai(args)` add:

```python
        if args.command == "report":
            return _report(args)
        if args.command == "trace":
            return _trace(args)
```

Replace `write_outputs` with:

```python
def render_outputs(
    record: RunRecord,
    pack: ResolvedPack,
    *,
    with_claim_ids: bool,
    docx_claim_ids: bool = False,
    docx_reference: Path | None = None,
) -> dict[str, str | bytes]:
    """Every file a run directory holds, by name. Pure: the same record renders the same bytes."""
    out: dict[str, str | bytes] = {"trace.json": _json(record.model_dump(mode="json"))}
    if record.gate is not None:
        out["gate.json"] = _json(record.gate.model_dump(mode="json"))
    if record.report is not None:
        open_ = delivered_open_findings(record)
        args = (record.report, pack, record.sources)
        out["report.json"] = _json(record.report.model_dump(mode="json"))
        out["report.md"] = render_markdown(*args, with_claim_ids=with_claim_ids, open_findings=open_)
        out["report.html"] = render_html(*args, with_claim_ids=with_claim_ids, open_findings=open_)
        out["report.docx"] = render_docx(
            *args, with_claim_ids=docx_claim_ids, open_findings=open_, reference=docx_reference
        )
    return out


def _json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_outputs(
    out_dir: Path, record: RunRecord, pack: ResolvedPack, with_claim_ids: bool
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:  # a rerun never leaves stale files from an earlier run
        (out_dir / name).unlink(missing_ok=True)
    written: list[Path] = []
    outputs = render_outputs(
        record, pack, with_claim_ids=with_claim_ids, docx_reference=pack.docx_reference_path
    )
    for name, content in outputs.items():
        path = out_dir / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
```

Add the two new command functions after `_discover`:

```python
def _load_run(run_dir: Path) -> tuple[RunRecord, ResolvedPack]:
    record = load_record(run_dir)
    return record, ResolvedPack.model_validate(record.pack_snapshot)


def _report(args: argparse.Namespace) -> int:
    try:
        record, pack = _load_run(args.run_dir)
    except TraceError as e:
        return _usage(str(e))
    if record.report is None:
        return _usage(f"run {record.run_id} has no report (state {record.state.value})")
    if args.format == "docx" and args.out is None:
        return _usage("--format docx needs --out FILE")
    reference = args.docx_reference
    if args.format == "docx" and reference is None and pack.format.docx_reference is not None:
        print(
            f"note: the run's profile names docx_reference '{pack.format.docx_reference}', which "
            "a run directory cannot locate; rendering with the neutral template. Pass "
            "--docx-reference FILE to use it.",
            file=sys.stderr,
        )
    try:
        outputs = render_outputs(
            record,
            pack,
            with_claim_ids=args.claim_ids,
            docx_claim_ids=args.claim_ids,
            docx_reference=reference,
        )
    except RenderError as e:
        return _usage(str(e))
    content = outputs[f"report.{args.format}"]
    if args.out is None:
        sys.stdout.write(content)  # text formats only; docx was refused above
        return EXIT_OK
    try:
        if isinstance(content, bytes):
            args.out.write_bytes(content)
        else:
            args.out.write_text(content, encoding="utf-8")
    except OSError as e:
        return _usage(f"cannot write {args.out}: {e.strerror or e}")
    return EXIT_OK


def _trace(args: argparse.Namespace) -> int:
    try:
        record = load_record(args.run_dir)
        if args.claim is not None:
            prov = claim_provenance(record, args.claim)
            if args.json:
                print(_json(prov.model_dump(mode="json")), end="")
                return EXIT_OK
            print(f"{prov.claim.id} ({prov.claim.kind.value}): {prov.claim.text}")
            if prov.claim.likelihood_term:
                print(f"likelihood: {prov.claim.likelihood_term}")
            for e in prov.evidence:
                print(f"  {e.ref}  {e.source_name}, {e.locator}")
                print(f"    {e.text}")
            if not prov.evidence:
                print("  (no evidence)")
            print(f"cited by: {', '.join(prov.cited_by) or 'nothing'}")
            return EXIT_OK
    except TraceError as e:
        return _usage(str(e))
    summary = summarize(record)
    if args.json:
        print(_json(summary.model_dump(mode="json")), end="")
    else:
        print(format_summary(summary), end="")
    return EXIT_OK
```

- [ ] **Step 5: Run the CLI tests**

Run: `uv run pytest tests/test_cli.py -q --no-cov`
Expected: all pass.

- [ ] **Step 6: Update the README**

In `README.md`, after the `## M1: engine and CLI` block add:

```markdown
## M2: rendering and trace

Every run directory holds `report.md`, `report.html` (self-contained, provenance attributes on
every paragraph) and `report.docx` (neutral template, or the profile's `format.docx_reference`),
plus `report.json`, `gate.json` and `trace.json`. Open audit findings are appended to all three
renders under "Audit findings open at delivery".

    uv run corelata trace /tmp/run1                       # timeline, findings per iteration, usage
    uv run corelata trace /tmp/run1 --claim c1            # a claim's evidence units and locators
    uv run corelata report /tmp/run1 --format html --claim-ids > review.html
    uv run corelata report /tmp/run1 --format docx --out report.docx --docx-reference house.docx

`report` re-renders from `trace.json` alone, so a stored trace is enough to reproduce every
export. The trace format is documented in `docs/trace-format.md`.
```

- [ ] **Step 7: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 8: Commit**

Stage `corelata/cli.py`, `tests/test_cli.py`, `../README.md` and commit with message `feat(cli): write HTML and DOCX; add report and trace subcommands`.

### Task 7: Trace export format — committed JSON Schema stays in sync; format document

**Files:**
- Modify: `engine/corelata/schema/export.py` (export `TraceSummary` and `ClaimProvenance` too)
- Modify: `engine/tests/schema/test_export.py` (append drift test)
- Regenerate: `schema/*.schema.json` (run `make schema` from the repository root; commit the result)
- Create: `docs/trace-format.md`

**Interfaces:**
- Consumes: `TraceSummary`, `ClaimProvenance` from `corelata.trace` (Task 5).
- Produces: `schema/trace-summary.schema.json`, `schema/claim-provenance.schema.json`; a CI-enforced guarantee that the committed `schema/` directory matches the models (M4a's web type generation builds on it).

- [ ] **Step 1: Write the failing test**

Append to `engine/tests/schema/test_export.py`:

```python
from pathlib import Path

REPO_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schema"


def test_committed_schema_matches_models(tmp_path):
    """`schema/` is generated; when a model changes, run `make schema` and commit the diff."""
    written = export(tmp_path)
    assert {p.name for p in written} >= {
        "run-record.schema.json",
        "trace-summary.schema.json",
        "claim-provenance.schema.json",
    }
    for path in written:
        committed = REPO_SCHEMA_DIR / path.name
        assert committed.is_file(), f"{committed} missing: run `make schema` and commit"
        assert committed.read_text() == path.read_text(), (
            f"{committed.name} is stale: run `make schema` and commit the result"
        )
```

Move `from pathlib import Path` to the top import block.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/schema/test_export.py -q --no-cov`
Expected: FAIL — `trace-summary.schema.json` not among the written files.

- [ ] **Step 3: Export the trace models**

In `engine/corelata/schema/export.py`, change the imports and `EXPORTED` to:

```python
from corelata.schema import DiscoveryResult, Report, RunRecord
from corelata.standards.schema import ResolvedPack
from corelata.trace import ClaimProvenance, TraceSummary

EXPORTED: dict[str, type[BaseModel]] = {
    "report": Report,
    "run-record": RunRecord,
    "resolved-pack": ResolvedPack,
    "discovery-result": DiscoveryResult,
    "trace-summary": TraceSummary,
    "claim-provenance": ClaimProvenance,
}
```

Then regenerate from the repository root: `make schema` (equivalently, from `engine/`: `uv run python -m corelata.schema.export ../schema`). Inspect `git status`: `resolved-pack.schema.json` changes (it gains `docx_reference_path`, from Task 3), `run-record.schema.json` may change only if `RunRecord` changed (it should not have), and two new files appear.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/schema -q --no-cov`
Expected: all pass. Then edit one committed schema file by hand (add a space), rerun, confirm the drift test fails with the "is stale" message, and restore the file (`git checkout -- ../schema`).

- [ ] **Step 5: Write the trace format document**

Create `docs/trace-format.md`:

```markdown
# Trace format

A run directory written by `corelata run` (and, from M3, every row the API serves) is described
by one document: `trace.json`, a `RunRecord` with `schema_version: "1"`. Its JSON Schema is
generated into `schema/run-record.schema.json`; CI fails when the committed schema and the
models disagree (`make schema` regenerates it).

## Files in a run directory

| File | Present when | Content |
|---|---|---|
| `trace.json` | always | the `RunRecord`: everything below |
| `gate.json` | the gate ran | `GateVerdict` |
| `report.json` | a report was delivered | `Report` (body + `metadata`) |
| `report.md`, `report.html`, `report.docx` | a report was delivered | renders of `report.json`; the appendix "Audit findings open at delivery" lists `delivered_open_findings` |

`corelata report RUN_DIR --format …` re-renders any of the three from `trace.json` alone; the
DOCX uses the neutral template unless `--docx-reference` names the profile's reference document
(a run directory does not carry it; M3 stores it with the run).

## RunRecord

- Identity: `run_id`, `created_at`, `corelata_version`, `config_hash`, `prompt_versions`
  (prompt id → version used), `pack_name`, `pack_hash`, `pack_snapshot` (the resolved pack as
  JSON — edit the pack directory later and this run still means what it meant), `profile`.
- Outcome: `state` (spec §7.2 state machine; terminal states `completed`, `gate_rejected`,
  `failed`, `cancelled`), `status` (`clean` | `findings_open`, completed runs only), `error`.
- Inputs: `value_statement`, `sources[]` (each with its ordered `units[]`: `id`, `text`,
  `locator`, `kind`, `meta`), `digests[]` for sources over the digest threshold.
- Process: `stages[]` — one entry per attempt of every stage, with `iteration`, `ok`,
  `started_at`, `finished_at`, `output` (small, stage-specific) or `error`; `drafts[]` — every
  writer and conveyor output with its `role` and `iteration`; `findings[]` — one `Finding` per
  rule per audit iteration (`rule_id`, `verdict`, `severity`, `route_to`, `evidence`,
  `cited_units`, `claim_ids`, `recommendation`, `iteration`); a finding's id is
  `<rule_id>@<iteration>`.
- Loop: `iterations` (revisions performed), `max_iterations`.
- Delivered: `report` — the final conveyed draft plus `metadata` (`run_id`, `pack_name`,
  `pack_hash`, `profile`, `iteration`, `status`, `open_findings` ids).
- Cost: `usage` (calls and tokens, total and by role), `llm_calls[]` (one per model call;
  `request` and `response` present when `audit.store_llm_io` is on).

## Derived views

`corelata trace RUN_DIR` prints a `TraceSummary` (`schema/trace-summary.schema.json`):
sources with unit counts and digest flags, the gate verdict, a stage timeline with durations,
failed and open rule ids per iteration, findings open at delivery, usage by role.
`corelata trace RUN_DIR --claim c1` prints a `ClaimProvenance`
(`schema/claim-provenance.schema.json`): the claim, its evidence units with source name and
locator, and where in the report it is cited.

## Invariants (spec §8.4)

1. Every claim in a report delivered `clean` has at least one evidence unit ref.
2. Every rule in the resolved pack has exactly one finding per audit iteration.
3. No judgment uses a likelihood term outside the pack lexicon.
4. The auditor never produces report text; only structured findings flow back to the writer
   and conveyor.
5. Every render is a pure function of `report`, `pack_snapshot`, `sources` and the open
   findings, all of which are in `trace.json`.

## Compatibility

`schema_version` changes only when a reader of version N could misinterpret a version N+1
record. Adding optional fields does not bump it; renaming or removing a field, or changing a
field's meaning, does.
```

- [ ] **Step 6: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 7: Commit**

Stage `corelata/schema/export.py`, `tests/schema/test_export.py`, `../schema/`, `../docs/trace-format.md` and commit with message `feat(schema): export trace models; CI pins committed JSON Schema; document the trace format`.

### Task 8: Scenario fixtures and runner

**Files:**
- Modify: `engine/corelata/ingest/units.py` (add `source_from_paragraphs`)
- Modify: `engine/corelata/testing/sources.py` (`text_source` delegates to it)
- Create: `engine/corelata/scenarios.py`
- Create: `engine/tests/fixtures/scenarios/` with nine YAML files (Step 4)
- Create: `engine/tests/test_scenarios.py`

**Interfaces:**
- Consumes: `run_report`, `RunOptions` (pipeline); `Source`, `SourceKind`, `SourceUnit`, `BlockKind`, `RunRecord`, `RunState`, `ReportStatus`, `Substance`, `Verdict`; `PipelineConfig`, `CorelataConfig`.
- Produces (M6 `corelata bench` reuses all of it):
  - `source_from_paragraphs(source_id: str, paragraphs: list[str], *, name: str | None = None) -> Source` in `corelata.ingest.units` — units `u1..uN`, locator `para N`, `sha256` of the joined text, `name` defaulting to `<source_id>.txt`. `corelata.testing.sources.text_source(source_id, *paragraphs, name=None)` keeps its signature and calls it.
  - `corelata.scenarios`: `class ScenarioError(ValueError)`; strict pydantic `ScenarioSource`, `ScenarioExpect`, `Scenario`; `load_scenario(path: Path) -> Scenario`; `load_scenarios(directory: Path) -> list[Scenario]` (sorted by file name); `scenario_sources(s: Scenario) -> list[Source]`; `async run_scenario(s, cfg, *, backends, prompts, log, now=utcnow) -> RunRecord`; `compare(s: Scenario, record: RunRecord) -> list[str]` (empty list means the scenario passed; each string is one mismatch, `"<field>: expected X, got Y"`).

Scenario YAML shape (strict; unknown keys are errors):

```yaml
name: unsourced-fixed-one-loop            # also used as the run id
description: one sentence on what this pins
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    name: port.txt                        # optional; default <id>.txt
    paragraphs: [ "…", "…" ]
max_iterations: 2                         # optional; default from config
profile: null                             # optional
pipeline: { digest_threshold_tokens: 500 }  # optional overrides of PipelineConfig fields
expect:
  state: completed                        # required
  status: clean                           # optional
  iterations: 1                           # optional
  gate_supported: true                    # optional
  substance: sufficient                   # optional
  failing_rules:                          # optional; audit iteration -> rule ids failing (any order)
    0: [icd203.as.5, icd203.tc.8, icd206.src.2]
    1: []
  open_findings: []                       # optional; finding ids open at delivery
  digested: []                            # optional; source ids that were digested
```

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/test_scenarios.py`:

```python
from pathlib import Path

import pytest
import yaml

from corelata.llm.agent import CallLog
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import (
    Scenario,
    ScenarioError,
    compare,
    load_scenario,
    load_scenarios,
    run_scenario,
    scenario_sources,
)
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.sources import text_source

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
SCENARIOS = load_scenarios(FIXTURES)


def test_fixture_directory_has_the_expected_set():
    assert [s.name for s in SCENARIOS] == [
        "badterm-fixed-one-loop",
        "clean-single-source",
        "clean-two-sources",
        "gate-rejected",
        "long-source-digested",
        "max-iterations-zero",
        "thin-material",
        "unsourced-fixed-one-loop",
        "unsourced-unfixable",
    ]
    assert all(s.description for s in SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
async def test_scenario_passes_against_the_fake_model(scenario, make_config):
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert record.run_id == scenario.name
    assert compare(scenario, record) == [], "\n".join(compare(scenario, record))


def test_source_from_paragraphs_matches_text_source():
    s = scenario_sources(
        Scenario.model_validate(
            {
                "name": "x",
                "statement": "s",
                "sources": [{"id": "src1", "paragraphs": ["a", "b"]}, {"id": "src2", "name": "n.md", "paragraphs": ["c"]}],
                "expect": {"state": "completed"},
            }
        )
    )
    assert s[0] == text_source("src1", "a", "b")
    assert s[1].name == "n.md" and s[1].refs() == ["src2/u1"]


def test_load_scenario_errors_name_the_file_and_problem(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: x\nstatement: s\nsources: [{id: src1, paragraphs: [a]}]\n"
        "expect: {state: completed}\nbogus: 1\n"
    )
    with pytest.raises(ScenarioError, match=r"bad\.yaml: bogus: Extra inputs are not permitted"):
        load_scenario(bad)
    bad.write_text("name: [\n")
    with pytest.raises(ScenarioError, match=r"bad\.yaml: invalid YAML"):
        load_scenario(bad)
    bad.write_text("- just\n- a list\n")
    with pytest.raises(ScenarioError, match=r"bad\.yaml: .*(dict|object|mapping)"):
        load_scenario(bad)
    with pytest.raises(ScenarioError, match="cannot read"):
        load_scenario(tmp_path / "missing.yaml")
    assert load_scenarios(tmp_path / "empty-dir") == []


async def test_compare_reports_every_mismatch(make_config):
    scenario = load_scenario(FIXTURES / "clean-single-source.yaml")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    wrong = scenario.model_copy(
        update={
            "expect": scenario.expect.model_copy(
                update={
                    "status": "findings_open",
                    "iterations": 3,
                    "substance": "thin",
                    "failing_rules": {0: ["icd203.tc.8", "nope.rule.1"], 4: []},
                    "open_findings": ["icd203.tc.8@0"],
                    "digested": ["src1"],
                }
            )
        }
    )
    mismatches = compare(wrong, record)
    assert mismatches == [
        "status: expected 'findings_open', got 'clean'",
        "iterations: expected 3, got 0",
        "gate.substance: expected 'thin', got 'sufficient'",
        "failing_rules[0]: not in pack: nope.rule.1",
        "failing_rules[0]: expected ['icd203.tc.8', 'nope.rule.1'], got []",
        "failing_rules[4]: no audit ran for iteration 4",
        "open_findings: expected ['icd203.tc.8@0'], got []",
        "digested: expected ['src1'], got []",
    ]
    rejected = load_scenario(FIXTURES / "gate-rejected.yaml")
    rec = await run_scenario(
        rejected,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    expects_gate = rejected.model_copy(
        update={"expect": rejected.expect.model_copy(update={"gate_supported": True})}
    )
    assert compare(expects_gate, rec) == ["gate.supported: expected True, got False"]
    no_gate = rec.model_copy(update={"gate": None})
    assert compare(rejected, no_gate) == ["gate: expected a verdict, got none"]


def test_scenario_yaml_round_trips_through_the_model():
    for s in SCENARIOS:
        data = yaml.safe_load((FIXTURES / f"{s.name}.yaml").read_text())
        assert Scenario.model_validate(data) == s
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_scenarios.py -q --no-cov`
Expected: FAIL at import with `ModuleNotFoundError: No module named 'corelata.scenarios'`.

- [ ] **Step 3: Move paragraph sources into production code**

In `engine/corelata/ingest/units.py` add (after `make_sources`):

```python
def source_from_paragraphs(
    source_id: str, paragraphs: list[str], *, name: str | None = None
) -> Source:
    """A plain-text source built from strings: one paragraph per unit, no file system."""
    text = "\n\n".join(paragraphs)
    return Source(
        id=source_id,
        kind=SourceKind.FILE,
        name=name or f"{source_id}.txt",
        format="txt",
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        units=[
            SourceUnit(id=f"u{i}", text=p, locator=f"para {i}", kind=BlockKind.PARAGRAPH)
            for i, p in enumerate(paragraphs, start=1)
        ],
    )
```

and `import hashlib` at the top. Replace the body of `engine/corelata/testing/sources.py` with:

```python
"""Build sources from strings for tests and demos, without touching the file system."""

from corelata.ingest.units import source_from_paragraphs
from corelata.schema import Source


def text_source(source_id: str, *paragraphs: str, name: str | None = None) -> Source:
    return source_from_paragraphs(source_id, list(paragraphs), name=name)
```

Run: `uv run pytest tests/stages tests/test_pipeline.py -q --no-cov`
Expected: all pass (same sources as before).

- [ ] **Step 4: Write the nine scenario files**

Create `engine/tests/fixtures/scenarios/clean-single-source.yaml`:

```yaml
name: clean-single-source
description: Three paragraphs that support the statement produce a clean report in one pass.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    name: port.txt
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
      - Capacity expansion was financed by a state bank.
      - Container traffic through Varna rose 40 percent.
expect:
  state: completed
  status: clean
  iterations: 0
  gate_supported: true
  substance: sufficient
  failing_rules:
    0: []
  open_findings: []
  digested: []
```

`clean-two-sources.yaml`:

```yaml
name: clean-two-sources
description: Two supporting sources; every source gets a sources entry and the report is clean.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
      - Capacity expansion was financed by a state bank.
      - Container traffic through Varna rose 40 percent.
  - id: src2
    name: shippers.md
    paragraphs:
      - Shippers welcomed the capacity at Varna.
      - Rail links to the port were upgraded.
expect:
  state: completed
  status: clean
  iterations: 0
  gate_supported: true
  substance: sufficient
  failing_rules:
    0: []
```

`thin-material.yaml`:

```yaml
name: thin-material
description: One supporting paragraph passes the gate as thin; the writer must carry the suggested scope.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
expect:
  state: completed
  status: clean
  iterations: 0
  gate_supported: true
  substance: thin
  failing_rules:
    0: []
```

`gate-rejected.yaml`:

```yaml
name: gate-rejected
description: Sources that do not address the statement end the run at the gate with no report.
statement: Lunar helium mining
sources:
  - id: src1
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
      - Capacity expansion was financed by a state bank.
expect:
  state: gate_rejected
  gate_supported: false
  substance: insufficient
  iterations: 0
```

`unsourced-fixed-one-loop.yaml`:

```yaml
name: unsourced-fixed-one-loop
description: An unsourced claim fails icd203.tc.8, icd206.src.2 and icd203.as.5; the writer fixes it in one revision.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
      - Capacity expansion was financed by a state bank.
      - Container traffic through Varna rose 40 percent.
      - UNSOURCED detail on Varna.
expect:
  state: completed
  status: clean
  iterations: 1
  failing_rules:
    0: [icd203.as.5, icd203.tc.8, icd206.src.2]
    1: []
  open_findings: []
```

`unsourced-unfixable.yaml`:

```yaml
name: unsourced-unfixable
description: A claim the writer cannot source stays open through both revisions; the report is delivered findings_open.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
      - Capacity expansion was financed by a state bank.
      - Container traffic through Varna rose 40 percent.
      - UNSOURCED UNFIXABLE detail on Varna.
max_iterations: 2
expect:
  state: completed
  status: findings_open
  iterations: 2
  failing_rules:
    0: [icd203.as.5, icd203.tc.8, icd206.src.2]
    1: [icd203.as.5, icd203.tc.8, icd206.src.2]
    2: [icd203.as.5, icd203.tc.8, icd206.src.2]
  open_findings: [icd203.as.5@2, icd203.tc.8@2, icd206.src.2@2]
```

`max-iterations-zero.yaml`:

```yaml
name: max-iterations-zero
description: With no revision budget the run audits once and delivers whatever it has, findings open.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
      - Capacity expansion was financed by a state bank.
      - Container traffic through Varna rose 40 percent.
      - UNSOURCED detail on Varna.
max_iterations: 0
expect:
  state: completed
  status: findings_open
  iterations: 0
  failing_rules:
    0: [icd203.as.5, icd203.tc.8, icd206.src.2]
  open_findings: [icd203.as.5@0, icd203.tc.8@0, icd206.src.2@0]
```

`badterm-fixed-one-loop.yaml`:

```yaml
name: badterm-fixed-one-loop
description: A key judgment with a non-lexicon term fails icd203.tc.2 (and as.5); one revision clears it.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    paragraphs:
      - The port of Varna expanded its container capacity in 2025.
      - Capacity expansion was financed by a state bank.
      - Container traffic through Varna rose 40 percent.
      - BADTERM appears in the Varna coverage.
expect:
  state: completed
  status: clean
  iterations: 1
  failing_rules:
    0: [icd203.as.5, icd203.tc.2]
    1: []
```

`long-source-digested.yaml`:

```yaml
name: long-source-digested
description: A source over the digest threshold is digested before gating and the run still completes clean.
statement: Varna port capacity expansion matters to shippers
sources:
  - id: src1
    name: long.txt
    paragraphs:
      - Paragraph 0 about Varna port capacity, traffic and finance.
      - Paragraph 1 about Varna port capacity, traffic and finance.
      - Paragraph 2 about Varna port capacity, traffic and finance.
      - Paragraph 3 about Varna port capacity, traffic and finance.
      - Paragraph 4 about Varna port capacity, traffic and finance.
      - Paragraph 5 about Varna port capacity, traffic and finance.
      - Paragraph 6 about Varna port capacity, traffic and finance.
      - Paragraph 7 about Varna port capacity, traffic and finance.
      - Paragraph 8 about Varna port capacity, traffic and finance.
      - Paragraph 9 about Varna port capacity, traffic and finance.
      - Paragraph 10 about Varna port capacity, traffic and finance.
      - Paragraph 11 about Varna port capacity, traffic and finance.
      - Paragraph 12 about Varna port capacity, traffic and finance.
      - Paragraph 13 about Varna port capacity, traffic and finance.
      - Paragraph 14 about Varna port capacity, traffic and finance.
      - Paragraph 15 about Varna port capacity, traffic and finance.
      - Paragraph 16 about Varna port capacity, traffic and finance.
      - Paragraph 17 about Varna port capacity, traffic and finance.
      - Paragraph 18 about Varna port capacity, traffic and finance.
      - Paragraph 19 about Varna port capacity, traffic and finance.
      - Paragraph 20 about Varna port capacity, traffic and finance.
      - Paragraph 21 about Varna port capacity, traffic and finance.
      - Paragraph 22 about Varna port capacity, traffic and finance.
      - Paragraph 23 about Varna port capacity, traffic and finance.
      - Paragraph 24 about Varna port capacity, traffic and finance.
      - Paragraph 25 about Varna port capacity, traffic and finance.
      - Paragraph 26 about Varna port capacity, traffic and finance.
      - Paragraph 27 about Varna port capacity, traffic and finance.
      - Paragraph 28 about Varna port capacity, traffic and finance.
      - Paragraph 29 about Varna port capacity, traffic and finance.
pipeline:
  digest_threshold_tokens: 500
expect:
  state: completed
  status: clean
  iterations: 0
  gate_supported: true
  substance: sufficient
  failing_rules:
    0: []
  digested: [src1]
```

The expectations come from the synthetic responder's documented behaviour (`corelata/testing/synthetic.py` module docstring) and the engine checks in `stages/audit.py`. If a scenario fails, decide which side is wrong: the fixture (rewrite it and say why in your report) or the engine (stop and report — never edit an expectation to match an unexplained result).

- [ ] **Step 5: Write the scenarios module**

Create `engine/corelata/scenarios.py`:

```python
"""Scenario fixtures (spec §13): sources plus a statement plus what the run must do. CI runs them
against the synthetic model; `corelata bench` (M6) runs the same files against real models and
reports agreement. Loading, running and comparing live here so both callers share one truth."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from corelata.config import CorelataConfig, PipelineConfig
from corelata.ingest.units import source_from_paragraphs
from corelata.llm.agent import CallLog
from corelata.llm.types import Backend
from corelata.pipeline import RunOptions, run_report, utcnow
from corelata.prompts.library import PromptLibrary
from corelata.schema import ReportStatus, RunRecord, RunState, Source, Substance, Verdict


class ScenarioError(ValueError):
    """A scenario file is unusable; the message names the file and the problem."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioSource(_Strict):
    id: str
    name: str | None = None
    paragraphs: list[str] = Field(min_length=1)


class ScenarioExpect(_Strict):
    state: RunState
    status: ReportStatus | None = None
    iterations: int | None = None
    gate_supported: bool | None = None
    substance: Substance | None = None
    failing_rules: dict[int, list[str]] = Field(default_factory=dict)
    open_findings: list[str] | None = None
    digested: list[str] | None = None


class Scenario(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""
    statement: str = Field(min_length=1)
    sources: list[ScenarioSource] = Field(min_length=1)
    max_iterations: int | None = Field(None, ge=0, le=10)
    profile: str | None = None
    pipeline: dict[str, Any] = Field(default_factory=dict)
    expect: ScenarioExpect


def load_scenario(path: Path) -> Scenario:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScenarioError(f"{path.name}: invalid YAML: {' '.join(str(e).split())}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ScenarioError(f"{path.name}: cannot read: {e}") from e
    if not isinstance(data, dict):
        raise ScenarioError(f"{path.name}: expected a mapping at the top level")
    try:
        return Scenario.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "(top level)"
        raise ScenarioError(f"{path.name}: {where}: {first['msg']}") from e


def load_scenarios(directory: Path) -> list[Scenario]:
    if not directory.is_dir():
        return []
    return [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]


def scenario_sources(scenario: Scenario) -> list[Source]:
    return [source_from_paragraphs(s.id, s.paragraphs, name=s.name) for s in scenario.sources]


async def run_scenario(
    scenario: Scenario,
    cfg: CorelataConfig,
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    now: Callable[[], datetime] = utcnow,
) -> RunRecord:
    if scenario.pipeline:
        pipeline = PipelineConfig.model_validate({**cfg.pipeline.model_dump(), **scenario.pipeline})
        cfg = cfg.model_copy(update={"pipeline": pipeline})
    return await run_report(
        cfg,
        scenario_sources(scenario),
        RunOptions(
            value_statement=scenario.statement,
            profile=scenario.profile,
            max_iterations=scenario.max_iterations,
            run_id=scenario.name,
        ),
        backends=backends,
        prompts=prompts,
        log=log,
        now=now,
    )


def compare(scenario: Scenario, record: RunRecord) -> list[str]:
    """Every way the record disagrees with the scenario's expectations; empty means it passed."""
    e = scenario.expect
    out: list[str] = []

    def check(label: str, expected: object, actual: object) -> None:
        if expected is not None and expected != actual:
            out.append(f"{label}: expected {_show(expected)}, got {_show(actual)}")

    check("state", e.state, record.state)
    check("status", e.status, record.status)
    check("iterations", e.iterations, record.iterations)
    if record.gate is None:
        if e.gate_supported is not None or e.substance is not None:
            out.append("gate: expected a verdict, got none")
    else:
        check("gate.supported", e.gate_supported, record.gate.supported)
        check("gate.substance", e.substance, record.gate.substance)
    pack_rules = {r["id"] for r in record.pack_snapshot.get("rules", [])}
    audited = {f.iteration for f in record.findings}
    for it, rules in sorted(e.failing_rules.items()):
        unknown = sorted(set(rules) - pack_rules)
        if unknown:
            out.append(f"failing_rules[{it}]: not in pack: {', '.join(unknown)}")
        if it not in audited:
            out.append(f"failing_rules[{it}]: no audit ran for iteration {it}")
            continue
        actual = sorted(
            f.rule_id for f in record.findings if f.iteration == it and f.verdict is Verdict.FAIL
        )
        check(f"failing_rules[{it}]", sorted(rules), actual)
    if e.open_findings is not None:
        actual_open = sorted(record.report.metadata.open_findings) if record.report else []
        check("open_findings", sorted(e.open_findings), actual_open)
    if e.digested is not None:
        check("digested", sorted(e.digested), sorted(d.source_id for d in record.digests))
    return out


def _show(value: object) -> str:
    if hasattr(value, "value"):  # enums print as their wire value
        return repr(value.value)
    return repr(value)
```

Check the `failing_rules[4]` ordering in `test_compare_reports_every_mismatch`: the loop above appends the "not in pack" line before the "expected/got" line for iteration 0, then handles iteration 4; the test's list is in that order.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_scenarios.py -q --no-cov -p no:cacheprovider`
Expected: all pass (nine scenarios plus five unit tests). The `_show` helper makes enum mismatches print as `'findings_open'`, matching the test's expected strings; booleans and ints print via `repr`.

- [ ] **Step 7: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 8: Commit**

Stage `corelata/scenarios.py`, `corelata/ingest/units.py`, `corelata/testing/sources.py`, `tests/fixtures/scenarios/`, `tests/test_scenarios.py` and commit with message `feat(scenarios): YAML scenario fixtures, runner and comparison; nine fixtures`.

### Task 9: Chunked digests and context budget checks (M1 carry-over, final review Important #5)

**Files:**
- Modify: `engine/corelata/config.py` (`PipelineConfig.digest_chunk_tokens`)
- Modify: `engine/corelata/stages/digest.py` (`chunk_units`, per-unit oversize check, chunked `run_digests`)
- Modify: `engine/corelata/pipeline.py` (`_check_source_sizes` → `_check_budgets`; ladder halves the chunk size too)
- Modify: `engine/corelata.example.yaml` (document the key)
- Modify: `engine/tests/stages/test_digest.py` (append), `engine/tests/test_pipeline.py` (rewrite one test), `engine/tests/test_config.py` (append one test)

**Interfaces:**
- Consumes: `StageContext`, `estimate_tokens`, `StageError`, `AgentRunner.run`, `DigestOutput`, `Digest`.
- Produces: `PipelineConfig.digest_chunk_tokens: int = Field(4000, ge=500)`; `chunk_units(source: Source, budget_tokens: int, bytes_per_token: float) -> list[list[int]]` (unit indexes per chunk, document order, greedy); `check_unit_sizes(ctx: StageContext) -> None` raising `StageError("ingesting", ...)` for a unit over the chunk budget in any source that needs a digest; `run_digests` makes one model call per chunk and concatenates the sections in order. The pipeline's `_check_budgets` raises `StageError("ingesting", ...)` when `digest_threshold_tokens` or `digest_chunk_tokens` exceeds `writer context_window - 2000`.

Why both checks: with chunking, no digest request can exceed the chunk budget, and a non-digested source is at most `digest_threshold_tokens`; the pipeline check makes both bounds smaller than the writer's window, so a run can no longer be doomed by its config, and the per-unit check catches the one thing chunking cannot split.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/stages/test_digest.py`:

```python
from corelata.stages.context import StageError
from corelata.stages.digest import check_unit_sizes, chunk_units


def test_chunk_units_packs_greedily_in_document_order():
    src = text_source("src1", "a" * 10, "b" * 10, "c" * 10, "d" * 25, "e" * 10)
    # bytes_per_token 1.0 → tokens == characters
    assert chunk_units(src, 25, 1.0) == [[0, 1], [2], [3], [4]]
    assert chunk_units(src, 1000, 1.0) == [[0, 1, 2, 3, 4]]
    assert chunk_units(text_source("src1", "x"), 1, 1.0) == [[0]]


async def test_oversized_source_is_digested_in_several_calls(make_ctx, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500, "digest_chunk_tokens": 500})
    ctx = make_ctx(big_source(), cfg=cfg)
    digests = await run_digests(ctx)
    digest_calls = [r for r in fake_backend.requests if '"task": "digest"' in r.messages[1].content]
    assert len(digest_calls) == 2
    d = digests["src1"]
    covered = [r for s in d.sections for r in s.unit_refs]
    assert covered == ctx.sources[0].refs()
    assert all(rec.role == "writer" for rec in ctx.runner.log.records)


async def test_unit_larger_than_chunk_budget_fails_fast(make_ctx, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500, "digest_chunk_tokens": 500})
    huge = text_source("src1", *[f"Paragraph {i} on Varna." for i in range(30)], "Z" * 5000)
    ctx = make_ctx(huge, cfg=cfg)
    with pytest.raises(StageError, match=r"ingesting: unit src1/u31 \(para 31\) in source 'src1.txt'") as e:
        check_unit_sizes(ctx)
    assert "exceeds pipeline.digest_chunk_tokens (500)" in str(e.value)
    with pytest.raises(StageError):
        await run_digests(ctx)
    assert fake_backend.requests == []
    small = make_ctx(text_source("src1", "Z" * 5000), cfg=make_config())  # below the threshold
    check_unit_sizes(small)  # not digested, so not checked here
```

In `engine/tests/test_pipeline.py`, replace `test_oversized_source_fails_fast_before_any_model_call` with:

```python
async def test_budgets_over_the_writer_window_fail_fast_before_any_model_call(
    run, make_config, fake_backend
):
    cfg = make_config(
        models={
            "model-a": {"backend": "fake", "context_window": 2048},
            "model-b": {"backend": "fake", "context_window": 2048},
        }
    )
    rec = await run(cfg=cfg)
    assert rec.state is RunState.FAILED
    assert rec.error == (
        "ingesting: pipeline.digest_threshold_tokens (6000) and pipeline.digest_chunk_tokens "
        "(4000) must be at most 48 for the writer model's context window (2048); lower them"
    )
    assert [s.stage for s in rec.stages] == ["ingesting"] and not rec.stages[0].ok
    assert fake_backend.requests == []
    ok = make_config(
        models={
            "model-a": {"backend": "fake", "context_window": 4096},
            "model-b": {"backend": "fake", "context_window": 4096},
        },
        pipeline={"digest_threshold_tokens": 2000, "digest_chunk_tokens": 2000},
    )
    assert (await run(cfg=ok)).state is RunState.COMPLETED


async def test_oversize_ladder_halves_chunk_size_too(run, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 600, "digest_chunk_tokens": 600})
    big = text_source(
        "src1", *[f"Paragraph {i} on Varna port capacity for shippers." for i in range(40)]
    )
    fake_backend.script("gate", ContextOverflowError("too long"))
    rec = await run(big, cfg=cfg)
    assert rec.state is RunState.COMPLETED
    digest_calls = [
        r for r in fake_backend.requests if '"task": "digest"' in r.messages[1].content
    ]
    # first pass: 40 units of ~55 bytes ≈ 880 tokens → 2 chunks of 600; after halving to 300 → 3
    assert len(digest_calls) == 5
```

Append to `engine/tests/test_config.py`:

```python
def test_pipeline_digest_chunk_tokens_default_and_floor():
    assert CorelataConfig.model_validate(BASE_CONFIG).pipeline.digest_chunk_tokens == 4000
    with pytest.raises(ValidationError):
        CorelataConfig.model_validate({**BASE_CONFIG, "pipeline": {"digest_chunk_tokens": 10}})
```

Check `tests/test_config.py`'s existing imports and add `pytest`, `ValidationError` (from `pydantic`), `BASE_CONFIG` (from `tests.conftest`) and `CorelataConfig` if they are not already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/stages/test_digest.py tests/test_pipeline.py tests/test_config.py -q --no-cov`
Expected: FAIL — `chunk_units`/`check_unit_sizes` missing; `digest_chunk_tokens` rejected as an extra field; the two pipeline tests fail on error text / call counts.

- [ ] **Step 3: Add the config key**

In `engine/corelata/config.py`, `PipelineConfig` becomes:

```python
class PipelineConfig(_Strict):
    """Spec §7.2, §7.4 and §5.4."""

    max_iterations: int = Field(2, ge=0, le=10)
    digest_threshold_tokens: int = Field(6000, ge=500)
    digest_chunk_tokens: int = Field(4000, ge=500)  # units per digest request, at most this many
    gate_unit_budget_tokens: int = Field(12000, ge=500)
```

In `engine/corelata.example.yaml`, after the `digest_threshold_tokens` line add:

```yaml
  digest_chunk_tokens: 4000        # a long source is digested in requests of at most this many tokens
```

- [ ] **Step 4: Chunk the digests**

Replace `engine/corelata/stages/digest.py` with:

```python
"""Digests for sources too long to show a model in full (spec §5.4). The writer role
summarises each source in chunks that fit pipeline.digest_chunk_tokens; sections are
concatenated in document order and traced like any stage output."""

from collections.abc import Callable

from corelata.schema import Digest, DigestOutput, DigestSection, Source
from corelata.stages.context import StageContext, StageError, estimate_tokens


def needs_digest(ctx: StageContext, source: Source) -> bool:
    text = "\n".join(u.text for u in source.units)
    threshold = ctx.cfg.pipeline.digest_threshold_tokens
    return estimate_tokens(text, ctx.bytes_per_token("writer")) > threshold


def chunk_units(source: Source, budget_tokens: int, bytes_per_token: float) -> list[list[int]]:
    """Unit indexes grouped greedily in document order so each group fits the budget. A unit
    that alone exceeds the budget still gets its own group; check_unit_sizes refuses it first."""
    chunks: list[list[int]] = []
    current: list[int] = []
    spent = 0
    for i, unit in enumerate(source.units):
        cost = estimate_tokens(unit.text, bytes_per_token)
        if current and spent + cost > budget_tokens:
            chunks.append(current)
            current, spent = [], 0
        current.append(i)
        spent += cost
    if current:
        chunks.append(current)
    return chunks


def check_unit_sizes(ctx: StageContext) -> None:
    """Review Focus 6: a unit no digest request can hold fails the run before any model call."""
    budget = ctx.cfg.pipeline.digest_chunk_tokens
    per_token = ctx.bytes_per_token("writer")
    for source in ctx.sources:
        if not needs_digest(ctx, source):
            continue
        for ref, unit in zip(source.refs(), source.units, strict=True):
            tokens = estimate_tokens(unit.text, per_token)
            if tokens > budget:
                raise StageError(
                    "ingesting",
                    f"unit {ref} ({unit.locator}) in source '{source.name}' (~{tokens} tokens) "
                    f"exceeds pipeline.digest_chunk_tokens ({budget}); split the source",
                )


def _validator(source: Source, expected: list[str]) -> Callable[[DigestOutput], list[str]]:
    def validate(out: DigestOutput) -> list[str]:
        errors: list[str] = []
        seen: list[str] = []
        for s in out.sections:
            for r in s.unit_refs:
                if r not in expected:
                    errors.append(f"unknown ref '{r}' for source {source.id}")
                elif r in seen:
                    errors.append(f"ref '{r}' appears in more than one section")
                seen.append(r)
        missing = [r for r in expected if r not in seen]
        if missing:
            errors.append(f"units not covered: {', '.join(missing[:5])}")
        return errors

    return validate


async def run_digests(ctx: StageContext) -> dict[str, Digest]:
    check_unit_sizes(ctx)
    digests: dict[str, Digest] = {}
    per_token = ctx.bytes_per_token("writer")
    for source in ctx.sources:
        if not needs_digest(ctx, source):
            continue
        refs = source.refs()
        sections: list[DigestSection] = []
        chunks = chunk_units(source, ctx.cfg.pipeline.digest_chunk_tokens, per_token)
        for n, chunk in enumerate(chunks, start=1):
            expected = [refs[i] for i in chunk]
            out = await ctx.runner.run(
                role="writer",
                model_key=ctx.model_key("writer"),
                prompt_id="digest",
                prompt_vars={},
                payload={
                    "task": "digest",
                    "source": {"id": source.id, "name": source.name},
                    "part": {"index": n, "of": len(chunks)},
                    "units": [{"ref": refs[i], "text": source.units[i].text} for i in chunk],
                },
                output_type=DigestOutput,
                validate=_validator(source, expected),
            )
            sections.extend(out.sections)
        digests[source.id] = Digest(source_id=source.id, sections=sections)
    return digests
```

The existing test `test_digest_validator_rejects_gaps_and_foreign_refs` scripts two bad replies for one call; with the default `digest_chunk_tokens` (4000) the 40-paragraph `big_source` is still one chunk, so it keeps passing.

- [ ] **Step 5: Replace the pipeline's size check and extend the ladder**

In `engine/corelata/pipeline.py`:

Replace `_check_source_sizes` with:

```python
    def _check_budgets(self) -> None:
        """A non-digested source is at most digest_threshold_tokens and a digest request at most
        digest_chunk_tokens; both must leave room in the writer's window (spec §7.4, §7.5)."""
        writer = self.ctx.model_key("writer")
        window = self.ctx.cfg.models[writer].context_window
        limit = window - 2000
        p = self.ctx.cfg.pipeline
        if p.digest_threshold_tokens > limit or p.digest_chunk_tokens > limit:
            raise StageError(
                "ingesting",
                f"pipeline.digest_threshold_tokens ({p.digest_threshold_tokens}) and "
                f"pipeline.digest_chunk_tokens ({p.digest_chunk_tokens}) must be at most {limit} "
                f"for the writer model's context window ({window}); lower them",
            )
```

and in `_ingest` call `self._check_budgets()` instead of `self._check_source_sizes()`.

In `stage()`, the oversize branch currently halves only `digest_threshold_tokens`; replace the `update={"digest_threshold_tokens": ...}` dict with:

```python
                            update={
                                "digest_threshold_tokens": max(
                                    500, self.ctx.cfg.pipeline.digest_threshold_tokens // 2
                                ),
                                "digest_chunk_tokens": max(
                                    500, self.ctx.cfg.pipeline.digest_chunk_tokens // 2
                                ),
                            }
```

Remove the now-unused `estimate_tokens` import from `pipeline.py` if ruff flags it.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/stages/test_digest.py tests/test_pipeline.py tests/test_config.py tests/test_scenarios.py -q --no-cov`
Expected: all pass. If `test_oversize_ladder_halves_chunk_size_too` disagrees on the call count, print `[len(c) for c in chunk_units(...)]` for 600 and 300 budgets with `bytes_per_token=2.5` and set the assertion to the arithmetic you can show — the point under test is that the count *rises* after halving; record the computed numbers in your report.

- [ ] **Step 7: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 8: Commit**

Stage `corelata/config.py`, `corelata/stages/digest.py`, `corelata/pipeline.py`, `corelata.example.yaml`, `tests/stages/test_digest.py`, `tests/test_pipeline.py`, `tests/test_config.py` and commit with message `feat(digest): chunk long sources by digest_chunk_tokens; fail fast on budgets the writer window cannot hold`.

### Task 10: Writer unit budget (spec §7.4 amendment; M1 "Spec issues to raise" #1)

**Files:**
- Modify: `engine/corelata/config.py` (`PipelineConfig.writer_unit_budget_tokens`)
- Modify: `engine/corelata/stages/write.py` (`select_writer_units` replaces `_cited_refs`)
- Modify: `engine/corelata/pipeline.py` (`_check_budgets` covers the new key)
- Modify: `engine/corelata.example.yaml`
- Modify: `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§7.4 writer row; §11 pipeline block)
- Modify: `engine/tests/stages/test_write.py` (append), `engine/tests/test_pipeline.py` (one assertion), `engine/tests/test_config.py` (append)

**Interfaces:**
- Consumes: `StageContext` (`gate_evidence`, `digests`, `sources`, `index`, `bytes_per_token`), `estimate_tokens`.
- Produces: `PipelineConfig.writer_unit_budget_tokens: int = Field(16000, ge=500)`; `select_writer_units(ctx: StageContext) -> list[str]` — gate-cited refs first (gate order, unknown refs dropped, always included), then every remaining unit of every non-digested source in document order while the budget holds; units of digested sources never appear (the digest stands in for them).

**The ruling this task implements** (controller, M2 planning): M1 followed spec §7.4 literally — the writer saw full text only for units the gate cited — so a mid-sized source the gate did not cite was invisible to the writer yet had to be listed and either cited or set aside (`icd203.as.4`). Real-model runs would trend to `findings_open` for a reason no model could fix. The amendment gives the writer everything that is not digested, gate-cited first, under an explicit budget. Cost if wrong: more writer tokens per call, bounded by the new key, revertible by setting the budget low.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/stages/test_write.py`:

```python
from corelata.stages.write import select_writer_units


def test_select_writer_units_cited_first_then_rest_within_budget(make_ctx, make_config):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link.", "Grain silo."))
    ctx.gate_evidence = ["src1/u3", "src2/u1", "src9/u1"]
    assert select_writer_units(ctx) == ["src1/u3", "src2/u1", "src1/u1", "src1/u2", "src2/u2"]
    tight = make_config(pipeline={"writer_unit_budget_tokens": 500})
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link.", "Grain silo."), cfg=tight)
    ctx.gate_evidence = ["src1/u3", "src2/u1"]
    # 500 tokens at 2.5 bytes/token is 1250 bytes: enough for every unit here, so the budget
    # does not bite; shrink the model's bytes_per_token to make it bite deterministically
    ctx.cfg = ctx.cfg.model_copy(
        update={
            "models": {
                k: m.model_copy(update={"bytes_per_token": 0.01}) for k, m in ctx.cfg.models.items()
            }
        }
    )
    ctx.runner.cfg = ctx.cfg
    # every unit now costs thousands of tokens: cited refs are always included, nothing else fits
    assert select_writer_units(ctx) == ["src1/u3", "src2/u1"]


async def test_writer_sees_uncited_units_of_non_digested_sources(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link."))
    ctx.gate_evidence = ["src1/u1"]
    await run_writer(ctx, iteration=0, prior=None, findings=[])
    rec = ctx.runner.log.records[0]
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert [u["ref"] for u in payload["units"]] == ["src1/u1", "src1/u2", "src1/u3", "src2/u1"]


async def test_writer_never_sees_units_of_digested_sources(make_ctx, make_config):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    long = text_source("src2", *[f"Paragraph {i} about Varna port finance." for i in range(40)])
    ctx = make_ctx(text_source("src1", *PORT), long, cfg=cfg)
    from corelata.stages.digest import run_digests

    ctx.digests = await run_digests(ctx)
    ctx.gate_evidence = ["src1/u2", "src2/u5"]
    assert select_writer_units(ctx) == ["src1/u2", "src2/u5", "src1/u1", "src1/u3"]
```

(`text_source`, `PORT`, `json`, `run_writer` are already imported in that file; the gate-cited `src2/u5` stays because the gate asked for it, even though its source is digested.)

In `engine/tests/test_pipeline.py`, `test_budgets_over_the_writer_window_fail_fast_before_any_model_call` (Task 9): change the expected error to

```python
    assert rec.error == (
        "ingesting: pipeline.digest_threshold_tokens (6000), pipeline.digest_chunk_tokens (4000) "
        "and pipeline.writer_unit_budget_tokens (16000) must each be at most 48 for the writer "
        "model's context window (2048); lower them"
    )
```

and add `"writer_unit_budget_tokens": 2000` to the `ok` config's `pipeline` dict.

Append to `engine/tests/test_config.py`:

```python
def test_pipeline_writer_unit_budget_default_and_floor():
    assert CorelataConfig.model_validate(BASE_CONFIG).pipeline.writer_unit_budget_tokens == 16000
    with pytest.raises(ValidationError):
        CorelataConfig.model_validate(
            {**BASE_CONFIG, "pipeline": {"writer_unit_budget_tokens": 10}}
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/stages/test_write.py tests/test_pipeline.py tests/test_config.py -q --no-cov`
Expected: FAIL — `select_writer_units` missing; `writer_unit_budget_tokens` rejected; error text differs.

- [ ] **Step 3: Implement**

`engine/corelata/config.py`, `PipelineConfig` gains, after `digest_chunk_tokens`:

```python
    writer_unit_budget_tokens: int = Field(16000, ge=500)  # full-text units the writer sees
```

`engine/corelata/stages/write.py`: replace `_cited_refs` with

```python
def select_writer_units(ctx: StageContext) -> list[str]:
    """Spec §7.4 (amended in M2): the gate's evidence first, then every other unit of every
    non-digested source in document order, until pipeline.writer_unit_budget_tokens is spent.
    Digested sources are represented by their digests, never by their units."""
    chosen = [r for r in ctx.gate_evidence if ctx.index.has(r)]
    seen = set(chosen)
    bpt = ctx.bytes_per_token("writer")
    spent = sum(estimate_tokens(ctx.index.text(r), bpt) for r in chosen)
    budget = ctx.cfg.pipeline.writer_unit_budget_tokens
    for source in ctx.sources:
        if source.id in ctx.digests:
            continue
        for ref in source.refs():
            if ref in seen:
                continue
            cost = estimate_tokens(ctx.index.text(ref), bpt)
            if spent + cost > budget:
                return chosen
            chosen.append(ref)
            seen.add(ref)
            spent += cost
    return chosen
```

add `estimate_tokens` to the `corelata.stages.context` import, and in `run_writer` replace `ctx.unit_payload(_cited_refs(ctx))` with `ctx.unit_payload(select_writer_units(ctx))`.

`engine/corelata/pipeline.py`, `_check_budgets` becomes:

```python
    def _check_budgets(self) -> None:
        """Everything the writer may receive in full must leave room in its window (spec §7.4,
        §7.5): a non-digested source (≤ digest_threshold_tokens), a digest request
        (≤ digest_chunk_tokens) and the writer's unit budget."""
        writer = self.ctx.model_key("writer")
        window = self.ctx.cfg.models[writer].context_window
        limit = window - 2000
        p = self.ctx.cfg.pipeline
        budgets = (p.digest_threshold_tokens, p.digest_chunk_tokens, p.writer_unit_budget_tokens)
        if any(b > limit for b in budgets):
            raise StageError(
                "ingesting",
                f"pipeline.digest_threshold_tokens ({p.digest_threshold_tokens}), "
                f"pipeline.digest_chunk_tokens ({p.digest_chunk_tokens}) and "
                f"pipeline.writer_unit_budget_tokens ({p.writer_unit_budget_tokens}) must each "
                f"be at most {limit} for the writer model's context window ({window}); lower them",
            )
```

`engine/corelata.example.yaml`, after the `digest_chunk_tokens` line:

```yaml
  writer_unit_budget_tokens: 16000 # full-text source units the writer sees: gate-cited first, then the rest
```

- [ ] **Step 4: Amend the spec**

In `docs/superpowers/specs/2026-10-12-corelata-v1-design.md`, replace the §7.4 writer row

```
| writer | template; resolved rules with `applies_to: writer`; lexicon; digests; full text of units the gate cited; prior conveyed draft and routed findings on iteration ≥ 1 |
```

with

```
| writer | template; resolved rules with `applies_to: writer`; lexicon; digests; full text of units the gate cited, then every other unit of non-digested sources in document order up to `pipeline.writer_unit_budget_tokens` (amended M2: the writer must be able to cite or set aside every listed source, so no non-digested source may be invisible to it); prior conveyed draft and routed findings on iteration ≥ 1 |
```

and in the §11 YAML block, after `  digest_threshold_tokens: 6000` add

```
  digest_chunk_tokens: 4000
  writer_unit_budget_tokens: 16000
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/stages/test_write.py tests/test_pipeline.py tests/test_config.py tests/test_scenarios.py tests/test_invariants.py -q --no-cov`
Expected: all pass. `test_writer_first_draft` (existing) asserts the writer's fact claims cite exactly `src1/u1` and `src1/u3`; it still holds because the synthetic writer builds fact claims from `gate_evidence`, not from the whole unit list.

- [ ] **Step 6: Lint and full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 7: Commit**

Stage `corelata/config.py`, `corelata/stages/write.py`, `corelata/pipeline.py`, `corelata.example.yaml`, `tests/stages/test_write.py`, `tests/test_pipeline.py`, `tests/test_config.py`, `../docs/superpowers/specs/2026-10-12-corelata-v1-design.md` and commit with message `feat(writer): give the writer all non-digested units within writer_unit_budget_tokens (spec §7.4 amendment)`.

### Task 11: Follow-ups ledger and M1 ledger reconciliation

**Files:**
- Create: `docs/m2-followups.md`
- Modify: `docs/m1-followups.md` (move the two carry-overs M2 closed, and the §7.4 issue it resolved, into a "Closed in M2" list)
- Modify: `README.md` (one line under "Development" pointing at the scenario fixtures)

**Interfaces:** none (documentation). This task has no test step; its check is that every claim in the two ledgers names something that exists in the tree after Tasks 1–10.

- [ ] **Step 1: Write the M2 follow-ups ledger**

Create `docs/m2-followups.md`:

```markdown
# M2 follow-ups

## Divergences from Coglossa

- None. M2 touched no module copied from Coglossa.

## Spec deviations

- §9 "if the profile names a `docx_reference`, its styles are used": true for `corelata run`
  (the loader resolves the path and the renderer takes it) but `corelata report RUN_DIR
  --format docx` cannot locate it from a run directory and renders with the neutral template
  unless `--docx-reference` is passed; it says so on stderr. The path is deliberately kept out
  of `pack_snapshot` and `pack_hash` so both stay identical across installs (§6.6). M3 should
  store the reference bytes (or their hash plus a copy under `storage`) with the run.
- §9 superscripts: HTML always carries `data-claim-ids` attributes (invisible) so the review UI
  can highlight provenance without re-rendering; the visible superscripts follow
  `--claim-ids` as specified.
- §7.4 writer row amended in M2 (Task 10): the writer receives all non-digested units within
  `pipeline.writer_unit_budget_tokens`, gate-cited first. Recorded in the spec itself.
- §7.5 oversize ladder now halves `digest_chunk_tokens` together with `digest_threshold_tokens`.
  It still cannot shrink an auditor or conveyor request (M1 "Spec issues to raise" #3, open).
- §6.6 `pack_hash` is now a key-sorted compact JSON dump (first 16 hex chars). Hashes of packs
  loaded by M1 differ from M2's; nothing persisted them yet.

## Should fix soon

- `corelata report` and the M3 API should render DOCX with the stored reference document, not
  the neutral fallback (see Spec deviations).
- `ResolvedPack.docx_reference_path` is an excluded pydantic field; when the shared foundation
  package is extracted, consider a separate "pack location" object instead of a field that is
  half in, half out of the model.
- Scenario fixtures cover the synthetic responder's markers only (UNSOURCED, UNFIXABLE, BADTERM,
  thin, rejected, digested). Add scenarios for conveyor-routed findings and for a profile with
  an added rule once the synthetic auditor can be steered to fail a conveyor-routed rule.
- `format_summary` prints durations from the frozen test clock as 0 ms; a real run shows real
  numbers. No test pins a non-zero duration.

## Spec issues still open from M1

- §7.2 loop-count wording ("iteration < max_iterations" vs "iteration == max_iterations →
  rendering"); M1/M2 implement `max_iterations` = number of revisions (default 2 → up to three
  audits). The scenario fixtures `unsourced-unfixable` and `max-iterations-zero` pin this.
- §7.5 ladder cannot shrink auditor/conveyor requests.

## Later

- `GET /runs/{id}/trace`, `/findings`, `/claims/{claim_id}` (M4a) should serve `TraceSummary`,
  `IterationFindings` and `ClaimProvenance` from `corelata.trace` unchanged; `draft_changes`
  backs the Process tab's draft-to-draft diff.
- `corelata bench` (M6) = `scenarios.load_scenarios` + `run_scenario` against a real backend +
  `compare`, aggregated into gate-agreement and rule-failure-agreement rates.
```

- [ ] **Step 2: Reconcile the M1 ledger**

In `docs/m1-followups.md`:

- Under **Should fix soon**, delete the two bullets ("Digest requests send a whole source in one call…" and "pack_hash follows YAML key order…").
- Under **Spec issues to raise**, delete the §7.4 bullet.
- Under **Later**, delete "DOCX/HTML render (M2)".
- Add at the end of the file:

```markdown
## Closed in M2

- Digest chunking (`pipeline.digest_chunk_tokens`) and per-unit oversize fail-fast.
- `pack_hash` is key-sorted and ignores excluded fields.
- §7.4 writer context amended: all non-digested units within `pipeline.writer_unit_budget_tokens`.
- HTML and DOCX renders; `corelata report` and `corelata trace`.
```

- [ ] **Step 3: README pointer**

In `README.md`, under `## Development`, add after the make line:

```markdown
Scenario fixtures (`engine/tests/fixtures/scenarios/*.yaml`) pin the pipeline's behaviour
against the synthetic model: sources, statement, expected gate verdict, failing rules per
iteration. Add one when you change what a run does.
```

- [ ] **Step 4: Verify the ledgers against the tree**

Run from `engine/`: `uv run corelata report --help && uv run corelata trace --help && ls tests/fixtures/scenarios | wc -l`
Expected: both help texts print; `9` scenario files.

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: clean; all pass; coverage ≥ 95%.

- [ ] **Step 5: Commit**

Stage `../docs/m2-followups.md`, `../docs/m1-followups.md`, `../README.md` and commit with message `docs: M2 follow-ups ledger; reconcile M1 ledger`.
