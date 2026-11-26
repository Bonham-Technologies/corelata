"""HTML render (spec §9): one self-contained file with inline CSS, nothing fetched from anywhere,
safe to open on an air-gapped network. Paragraphs and list items carry data-claim-ids so the
review screen can highlight provenance; the visible superscripts appear only on request.

The stylesheet is `templates/report.css`, and the document's one `<style>` element holds exactly
its text: the web build hashes the same file into the review frame's policy (`style-src
'sha256-…'`, CRL-23), so the report needs no `'unsafe-inline'`. The report has no `style`
attributes."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from corelata.render.outline import (
    APPENDIX_TITLE,
    DEGRADATION_TITLE,
    PRODUCTION_TITLE,
    QUOTES_TITLE,
    build_outline,
)
from corelata.schema import Finding, Report, Source
from corelata.standards.schema import ResolvedPack

_TEMPLATES = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
# Read as bytes and decoded, not read_text(): newline translation would change the hashed text.
REPORT_CSS = (_TEMPLATES / "report.css").read_bytes().decode("utf-8")


def render_html(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    with_claim_ids: bool = False,
    open_findings: list[Finding] | None = None,
    production: list[str] | None = None,
) -> str:
    blocks = build_outline(
        report, pack, sources, open_findings=open_findings, production=production
    )
    return _ENV.get_template("report.html.j2").render(
        report=report,
        meta=report.metadata,
        blocks=blocks,
        with_claim_ids=with_claim_ids,
        appendix_titles=(QUOTES_TITLE, DEGRADATION_TITLE, APPENDIX_TITLE, PRODUCTION_TITLE),
        css=Markup(REPORT_CSS),  # our own file: not escaped (its quotes must stay quotes)
    )
