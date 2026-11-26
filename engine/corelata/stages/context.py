"""What every stage needs, and the payload helpers they share (spec §7.4)."""

import math
from dataclasses import dataclass, field
from typing import Any

from corelata.config import CorelataConfig, EvidenceQuotes
from corelata.ingest.base import HINT_KEYS
from corelata.ingest.injection import suspect_flag
from corelata.ingest.units import UnitIndex
from corelata.llm.agent import AgentRunner
from corelata.quotes import QuoteCheck
from corelata.schema import Digest, Finding, PriorReport, Source, SourceUnit, reliability_tier
from corelata.standards.schema import ResolvedPack


class StageError(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


def ocr_flag(unit: SourceUnit) -> dict[str, Any]:
    """`{"ocr": true, "ocr_confidence": 0-100}` for a unit OCR read from a scanned page (CRL-95),
    so the writer and the auditor can weigh it (icd203.tc.1); nothing for any other unit."""
    if not unit.meta.get("ocr"):
        return {}
    return {"ocr": True, "ocr_confidence": unit.meta.get("ocr_confidence")}


def unit_flags(unit: SourceUnit) -> dict[str, Any]:
    """What a model's input says about a unit beyond its text: the OCR flag (CRL-95) and
    `"suspect": true` for text that reads as an instruction to an AI system (CRL-137)."""
    return ocr_flag(unit) | suspect_flag(unit.meta)


def estimate_tokens(text: str, bytes_per_token: float) -> int:
    return math.ceil(len(text.encode("utf-8")) / bytes_per_token)


@dataclass
class StageContext:
    cfg: CorelataConfig
    runner: AgentRunner
    pack: ResolvedPack
    sources: list[Source]
    index: UnitIndex
    value_statement: str
    digests: dict[str, Digest] = field(default_factory=dict)
    # sources under the threshold digested only so the writer's budget holds (spec §7.4); the
    # gate still reads their full text
    forced_digests: set[str] = field(default_factory=set)
    extra_guidance: str = ""
    gate_evidence: list[str] = field(default_factory=list)
    # Units of non-digested sources the writer's last request left out for the budget (spec
    # §7.4 safety cut); empty whenever every non-digested source fits, as ingest ensures.
    withheld_refs: list[str] = field(default_factory=list)
    # CRL-97: the project's earlier accepted reports the writer and the auditor read, newest
    # first (none cut); empty when the run read none.
    prior_reports: list[PriorReport] = field(default_factory=list)
    # Rules the engine records `not_applicable` (initial coverage) after the audit: the rules
    # with `with_prior_reports` when the project has no earlier accepted report.
    initial_coverage: list[str] = field(default_factory=list)
    # CRL-138: the source entry values the engine wrote over in the last writer or conveyor
    # reply because the analyst stated them (`stages.stated.apply_stated`); empty when none.
    stated_overrides: list[dict[str, Any]] = field(default_factory=list)
    # CRL-139: the claims of the returned report the reviewer disputed, one finding each; the
    # writer reads them with its first draft. Empty for every run that is not such a rerun.
    reviewer_findings: list[Finding] = field(default_factory=list)

    def source(self, source_id: str) -> Source:
        return next(s for s in self.sources if s.id == source_id)

    def model_key(self, role: str) -> str:
        return self.cfg.roles.model_for(role)

    def bytes_per_token(self, role: str) -> float:
        return self.cfg.models[self.model_key(role)].bytes_per_token

    def unit_payload(self, refs: list[str]) -> list[dict[str, Any]]:
        out = []
        for ref in refs:
            source, unit = self.index.get(ref)
            out.append(
                {"ref": ref, "text": unit.text, "locator": unit.locator, "source": source.name}
                | unit_flags(unit)
            )
        return out

    def digest_payload(self) -> list[dict[str, Any]]:
        return [d.model_dump() for d in self.digests.values()]

    def source_payload(self) -> list[dict[str, Any]]:
        """Each source as the writer reads it; a Coglossa export with scored spans adds its
        `reliability_tier` (CRL-96). Ingest's date and origin hints (`HINT_KEYS`) are offered
        only when the pack asks for source details, so without them the payload is the one
        sent before CRL-96."""
        out = []
        for s in self.sources:
            provenance = s.provenance
            if not self.pack.source_details:
                provenance = {k: v for k, v in provenance.items() if k not in HINT_KEYS}
            item = {"id": s.id, "name": s.name, "format": s.format, "provenance": provenance}
            tier = reliability_tier(s)
            if tier is not None:
                item["reliability_tier"] = tier
            out.append(item)
        return out

    @property
    def evidence_quotes(self) -> EvidenceQuotes:
        return self.cfg.pipeline.evidence_quotes

    def quote_check(self) -> QuoteCheck | None:
        """The engine's quote check for this run (CRL-93); None with `evidence_quotes: off`."""
        if self.evidence_quotes is EvidenceQuotes.OFF:
            return None
        return QuoteCheck(
            required=self.evidence_quotes is EvidenceQuotes.REQUIRED,
            threshold=self.cfg.pipeline.quote_match_threshold,
            unit_text=lambda ref: self.index.text(ref) if self.index.has(ref) else None,
            # the writer sees a digested source's summary, never its units' words
            needs_quote=lambda ref: (
                self.index.has(ref) and self.index.get(ref)[0].id not in self.digests
            ),
        )

    def check_refs(self, refs: list[str]) -> list[str]:
        """Validation errors for refs that are not in the index (used by every validator),
        worded as an instruction with real refs to copy (R-M11-3)."""
        bad = [r for r in refs if not self.index.has(r)]
        if not bad:
            return []
        examples = ", ".join(self.index.refs()[:3]) or "<source_id>/<unit_id>"
        return [
            f"'{r}' is not a unit id; cite unit ids exactly as given in the input, "
            f"such as {examples}"
            for r in bad
        ]
