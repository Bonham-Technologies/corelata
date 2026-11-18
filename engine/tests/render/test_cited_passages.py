"""CRL-93: the "Cited passages" appendix lists every quote, in the three renders alike."""

import io

from docx import Document

from corelata.render.docx import render_docx
from corelata.render.html import render_html
from corelata.render.markdown import render_markdown
from corelata.render.outline import QUOTES_TITLE, Bullets, Heading, build_outline, passage_lead
from corelata.schema import Quote
from tests.render.fixtures import PACK, SOURCES, make_report


def _quoted():
    report = make_report()
    claim = report.claims[0].model_copy(
        update={"quotes": [Quote(ref="src1/u1", text="Grew 40 percent")]}
    )
    return report.model_copy(update={"claims": [claim]})


def test_the_appendix_follows_the_body_and_appears_only_with_quotes():
    blocks = build_outline(_quoted(), PACK, SOURCES)
    at = next(i for i, b in enumerate(blocks) if isinstance(b, Heading) and b.text == QUOTES_TITLE)
    passages = blocks[at + 1]
    assert isinstance(passages, Bullets) and passages.role == "quotes"
    [item] = passages.items
    assert (item.lead, item.text, item.claim_ids) == (
        "c1 · a.txt, para 1",
        "“Grew 40 percent”",
        ("c1",),
    )
    plain = build_outline(make_report(), PACK, SOURCES)
    assert not any(isinstance(b, Heading) and b.text == QUOTES_TITLE for b in plain)


def test_a_passage_the_sources_do_not_hold_is_named_by_its_ref():
    assert passage_lead("c1", "src2/u9", {s.id: s for s in SOURCES}) == "c1 · src2/u9"
    assert passage_lead("c1", "src9/u1", {}) == "c1 · src9/u1"
    assert passage_lead("c1", "bad", {}) == "c1 · bad"


def test_markdown_html_and_docx_carry_the_appendix():
    report = _quoted()
    md = render_markdown(report, PACK, SOURCES)
    assert f"## {QUOTES_TITLE}\n\n- **c1 · a.txt, para 1** “Grew 40 percent”" in md
    html = render_html(report, PACK, SOURCES)
    assert '<section class="appendix">\n<h2>Cited passages</h2>' in html
    assert '<ul class="quotes">' in html
    doc = Document(io.BytesIO(render_docx(report, PACK, SOURCES)))
    texts = [p.text for p in doc.paragraphs]
    assert QUOTES_TITLE in texts
    assert any(t.endswith("c1 · a.txt, para 1 “Grew 40 percent”") for t in texts)
