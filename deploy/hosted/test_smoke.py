import httpx
import pytest

import smoke

SITE = "https://site.test"
API = "https://api.test"
MODAL_AUTH = {"Modal-Key": "wk-1", "Modal-Secret": "ws-1"}


SEEN = []


def make_transport(
    login_location="/", api_me_status=401, health_status=200, me_user="ci", no_token_status=401,
    modal_auth_on=True, projects=None,
):
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        SEEN.append((request.method, host, path))
        if host == "site.test" and path == "/login" and request.method == "POST":
            assert "origin" not in request.headers
            headers = {"location": login_location}
            if login_location == "/":
                headers["set-cookie"] = "crl_session=abc; Path=/; HttpOnly"
            return httpx.Response(303, headers=headers)
        signed_in = "crl_session=abc" in request.headers.get("cookie", "")
        if host == "site.test" and path == "/api/system/info":
            if signed_in:
                return httpx.Response(200, json={"user": me_user, "logout_url": "/logout"})
            return httpx.Response(401)
        if host == "site.test" and path == "/api/projects":
            if not signed_in:
                return httpx.Response(401)
            names = [smoke.EXAMPLE_PROJECT] if projects is None else projects
            return httpx.Response(200, json=[{"id": str(i), "name": n} for i, n in enumerate(names)])
        if host == "api.test":  # Modal proxy auth, in front of the API
            given = (request.headers.get("modal-key"), request.headers.get("modal-secret"))
            if modal_auth_on and given != ("wk-1", "ws-1"):
                return httpx.Response(no_token_status)
        if host == "api.test" and path == "/api/system/info":
            return httpx.Response(api_me_status)
        if host == "api.test" and path == "/api/health":
            return httpx.Response(health_status)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def run(transport):
    return smoke.run_checks(SITE, API, "ci", "pw", MODAL_AUTH, transport=transport)


@pytest.fixture
def smoke_env(monkeypatch):
    monkeypatch.setenv("CORELATA_SMOKE_PASSWORD", "pw")
    monkeypatch.setenv("CORELATA_MODAL_KEY", "wk-1")
    monkeypatch.setenv("CORELATA_MODAL_SECRET", "ws-1")


def test_all_checks_pass(capsys):
    results = run(make_transport())
    assert len(results) == 6 and all(ok for _, ok, _ in results)


def test_modal_may_refuse_with_403(capsys):
    results = run(make_transport(no_token_status=403))
    assert results[2] == ("the API refuses requests without the Modal token", True, "HTTP 403")


def test_an_api_open_without_the_modal_token_fails():
    results = run(make_transport(no_token_status=200))
    assert not results[2][1] and "without the Modal token (HTTP 200)" in results[2][2]
    assert all(ok for _, ok, _ in results[3:])  # the token is sent where it is needed


def test_check_3_fails_when_modal_proxy_auth_is_off():
    # Without Modal's proxy auth the API still answers a tokenless /api/system/info with 401 (its own
    # proxy-secret check), which must not pass for Modal's refusal.
    results = run(make_transport(modal_auth_on=False))
    assert not results[2][1] and "without the Modal token (HTTP 200)" in results[2][2]


def test_main_exits_zero_with_six_ok_lines(capsys, monkeypatch, smoke_env):
    monkeypatch.setattr(smoke, "_transport", make_transport())
    code = smoke.main(["--site", SITE, "--api-origin", API, "--user", "ci"])
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert len([line for line in out if line.startswith("ok")]) == 6


def test_api_answering_without_secret_fails(capsys, monkeypatch, smoke_env):
    monkeypatch.setattr(smoke, "_transport", make_transport(api_me_status=200))
    code = smoke.main(["--site", SITE, "--api-origin", API, "--user", "ci"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out and "the API answers without the proxy secret" in out


def test_failed_login_fails_check_one(capsys, monkeypatch, smoke_env):
    monkeypatch.setattr(smoke, "_transport", make_transport(login_location="/login?failed=1"))
    code = smoke.main(["--site", SITE, "--api-origin", API, "--user", "ci"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out and "sign in" in out


def test_wrong_user_fails():
    results = run(make_transport(me_user="someone"))
    assert not results[1][1]


def test_missing_password_is_an_error(monkeypatch, smoke_env):
    monkeypatch.delenv("CORELATA_SMOKE_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="^CORELATA_SMOKE_PASSWORD is not set$"):
        smoke.main(["--site", SITE, "--api-origin", API, "--user", "ci"])


def test_a_missing_modal_token_is_an_error(monkeypatch, smoke_env):
    monkeypatch.delenv("CORELATA_MODAL_KEY")
    monkeypatch.delenv("CORELATA_MODAL_SECRET")
    with pytest.raises(SystemExit, match="^CORELATA_MODAL_KEY, CORELATA_MODAL_SECRET are not set$"):
        smoke.main(["--site", SITE, "--api-origin", API, "--user", "ci"])


def test_login_redirect_is_not_followed():
    SEEN.clear()
    run(make_transport())
    assert ("GET", "site.test", "/") not in SEEN


# Corelata's check 6: the seed's example project, through the site.


def test_a_missing_example_project_fails_check_six():
    results = run(make_transport(projects=["Black Sea"]))
    assert results[5] == (
        "the example project exists",
        False,
        "HTTP 200, 1 project(s), no 'Example: Varna port'",
    )
    assert all(ok for _, ok, _ in results[:5])


def test_check_six_reads_the_projects_with_the_session():
    SEEN.clear()
    results = run(make_transport(projects=["Black Sea", smoke.EXAMPLE_PROJECT]))
    assert results[5] == ("the example project exists", True, "HTTP 200, 2 project(s)")
    assert ("GET", "site.test", "/api/projects") in SEEN


def test_check_six_fails_when_signed_out():
    results = run(make_transport(login_location="/login?failed=1"))
    assert not results[0][1] and not results[5][1] and "HTTP 401" in results[5][2]


def test_the_smoke_tests_name_matches_the_seeds():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent / "modal"))
    import settings

    assert smoke.EXAMPLE_PROJECT == settings.EXAMPLE_PROJECT
