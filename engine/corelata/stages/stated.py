"""What the analyst states about a source (CRL-138): checked against the pack's lexicon, and
written over the writer's and conveyor's source entries, which may not have the last word."""

from typing import Any

from corelata.schema import ReportBody, Source, SourceEntry, SourceStatement
from corelata.standards.schema import Lexicon, ResolvedPack

# A source entry's date of information, origin and access: present only when the pack asks for
# source details (CRL-96); the descriptor and reliability note always are.
DETAIL_FIELDS = ("date_of_information", "origin", "access")


def statement_errors(stated: SourceStatement, lexicon: Lexicon, source: str) -> list[str]:
    """A stated descriptor must be one of the lexicon's source descriptors, and a stated access
    one of its `source_access` terms, where the lexicon has such a list."""
    errors: list[str] = []
    descriptors = lexicon.source_descriptors
    if stated.descriptor and descriptors and stated.descriptor not in descriptors:
        errors.append(
            f"{source}: descriptor '{stated.descriptor}' is not in the lexicon "
            f"(allowed: {', '.join(descriptors)})"
        )
    terms = lexicon.source_access
    if stated.access and terms and stated.access not in terms:
        errors.append(
            f"{source}: access '{stated.access}' is not in the lexicon "
            f"(allowed: {', '.join(terms)})"
        )
    return errors


def applied_values(stated: SourceStatement, pack: ResolvedPack) -> dict[str, str]:
    """The stated values a run writes into the source's entry: all of them, less the date,
    origin and access when the pack asks for no source details (the entry has none then)."""
    values = stated.values()
    if pack.source_details:
        return values
    return {k: v for k, v in values.items() if k not in DETAIL_FIELDS}


def apply_stated(
    sources: list[Source], pack: ResolvedPack, body: ReportBody
) -> tuple[ReportBody, list[dict[str, Any]]]:
    """`body` with each source entry carrying its source's stated values verbatim, and what the
    engine overwrote: one `{source_id, field, model_value, stated_value}` per field whose value
    the model gave differently (blank included). `body` itself, and no overrides, when it already
    carries every stated value, as it always does when nothing is stated."""
    stated = {s.id: applied_values(s.stated, pack) for s in sources}
    overrides: list[dict[str, Any]] = []
    entries: list[SourceEntry] = []
    for entry in body.sources:
        values = stated.get(entry.source_id) or {}
        changed = {k: v for k, v in values.items() if getattr(entry, k) != v}
        overrides += [
            {
                "source_id": entry.source_id,
                "field": k,
                "model_value": getattr(entry, k),
                "stated_value": v,
            }
            for k, v in changed.items()
        ]
        entries.append(entry.model_copy(update=changed) if changed else entry)
    if not overrides:
        return body, []
    return body.model_copy(update={"sources": entries}), overrides
