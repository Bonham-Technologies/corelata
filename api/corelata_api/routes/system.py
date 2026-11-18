"""What a client needs to know about this deployment, and the deep health check."""

from typing import Literal

from corelata.doctor import run_doctor
from corelata.schema import DoctorReport
from corelata.version import build_version
from fastapi import APIRouter
from pydantic import BaseModel, Field

from corelata_api.auth import User
from corelata_api.context import Ctx

router = APIRouter(tags=["system"])


class SystemInfo(BaseModel):
    version: str
    auth_mode: Literal["none", "trusted_header"]
    user: str | None  # who the proxy says is calling; None with auth.mode none
    coglossa: bool  # integrations.coglossa is configured: "Fetch from Coglossa" is available
    max_upload_mb: int
    default_pack: str
    default_profile: str | None
    max_iterations: int = Field(
        description=(
            "The audit loop's revision rounds (`pipeline.max_iterations`); the web app starts "
            "a run with this unless the analyst changes it."
        ),
    )
    logout_url: str | None = Field(
        None,
        description=(
            "The proxy's sign-out page (`auth.logout_url`); the web app shows Sign out only "
            "when it is set."
        ),
    )


@router.get("/system/info")
async def get_info(ctx: Ctx, user: User) -> SystemInfo:
    cfg = ctx.cfg
    return SystemInfo(
        version=build_version(),
        auth_mode=cfg.auth.mode,
        user=user,
        coglossa=cfg.integrations.coglossa is not None,
        max_upload_mb=cfg.api.max_upload_mb,
        default_pack=cfg.standards.default_pack,
        default_profile=cfg.standards.default_profile,
        max_iterations=cfg.pipeline.max_iterations,
        logout_url=cfg.auth.logout_url,
    )


@router.get("/system/doctor")
async def get_doctor(ctx: Ctx, probe: bool = True) -> DoctorReport:
    """The checks `corelata doctor` runs, from the API's own config file. The one route that
    talks to the model servers (spec §10.1); `probe=false` skips the test completions."""
    return await run_doctor(ctx.config_path, probe=probe)
