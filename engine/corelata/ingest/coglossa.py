"""Coglossa export adapter (spec §5.3). The vendored JSON Schema documents the full export; the
pydantic subset below is what Corelata reads. Unknown fields are ignored, unknown schema
versions are refused."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from corelata.ingest.base import IngestError, file_sha256, read_utf8
from corelata.schema import BlockKind, Source, SourceKind, SourceUnit

VENDORED_SCHEMA = Path(__file__).parent / "vendor" / "coglossa-report-1.schema.json"


class CoglossaExportError(IngestError):
    pass


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Flag(_Loose):
    code: str


class _Score(_Loose):
    reliability: str = "unscored"


class _Span(_Loose):
    id: str
    text: str
    agreement: str
    chosen_from: str
    score: _Score = Field(default_factory=_Score)
    flags: list[_Flag] = Field(default_factory=list)


class _Glossary(_Loose):
    term: str
    rendering: str
    locked: bool = False


class _Guide(_Loose):
    summary: str = ""
    style_guide: str = ""
    glossary: list[_Glossary] = Field(default_factory=list)


class _Document(_Loose):
    source_path: str
    format: str
    sha256: str


class CoglossaExport(_Loose):
    schema_version: Literal["1"]
    coglossa_version: str
    run_id: str | None = None
    document: _Document
    spans: list[_Span]
    guide: _Guide = Field(default_factory=_Guide)


def _parse(path: Path) -> CoglossaExport:
    try:
        raw: Any = json.loads(read_utf8(path))
    except json.JSONDecodeError as e:
        raise CoglossaExportError(f"{path.name} is not valid JSON ({e.msg})") from e
    version = raw.get("schema_version") if isinstance(raw, dict) else None
    if version != "1":
        raise CoglossaExportError(
            f"{path.name}: Coglossa export schema_version '{version}' is not supported (want '1')"
        )
    try:
        return CoglossaExport.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise CoglossaExportError(f"{path.name}: {where}: {first['msg']}") from e


def load_coglossa_export(source_id: str, path: Path) -> list[Source]:
    export = _parse(path)
    run_id = export.run_id or "unknown"
    units = [
        SourceUnit(
            id=f"u{i}",
            text=span.text,
            locator=f"coglossa:{run_id}/span:{span.id}",
            kind=BlockKind.PARAGRAPH,
            meta={
                "reliability": span.score.reliability,
                "agreement": span.agreement,
                "chosen_from": span.chosen_from,
                "flags": [f.code for f in span.flags],
            },
        )
        for i, span in enumerate(export.spans, start=1)
        if span.text.strip()
    ]
    if not units:
        raise CoglossaExportError(f"{path.name} contains no usable text (no spans)")
    sha = file_sha256(path)
    main = Source(
        id=source_id,
        kind=SourceKind.COGLOSSA_EXPORT,
        name=path.name,
        format="coglossa",
        sha256=sha,
        provenance={
            "coglossa_run_id": run_id,
            "coglossa_version": export.coglossa_version,
            "document": export.document.model_dump(),
        },
        units=units,
    )
    guide_texts: list[tuple[str, dict[str, Any]]] = []
    if export.guide.summary.strip():
        guide_texts.append((export.guide.summary, {"part": "summary"}))
    if export.guide.style_guide.strip():
        guide_texts.append((export.guide.style_guide, {"part": "style_guide"}))
    guide_texts += [
        (f"{g.term} -> {g.rendering}", {"locked": g.locked}) for g in export.guide.glossary
    ]
    if not guide_texts:
        return [main]
    guide = Source(
        id=f"{source_id}-guide",
        kind=SourceKind.COGLOSSA_EXPORT,
        name=f"{path.name} (translation guide)",
        format="coglossa-guide",
        sha256=sha,
        provenance={"coglossa_run_id": run_id, "part": "guide"},
        units=[
            SourceUnit(
                id=f"u{i}",
                text=text,
                locator=f"coglossa:{run_id}/guide:{i}",
                kind=BlockKind.PARAGRAPH,
                meta=meta,
            )
            for i, (text, meta) in enumerate(guide_texts, start=1)
        ],
    )
    return [main, guide]
