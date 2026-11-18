"""Sources and their addressable units (spec §5.2). A unit ref is "<source_id>/<unit_id>"."""

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
