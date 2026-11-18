"""Auditor output (spec §8.2). There is no report field: the auditor cannot edit."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    ATTESTED = "attested"


class FindingOut(BaseModel):
    rule_id: str
    verdict: Verdict
    evidence: str = Field(description="What in the draft (or missing from it) decided this")
    cited_units: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    recommendation: str = ""


class AuditOutput(BaseModel):
    findings: list[FindingOut]
    summary: str


class Finding(FindingOut):
    severity: str  # from the rule, never from the model
    route_to: str
    iteration: int

    @property
    def id(self) -> str:
        return f"{self.rule_id}@{self.iteration}"
