"""Sources and their addressable units (spec §5.2). A unit ref is "<source_id>/<unit_id>"."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from corelata.schema.document import BlockKind


class SourceKind(StrEnum):
    FILE = "file"
    COGLOSSA_EXPORT = "coglossa_export"


class SourceUnit(BaseModel):
    id: str  # "u1", "u2", … in reading order, scoped to the source
    text: str
    locator: str  # "page 3 / para 7", "row 42", "coglossa:<run_id>/span:p14"
    kind: BlockKind
    meta: dict[str, Any] = Field(default_factory=dict)


class Source(BaseModel):
    id: str  # "src1", "src2", … in upload order
    kind: SourceKind
    name: str  # file name as uploaded
    format: str
    sha256: str
    provenance: dict[str, Any] = Field(default_factory=dict)  # e.g. {"coglossa_run_id": ...}
    units: list[SourceUnit]

    def refs(self) -> list[str]:
        return [unit_ref(self.id, u.id) for u in self.units]


def unit_ref(source_id: str, unit_id: str) -> str:
    return f"{source_id}/{unit_id}"


def split_ref(ref: str) -> tuple[str, str]:
    parts = ref.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"malformed unit ref '{ref}' (expected <source_id>/<unit_id>)")
    return parts[0], parts[1]


# Coglossa's span reliability tiers, best first (`ingest/vendor/coglossa-report-1.schema.json`).
COGLOSSA_TIERS = ("A", "B", "C")


def reliability_tier(source: Source) -> str | None:
    """A Coglossa export's reliability tier (CRL-96): the lowest tier among its scored spans, as
    ingest recorded them in each unit's `meta.reliability`, since a translation is as reliable
    as its weakest part; None for any other source, or when no span was scored."""
    if source.kind is not SourceKind.COGLOSSA_EXPORT:
        return None
    return lowest_tier(u.meta.get("reliability") for u in source.units)


def lowest_tier(tiers: Iterable[object]) -> str | None:
    """The lowest of the Coglossa tiers among `tiers`; None when none of them is one. A value
    that is not a string is not a tier (the database's count reads each as text, CRL-124)."""
    present = {t for t in tiers if isinstance(t, str)}
    scored = [t for t in COGLOSSA_TIERS if t in present]
    return scored[-1] if scored else None
