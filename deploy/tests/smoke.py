"""The analyst's path through a running Corelata, from inside the stack (standard library only):
    python3 smoke.py BASE_URL run NAME     create project NAME, upload the example source, run a
                                           report, wait for it, download every export
    python3 smoke.py BASE_URL check NAME   the project and its completed run still exist and the
                                           exports still download; then a new run completes
Exit 0 on success; any failure raises with the step in the message."""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

STATEMENT = "Varna port capacity expansion matters to shippers"
SOURCE = "/opt/corelata/examples/varna-port.txt"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TERMINAL = {"completed", "gate_rejected", "failed", "cancelled"}


def call(base, method, path, body=None, headers=None, timeout=60):
    data = None
    hdrs = dict(headers or {})
    if body is not None and not isinstance(body, bytes):
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    elif body is not None:
        data = body
    req = urllib.request.Request(base + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def expect(ok, what):
    if not ok:
        raise SystemExit(f"smoke: {what}")


def json_of(status, body, path, want=200):
    expect(status == want, f"{path} answered {status}: {body[:300]!r}")
    return json.loads(body)


def multipart(fields, filename, content):
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    out += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    out += b"Content-Type: text/plain\r\n\r\n" + content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def wait_terminal(base, run_id, timeout_s=300):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        progress = json_of(*call(base, "GET", f"/api/runs/{run_id}")[0::2], f"/api/runs/{run_id}")
        if progress["state"] in TERMINAL:
            return progress
        time.sleep(1)
    raise SystemExit(f"smoke: run {run_id} did not finish within {timeout_s} s")


def check_exports(base, run_id):
    for fmt, prefix, ctype in (
        ("docx", b"PK", DOCX),
        ("html", b"<!DOCTYPE html", "text/html"),
        ("md", b"", "text/markdown"),
        ("json", b"{", "application/json"),
    ):
        status, headers, body = call(base, "GET", f"/api/runs/{run_id}/report?format={fmt}")
        expect(status == 200, f"report {fmt} answered {status}")
        expect(headers.get("Content-Type", "").startswith(ctype), f"report {fmt} content-type {headers.get('Content-Type')}")
        expect(body.startswith(prefix) and len(body) > 100, f"report {fmt} looks wrong: {body[:40]!r}")
    status, _, body = call(base, "GET", f"/api/runs/{run_id}/exports/trace.json")
    trace = json_of(status, body, "trace.json")
    expect(trace["run_id"] == run_id and trace["state"] == "completed", "trace.json is not this run's completed trace")


def completed_run(base, project_id):
    page = json_of(*call(base, "GET", f"/api/runs?project_id={project_id}")[0::2], "/api/runs")
    runs = page["runs"]  # M14: the list route answers a page {runs, next_before}
    done = [r for r in runs if r["state"] == "completed"]
    expect(done, f"project {project_id} has no completed run")
    return done[0]["run_id"]


def project_named(base, name):
    projects = json_of(*call(base, "GET", "/api/projects")[0::2], "/api/projects")
    found = [p for p in projects if p["name"] == name]
    expect(found, f"no project named {name!r}")
    return found[0]["id"]


def start_run(base, project_id, source_id):
    body = {"project_id": project_id, "source_ids": [source_id], "value_statement": STATEMENT, "max_iterations": 1, "extra_guidance": ""}
    run = json_of(*call(base, "POST", "/api/runs", body)[0::2], "/api/runs", want=202)
    progress = wait_terminal(base, run["run_id"])
    expect(progress["state"] == "completed", f"run ended {progress['state']}: {progress.get('error')}")
    return run["run_id"]


def run(base, name):
    status, _, body = call(base, "GET", "/")
    expect(status == 200 and b'<div id="root">' in body, "the web app is not served at /")
    doctor = json_of(*call(base, "GET", "/api/system/doctor")[0::2], "/api/system/doctor")
    expect(doctor["ok"], "doctor: " + "; ".join(f"{c['name']}: {c['message']}" for c in doctor["checks"] if c["status"] != "pass"))
    project = json_of(*call(base, "POST", "/api/projects", {"name": name})[0::2], "/api/projects", want=201)
    with open(SOURCE, "rb") as f:
        content = f.read()
    data, headers = multipart({"kind": "file"}, "varna-port.txt", content)
    sources = json_of(*call(base, "POST", f"/api/projects/{project['id']}/sources", data, headers)[0::2], "sources", want=201)
    run_id = start_run(base, project["id"], sources[0]["id"])
    check_exports(base, run_id)
    print(f"smoke run: project {project['id']} run {run_id} completed; exports ok")


def check(base, name):
    project_id = project_named(base, name)
    check_exports(base, completed_run(base, project_id))
    sources = json_of(*call(base, "GET", f"/api/projects/{project_id}/sources")[0::2], "sources")
    expect(sources, "the project's sources are gone")
    run_id = start_run(base, project_id, sources[0]["id"])
    check_exports(base, run_id)
    print(f"smoke check: project {project_id} kept its data; new run {run_id} completed")


if __name__ == "__main__":
    base_url, mode, project_name = sys.argv[1:4]
    {"run": run, "check": check}[mode](base_url.rstrip("/"), project_name)
