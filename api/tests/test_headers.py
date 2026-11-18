"""CRL-68: every response carries X-Content-Type-Options and Referrer-Policy, set by a pure ASGI
middleware so the progress stream stays unbuffered (test_progress.py streams through it)."""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse

from corelata_api.headers import SecurityHeadersMiddleware
from corelata_api.proxy import PROXY_SECRET_HEADER

EXPECTED = {"x-content-type-options": "nosniff", "referrer-policy": "same-origin"}


def _has_them(response) -> bool:
    return all(response.headers.get(k) == v for k, v in EXPECTED.items())


async def test_every_kind_of_response_carries_them(make_api, tmp_path):
    web_dir = tmp_path / "dist"
    (web_dir / "assets").mkdir(parents=True)
    (web_dir / "index.html").write_text("<title>Corelata</title>", encoding="utf-8")
    (web_dir / "assets" / "app.js").write_text("1", encoding="utf-8")
    async with make_api(api={"web_dir": str(web_dir)}) as api:
        for path in ("/api/health", "/api/projects", "/", "/assets/app.js", "/api/runs/x"):
            response = await api.client.get(path)
            assert _has_them(response), (path, response.status_code, response.headers)
        missing = await api.client.get("/api/projects/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404 and _has_them(missing)


@pytest.fixture
def secret_env(monkeypatch):
    monkeypatch.setenv("CORELATA_PROXY_SECRET", "s3cret-" * 5)


async def test_a_request_the_proxy_check_refuses_carries_them(secret_env, make_api):
    auth = {"mode": "trusted_header", "proxy_secret_env": "CORELATA_PROXY_SECRET"}
    async with make_api(auth=auth) as api:
        refused = await api.client.get("/api/projects", headers={PROXY_SECRET_HEADER: "x"})
        assert refused.status_code == 401 and _has_them(refused)


async def test_a_header_the_app_set_is_kept_and_other_scopes_pass_through():
    async def stricter(request):
        return PlainTextResponse("x", headers={"Referrer-Policy": "no-referrer"})

    app = Starlette()
    app.add_route("/", stricter)
    app.add_middleware(SecurityHeadersMiddleware)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://app.test") as client:
        response = await client.get("/")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"

    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    await SecurityHeadersMiddleware(inner)({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]  # the lifespan scope passes through untouched
