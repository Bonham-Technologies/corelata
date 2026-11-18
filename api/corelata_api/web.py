"""Serve the built web app (spec §10.3) from api.web_dir: hashed assets forever, everything else
the index so the SPA router owns the URL. Copied from Coglossa."""

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

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        try:
            candidate = (root / path).resolve()
            if (
                path
                and candidate != index
                and candidate.is_file()
                and candidate.is_relative_to(root)
            ):
                return FileResponse(candidate)
        except (OSError, ValueError):  # a null byte or an over-long name is not a file
            pass
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
