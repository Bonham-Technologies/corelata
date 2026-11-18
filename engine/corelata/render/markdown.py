"""Markdown render of a Report: a pure function of report, resolved pack and sources (spec §9).
The layout comes from `render.outline`; this module only knows Markdown syntax."""

from corelata.render.outline import Bullets, Heading, Marking, Para, Title, build_outline
from corelata.schema import Finding, Report, Source
from corelata.standards.schema import ResolvedPack


def _ids(claim_ids: tuple[str, ...], on: bool) -> str:
    return f" ^[{', '.join(claim_ids)}]" if on and claim_ids else ""


def _refs(refs: tuple[int, ...]) -> str:
    """Source reference numbers as a superscript (Pandoc's `^…^`), right after the text."""
    return f"^{','.join(map(str, refs))}^" if refs else ""


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
            case Para(text, claim_ids, refs):
                out += [f"{text}{_refs(refs)}{_ids(claim_ids, with_claim_ids)}", ""]
            case Bullets(items, numbered=numbered):
                for n, item in enumerate(items, start=1):
                    mark = f"{n}." if numbered else "-"
                    lead = f"**{item.lead}** " if item.lead else ""
                    tail = f"{_refs(item.refs)}{_ids(item.claim_ids, with_claim_ids)}"
                    out.append(f"{mark} {lead}{item.text}{tail}")
                out.append("")
    return "\n".join(out).rstrip() + "\n"
