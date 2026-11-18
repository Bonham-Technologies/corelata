"""Spec §10.1 auth: `none` (anyone who reaches the API) or `trusted_header` (a reverse proxy
authenticates people and passes the user name in a header). Copied from Coglossa."""

import contextlib
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from corelata_api.context import get_context


def current_user(request: Request) -> str | None:
    auth = get_context(request).cfg.auth
    if auth.mode == "none":
        return None
    user = request.headers.get(auth.header) or ""
    # Starlette decodes header bytes as latin-1; proxies send UTF-8
    with contextlib.suppress(UnicodeEncodeError, UnicodeDecodeError):
        user = user.encode("latin-1").decode("utf-8")
    user = user.strip()
    if not user:
        raise HTTPException(
            status_code=401,
            detail=f"missing {auth.header} header: sign in through the proxy in front of Corelata",
        )
    return user


User = Annotated[str | None, Depends(current_user)]
