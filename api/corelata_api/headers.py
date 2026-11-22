"""Defence-in-depth headers on every response (CRL-68, CRL-131). A pure ASGI middleware, not
BaseHTTPMiddleware, so streamed responses (the progress events) pass through unbuffered."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# What every response carries: no MIME sniffing of a download or an error body into something
# a browser would run, no full URL (with its run ids) sent to another site in a Referer, and no
# framing by another site, so a page behind the proxy's sign-in cannot be click-jacked into a
# one-click Accept (CRL-131). A header the response set itself is kept: the HTML report's DENY.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "SAMEORIGIN",
}

# Every /api answer but the liveness check carries report, source or trace text, or says who is
# signed in: none of it may sit in a shared workstation's disk cache (CRL-131). A Cache-Control
# the route set itself (the progress stream's no-cache, for the proxies between) gains no-store.
NO_STORE = "no-store"
CACHEABLE_API_PATHS = frozenset({"/api/health"})

# A report or export rendered as HTML, opened at the app's own origin (the API's report link,
# a direct address): it runs in a sandbox with no script, and loads nothing but its own inline
# stylesheet, so model-derived text cannot act as the app even if it got past escaping. The
# review screen fetches the HTML as text into its own sandboxed frame, which has its own policy.
REPORT_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
# frame-ancestors 'none' for a browser that predates it, and for a proxy that replaces the policy
REPORT_FRAME_OPTIONS = "DENY"


def must_not_store(path: str) -> bool:
    """Whether a response to `path` must carry no-store: /api, other than the liveness check."""
    return (path == "/api" or path.startswith("/api/")) and path not in CACHEABLE_API_PATHS


def with_no_store(cache_control: str | None) -> str:
    """`cache_control` with no-store in it; no-store alone when there was none."""
    if cache_control is None:
        return NO_STORE
    directives = {d.strip().split("=", 1)[0].lower() for d in cache_control.split(",")}
    return cache_control if NO_STORE in directives else f"{cache_control}, {NO_STORE}"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        no_store = must_not_store(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])  # ASGI lets a response leave it out
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if no_store:
                    headers["Cache-Control"] = with_no_store(headers.get("Cache-Control"))
            await send(message)

        await self.app(scope, receive, send_with_headers)
