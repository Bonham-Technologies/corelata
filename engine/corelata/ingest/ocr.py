"""Offline OCR for scanned PDF pages (ingest.ocr, CRL-95). A page with an image and no text layer
is rendered with pdfium and read by Tesseract, a page per CPU at a time. Tesseract's TSV output
gives the page's paragraphs (its block and paragraph numbers) and a confidence for every word, so
each paragraph becomes one unit, as a text box does on a page with a text layer, and carries the
mean confidence of its words. Nothing leaves the machine: the language packs are files on disk."""

import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

TESSERACT = "tesseract"
DPI = 300  # Tesseract's own advice for printed text
MAX_SIDE_PX = 10_000  # a poster-sized page is rendered smaller, so memory stays bounded
PAGE_TIMEOUT_S = 300.0
_WORD = "5"  # TSV level of a word
# Tesseract skips a language it has no pack for and still exits 0 when another loaded; the
# page would then be read without it, so a missing pack is an error on every call.
_FAILED_LANGUAGE = re.compile(r"Failed loading language '([^']*)'")
# pdfium is not thread-safe: one page is rendered at a time; Tesseract runs in parallel.
_PDFIUM = threading.Lock()
# A page per CPU across every upload at once, so concurrent scans cannot oversubscribe the
# machine's CPUs or hold more page images in memory than it has CPUs.
_PAGE_SLOTS = threading.BoundedSemaphore(os.cpu_count() or 1)


@dataclass(frozen=True)
class OcrSettings:
    """`ingest.ocr: auto` with its languages, in Tesseract's codes joined by "+" on the call."""

    languages: tuple[str, ...] = ("eng",)


@dataclass(frozen=True)
class OcrParagraph:
    text: str  # the paragraph's lines joined by "\n", its words by " "
    confidence: float  # mean Tesseract word confidence, 0 to 100


class OcrError(Exception):
    """Text recognition could not read a page; the message is user-facing."""


class OcrUnavailableError(OcrError):
    """Tesseract is not installed on this machine."""


def tesseract_path() -> str | None:
    return shutil.which(TESSERACT)


def _call(args: list[str], *, data: bytes | None = None, timeout: float) -> str:
    """Run Tesseract; OMP_THREAD_LIMIT=1 since pages already run in parallel."""
    exe = tesseract_path()
    if exe is None:
        raise OcrUnavailableError("tesseract is not installed")
    try:
        done = subprocess.run(
            [exe, *args],
            input=data,
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise OcrError(f"tesseract did not finish within {timeout:g} s") from e
    stderr = done.stderr.decode("utf-8", "replace")
    if missing := _FAILED_LANGUAGE.findall(stderr):
        raise OcrError(f"tesseract has no language pack for {', '.join(missing)}")
    if done.returncode != 0:
        lines = stderr.strip().splitlines()
        raise OcrError(f"tesseract failed: {lines[-1] if lines else f'exit {done.returncode}'}")
    return done.stdout.decode("utf-8", "replace")


def tesseract_version() -> str:
    """ "5.3.0" from `tesseract --version`'s first line, "tesseract 5.3.0"."""
    first = _call(["--version"], timeout=30).strip().splitlines()[0]
    return first.removeprefix("tesseract").strip()


def installed_languages() -> list[str]:
    """`tesseract --list-langs`: a heading line, then one language code per line."""
    lines = _call(["--list-langs"], timeout=30).strip().splitlines()
    return sorted(line.strip() for line in lines[1:] if line.strip())


def render_page(path: Path, number: int, dpi: int = DPI) -> bytes:
    """Page `number` (from 1) as a greyscale PGM image, which Tesseract reads from stdin."""
    with _PDFIUM:
        pdf = pdfium.PdfDocument(path)
        try:
            page = pdf[number - 1]
            width, height = page.get_size()
            scale = min(dpi / 72, MAX_SIDE_PX / max(width, height, 1))
            bitmap = page.render(scale=scale, grayscale=True)
            w, h, stride = bitmap.width, bitmap.height, bitmap.stride
            raw = bytes(bitmap.buffer)
        finally:
            pdf.close()
    rows = b"".join(raw[i * stride : i * stride + w] for i in range(h))  # drop row padding
    return b"P5\n%d %d\n255\n" % (w, h) + rows


def read_image(image: bytes, languages: tuple[str, ...]) -> str:
    """Tesseract's TSV for one page image. The seam the tests replace."""
    args = ["stdin", "stdout", "-l", "+".join(languages), "--dpi", str(DPI), "tsv"]
    return _call(args, data=image, timeout=PAGE_TIMEOUT_S)


def parse_tsv(tsv: str) -> list[OcrParagraph]:
    """The page's paragraphs in reading order: words grouped by (block, paragraph) and by line."""
    paragraphs: dict[tuple[str, str], dict[str, list[str]]] = {}
    confidences: dict[tuple[str, str], list[float]] = {}
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != _WORD or not cols[11].strip():
            continue
        key = (cols[2], cols[3])
        paragraphs.setdefault(key, {}).setdefault(cols[4], []).append(cols[11].strip())
        confidences.setdefault(key, []).append(max(float(cols[10]), 0.0))
    return [
        OcrParagraph(
            text="\n".join(" ".join(words) for words in lines.values()),
            confidence=round(sum(confidences[key]) / len(confidences[key]), 1),
        )
        for key, lines in paragraphs.items()
    ]


def ocr_pages(path: Path, pages: list[int], settings: OcrSettings) -> dict[int, list[OcrParagraph]]:
    """Each of `pages` read by Tesseract, by page number. Raises OcrUnavailableError before any
    page is rendered when Tesseract is missing, and OcrError naming the first page that fails."""
    if tesseract_path() is None:
        raise OcrUnavailableError("tesseract is not installed")

    def one(number: int) -> list[OcrParagraph]:
        try:
            with _PAGE_SLOTS:
                return parse_tsv(read_image(render_page(path, number, DPI), settings.languages))
        except OcrError as e:
            raise OcrError(f"page {number}: {e}") from e

    workers = max(1, min(len(pages), os.cpu_count() or 1))  # a page per CPU at a time
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr")
    try:
        return dict(zip(pages, pool.map(one, pages), strict=True))
    finally:  # after a failure, the pages not yet started are not read
        pool.shutdown(wait=True, cancel_futures=True)
