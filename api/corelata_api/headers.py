"""Defence-in-depth headers on every response (CRL-68). A pure ASGI middleware, not
BaseHTTPMiddleware, so streamed responses (the progress events) pass through unbuffered."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# What every response carries: no MIME sniffing of a download or an error body into something
# a browser would run, and no full URL (with its run ids) sent to another site in a Referer.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}

# A report or export rendered as HTML, opened at the app's own origin (the API's report link,
# a direct address): it runs in a sandbox with no script, and loads nothing but its own inline
# stylesheet, so model-derived text cannot act as the app even if it got past escaping. The
# review screen fetches the HTML as text into its own sandboxed frame, which has its own policy.
REPORT_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])  # ASGI lets a response leave it out
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
