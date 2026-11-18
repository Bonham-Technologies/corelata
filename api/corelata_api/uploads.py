"""Reading an upload within api.max_upload_mb, and naming a download. Copied from Coglossa."""

import re
from collections.abc import Callable, Coroutine
from typing import Any, BinaryIO
from urllib.parse import quote

from corelata.storage import display_name
from fastapi import Request, Response, UploadFile
from fastapi.routing import APIRoute
from starlette.types import Message, Receive

from corelata_api.context import get_context
from corelata_api.errors import UploadTooLargeError

CHUNK = 1 << 20  # 1 MiB
# What a multipart request carries besides the file: boundaries, part headers, the kind field.
MULTIPART_ALLOWANCE = 64 * 1024
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")


def _too_large(filename: str | None, max_mb: int) -> UploadTooLargeError:
    name = display_name(filename or "") or "the upload"
    return UploadTooLargeError(
        f"{name} is larger than the {max_mb} MB upload limit (api.max_upload_mb)"
    )


class _BodyTooLarge(Exception):
    """Raised from receive when the body passes the limit; UploadRoute answers 413 for it."""


class _CountingReceive:
    """An ASGI receive that counts the body's bytes and raises once they pass `limit`, before
    the message that passes it reaches the form parser."""

    def __init__(self, receive: Receive, limit: int) -> None:
        self._receive = receive
        self._limit = limit
        self._total = 0
        self.passed = False

    async def __call__(self) -> Message:
        message = await self._receive()
        if message["type"] == "http.request":
            self._total += len(message.get("body", b""))
            if self._total > self._limit:
                self.passed = True
                raise _BodyTooLarge
        return message


class UploadRoute(APIRoute):
    """A route that holds a multipart body to api.max_upload_mb plus MULTIPART_ALLOWANCE
    before FastAPI parses it, since Starlette spools the parsed file to the API's temp disk.
    A request that announces more in its Content-Length gets 413 before any of its body is
    read (CRL-88); any other request (chunked, or one that understates its length) is counted
    as it is read and gets the same 413 once it passes the limit, so nothing past it reaches
    temp (CRL-104). It is a route class, not a dependency, because FastAPI parses the form
    before it solves any dependency. read_upload still measures the file itself."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def checked(request: Request) -> Response:
            max_mb = get_context(request).cfg.api.max_upload_mb
            limit = max_mb * CHUNK + MULTIPART_ALLOWANCE
            length = request.headers.get("content-length", "")
            # isdigit alone accepts digits int() refuses, such as a latin-1 superscript
            if length.isascii() and length.isdigit() and int(length) > limit:
                raise _too_large(None, max_mb)
            receive = _CountingReceive(request.receive, limit)
            try:
                return await handle(Request(request.scope, receive))
            except Exception:
                # FastAPI turns an error while parsing the form into a 400; the multipart
                # parser has closed its temp files by then.
                if receive.passed:
                    raise _too_large(None, max_mb) from None
                raise

        return checked


async def read_upload(file: UploadFile, max_mb: int) -> BinaryIO:
    """The upload as the file Starlette spooled it to, rewound, or UploadTooLargeError when it
    passes the limit (nothing is stored before this returns). The size Starlette recorded while
    parsing decides when it is known (CRL-88). Otherwise the file is read a chunk at a time and
    never joined, so an upload costs the API one chunk of memory, not its size (CRL-73);
    UploadFile reads and seeks a file rolled over to disk in a thread."""
    limit = max_mb * CHUNK
    if file.size is not None:
        if file.size > limit:
            raise _too_large(file.filename, max_mb)
    else:
        total = 0
        while chunk := await file.read(CHUNK):
            total += len(chunk)
            if total > limit:
                raise _too_large(file.filename, max_mb)
    await file.seek(0)
    return file.file


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """RFC 6266: an ASCII fallback plus the UTF-8 name."""
    fallback = _UNSAFE.sub("_", filename) or "download"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
