"""In-memory JobQueue for tests. Like procrastinate, a queueing lock that is already queued
is not queued again; `attempts` records every defer call so tests can see duplicates."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueuedJob:
    task: str
    lock: str | None
    kwargs: dict[str, str] = field(default_factory=dict)
    priority: int = 0


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[QueuedJob] = []
        self.attempts: list[QueuedJob] = []

    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None:
        job = QueuedJob(task, lock, kwargs, priority)
        self.attempts.append(job)
        if lock is not None and any(j.lock == lock for j in self.jobs):
            return
        self.jobs.append(job)

    def pop(self) -> QueuedJob | None:
        return self.jobs.pop(0) if self.jobs else None
