"""What the profiler returns (spec §4.4): a constrained sketch of a team profile, drawn from
example reports. The extractor turns it into a `Profile` with `draft: true`."""

from typing import Literal

from pydantic import BaseModel, Field


class DraftLimits(BaseModel):
    min: int = Field(ge=0)
    max: int = Field(ge=1)


class DraftRuleOverride(BaseModel):
    id: str = Field(description="A rule id from INPUT_JSON.pack.rule_ids")
    # Not `Severity` from corelata.standards.schema: that module imports corelata.schema.report,
    # so importing it here would be circular. The extractor converts with `Severity(...)`.
    severity: Literal["blocking", "major", "minor"]


class ProfileDraft(BaseModel):
    observations: list[str] = Field(
        min_length=1,
        description="What the example reports share: structure, length, voice, markings; "
        "one sentence each, for the reviewer",
    )
    tone: str = Field(
        min_length=1,
        description="House guidance the writer and conveyor read verbatim: voice, length, "
        "what to lead with, what to avoid",
    )
    key_judgments: DraftLimits | None = Field(
        None, description="How many key judgments the team's reports carry, if consistent"
    )
    analysis_max_words: int | None = Field(
        None,
        ge=50,
        description="A word limit for the analysis if the reports are consistently short",
    )
    heading_style: Literal["plain", "numbered"] = "plain"
    handling_markings: list[str] = Field(
        default_factory=list,
        description="Handling markings seen in the reports that the pack's lexicon lacks",
    )
    source_descriptors: list[str] = Field(
        default_factory=list,
        description="Source descriptor phrases the reports use that the lexicon lacks",
    )
    disable: list[str] = Field(
        default_factory=list,
        description="Rule ids the team's reports never meet by design; use sparingly",
    )
    override: list[DraftRuleOverride] = Field(
        default_factory=list, description="Rules whose severity the team treats differently"
    )
