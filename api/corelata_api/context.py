"""What every route needs, built once per process by the app lifespan."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from corelata.config import CorelataConfig
from corelata.integrations.coglossa import CoglossaClient
from corelata.prompts.library import PromptLibrary
from corelata.service import JobQueue
from corelata.storage import Storage
from corelata.store.db import Database
from fastapi import Depends, Request

from corelata_api.pack_index import PackIndex
from corelata_api.progress_feed import ProgressFeed
from corelata_api.render_cache import RenderCache


@dataclass(frozen=True)
class ApiContext:
    cfg: CorelataConfig
    config_path: Path
    db: Database
    storage: Storage
    prompts: PromptLibrary
    queue: JobQueue
    coglossa: CoglossaClient | None  # None when integrations.coglossa is not configured
    renders: RenderCache  # claim-id re-renders per (run, format), within api.render_cache_mb
    progress: ProgressFeed  # one poller per run for the SSE streams, woken by NOTIFY (CRL-22)
    packs: PackIndex  # the pack listing, re-read when a pack file changes (CRL-8)


def get_context(request: Request) -> ApiContext:
    return request.app.state.ctx


Ctx = Annotated[ApiContext, Depends(get_context)]
