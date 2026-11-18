"""Smoke test for the hosted demo (spec §19; copied from Coglossa).

Usage: CORELATA_SMOKE_PASSWORD=... CORELATA_MODAL_KEY=... CORELATA_MODAL_SECRET=... \
           python smoke.py --site URL --api-origin URL --user NAME
Exits 0 when every check passes and prints one line per check.

The API endpoint requires Modal proxy auth: Modal itself refuses a request without the
workspace proxy-auth token (Modal-Key/Modal-Secret) with 401 or 403, before the API runs.
Check 3 asks for the health check without the token, which the API itself would answer
200. Checks 4 and 5 send the token, so they reach the API: check 4 then proves the API's own
proxy-secret check, and check 5 that the health check answers. Check 6 (Corelata's) finds
the example project the seed writes, through the site.
"""

import argparse
import os
import sys

import httpx

EXAMPLE_PROJECT = "Example: Varna port"  # settings.EXAMPLE_PROJECT

# Tests replace this with an httpx.MockTransport.
_transport = None


def _cookie(response: httpx.Response, name: str) -> str | None:
    for value in response.headers.get_list("set-cookie"):
        first = value.split(";", 1)[0]
        key, _, val = first.partition("=")
        if key.strip() == name and val:
            return val
    return None


def run_checks(site, api_origin, user, password, modal_auth, transport=None):
    """Return (name, ok, detail) for each check, in order. `modal_auth` is the Modal-Key and
    Modal-Secret headers."""
    site, api_origin = site.rstrip("/"), api_origin.rstrip("/")
    results: list[tuple[str, bool, str]] = []
    with httpx.Client(transport=transport, follow_redirects=False, timeout=60) as client:
        # 1. Sign in. No Origin header is sent, so the front door's origin check does not apply.
        session = None
        try:
            r = client.post(f"{site}/login", data={"name": user, "password": password})
            session = _cookie(r, "crl_session")
            location = r.headers.get("location", "")
            ok = r.status_code == 303 and location == "/" and session is not None
            detail = f"HTTP {r.status_code}, location {location!r}, cookie {'set' if session else 'missing'}"
        except httpx.HTTPError as exc:
            ok, detail = False, f"request failed: {exc}"
        results.append(("sign in through the front door", ok, detail))

        # 2. The session works through the proxy (Corelata has no /api/me: system/info names
        # the user).
        cookie = {"Cookie": f"crl_session={session or ''}"}
        try:
            r = client.get(f"{site}/api/system/info", headers=cookie)
            body = r.json() if r.status_code == 200 else {}
            got = body.get("user") if isinstance(body, dict) else None
            ok = r.status_code == 200 and got == user
            detail = f"HTTP {r.status_code}, user {got!r}"
        except (httpx.HTTPError, ValueError) as exc:
            ok, detail = False, f"request failed: {exc}"
        results.append(("the session reaches the API", ok, detail))

        # 3. Modal refuses callers without the proxy-auth token (401 or 403, by Modal's choice).
        # Health is used because the API answers it 200 without any secret, so a 401 or 403
        # can only come from Modal.
        try:
            r = client.get(f"{api_origin}/api/health")
            ok = r.status_code in (401, 403)
            detail = (
                f"HTTP {r.status_code}"
                if ok
                else f"the API answers without the Modal token (HTTP {r.status_code})"
            )
        except httpx.HTTPError as exc:
            ok, detail = False, f"request failed: {exc}"
        results.append(("the API refuses requests without the Modal token", ok, detail))

        # 4. Past Modal, the API refuses callers without the proxy secret.
        try:
            r = client.get(f"{api_origin}/api/system/info", headers=modal_auth)
            ok = r.status_code == 401
            detail = (
                "HTTP 401"
                if ok
                else f"the API answers without the proxy secret (HTTP {r.status_code})"
            )
        except httpx.HTTPError as exc:
            ok, detail = False, f"request failed: {exc}"
        results.append(("the API refuses requests without the proxy secret", ok, detail))

        # 5. Health needs no proxy secret.
        try:
            r = client.get(f"{api_origin}/api/health", headers=modal_auth)
            ok, detail = r.status_code == 200, f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            ok, detail = False, f"request failed: {exc}"
        results.append(("the API health check answers", ok, detail))

        # 6. The seed's example project is there, through the site (spec §13.6).
        try:
            r = client.get(f"{site}/api/projects", headers=cookie)
            body = r.json() if r.status_code == 200 else []
            names = [p.get("name") for p in body] if isinstance(body, list) else []
            ok = EXAMPLE_PROJECT in names
            detail = f"HTTP {r.status_code}, {len(names)} project(s)" + ("" if ok else f", no {EXAMPLE_PROJECT!r}")
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            ok, detail = False, f"request failed: {exc}"
        results.append(("the example project exists", ok, detail))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("--api-origin", required=True)
    parser.add_argument("--user", required=True)
    args = parser.parse_args(argv)
    names = ["CORELATA_SMOKE_PASSWORD", "CORELATA_MODAL_KEY", "CORELATA_MODAL_SECRET"]
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        sys.exit(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set")
    password, key, secret = (os.environ[name] for name in names)
    modal_auth = {"Modal-Key": key, "Modal-Secret": secret}
    results = run_checks(
        args.site, args.api_origin, args.user, password, modal_auth, transport=_transport
    )
    for i, (name, ok, detail) in enumerate(results, 1):
        print(f"{'ok  ' if ok else 'FAIL'} {i}. {name}: {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
