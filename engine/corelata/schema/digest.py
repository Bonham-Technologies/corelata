"""Digests of oversized sources (spec §5.4)."""

from pydantic import BaseModel, Field


class DigestSection(BaseModel):
    summary: str
    unit_refs: list[str] = Field(description="The units this section covers")


class DigestOutput(BaseModel):
    sections: list[DigestSection]


class Digest(BaseModel):
    source_id: str
    sections: list[DigestSection]
