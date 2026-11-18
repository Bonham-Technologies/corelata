"""The OCR seam (CRL-95): Tesseract is replaced by small scripts, so these run anywhere; the
one test against the real program is in test_pdf.py."""

import stat
import threading

import pytest

from corelata.ingest import ocr
from corelata.ingest.ocr import OcrError, OcrParagraph, OcrSettings, OcrUnavailableError
from corelata.testing.pdf import make_pdf

HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
)


def _word(block, par, line, word, conf, text):
    return f"5\t1\t{block}\t{par}\t{line}\t{word}\t0\t0\t1\t1\t{conf}\t{text}"


def tsv(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def _fake_tesseract(tmp_path, monkeypatch, body):
    """A `tesseract` that runs `body` (sh), found where shutil.which would find the real one."""
    exe = tmp_path / "tesseract"
    exe.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(ocr, "tesseract_path", lambda: str(exe))
    return exe


def test_parse_tsv_groups_words_into_paragraphs_with_their_mean_confidence():
    out = ocr.parse_tsv(
        tsv(
            "1\t1\t0\t0\t0\t0\t0\t0\t2550\t3300\t-1\t",  # the page: not a word
            "2\t1\t1\t0\t0\t0\t0\t0\t10\t10\t-1\t",
            _word(1, 1, 1, 1, "90.0", "Une"),
            _word(1, 1, 1, 2, "80.0", "conti-"),
            _word(1, 1, 2, 1, "70.0", "nue"),
            _word(1, 1, 2, 2, "-1", " "),  # an empty word is left out, with its confidence
            _word(1, 2, 1, 1, "-1", "seule"),  # Tesseract's -1 counts as 0
            _word(2, 1, 1, 1, "95.55", "12"),
            "5\t1\t2",  # a cut row
            "",
        )
    )
    assert out == [
        OcrParagraph("Une conti-\nnue", 80.0),
        OcrParagraph("seule", 0.0),
        OcrParagraph("12", 95.5),
    ]
    assert ocr.parse_tsv(HEADER) == [] and ocr.parse_tsv("") == []


def test_render_page_gives_a_greyscale_pgm_of_the_page(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf([["x"], ["Page two."]]))
    image = ocr.render_page(path, 2, dpi=72)
    assert image.startswith(b"P5\n612 792\n255\n")
    assert len(image) == len(b"P5\n612 792\n255\n") + 612 * 792
    assert min(image[16:]) < 128 < max(image[16:])  # some ink on white
    monkeypatch.setattr(ocr, "MAX_SIDE_PX", 396)  # a poster is rendered smaller
    assert ocr.render_page(path, 1).startswith(b"P5\n306 396\n255\n")


def test_read_image_sends_the_image_and_languages_to_tesseract(tmp_path, monkeypatch):
    args = tmp_path / "args"
    seen = tmp_path / "stdin"
    _fake_tesseract(
        tmp_path,
        monkeypatch,
        f'echo "$@" > {args}; echo "$OMP_THREAD_LIMIT" >> {args}; cat > {seen}; echo "TSV"',
    )
    assert ocr.read_image(b"P5 image", ("eng", "fra")) == "TSV\n"
    assert args.read_text().split("\n")[:2] == [
        "stdin stdout -l eng+fra --dpi 300 tsv",
        "1",  # pages run in parallel, so each Tesseract keeps to one thread
    ]
    assert seen.read_bytes() == b"P5 image"


def test_tesseract_failures_name_the_cause(tmp_path, monkeypatch):
    _fake_tesseract(
        tmp_path,
        monkeypatch,
        'echo "warning" >&2; echo "Failed loading language \'xx\'" >&2; exit 1',
    )
    with pytest.raises(OcrError, match=r"^tesseract has no language pack for xx$"):
        ocr.read_image(b"", ("xx",))
    # with another language loaded Tesseract reads the page without the missing one and exits
    # 0: that is still an error, or the source would name a language its text was not read in
    _fake_tesseract(
        tmp_path,
        monkeypatch,
        "echo \"Failed loading language 'fra'\" >&2; echo \"Failed loading language 'deu'\" >&2; "
        'echo "TSV"',
    )
    with pytest.raises(OcrError, match=r"^tesseract has no language pack for fra, deu$"):
        ocr.read_image(b"", ("eng", "fra", "deu"))
    _fake_tesseract(tmp_path, monkeypatch, 'echo "noise" >&2; echo "Could not init" >&2; exit 1')
    with pytest.raises(OcrError, match=r"^tesseract failed: Could not init$"):
        ocr.read_image(b"", ("eng",))
    _fake_tesseract(tmp_path, monkeypatch, "exit 3")
    with pytest.raises(OcrError, match=r"^tesseract failed: exit 3$"):
        ocr.read_image(b"", ("eng",))
    _fake_tesseract(tmp_path, monkeypatch, "exec sleep 5")
    monkeypatch.setattr(ocr, "PAGE_TIMEOUT_S", 0.2)
    with pytest.raises(OcrError, match=r"^tesseract did not finish within 0.2 s$"):
        ocr.read_image(b"", ("eng",))
    monkeypatch.setattr(ocr, "tesseract_path", lambda: None)
    with pytest.raises(OcrUnavailableError, match="tesseract is not installed"):
        ocr.read_image(b"", ("eng",))


def test_version_and_installed_languages(tmp_path, monkeypatch):
    _fake_tesseract(
        tmp_path,
        monkeypatch,
        'if [ "$1" = --version ]; then printf "tesseract 5.3.0\\n leptonica-1.82.0\\n"; '
        'else printf "List of available languages in \\"/usr/share/tessdata/\\" (3):\\n'
        'osd\\nfra\\n\\neng\\n"; fi',
    )
    assert ocr.tesseract_version() == "5.3.0"
    assert ocr.installed_languages() == ["eng", "fra", "osd"]


def test_tesseract_path_is_looked_up_on_the_path(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda name: f"/opt/bin/{name}")
    assert ocr.tesseract_path() == "/opt/bin/tesseract"


def test_ocr_pages_reads_every_page_in_parallel_and_keys_them_by_number(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf([["one"], ["two"], ["three"]]))
    monkeypatch.setattr(ocr, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr, "DPI", 20)
    threads, calls = set(), []

    def read(image, languages):
        threads.add(threading.current_thread().name)
        calls.append(languages)
        size = image.split(b"\n")[1]
        return tsv(_word(1, 1, 1, 1, "50", size.decode().replace(" ", "x")))

    monkeypatch.setattr(ocr, "read_image", read)
    monkeypatch.setattr(ocr.os, "cpu_count", lambda: None)  # unknown: one page at a time
    out = ocr.ocr_pages(path, [3, 1], OcrSettings(languages=("deu",)))
    assert list(out) == [3, 1]
    assert out[3] == [OcrParagraph("170x220", 50.0)]
    assert calls == [("deu",), ("deu",)] and len(threads) == 1
    assert all(name.startswith("ocr") for name in threads)


def test_ocr_pages_needs_tesseract_and_names_the_page_that_failed(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf([["one"], ["two"]]))
    monkeypatch.setattr(ocr, "tesseract_path", lambda: None)
    with pytest.raises(OcrUnavailableError):
        ocr.ocr_pages(path, [1], OcrSettings())
    monkeypatch.setattr(ocr, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr, "DPI", 20)

    def read(image, languages):
        raise OcrError("tesseract failed: out of memory")

    monkeypatch.setattr(ocr, "read_image", read)
    with pytest.raises(OcrError, match=r"^page 2: tesseract failed: out of memory$"):
        ocr.ocr_pages(path, [2], OcrSettings())
