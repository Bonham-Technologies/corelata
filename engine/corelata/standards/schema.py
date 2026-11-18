"""The standards pack data model (spec §6). Everything a customer edits is strict pydantic."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from corelata.schema.report import Confidence

RoleName = Literal["gate", "writer", "conveyor", "auditor"]
RULE_ID = r"^[a-z0-9]+(\.[a-z0-9]+)+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


class Checkability(StrEnum):
    VERIFIABLE = "verifiable"
    ADVISORY = "advisory"


class RouteTo(StrEnum):
    WRITER = "writer"
    CONVEYOR = "conveyor"


class PriorReportsRule(_Strict):
    """How a rule reads when the run has the key judgments of its project's earlier accepted
    reports (CRL-97); `Rule.with_prior_reports`."""

    checkability: Checkability
    evidence_required: str


def _unset(value: object) -> bool:
    return value is None


class Rule(_Strict):
    id: str = Field(pattern=RULE_ID)
    title: str
    source: str = ""  # where the standard comes from, e.g. "ICD 203 (2015) D.6.e(2)"
    text: str
    severity: Severity
    checkability: Checkability
    applies_to: list[RoleName]
    evidence_required: str
    route_to: RouteTo
    # CRL-97: the rule judges a report against the project's earlier accepted reports. A run
    # given some reads it with these fields; a run whose project has none records it
    # `not_applicable` (initial coverage) without asking the auditor; a run without project
    # memory reads the rule as written above. Left out of every dump when unset, so a pack
    # without it snapshots and hashes as before.
    with_prior_reports: PriorReportsRule | None = Field(None, exclude_if=_unset)


class ItemLimits(_Strict):
    min: int = Field(ge=0)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> "ItemLimits":
        if self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class Template(_Strict):
    section_order: list[str]
    key_judgments: ItemLimits
    analysis_max_words: int = Field(ge=50)
    alternatives_required_unless_all_high: bool
    gaps_required: bool


class LikelihoodTerm(_Strict):
    term: str
    low: int = Field(ge=0, le=100)
    high: int = Field(ge=0, le=100)


class Lexicon(_Strict):
    likelihood: list[LikelihoodTerm]
    confidence_definitions: dict[Confidence, str]
    source_descriptors: list[str]
    handling_markings: list[str] = Field(min_length=1)

    def terms(self) -> set[str]:
        return {t.term for t in self.likelihood}


class PackMeta(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    version: str
    extends: str | None = None
    description: str = ""


class RuleOverride(_Strict):
    id: str = Field(pattern=RULE_ID)
    severity: Severity | None = None
    checkability: Checkability | None = None
    route_to: RouteTo | None = None
    text: str | None = None
    evidence_required: str | None = None


class ProfileRules(_Strict):
    add: list[Rule] = Field(default_factory=list)
    disable: list[str] = Field(default_factory=list)
    override: list[RuleOverride] = Field(default_factory=list)


class TemplateOverride(_Strict):
    key_judgments: ItemLimits | None = None
    analysis_max_words: int | None = Field(None, ge=50)


class ProfileFormat(_Strict):
    docx_reference: Path | None = None
    heading_style: Literal["plain", "numbered"] = "plain"


class LexiconAdditions(_Strict):
    handling_markings: list[str] = Field(default_factory=list)
    source_descriptors: list[str] = Field(default_factory=list)


class Profile(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    extends: str
    draft: bool = False
    rules: ProfileRules = Field(default_factory=ProfileRules)
    template: TemplateOverride | None = None
    tone: str = ""
    format: ProfileFormat = Field(default_factory=ProfileFormat)
    lexicon: LexiconAdditions = Field(default_factory=LexiconAdditions)


class ResolvedPack(BaseModel):
    """What a run snapshots (spec §6.6). Rules are sorted by id so the hash is stable."""

    name: str
    version: str
    profile: str | None
    rules: list[Rule]
    template: Template
    lexicon: Lexicon
    tone: str
    format: ProfileFormat
    # Where the profile's reference document lives on this machine. Excluded from every dump so
    # the snapshot and pack_hash stay identical across installs (spec §6.6); None when rebuilt
    # from a snapshot. Set by the loader, read by the DOCX renderer; not in the published schema.
    docx_reference_path: SkipJsonSchema[Path | None] = Field(None, exclude=True)

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)

    def rules_for(self, role: RoleName) -> list[Rule]:
        return [r for r in self.rules if role in r.applies_to]

    def rule_ids(self) -> list[str]:
        return [r.id for r in self.rules]

    def prior_report_rules(self) -> list[str]:
        """The ids of the rules with `with_prior_reports` (CRL-97)."""
        return [r.id for r in self.rules if r.with_prior_reports is not None]

    def for_run(self, *, prior_reports: bool) -> "ResolvedPack":
        """The pack as a run's stages read it (CRL-97): a rule with `with_prior_reports` takes
        that block's checkability and evidence when the run has earlier accepted reports to
        read, and stays as written otherwise; the block itself is dropped, so every rule dumps
        as it did before the block existed. A pack without such rules is returned as it is."""
        if not self.prior_report_rules():
            return self
        rules = []
        for r in self.rules:
            if r.with_prior_reports is not None:
                update: dict[str, object] = {"with_prior_reports": None}
                if prior_reports:
                    update |= dict(r.with_prior_reports)
                r = r.model_copy(update=update)
            rules.append(r)
        return self.model_copy(update={"rules": rules})
