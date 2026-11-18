"""One router per resource; `ROUTERS` is what the app mounts under /api behind auth."""

from corelata_api.routes import (
    coglossa,
    discoveries,
    packs,
    progress,
    projects,
    reports,
    runs,
    system,
)

ROUTERS = [
    projects.router,
    coglossa.router,
    runs.router,
    progress.router,
    reports.router,
    discoveries.router,
    packs.router,
    system.router,
]
