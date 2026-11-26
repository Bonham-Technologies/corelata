"""The section "How this report was produced" (CRL-139): the lines a profile with
`format.production_statement: true` adds to the end of every render, from the trace alone: the
model each role used, the standards pack and its hash, the audit result and how many claims a
reviewer checked."""

from corelata.schema import ClaimMark, RunRecord
from corelata.schema.review import checked_by, current_marks
from corelata.standards.schema import ResolvedPack

# The roles in the order a run calls them; a role this list does not know comes after, by name.
ROLE_ORDER = ("gate", "digest", "structurer", "writer", "conveyor", "auditor")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def names(people: list[str]) -> str:
    """ "ana", "ana and bob", "ana, bob and cy"."""
    if len(people) < 2:
        return "".join(people)
    return f"{', '.join(people[:-1])} and {people[-1]}"


def _models(record: RunRecord) -> str:
    by_role: dict[str, list[str]] = {}
    for call in record.llm_calls:
        if call.ok:
            models = by_role.setdefault(call.role, [])
            if call.model not in models:
                models.append(call.model)
    order = {role: i for i, role in enumerate(ROLE_ORDER)}
    roles = sorted(by_role, key=lambda r: (order.get(r, len(order)), r))
    if not roles:
        return "Models: none recorded."
    return "Models: " + "; ".join(f"{r} {', '.join(by_role[r])}" for r in roles) + "."


def production_lines(record: RunRecord, pack: ResolvedPack) -> list[str] | None:
    """The section's lines, or None when the profile leaves it off or the run has no report."""
    report = record.report
    if not pack.format.production_statement or report is None:
        return None
    profile = f", profile {pack.profile}" if pack.profile else ""
    meta = report.metadata
    audit = (
        f"{_plural(len(meta.open_findings), 'finding')} open at delivery"
        if meta.open_findings
        else "no findings open at delivery"
    )
    if meta.degradations:
        audit += f"; {_plural(len(meta.degradations), 'stage')} incomplete"
    current = current_marks(record.review_marks)
    marked = [current[c.id] for c in report.claims if c.id in current]
    checked = {m.claim_id for m in marked if m.mark is ClaimMark.CHECKED}
    who = names(checked_by(record.review_marks, checked))
    review = f"{len(checked)} of {_plural(len(report.claims), 'claim')} checked"
    if who:
        review += f" by {who}"
    if disputed := len(marked) - len(checked):
        review += f"; {disputed} disputed"
    return [
        _models(record),
        f"Standards pack: {pack.name} {pack.version}{profile} (hash {record.pack_hash}).",
        f"Audit: {audit} after {_plural(record.iterations, 'revision')}.",
        f"Review: {review}.",
    ]
