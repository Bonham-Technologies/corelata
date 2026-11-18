from corelata.ingest.units import UnitIndex
from corelata.stages.context import StageError, estimate_tokens
from corelata.testing.sources import text_source


def test_estimate_tokens_rounds_up():
    assert estimate_tokens("abcd", 2.5) == 2
    assert estimate_tokens("", 2.5) == 0
    assert estimate_tokens("é", 2.5) == 1  # 2 bytes


def test_context_payload_helpers(make_ctx):
    ctx = make_ctx(text_source("src1", "alpha", "beta", name="a.txt"))
    assert ctx.model_key("writer") == "model-a" and ctx.bytes_per_token("auditor") == 2.5
    assert ctx.unit_payload(["src1/u2"]) == [
        {"ref": "src1/u2", "text": "beta", "locator": "para 2", "source": "a.txt"}
    ]
    assert ctx.source_payload()[0] == {
        "id": "src1",
        "name": "a.txt",
        "format": "txt",
        "provenance": {},
    }
    assert ctx.digest_payload() == []


def test_stage_error_carries_stage():
    e = StageError("gating", "boom")
    assert e.stage == "gating" and str(e) == "gating: boom"


HINT = "is not a unit id; cite unit ids exactly as given in the input, such as"


def test_check_refs_names_up_to_three_real_refs_to_copy(make_ctx):
    ctx = make_ctx(text_source("src1", "alpha", "beta"), text_source("src2", "gamma", "delta"))
    assert ctx.check_refs(["src1/u1", "src1", "src2/u9"]) == [
        f"'src1' {HINT} src1/u1, src1/u2, src2/u1",
        f"'src2/u9' {HINT} src1/u1, src1/u2, src2/u1",
    ]
    assert ctx.check_refs(["src2/u2"]) == []
    ctx.index = UnitIndex()  # no units at all: the form is the only example there is
    assert ctx.check_refs(["x"]) == [f"'x' {HINT} <source_id>/<unit_id>"]


def _scanned(source):
    """`source` with its second unit read by OCR from a scanned page (CRL-95)."""
    units = list(source.units)
    units[1] = units[1].model_copy(update={"meta": {"ocr": True, "ocr_confidence": 71.5}})
    return source.model_copy(update={"units": units, "provenance": {"ocr_pages": [1]}})


def test_writer_and_gate_see_which_units_ocr_read(make_ctx):
    ctx = make_ctx(_scanned(text_source("src1", "alpha", "beta", name="scan.pdf")))
    assert ctx.unit_payload(["src1/u1", "src1/u2"]) == [
        {"ref": "src1/u1", "text": "alpha", "locator": "para 1", "source": "scan.pdf"},
        {
            "ref": "src1/u2",
            "text": "beta",
            "locator": "para 2",
            "source": "scan.pdf",
            "ocr": True,
            "ocr_confidence": 71.5,
        },
    ]
    assert ctx.source_payload()[0]["provenance"] == {"ocr_pages": [1]}
