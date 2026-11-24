"""HTML ingestion (spec §4.1), also used for the XHTML chapters of EPUB files. Block-level
elements become blocks in document order: headings, paragraphs, list items, table cells,
footnotes and breaks. Inline markup is flattened to its text; the head, scripts, styles,
comments and note-reference markers are skipped. Text the page hides from its reader (the
`hidden` attribute, `aria-hidden="true"`, an inline `display:none` or `visibility:hidden`)
becomes blocks of its own marked hidden (CRL-137): the trace keeps them and no model reads them.
Stylesheets and classes are not evaluated, so text hidden only by a stylesheet stays visible."""

import re
from pathlib import Path
from typing import Any

import lxml.html
from lxml import etree

from corelata.ingest.base import file_sha256, is_scene_break, make_blocks, source_meta, strip_nul
from corelata.schema import BlockKind, SourceDocument

Item = tuple[BlockKind, str, str | None]

_SKIP = frozenset(
    {
        "head",
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "math",
        "iframe",
        "object",
        "select",
        "textarea",
        "button",
    }
)
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_KIND_OF_TAG = {
    **{h: BlockKind.HEADING for h in _HEADINGS},
    "li": BlockKind.LIST_ITEM,
    "td": BlockKind.TABLE_CELL,
    "th": BlockKind.TABLE_CELL,
}
_BLOCK_TAGS = _HEADINGS | {
    "html",
    "body",
    "p",
    "div",
    "section",
    "article",
    "aside",
    "header",
    "footer",
    "main",
    "nav",
    "blockquote",
    "pre",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "li",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "figure",
    "figcaption",
    "address",
    "details",
    "summary",
    "hgroup",
    "center",
    "form",
    "fieldset",
    "legend",
}
_FOOTNOTE_TYPES = frozenset({"footnote", "endnote", "rearnote", "note"})
_FOOTNOTE_ROLES = frozenset({"doc-footnote", "doc-endnote"})
_NOTEREF_TYPES = frozenset({"noteref"})
_LINE_BREAK = "\ue000"  # private-use char standing for <br> until whitespace is normalized
_WHITESPACE = re.compile(r"\s+")
_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_HIDDEN_STYLE = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*"
    r"(?:!\s*important\s*)?(?=;|$)",
    re.IGNORECASE,
)


def _tag(el: Any) -> str | None:
    if not isinstance(el.tag, str):
        return None  # a comment or processing instruction
    return el.tag.rsplit("}", 1)[-1].lower()


def _epub_types(el: Any) -> set[str]:
    return set((el.get("epub:type") or "").split())


def _is_footnote(el: Any) -> bool:
    return bool(_epub_types(el) & _FOOTNOTE_TYPES) or el.get("role") in _FOOTNOTE_ROLES


def _is_noteref(el: Any) -> bool:
    return bool(_epub_types(el) & _NOTEREF_TYPES) or el.get("role") == "doc-noteref"


def _is_hidden(el: Any) -> bool:
    """The element hides its content from the page's reader (CRL-137)."""
    if el.get("hidden") is not None:
        return True
    if (el.get("aria-hidden") or "").strip().casefold() == "true":
        return True
    return bool(_HIDDEN_STYLE.search(el.get("style") or ""))


def _clean(text: str) -> str:
    return strip_nul(text).replace(_LINE_BREAK, "")


def _normalize(text: str) -> str:
    lines = (_WHITESPACE.sub(" ", line).strip() for line in text.split(_LINE_BREAK))
    return "\n".join(line for line in lines if line)


class _Collector:
    def __init__(
        self, locator: str | None, kind: BlockKind = BlockKind.PARAGRAPH, *, hiding: bool = False
    ) -> None:
        self.locator = locator
        self.items: list[Item] = []
        self.hidden: set[int] = set()  # indexes of the items the page hides (CRL-137)
        self._buffer: list[str] = []
        self._kinds: list[BlockKind] = [kind]
        self._hiding = hiding  # collecting a hidden element's text
        self._pending: list[Item] = []  # hidden inline text, placed after its block

    def flush(self) -> None:
        text = _normalize("".join(self._buffer))
        self._buffer.clear()
        if text:
            kind = self._kinds[-1]
            if kind is BlockKind.PARAGRAPH and is_scene_break(text):
                kind = BlockKind.BREAK
            self.items.append((kind, text, self.locator))
        self._add_hidden(self._pending)
        self._pending = []

    def _add_hidden(self, items: list[Item]) -> None:
        for item in items:
            self.hidden.add(len(self.items))
            self.items.append(item)

    def _hide(self, el: Any, tag: str) -> None:
        """A hidden element's text as blocks of their own, kept out of the visible text around
        it: after the current block for an inline element, in place for a block."""
        inner = _Collector(self.locator, self._kinds[-1], hiding=True)
        inner.walk(el)
        inner.flush()
        if _is_footnote(el) or tag in _BLOCK_TAGS:
            self.flush()
            self._add_hidden(inner.items)
        else:
            self._pending.extend(inner.items)

    def walk(self, el: Any) -> None:
        tag = _tag(el)
        if tag is None or tag in _SKIP or _is_noteref(el):
            return  # the caller keeps the element's tail text
        if not self._hiding and _is_hidden(el):
            self._hide(el, tag)
            return
        if tag == "br":
            self._buffer.append(_LINE_BREAK)
            return
        if tag == "hr":
            self.flush()
            self.items.append((BlockKind.BREAK, "* * *", self.locator))
            return
        footnote = _is_footnote(el)
        block = footnote or tag in _BLOCK_TAGS
        if block:
            self.flush()
            outer = self._kinds[-1]
            if outer is not BlockKind.PARAGRAPH:
                kind = outer  # blocks nested in a heading, item, cell or note keep its kind
            else:
                kind = BlockKind.FOOTNOTE if footnote else _KIND_OF_TAG.get(tag, outer)
            self._kinds.append(kind)
        if tag == "pre":
            self._buffer.append(_clean(el.text_content()).replace("\n", _LINE_BREAK))
        else:
            if el.text:
                self._buffer.append(_clean(el.text))
            for child in el:
                self.walk(child)
                if child.tail:
                    self._buffer.append(_clean(child.tail))
        if block:
            self.flush()
            self._kinds.pop()


def parse_html(data: bytes) -> Any | None:
    """The document's root element, or None for an empty document. UTF-8 is assumed; bytes
    that are not valid UTF-8 go to lxml, which honours the document's declared charset."""
    source: str | bytes
    try:
        source = _XML_DECLARATION.sub("", data.decode("utf-8-sig"), count=1)
    except UnicodeDecodeError:
        source = data
    if not source.strip():
        return None
    try:
        return lxml.html.document_fromstring(source)
    except etree.ParserError:  # "Document is empty": only comments or whitespace
        return None


# `<meta>` names and properties that say when a page was issued and who issued it (CRL-96), in
# order of preference: the page's own date and author before its site's name.
_DATE_META = (
    "article:published_time",
    "date",
    "dc.date",
    "dc.date.issued",
    "dcterms.issued",
    "dcterms.date",
    "citation_publication_date",
    "article:modified_time",
)
_ORIGIN_META = (
    "author",
    "dc.creator",
    "dcterms.creator",
    "citation_author",
    "article:author",
    "dc.publisher",
    "dcterms.publisher",
    "publisher",
    "og:site_name",
)


def html_meta(root: Any) -> dict[str, str]:
    """The page's date and origin from its `<meta>` elements, as ingest hints (CRL-96)."""
    found: dict[str, str] = {}
    for el in root.iter("meta"):
        key = (el.get("name") or el.get("property") or "").strip().casefold()
        content = (el.get("content") or "").strip()
        if key and content:
            found.setdefault(key, content)
    date = next((found[k] for k in _DATE_META if k in found), None)
    origin = next((found[k] for k in _ORIGIN_META if k in found), None)
    return source_meta(date, origin)


def _collect(root: Any, locator: str | None) -> _Collector:
    collector = _Collector(locator)
    collector.walk(root)
    collector.flush()
    return collector


def collect_blocks(root: Any, locator: str | None) -> list[Item]:
    return _collect(root, locator).items


def html_document(data: bytes, source_path: str, sha256: str) -> SourceDocument:
    """An HTML document's blocks, hidden text marked (CRL-137), and its `<meta>` hints."""
    root = parse_html(data)
    if root is None:
        return SourceDocument(source_path=source_path, format="html", sha256=sha256, blocks=[])
    found = _collect(root, None)
    return SourceDocument(
        source_path=source_path,
        format="html",
        sha256=sha256,
        blocks=make_blocks(source_path, found.items, found.hidden),
        meta=html_meta(root),
    )


class HtmlIngestor:
    format = "html"
    extensions = (".html", ".htm", ".xhtml")

    def ingest(self, path: Path) -> SourceDocument:
        return html_document(path.read_bytes(), str(path), file_sha256(path))
