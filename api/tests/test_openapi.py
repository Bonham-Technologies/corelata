import json
from pathlib import Path

from corelata_api import openapi

COMMITTED = Path(__file__).resolve().parents[2] / "schema" / "openapi.json"


def test_committed_openapi_matches_the_app():
    """Fails when a route or model changes but `make schema` was not run."""
    expected = (
        json.dumps(openapi.openapi_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    assert COMMITTED.read_text(encoding="utf-8") == expected, (
        "schema/openapi.json is stale: run `make schema` and commit the result"
    )


def test_main_writes_the_document(tmp_path, capsys):
    out = tmp_path / "openapi.json"
    assert openapi.main([str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["info"]["title"] == "Corelata"
    assert "/api/health" in document["paths"] and "/api/openapi.json" not in document["paths"]
    assert capsys.readouterr().out.strip() == str(out)


SCREEN_ROUTES = [
    "/api/health",
    "/api/system/info",
    "/api/system/doctor",
    "/api/projects",
    "/api/projects/{project_id}",
    "/api/projects/{project_id}/sources",
    "/api/projects/{project_id}/sources/from-coglossa",
    "/api/discoveries",
    "/api/discoveries/{discovery_id}",
    "/api/runs",
    "/api/runs/{run_id}",
    "/api/runs/{run_id}/events",
    "/api/runs/{run_id}/cancel",
    "/api/runs/{run_id}/review",
    "/api/runs/{run_id}/report",
    "/api/runs/{run_id}/exports/{name}",
    "/api/runs/{run_id}/trace",
    "/api/runs/{run_id}/findings",
    "/api/runs/{run_id}/claims/{claim_id}",
    "/api/packs",
    "/api/packs/{name}/resolved",
    "/api/packs/{name}/validate",
]


def test_every_screen_has_its_routes():
    """Spec §10.1 as the web (M4b) will call it; a renamed route fails here first."""
    paths = openapi.openapi_document()["paths"]
    assert sorted(paths) == sorted(SCREEN_ROUTES)


def test_the_m18_fields_are_described():
    """Each field M18 added says what it means in the published schema."""
    schemas = openapi.openapi_document()["components"]["schemas"]
    expected = {
        "ProjectView": ["last_activity_at", "reports_writing", "reports_to_review", "latest_run"],
        "RunSummary": ["review_decision", "review_child_state"],
        "LatestRun": ["state", "status", "decision", "child_state"],
        "SystemInfo": ["logout_url"],
    }
    for model, fields in expected.items():
        for field in fields:
            assert schemas[model]["properties"][field].get("description"), (model, field)
