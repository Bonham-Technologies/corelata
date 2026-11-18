"""A reverse proxy that adds the operator guide's sample Content-Security-Policy to every
response (docs/operator-guide.md, section 6), for the Playwright journey that pins the sample
(CRL-23, R-M14-2). `devstack.py --csp-proxy-port` starts it in front of the dev stack. It streams
bodies through as they come, so progress streams stay live. Development only: not in the image."""

import argparse
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import uvicorn

# Must equal the policy in the guide's nginx sample; tests/test_csp_proxy.py checks the two match.
SAMPLE_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'"
)
# Headers that describe one hop, not the message (RFC 9110 section 7.6.1); the server sets its own.
HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
        b"host",
    }
)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def create_proxy(
    upstream: str, *, policy: str = SAMPLE_POLICY, transport: httpx.AsyncBaseTransport | None = None
) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    client = httpx.AsyncClient(base_url=upstream, transport=transport, timeout=None)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while (message := await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await client.aclose()
            await send({"type": "lifespan.shutdown.complete"})
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        path = scope["raw_path"].decode("latin-1")
        if scope["query_string"]:
            path += "?" + scope["query_string"].decode("latin-1")
        request = client.build_request(
            scope["method"],
            path,
            headers=[(k, v) for k, v in scope["headers"] if k.lower() not in HOP_BY_HOP],
            content=body,
        )
        try:
            response = await client.send(request, stream=True)
        except httpx.HTTPError as e:
            # the dev stack behind it is down or restarting: a gateway error, not a crash (CRL-37)
            print(f"csp_proxy: {upstream} did not answer: {e!r}", file=sys.stderr, flush=True)
            text = f"bad gateway: {upstream} did not answer ({type(e).__name__})".encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 502,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"content-length", str(len(text)).encode()),
                        (b"content-security-policy", policy.encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": text})
            return
        try:
            headers = [
                (k, v)
                for k, v in response.headers.raw
                if k.lower() not in HOP_BY_HOP and k.lower() != b"content-security-policy"
            ]
            headers.append((b"content-security-policy", policy.encode("ascii")))
            await send(
                {"type": "http.response.start", "status": response.status_code, "headers": headers}
            )
            async for chunk in response.aiter_raw():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await response.aclose()

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream", required=True, help="e.g. http://127.0.0.1:8765")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    uvicorn.run(
        create_proxy(args.upstream),
        host=args.host,
        port=args.port,
        log_level="warning",
        timeout_graceful_shutdown=2,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
