"""Serve the built web app (spec §10.3) from api.web_dir: hashed assets forever, everything else
the index so the SPA router owns the URL. Copied from Coglossa."""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

IMMUTABLE = "public, max-age=31536000, immutable"


class _Assets(StaticFiles):
    async def get_response(self, path: str, scope: Scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = IMMUTABLE
        return response


def missing_index(web_dir: Path) -> str | None:
    if (web_dir / "index.html").is_file():
        return None
    return (
        f"api.web_dir {web_dir} has no index.html; build the web app (cd web && pnpm build) "
        "or remove api.web_dir"
    )


def mount_web(app: FastAPI, web_dir: Path) -> None:
    """Mount last, after every /api router: the catch-all must not shadow them."""
    root = web_dir.resolve()
    index = root / "index.html"
    if (root / "assets").is_dir():
        app.mount("/assets", _Assets(directory=root / "assets"), name="assets")

    def static_file(path: str) -> Path | None:
        """The file under the web root that `path` names, other than the index; None for a
        route the SPA owns."""
        try:
            candidate = (root / path).resolve()
            if (
                path
                and candidate != index
                and candidate.is_file()
                and candidate.is_relative_to(root)
            ):
                return candidate
        except (OSError, ValueError):  # a null byte or an over-long name is not a file
            pass
        return None

    # GET and HEAD: monitors and `curl -I` probe with HEAD, and FileResponse sends no body
    # for it (CRL-116)
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        # off the event loop: resolve() and is_file() touch the filesystem (CRL-113)
        found = await asyncio.to_thread(static_file, path)
        if found is not None:
            return FileResponse(found)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
