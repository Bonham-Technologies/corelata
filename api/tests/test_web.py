import pytest
from corelata.config import load_config

from corelata_api.app import create_app
from tests.conftest import serve


@pytest.fixture
def web_dir(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Corelata</title>", encoding="utf-8")
    (web / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (web / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not served", encoding="utf-8")
    return web


@pytest.fixture
async def web(write_config, web_dir):
    path = write_config(api={"web_dir": str(web_dir), "progress_poll_s": 0.02})
    cfg, _ = load_config(path)
    async with serve(create_app(cfg, path)) as client:
        yield client


async def test_index_is_served_for_app_routes_and_never_cached(web):
    for path in ("/", "/index.html", "/runs/123/review", "/projects"):
        response = await web.get(path)
        assert response.status_code == 200, path
        assert "<title>Corelata</title>" in response.text
        assert response.headers["cache-control"] == "no-cache"


async def test_assets_are_immutable_and_other_files_are_served(web):
    response = await web.get("/assets/app-abc123.js")
    assert response.status_code == 200 and response.text == "console.log(1)"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert (await web.get("/favicon.svg")).text == "<svg/>"


async def test_unknown_api_paths_are_json_404s_not_the_index(web):
    response = await web.get("/api/nope")
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert (await web.get("/api")).status_code == 404


async def test_paths_outside_the_web_dir_fall_back_to_the_index(web):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/a%00b"):
        response = await web.get(path)
        assert response.status_code == 200 and "not served" not in response.text


async def test_posting_to_a_page_is_405(web):
    assert (await web.post("/runs/1")).status_code == 405
