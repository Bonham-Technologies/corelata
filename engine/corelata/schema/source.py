"""Sources and their addressable units (spec §5.2). A unit ref is "<source_id>/<unit_id>"."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from corelata.schema.document import BlockKind
from corelata.text import clean_text


class SourceKind(StrEnum):
    FILE = "file"
    COGLOSSA_EXPORT = "coglossa_export"


class SourceUnit(BaseModel):
    id: str  # "u1", "u2", … in reading order, scoped to the source
    text: str
    locator: str  # "page 3 / para 7", "row 42", "coglossa:<run_id>/span:p14"
    kind: BlockKind
    meta: dict[str, Any] = Field(default_factory=dict)


def _blank(value: str) -> bool:
    return not value


# CRL-138: the source entry fields an analyst may state, in the order a source entry has them.
STATED_FIELDS = ("descriptor", "reliability_note", "date_of_information", "origin", "access")
# Lengths an analyst's statement may take: a descriptor or access term is a lexicon phrase, a
# date a short phrase, an origin a name, a reliability note a few sentences.
STATED_MAX_LENGTH = {
    "descriptor": 200,
    "reliability_note": 2000,
    "date_of_information": 100,
    "origin": 500,
    "access": 200,
}


class SourceStatement(BaseModel):
    """What the analyst states about a source for its entry in the report (CRL-138). A stated
    value replaces whatever the writer or conveyor gives that field; a blank one is not stated
    and is left out of every dump, so a source with nothing stated serialises as it did before."""

    descriptor: str = Field(
        "",
        max_length=STATED_MAX_LENGTH["descriptor"],
        description="A source descriptor phrase from the pack's lexicon",
        exclude_if=_blank,
    )
    reliability_note: str = Field(
        "",
        max_length=STATED_MAX_LENGTH["reliability_note"],
        description="The source's reliability, currency and completeness",
        exclude_if=_blank,
    )
    date_of_information: str = Field(
        "",
        max_length=STATED_MAX_LENGTH["date_of_information"],
        description="When the source's information was issued or current",
        exclude_if=_blank,
    )
    origin: str = Field(
        "",
        max_length=STATED_MAX_LENGTH["origin"],
        description="Who originated, authored or published the information",
        exclude_if=_blank,
    )
    access: str = Field(
        "",
        max_length=STATED_MAX_LENGTH["access"],
        description="The source's access to what it reports, a term from the lexicon's "
        "source_access",
        exclude_if=_blank,
    )

    @field_validator(*STATED_FIELDS, mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        # a pasted value may carry characters a DOCX export cannot hold (a vertical tab, other
        # controls): they go, as ingest drops them from a source's text
        return clean_text(value).strip() if isinstance(value, str) else value

    def values(self) -> dict[str, str]:
        """The stated fields and their values, in source entry order; empty when none is."""
        return {name: getattr(self, name) for name in STATED_FIELDS if getattr(self, name)}


def _nothing_stated(stated: SourceStatement) -> bool:
    return not stated.values()


class Source(BaseModel):
    id: str  # "src1", "src2", … in upload order
    kind: SourceKind
    name: str  # file name as uploaded
    format: str
    sha256: str
    provenance: dict[str, Any] = Field(default_factory=dict)  # e.g. {"coglossa_run_id": ...}
    units: list[SourceUnit]
    # CRL-138: what the analyst stated about the source when the run was queued; left out of the
    # dump when nothing was, so such a source reads as it did before.
    stated: SourceStatement = Field(default_factory=SourceStatement, exclude_if=_nothing_stated)

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
