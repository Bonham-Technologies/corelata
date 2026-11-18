"""Pick an ingestor by file extension; third parties add formats via corelata.ingestors."""

from importlib.metadata import entry_points
from pathlib import Path, PurePosixPath

from corelata.ingest.base import IngestError, Ingestor, UnsupportedFormatError
from corelata.ingest.docx import DocxIngestor
from corelata.ingest.html import HtmlIngestor
from corelata.ingest.markdown import MarkdownIngestor
from corelata.ingest.ocr import OcrSettings
from corelata.ingest.pdf import PdfIngestor
from corelata.ingest.tabular import CsvIngestor, JsonIngestor
from corelata.ingest.txt import TextIngestor
from corelata.schema import BlockKind, SourceDocument
from corelata.text import clean_text


def available_ingestors(ocr: OcrSettings | None = None) -> list[Ingestor]:
    """`ocr`: the settings of `ingest.ocr: auto`, or None when it is off."""
    ingestors: list[Ingestor] = [
        TextIngestor(),
        MarkdownIngestor(),
        DocxIngestor(),
        HtmlIngestor(),
        PdfIngestor(ocr),
        JsonIngestor(),
        CsvIngestor(),
    ]
    ingestors += [ep.load()() for ep in entry_points(group="corelata.ingestors")]
    return ingestors


def check_extension(name: str) -> None:
    """Fail fast on a file name no ingestor handles (uploads have no path to check)."""
    ext = PurePosixPath(name).suffix.lower()
    ingestors = available_ingestors()
    if not any(ext in i.extensions for i in ingestors):
        supported = sorted({e for i in ingestors for e in i.extensions})
        raise UnsupportedFormatError(
            f"unsupported file type '{ext or name}'; supported: {', '.join(supported)}"
        )


def check_supported(path: Path) -> None:
    """Fail fast on a missing file or an extension no ingestor handles."""
    if not path.is_file():
        raise IngestError(f"input file not found: {path}")
    check_extension(path.name)


def ingest_file(path: Path, *, ocr: OcrSettings | None = None) -> SourceDocument:
    check_supported(path)
    ext = path.suffix.lower()
    for ingestor in available_ingestors(ocr):
        if ext in ingestor.extensions:
            try:
                doc = ingestor.ingest(path)
            except OSError as e:
                raise IngestError(f"{path.name} cannot be read: {e.strerror or e}") from e
            except (IngestError, MemoryError):  # MemoryError: the server's state, not the file's
                raise
            except Exception as e:  # a parser's own failure is the file's: 422, not 500 (CRL-99)
                # The message goes to the client: name the file, never the server's path to it.
                detail = str(e).replace(str(path), path.name)
                reason = f"{type(e).__name__}: {detail}" if detail else type(e).__name__
                raise IngestError(f"{path.name} could not be read ({reason})") from e
            if any(clean_text(b.text) != b.text for b in doc.blocks):  # NUL, form feeds, ...
                blocks = [b.model_copy(update={"text": clean_text(b.text)}) for b in doc.blocks]
                doc = doc.model_copy(update={"blocks": blocks})
            if not any(b.kind is not BlockKind.BREAK and b.text.strip() for b in doc.blocks):
                raise IngestError(f"{path.name} contains no usable text")
            return doc
    raise AssertionError("unreachable")  # pragma: no cover - check_supported guarantees a match
