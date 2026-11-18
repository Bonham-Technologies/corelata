"""PDF ingestion (spec §4.1). Each text box pdfminer finds becomes a paragraph with its page
number. A page that shows an image but has no text is a scanned page: with `ingest.ocr: auto`
Tesseract reads it (`corelata.ingest.ocr`, CRL-95) and each paragraph it finds becomes a block
marked as OCR text with its mean confidence; with OCR off, ingest stops with needs_ocr. Bare page
numbers are dropped; blank pages are skipped."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTFigure, LTImage, LTTextContainer
from pdfminer.pdfdocument import PDFPasswordIncorrect

from corelata.ingest.base import IngestError, error_reason, file_sha256, strip_nul
from corelata.ingest.ocr import OcrError, OcrSettings, OcrUnavailableError, ocr_pages
from corelata.schema import Block, BlockKind, Provenance, SourceDocument

_HYPHENATED = re.compile(r"(\w)-\n(\w)")
_WHITESPACE = re.compile(r"\s+")
_PAGE_NUMBER = re.compile(r"^\d{1,4}$")


class NeedsOCRError(IngestError):
    def __init__(self, filename: str, pages: list[int]) -> None:
        self.pages = pages
        super().__init__(
            f"{filename} needs OCR (needs_ocr): page(s) {', '.join(map(str, pages))} have no "
            "text layer; scanned pages are not supported yet, use a PDF with a text layer"
        )


class OcrMissingError(NeedsOCRError):
    """ingest.ocr is auto, but this server has no Tesseract to read the scanned pages."""

    def __init__(self, filename: str, pages: list[int]) -> None:
        self.pages = pages
        IngestError.__init__(
            self,
            f"{filename} needs OCR (needs_ocr): page(s) {', '.join(map(str, pages))} have no "
            "text layer, and the text recognition program (tesseract) is not installed on the "
            "server; ask your administrator to run corelata doctor",
        )


def _join_hyphenated(match: re.Match[str]) -> str:
    before, after = match.group(1), match.group(2)
    return before + after if after.islower() else match.group(0)


def _clean(raw: str) -> str:
    text = _HYPHENATED.sub(_join_hyphenated, strip_nul(raw))
    return _WHITESPACE.sub(" ", text).strip()


def _walk(elements: Any) -> Iterator[Any]:
    for element in elements:
        yield element
        if isinstance(element, LTFigure):
            yield from _walk(element)


def _kept(text: str) -> bool:
    return bool(text) and not _PAGE_NUMBER.match(text)


def _page_content(page: Any) -> tuple[list[str], bool]:
    texts: list[str] = []
    has_image = False
    for element in _walk(page):
        if isinstance(element, LTTextContainer):
            text = _clean(element.get_text())
            if _kept(text):
                texts.append(text)
        elif isinstance(element, LTImage):
            has_image = True
    return texts, has_image


class PdfIngestor:
    format = "pdf"
    extensions = (".pdf",)

    def __init__(self, ocr: OcrSettings | None = None) -> None:
        self.ocr = ocr  # None: ingest.ocr is off

    def ingest(self, path: Path) -> SourceDocument:
        # per page: (text, OCR confidence or None for the text layer's own text)
        pages: dict[int, list[tuple[str, float | None]]] = {}
        scanned: list[int] = []
        try:
            for number, page in enumerate(
                extract_pages(path, laparams=LAParams(all_texts=True)), start=1
            ):
                texts, has_image = _page_content(page)
                if not texts and has_image:
                    scanned.append(number)
                pages[number] = [(text, None) for text in texts]
        except PDFPasswordIncorrect as e:
            raise IngestError(
                f"{path.name} is password-protected; remove the password and retry"
            ) from e
        except OSError:
            raise  # the registry reports "cannot be read"
        except Exception as e:  # pdfminer raises many unrelated types for damaged files
            raise IngestError(
                f"{path.name} is not a readable PDF file ({type(e).__name__}: {error_reason(e)})"
            ) from e
        if not pages:
            raise IngestError(f"{path.name} is not a readable PDF file (it has no pages)")
        if scanned:
            pages.update(self._recognise(path, scanned))
        blocks: list[Block] = []
        for number, texts in pages.items():
            for text, confidence in texts:
                index = len(blocks)
                blocks.append(
                    Block(
                        id=f"b{index + 1}",
                        kind=BlockKind.PARAGRAPH,
                        text=text,
                        provenance=Provenance(
                            source_path=str(path),
                            index=index,
                            page=number,
                            locator=f"page {number}",
                            ocr=confidence is not None,
                            ocr_confidence=confidence,
                        ),
                    )
                )
        return SourceDocument(
            source_path=str(path), format=self.format, sha256=file_sha256(path), blocks=blocks
        )

    def _recognise(
        self, path: Path, scanned: list[int]
    ) -> dict[int, list[tuple[str, float | None]]]:
        if self.ocr is None:
            raise NeedsOCRError(path.name, scanned)
        try:
            found = ocr_pages(path, scanned, self.ocr)
        except OcrUnavailableError as e:
            raise OcrMissingError(path.name, scanned) from e
        except OcrError as e:
            raise IngestError(f"{path.name}: text recognition failed on {e}") from e
        return {
            number: [(text, p.confidence) for p in paragraphs if _kept(text := _clean(p.text))]
            for number, paragraphs in found.items()
        }
