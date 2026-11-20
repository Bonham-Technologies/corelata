"""Spec §10.1 packs: what is installed, how a pack resolves with a profile, and whether it is
valid. The listing is re-read when a pack file changes (`PackIndex`); resolving and validating
read the directories on every call, since a customer edits them in place."""

import asyncio
from typing import Annotated

from corelata.config import ConfigIssue
from corelata.standards.loader import (
    PACK_NAME_MAX_LENGTH,
    PACK_NAME_PATTERN,
    PackSummary,
    load_pack,
    validate_pack,
)
from corelata.standards.schema import ResolvedPack
from corelata.store.runs import NotFoundError
from fastapi import APIRouter, Path
from pydantic import BaseModel

from corelata_api.context import Ctx

router = APIRouter(tags=["packs"])

PackName = Annotated[str, Path(pattern=PACK_NAME_PATTERN.pattern, max_length=PACK_NAME_MAX_LENGTH)]


class PackValidation(BaseModel):
    ok: bool
    issues: list[ConfigIssue]


async def _known(ctx: Ctx, name: str) -> None:
    if name not in await asyncio.to_thread(ctx.packs.names):
        raise NotFoundError(f"pack '{name}' not found")


@router.get("/packs")
async def get_packs(ctx: Ctx) -> list[PackSummary]:
    return await asyncio.to_thread(ctx.packs.listing)


@router.get("/packs/{name}/resolved")
async def get_resolved(name: PackName, ctx: Ctx, profile: str | None = None) -> ResolvedPack:
    """The pack as a run would snapshot it (spec §6.6); draft profiles may be inspected here."""
    await _known(ctx, name)
    return await asyncio.to_thread(
        load_pack, name, packs_dir=ctx.cfg.standards.packs_dir, profile=profile, allow_draft=True
    )


@router.get("/packs/{name}/validate")
async def get_validation(name: PackName, ctx: Ctx) -> PackValidation:
    await _known(ctx, name)
    issues = await asyncio.to_thread(validate_pack, name, packs_dir=ctx.cfg.standards.packs_dir)
    return PackValidation(ok=all(i.level != "error" for i in issues), issues=issues)
