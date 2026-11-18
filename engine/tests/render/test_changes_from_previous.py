"""CRL-97: "Changes from previous analysis" follows the key judgments in the three renders, and
names each earlier report by its title and date, never its run id."""

import io
from datetime import UTC, datetime

from docx import Document

from corelata.render.docx import render_docx
from corelata.render.html import render_html
from corelata.render.markdown import render_markdown
from corelata.render.outline import SECTION_TITLES, Bullets, Heading, build_outline
from corelata.schema import ChangeKind, JudgmentChange, PriorReportRef
from tests.render.fixtures import NUMBERED, PACK, SOURCES, make_report

TITLE = SECTION_TITLES["changes_from_previous"]
EARLIER = PriorReportRef(
    run_id="r-earlier", title="Varna in 2025", accepted_at=datetime(2026, 11, 3, tzinfo=UTC)
)


def _changed(*, refs=(EARLIER,), run_id="r-earlier"):
    report = make_report(prior_reports=list(refs))
    change = JudgmentChange(
        prior_run_id=run_id,
        prior_judgment="Capacity will stall.",
        change=ChangeKind.CHANGED,
        explanation="New financing arrived.",
        claim_ids=["c1"],
    )
    return report.model_copy(update={"changes_from_previous": [change]})


def _headings(blocks):
    return [b.text for b in blocks if isinstance(b, Heading)]


def test_the_section_follows_the_key_judgments_and_names_the_earlier_report():
    blocks = build_outline(_changed(), PACK, SOURCES)
    headings = _headings(blocks)
    assert headings.index(TITLE) == headings.index("Key judgments") + 1
    at = next(i for i, b in enumerate(blocks) if isinstance(b, Heading) and b.text == TITLE)
    changes = blocks[at + 1]
    assert isinstance(changes, Bullets) and changes.role == "changes"
    [item] = changes.items
    assert item.lead == "Changed from earlier analysis."
    assert item.text == (
        "New financing arrived. Earlier judgment (“Varna in 2025”, 3 November 2026): "
        "“Capacity will stall.”"
    )
    assert item.claim_ids == ("c1",)
    assert TITLE not in _headings(build_outline(make_report(), PACK, SOURCES))


def test_an_unknown_earlier_report_and_numbered_headings():
    blocks = build_outline(_changed(refs=()), NUMBERED, SOURCES)
    heading = next(b for b in blocks if isinstance(b, Heading) and b.text == TITLE)
    assert heading.label == f"2. {TITLE}"
    item = next(b for b in blocks if isinstance(b, Bullets) and b.role == "changes").items[0]
    assert "(an earlier report)" in item.text


def test_a_template_without_key_judgments_still_shows_the_section_before_the_appendices():
    pack = PACK.model_copy(
        update={"template": PACK.template.model_copy(update={"section_order": ["title"]})}
    )
    blocks = build_outline(_changed(), pack, SOURCES)
    assert [b.kind for b in blocks] == ["marking", "title", "heading", "bullets", "marking"]
    assert _headings(blocks) == [TITLE]


def test_the_three_renders_show_it():
    report = _changed()
    md = render_markdown(report, PACK, SOURCES)
    assert f"## {TITLE}" in md and "**Changed from earlier analysis.**" in md
    html = render_html(report, PACK, SOURCES, with_claim_ids=True)
    assert f"<h2>{TITLE}</h2>" in html and '<ul class="changes">' in html
    assert "3 November 2026" in html and "r-earlier" not in html
    doc = Document(io.BytesIO(render_docx(report, PACK, SOURCES)))
    texts = [p.text for p in doc.paragraphs]
    assert TITLE in texts
    assert any(t.startswith("Changed from earlier analysis.") for t in texts)
