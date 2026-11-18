"""Project memory (CRL-97): the key judgments of the project's earlier accepted reports, as the
writer and the auditor read them, cut to `pipeline.prior_judgments.budget_tokens`."""

import json
from collections.abc import Sequence
from typing import Any

from corelata.schema import PriorReport
from corelata.stages.context import estimate_tokens


def prior_report_entry(report: PriorReport) -> dict[str, Any]:
    """One earlier report in the writer's and the auditor's input: its run id, title, the date
    it was accepted and its key judgments (text and confidence)."""
    return {
        "run_id": report.run_id,
        "title": report.title,
        "date": report.accepted_at.date().isoformat(),
        "key_judgments": [j.model_dump(mode="json") for j in report.key_judgments],
    }


def select_prior_reports(
    found: Sequence[PriorReport], *, max_reports: int, budget_tokens: int, bytes_per_token: float
) -> list[PriorReport]:
    """`found` newest first, at most `max_reports` of them, each marked `cut` or not: reports are
    taken newest first while their entries fit `budget_tokens`; the first that does not fit and
    every older one are cut, so the oldest go first."""
    out: list[PriorReport] = []
    spent = 0
    cutting = False
    for report in found[:max_reports]:
        entry = json.dumps(prior_report_entry(report), ensure_ascii=False)
        cost = estimate_tokens(entry, bytes_per_token)
        cutting = cutting or spent + cost > budget_tokens
        if not cutting:
            spent += cost
        out.append(report.model_copy(update={"cut": cutting}))
    return out
