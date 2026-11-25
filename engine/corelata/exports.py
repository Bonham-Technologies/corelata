"""A run's files (spec §7.2 rendering, §8.4 invariant 5): the same functions write a run
directory for `corelata run` and the worker's stored exports."""

import csv
import io
import json
from collections.abc import Iterable
from pathlib import Path

from corelata.render.docx import render_docx
from corelata.render.html import render_html
from corelata.render.markdown import render_markdown
from corelata.schema import RunKind, RunRecord
from corelata.standards.schema import ResolvedPack
from corelata.trace import delivered_open_findings

OUTPUT_FILES = (
    "trace.json",
    "gate.json",
    "report.json",
    "report.md",
    "report.html",
    "report.docx",
    "findings.csv",
)
REPORT_FORMATS = ("json", "md", "html", "docx")
FINDINGS_SHEET = "findings.csv"
FINDINGS_COLUMNS = (
    "rule_id",
    "title",
    "verdict",
    "severity",
    "claim_ids",
    "cited_units",
    "evidence",
    "recommendation",
)
# A spreadsheet runs a cell that starts with one of these as a formula; the sheet's cells hold
# model text, so such a cell is written with a leading apostrophe.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: str) -> str:
    return f"'{value}" if value.startswith(_FORMULA) else value


def findings_sheet(record: RunRecord, pack: ResolvedPack) -> str:
    """A check run's findings sheet (CRL-94): one row per rule of its audit, in pack order, with
    the rule's title; the claim ids and unit refs space-separated. CSV, UTF-8."""
    titles = {r.id: r.title for r in pack.rules}
    last = max((f.iteration for f in record.findings), default=0)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(FINDINGS_COLUMNS)
    for f in record.findings:
        if f.iteration != last:
            continue
        row = (
            f.rule_id,
            titles.get(f.rule_id, ""),
            f.verdict.value,
            f.severity,
            " ".join(f.claim_ids),
            " ".join(f.cited_units),
            f.evidence,
            f.recommendation,
        )
        writer.writerow([_cell(v) for v in row])
    return out.getvalue()


def _report_file(
    fmt: str,
    record: RunRecord,
    pack: ResolvedPack,
    *,
    with_claim_ids: bool,
    docx_claim_ids: bool,
    docx_reference: Path | None,
) -> str | bytes:
    """One export of a finished run's report (`fmt` is one of REPORT_FORMATS)."""
    assert record.report is not None
    open_ = delivered_open_findings(record)
    args = (record.report, pack, record.sources)
    if fmt == "json":
        return dump_json(record.report.model_dump(mode="json"))
    if fmt == "md":
        return render_markdown(*args, with_claim_ids=with_claim_ids, open_findings=open_)
    if fmt == "html":
        return render_html(*args, with_claim_ids=with_claim_ids, open_findings=open_)
    if fmt != "docx":
        raise ValueError(f"unknown report format '{fmt}'")
    return render_docx(
        *args, with_claim_ids=docx_claim_ids, open_findings=open_, reference=docx_reference
    )


def _trace_files(record: RunRecord) -> dict[str, str | bytes]:
    out: dict[str, str | bytes] = {"trace.json": dump_json(record.model_dump(mode="json"))}
    if record.gate is not None:
        out["gate.json"] = dump_json(record.gate.model_dump(mode="json"))
    return out


def render_outputs(
    record: RunRecord,
    pack: ResolvedPack,
    *,
    with_claim_ids: bool,
    docx_claim_ids: bool = False,
    docx_reference: Path | None = None,
    formats: Iterable[str] = REPORT_FORMATS,
) -> dict[str, str | bytes]:
    """The run directory's files, by name: always trace.json (and gate.json when the gate ran),
    plus report.<fmt> for each requested format when there is a report. Pure: the same record
    renders the same bytes."""
    out = _trace_files(record)
    if record.report is not None and record.kind is RunKind.CHECK:
        out[FINDINGS_SHEET] = findings_sheet(record, pack)
    if record.report is not None:
        for fmt in formats:
            out[f"report.{fmt}"] = _report_file(
                fmt,
                record,
                pack,
                with_claim_ids=with_claim_ids,
                docx_claim_ids=docx_claim_ids,
                docx_reference=docx_reference,
            )
    return out


def dump_json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


class DocxExportError(Exception):
    """The DOCX export failed after every other output was written."""


def write_outputs(
    out_dir: Path, record: RunRecord, pack: ResolvedPack, with_claim_ids: bool
) -> list[Path]:
    """Write the run directory in order of importance: trace and gate, then report.json, the
    Markdown and the HTML, then the DOCX. Each export is rendered and written on its own, so the
    trace is on disk even if an export fails; a DOCX failure (the only export that reads an
    external file, the profile's reference document) raises DocxExportError."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:  # a rerun never leaves stale files from an earlier run
        (out_dir / name).unlink(missing_ok=True)
    written: list[Path] = []

    def put(name: str, content: str | bytes) -> None:
        path = out_dir / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        written.append(path)

    for name, content in _trace_files(record).items():
        put(name, content)
    if record.report is None:
        return written

    def render(fmt: str) -> str | bytes:
        return _report_file(
            fmt,
            record,
            pack,
            with_claim_ids=with_claim_ids,
            docx_claim_ids=False,
            docx_reference=pack.docx_reference_path,
        )

    if record.kind is RunKind.CHECK:
        put(FINDINGS_SHEET, findings_sheet(record, pack))
    for fmt in ("json", "md", "html"):
        put(f"report.{fmt}", render(fmt))
    try:
        docx = render("docx")
    except Exception as e:  # noqa: BLE001 - whatever the reference document provokes
        raise DocxExportError(str(e) or type(e).__name__) from e
    put("report.docx", docx)
    return written
