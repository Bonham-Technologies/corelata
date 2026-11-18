"""Gate outputs (spec §7.1, §7.2)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Substance(StrEnum):
    SUFFICIENT = "sufficient"
    THIN = "thin"
    INSUFFICIENT = "insufficient"


class GateVerdict(BaseModel):
    supported: bool = Field(description="The sources support the value statement")
    substance: Substance
    reasons: list[str] = Field(description="One sentence each; what supports or undermines")
    evidence: list[str] = Field(default_factory=list, description="Unit refs that matter most")
    suggested_scope: str = Field("", description="A scope note the writer must include if thin")


class CandidateStatement(BaseModel):
    text: str
    audience: str
    evidence: list[str] = Field(default_factory=list)
    confidence_note: str = ""


class DiscoveryResult(BaseModel):
    candidates: list[CandidateStatement] = Field(max_length=5)
