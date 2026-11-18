"""What the control plane reports about queued work (spec §10.1 GET /runs/{id}, SSE, discovery).
Pure views over stored rows; the API serves them unchanged in M4a."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from corelata.schema.common import Usage
from corelata.schema.gate import CandidateStatement
from corelata.schema.report import ReportStatus
from corelata.schema.run import RunState, StageResult


class ReviewAction(StrEnum):
    ACCEPT = "accept"
    RETURN = "return"


class ReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    RETURNED = "returned"


class ReviewState(BaseModel):
    """What a reviewer decided about a completed run (spec §10.1), from its review events and the
    reruns they created. A return whose rerun is live or completed wins over an accept: the rerun
    supersedes the accepted report (R-M9-1). A rerun that ended any other way spent nothing
    (R-M15-1): the latest event decides, and the run can be returned or accepted again."""

    decision: ReviewDecision
    at: datetime
    actor: str | None = None
    child_run_id: str | None = None  # the rerun a return created; None while it is being made
    child_state: RunState | None = None  # the rerun's state once it ended; None while it runs
    child_error: str | None = None  # why the rerun failed, when it did
    note: str | None = None  # a return's note for the writer, so it can be offered again


class RunProgress(BaseModel):
    run_id: str
    project_id: str
    parent_run_id: str | None = None
    state: RunState
    status: ReportStatus | None = None
    # What the run was asked, so a new report can start from it (CRL-84).
    value_statement: str = Field(description="The value statement the run was given.")
    profile: str | None = Field(
        None, description="The team profile the run used; null for the deployment's default."
    )
    source_ids: list[str] = Field(
        description=(
            "The project sources the run used, in the run's order (source `src<n>` of its trace "
            "is the n-th). A source deleted since is left out."
        ),
    )
    iteration: int
    max_iterations: int
    stages: list[StageResult] = Field(default_factory=list)  # every attempt recorded so far
    usage: Usage | None = None
    cancel_requested: bool = False
    worker_gone: bool = Field(
        False,
        description=(
            "The worker that took the run is gone: its heartbeat is `worker.stalled_after_s` old "
            "or its worker row was deleted, so the run is not moving. It starts over when a "
            "running worker re-queues its job; a cancel ends it at once (CRL-49, CRL-69). False "
            "for a run that ended, and for one no worker has taken yet."
        ),
    )
    attempts: int = 0  # executions the worker started (2 after a crash and a requeue)
    error: str | None = None
    export_error: str | None = None  # the run completed but its DOCX export failed
    review: ReviewState | None = None  # completed runs only (M9, CRL-15)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunSummary(BaseModel):
    """One row of `GET /api/runs?project_id=`: enough to list a project's runs and open one."""

    run_id: str
    project_id: str
    parent_run_id: str | None = None
    state: RunState
    status: ReportStatus | None = None
    value_statement: str
    profile: str | None = None
    iteration: int
    max_iterations: int
    created_at: datetime
    finished_at: datetime | None = None
    # The stored decision (`RunProgress.review`), so a list shows "accepted" or "returned"
    # without a request per row (M18 spec §7.2), and the revision's end, so it shows a return
    # whose revision ended without a report as "to review" again (R-M15-1, R-M18-7).
    review_decision: ReviewDecision | None = Field(
        None, description="The reviewer's decision on this run, or null while it has none."
    )
    review_child_state: RunState | None = Field(
        None,
        description=(
            "The state the revision of a returned run ended in; null while it is still being "
            "written. Failed, cancelled and gate-rejected mean the return produced no report."
        ),
    )


class LatestRun(BaseModel):
    """A project's newest run by `(created_at, id)` (M18 spec §7.1)."""

    run_id: str
    state: RunState = Field(description="The run's pipeline state.")
    status: ReportStatus | None = Field(
        None, description="The report's status, once the run has one."
    )
    decision: ReviewDecision | None = Field(
        None, description="The reviewer's decision on the run, or null while it has none."
    )
    child_state: RunState | None = Field(
        None,
        description=(
            "For a returned run, the state its revision ended in (null while it is being "
            "written); the same as a run summary's `review_child_state`."
        ),
    )


class ProjectSummary(BaseModel):
    """What the sidebar shows for a project (M18 spec §7.1, R-M18-3): computed for the whole
    list by a fixed number of grouped queries, whatever its length (`store.runs`)."""

    last_activity_at: datetime = Field(
        description=(
            "The latest of the project's `created_at`, its sources' `created_at`, and its runs' "
            "`created_at` and `finished_at`."
        )
    )
    reports_writing: int = Field(0, description="Runs not in a terminal state.")
    reports_to_review: int = Field(
        0,
        description=(
            "Completed runs with no decision, or whose return's revision ended without a "
            "report (failed, cancelled or not supported; R-M15-1)."
        ),
    )
    latest_run: LatestRun | None = Field(
        None, description="The project's newest run, or null when it has none."
    )


class DiscoveryState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DiscoveryView(BaseModel):
    discovery_id: str
    project_id: str
    state: DiscoveryState
    audience_hint: str = ""
    source_ids: list[str]
    candidates: list[CandidateStatement] = Field(default_factory=list)
    usage: Usage | None = None
    error: str | None = None
    created_at: datetime
    deadline_at: datetime = Field(
        description=(
            "When the discovery is failed if it has not ended, by the limit that applies "
            "(CRL-38, R-M17-27): `started_at` plus `worker.discovery_deadline_s` once the "
            "worker has claimed it (ended or not); otherwise `created_at` plus "
            "`worker.discovery_start_deadline_s`."
        )
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
