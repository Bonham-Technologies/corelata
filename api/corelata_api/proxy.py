"""Refuse requests that did not come through the authenticating proxy (the hosted demo's front
door, M19 spec §12.1; copied from Coglossa). A pure ASGI middleware, not BaseHTTPMiddleware, so
streamed responses (the progress events) pass through unbuffered."""

import hmac
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

PROXY_SECRET_HEADER = "X-Corelata-Proxy-Secret"
OPEN_PATHS = frozenset({"/api/health"})  # liveness checks never carry the secret

log = logging.getLogger("corelata.api")


class ProxySecretMiddleware:
    """Fails closed (R-M19-21, a divergence from Coglossa): only lifespan passes without the
    secret; a websocket handshake is closed before the app sees it; an empty configured secret
    refuses everything, since a missing header must never equal it."""

    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self._secret = secret.encode()
        self._header = PROXY_SECRET_HEADER.lower().encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "lifespan":
            await self.app(scope, receive, send)
            return
        if kind not in ("http", "websocket"):
            # dropped before its headers are read (it may have none): the app never sees it,
            # even with the secret (CRL-57)
            log.warning("refused an ASGI scope of unknown type %r", kind)
            return
        if kind == "http" and scope["path"] in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        given = next((v for k, v in scope["headers"] if k == self._header), b"")
        if self._secret and hmac.compare_digest(given, self._secret):
            await self.app(scope, receive, send)
            return
        if kind == "http":
            response = JSONResponse(
                {"detail": "this address only answers requests from the Corelata sign-in proxy"},
                status_code=401,
            )
            await response(scope, receive, send)
        else:  # websocket
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})
