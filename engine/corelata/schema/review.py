"""Review marks (CRL-139): a reviewer marks a claim of the delivered report checked or disputed,
with a comment. Every mark is an event: a claim's latest mark is its mark, and the run's trace
keeps them all. A return hands each disputed claim to the rerun's writer as a finding."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from corelata.schema.audit import Finding, Verdict
from corelata.schema.report import Report

# The rule id of a finding a disputed claim becomes. No pack has it: rule ids are the pack's,
# and "review" names no standard.
REVIEW_FINDING_RULE = "review.disputed"


class ClaimMark(StrEnum):
    CHECKED = "checked"
    DISPUTED = "disputed"


class ReviewMark(BaseModel):
    """One mark a reviewer put on a claim of the delivered report."""

    claim_id: str = Field(description="The claim of the delivered report the mark is on.")
    mark: ClaimMark = Field(
        description="`checked`: the reviewer checked the claim against its evidence; "
        "`disputed`: the reviewer disputes it."
    )
    comment: str = Field("", description="What the reviewer said about the claim.")
    actor: str | None = Field(None, description="Who marked it, when the sign-in names them.")
    at: datetime = Field(description="When it was marked.")


class ReviewMarks(BaseModel):
    """`GET /api/runs/{id}/marks`: each claim's mark and the counts the review screen shows."""

    marks: list[ReviewMark] = Field(
        description="Each marked claim's current mark (its latest), in the report's claim order; "
        "a claim nobody marked is not listed."
    )
    claims: int = Field(description="The claims in the delivered report.")
    checked: int = Field(description="The claims whose current mark is `checked`.")
    disputed: int = Field(description="The claims whose current mark is `disputed`.")
    reviewers: list[str] = Field(
        description="Who marked the checked claims, in the order they first did."
    )
    editable: bool = Field(
        description="Marks can be added or changed: false once the run is accepted, while a "
        "return's revision is being written or has its report, and for a check run."
    )
    require_key_judgments_checked: bool = Field(
        description="The run's profile has `review.require_key_judgments_checked`: Accept is "
        "refused until every claim a key judgment rests on is checked and no claim is disputed."
    )
    key_judgment_claim_ids: list[str] = Field(
        description="The claims the report's key judgments rest on, in the report's order."
    )


def current_marks(marks: list[ReviewMark]) -> dict[str, ReviewMark]:
    """Each claim's latest mark, by claim id; `marks` are in the order they were made."""
    return {m.claim_id: m for m in marks}


def key_judgment_claims(report: Report) -> list[str]:
    """The claim ids the report's key judgments rest on, each once, in the report's order."""
    return list(dict.fromkeys(c for kj in report.key_judgments for c in kj.claim_ids))


def marks_view(
    report: Report,
    marks: list[ReviewMark],
    *,
    editable: bool,
    require_key_judgments_checked: bool,
) -> ReviewMarks:
    """`ReviewMarks` for the report's claims; a mark on a claim the report lacks is ignored."""
    current = current_marks(marks)
    listed = [current[c.id] for c in report.claims if c.id in current]
    checked = [m for m in listed if m.mark is ClaimMark.CHECKED]
    return ReviewMarks(
        marks=listed,
        claims=len(report.claims),
        checked=len(checked),
        disputed=len(listed) - len(checked),
        reviewers=checked_by(marks, {m.claim_id for m in checked}),
        editable=editable,
        require_key_judgments_checked=require_key_judgments_checked,
        key_judgment_claim_ids=key_judgment_claims(report),
    )


def checked_by(marks: list[ReviewMark], checked: set[str]) -> list[str]:
    """Who put the current `checked` marks on the claims in `checked`, in first-mark order."""
    current = current_marks(marks)
    actors = [
        m.actor for m in marks if m.claim_id in checked and m.actor and current[m.claim_id] is m
    ]
    return list(dict.fromkeys(actors))


def accept_blockers(report: Report, marks: list[ReviewMark]) -> list[str]:
    """Why a profile with `review.require_key_judgments_checked` refuses an accept: the
    key-judgment claims not marked checked, and the claims marked disputed. Empty when none."""
    current = current_marks(marks)
    unchecked = [
        c
        for c in key_judgment_claims(report)
        if c not in current or current[c].mark is not ClaimMark.CHECKED
    ]
    disputed = [
        c.id for c in report.claims if c.id in current and current[c.id].mark is ClaimMark.DISPUTED
    ]
    out = []
    if unchecked:
        out.append(f"key-judgment claims not checked: {', '.join(unchecked)}")
    if disputed:
        out.append(f"claims disputed: {', '.join(disputed)}")
    return out


def disputed_findings(report: Report, marks: list[ReviewMark]) -> list[Finding]:
    """One writer finding per claim whose current mark is `disputed`, in the report's claim
    order: the claim's id and text, the units it cited and the reviewer's comment."""
    current = current_marks(marks)
    out = []
    for claim in report.claims:
        mark = current.get(claim.id)
        if mark is None or mark.mark is not ClaimMark.DISPUTED:
            continue
        out.append(
            Finding(
                rule_id=REVIEW_FINDING_RULE,
                verdict=Verdict.FAIL,
                evidence=f"The reviewer disputed claim {claim.id}: “{claim.text}”",
                cited_units=list(claim.evidence),
                claim_ids=[claim.id],
                recommendation=mark.comment.strip(),
                severity="major",
                route_to="writer",
                iteration=0,
            )
        )
    return out
