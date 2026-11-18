import asyncio
from pathlib import Path

import httpx

from csp_proxy import SAMPLE_POLICY, create_proxy

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "operator-guide.md"


def test_the_proxy_sets_the_operator_guides_sample_policy_word_for_word():
    guide = GUIDE.read_text(encoding="utf-8")
    assert f'add_header Content-Security-Policy "{SAMPLE_POLICY}" always;' in guide


async def upstream(scope, receive, send):
    """Echoes the request and sets a policy of its own, which the proxy must replace."""
    message = await receive()
    echo = "|".join(
        [
            scope["method"],
            scope["raw_path"].decode(),
            scope["query_string"].decode(),
            dict(scope["headers"]).get(b"x-remote-user", b"").decode(),
            message.get("body", b"").decode(),
        ]
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 201,
            "headers": [
                (b"content-type", b"text/plain"),
                (b"content-length", str(len(echo)).encode()),
                (b"content-security-policy", b"default-src *"),
                (b"x-accel-buffering", b"no"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": echo})


async def test_the_proxy_forwards_the_request_and_adds_the_policy():
    proxy = create_proxy("http://app.test", transport=httpx.ASGITransport(app=upstream))
    transport = httpx.ASGITransport(app=proxy)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy.test") as client:
        response = await client.post(
            "/api/runs/x?limit=2", content=b"body", headers={"X-Remote-User": "ana"}
        )
    assert response.status_code == 201
    assert response.text == "POST|/api/runs/x|limit=2|ana|body"
    assert response.headers.get_list("content-security-policy") == [SAMPLE_POLICY]
    assert response.headers["x-accel-buffering"] == "no"


async def test_the_proxy_closes_its_client_at_shutdown():
    proxy = create_proxy("http://app.test", transport=httpx.ASGITransport(app=upstream))
    inbox: asyncio.Queue = asyncio.Queue()
    for kind in ("lifespan.startup", "lifespan.shutdown"):
        inbox.put_nowait({"type": kind})
    sent: list[str] = []

    async def send(message):
        sent.append(message["type"])

    await proxy({"type": "lifespan"}, inbox.get, send)
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


async def test_an_unreachable_upstream_is_a_502_with_a_short_text(capsys):
    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    proxy = create_proxy("http://app.test", transport=httpx.MockTransport(refused))
    transport = httpx.ASGITransport(app=proxy)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy.test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 502
    assert response.text == "bad gateway: http://app.test did not answer (ConnectError)"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers.get_list("content-security-policy") == [SAMPLE_POLICY]
    # the body stays short; the developer's terminal gets the reason
    err = capsys.readouterr().err
    assert err == "csp_proxy: http://app.test did not answer: ConnectError('connection refused')\n"


class _TwoChunks(httpx.AsyncByteStream):
    """An upstream body in two chunks; the second is sent only after the proxy has passed the
    first to its client, so a proxy that buffered the body would wait here forever."""

    def __init__(self, forwarded: asyncio.Event) -> None:
        self._forwarded = forwarded

    async def __aiter__(self):
        yield b"first "
        await asyncio.wait_for(self._forwarded.wait(), timeout=5)
        yield b"second"


async def test_a_streamed_body_is_forwarded_chunk_by_chunk():
    forwarded = asyncio.Event()

    async def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, stream=_TwoChunks(forwarded)
        )

    proxy = create_proxy("http://app.test", transport=httpx.MockTransport(handler))
    inbox: asyncio.Queue = asyncio.Queue()
    inbox.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    bodies: list[tuple[bytes, bool]] = []

    async def send(message):
        if message["type"] == "http.response.body":
            bodies.append((message["body"], message["more_body"]))
            if message["body"] == b"first ":
                forwarded.set()  # the client has the first chunk: the upstream may go on

    scope = {
        "type": "http",
        "method": "GET",
        "raw_path": b"/api/runs/x/events",
        "query_string": b"",
        "headers": [],
    }
    await proxy(scope, inbox.get, send)
    assert bodies == [(b"first ", True), (b"second", True), (b"", False)]
