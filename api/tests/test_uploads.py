"""CRL-73: an upload is checked against api.max_upload_mb chunk by chunk and handed to the store
as the file Starlette spooled it to, never as one bytes object of the whole body."""

import io
import json
import tempfile
from collections.abc import Iterable, Iterator
from typing import Any

import pytest
from corelata.storage import LocalStorage
from fastapi import UploadFile

from corelata_api.errors import UploadTooLargeError
from corelata_api.uploads import CHUNK, MULTIPART_ALLOWANCE, _CountingReceive, read_upload


class _Watched(UploadFile):
    """An UploadFile that records the size of every read."""

    def __init__(self, data: bytes, filename: str = "big.txt", *, sized: bool = True) -> None:
        spooled = tempfile.SpooledTemporaryFile(max_size=CHUNK)  # noqa: SIM115 - closed below
        spooled.write(data)
        spooled.seek(0)
        super().__init__(spooled, filename=filename, size=len(data) if sized else None)
        self.reads: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        got = await super().read(size)
        self.reads.append(len(got))
        return got


async def test_an_upload_larger_than_a_chunk_is_streamed_not_joined():
    body = b"0123456789" * (CHUNK // 5) + b"tail"  # two chunks and a bit
    upload = _Watched(body, sized=False)
    try:
        got = await read_upload(upload, max_mb=3)
        assert not isinstance(got, bytes | bytearray | memoryview)
        assert got is upload.file  # the spooled file itself, rewound
        assert max(upload.reads) <= CHUNK and len(upload.reads) >= 3
        assert got.tell() == 0 and got.read() == body
    finally:
        await upload.close()


async def test_an_upload_of_exactly_the_limit_is_accepted():
    upload = _Watched(b"x" * CHUNK, sized=False)
    try:
        got = await read_upload(upload, max_mb=1)
        assert got.read() == b"x" * CHUNK
    finally:
        await upload.close()


async def test_an_upload_over_the_limit_stops_at_the_chunk_that_passes_it():
    upload = _Watched(b"x" * (3 * CHUNK), filename="dir/big\r\nname.txt", sized=False)
    try:
        with pytest.raises(UploadTooLargeError) as e:
            await read_upload(upload, max_mb=1)
        assert str(e.value) == (
            "big name.txt is larger than the 1 MB upload limit (api.max_upload_mb)"
        )
        assert upload.reads == [CHUNK, CHUNK]  # the rest is never read
    finally:
        await upload.close()


async def test_an_unnamed_upload_over_the_limit():
    upload = UploadFile(io.BytesIO(b"x" * (CHUNK + 1)), filename=None)
    with pytest.raises(UploadTooLargeError, match="^the upload is larger than the 1 MB"):
        await read_upload(upload, max_mb=1)


async def test_the_route_hands_the_store_a_file_and_stores_every_byte(make_api, monkeypatch):
    given: list[type] = []
    put = LocalStorage.put

    def watching(self, key, data):
        given.append(type(data))
        put(self, key, data)

    monkeypatch.setattr(LocalStorage, "put", watching)
    body = b"The port of Varna handles grain.\n\n" * (2 * CHUNK // 34 + 1)
    async with make_api(api={"max_upload_mb": 3, "progress_poll_s": 0.02}) as api:
        project = (await api.client.post("/api/projects", json={"name": "big"})).json()
        response = await api.client.post(
            f"/api/projects/{project['id']}/sources",
            files={"file": ("port.txt", body, "text/plain")},
        )
        assert response.status_code == 201, response.text
        assert len(given) == 1 and not issubclass(given[0], bytes)
        [stored] = api.storage_root.rglob("port.txt")
        assert stored.read_bytes() == body


async def test_the_limit_is_still_checked_before_the_name_and_nothing_is_stored(make_api):
    async with make_api(api={"max_upload_mb": 1, "progress_poll_s": 0.02}) as api:
        project = (await api.client.post("/api/projects", json={"name": "big"})).json()
        response = await api.client.post(
            f"/api/projects/{project['id']}/sources",
            files={"file": ("big.png", b"x" * (CHUNK + 1), "image/png")},
        )
        assert response.status_code == 413  # not the 422 a .png gets within the limit
        assert response.json() == {
            "detail": "big.png is larger than the 1 MB upload limit (api.max_upload_mb)"
        }
        assert not list(api.storage_root.rglob("*"))


# CRL-88: the limit holds before the multipart body is parsed and spooled.


async def _post_raw(
    app, path: str, headers: list[tuple[bytes, bytes]], body: Iterable[bytes] = ()
) -> tuple[int, Any, int]:
    """POSTs straight to the ASGI app with the given headers, sending `body` one message per
    chunk (none by default): the status, the JSON body and how many times the app asked for the
    body."""
    asked = 0
    sent: list[dict] = []
    chunks = iter(body)

    async def receive() -> dict:
        nonlocal asked
        asked += 1
        chunk = next(chunks, None)
        if chunk is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"corelata.test"), *headers],
        "client": ("127.0.0.1", 1),
        "server": ("corelata.test", 80),
        "state": {},
    }
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], json.loads(body), asked


async def test_an_over_limit_content_length_is_refused_before_the_body_is_read(make_api):
    async with make_api(api={"max_upload_mb": 1, "progress_poll_s": 0.02}) as api:
        project = (await api.client.post("/api/projects", json={"name": "big"})).json()
        status, body, asked = await _post_raw(
            api.app,
            f"/api/projects/{project['id']}/sources",
            [
                (b"content-type", b"multipart/form-data; boundary=x"),
                (b"content-length", str(10 * 1024 * CHUNK).encode()),  # 10 GB announced
            ],
        )
        assert status == 413
        assert body == {
            "detail": "the upload is larger than the 1 MB upload limit (api.max_upload_mb)"
        }
        assert asked == 0  # not one byte of the body was asked for
        assert not list(api.storage_root.rglob("*"))


async def test_a_content_length_within_the_multipart_allowance_is_parsed(make_api):
    """The limit is on the file; boundaries and the kind field may take the request a little
    past it, and the file itself is still measured once it is parsed."""
    async with make_api(api={"max_upload_mb": 1, "progress_poll_s": 0.02}) as api:
        project = (await api.client.post("/api/projects", json={"name": "big"})).json()
        response = await api.client.post(
            f"/api/projects/{project['id']}/sources",
            files={"file": ("exact.txt", b"x" * CHUNK, "text/plain")},
            data={"kind": "file"},
        )
        assert int(response.request.headers["content-length"]) > CHUNK
        assert response.status_code == 201, response.text


@pytest.mark.parametrize("length", [b"lots", b"\xb2", b"-1", b""])
async def test_an_unreadable_content_length_is_left_to_the_parser(make_api, length):
    async with make_api(api={"max_upload_mb": 1, "progress_poll_s": 0.02}) as api:
        project = (await api.client.post("/api/projects", json={"name": "big"})).json()
        status, _, asked = await _post_raw(
            api.app,
            f"/api/projects/{project['id']}/sources",
            [
                (b"content-type", b"multipart/form-data; boundary=x"),
                (b"content-length", length),
            ],
        )
        assert status == 422  # no file part: the form is invalid, not too large
        assert asked >= 1


# CRL-104: a request without a usable Content-Length (chunked, or one that understates the body)
# is counted as it is read, and stops at the same limit.

_PIECE = 64 * 1024


def _multipart(name: str, size: int, pulled: list[int]) -> Iterator[bytes]:
    """A multipart body with one file part of `size` bytes, one message per 64 KB piece;
    `pulled` records the size of every piece the app asked for."""
    head = (
        f'--x\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode()
    tail = b"\r\n--x--\r\n"
    for piece in [head, *[b"x" * _PIECE] * (size // _PIECE), b"x" * (size % _PIECE), tail]:
        pulled.append(len(piece))
        yield piece


class _Spool(tempfile.SpooledTemporaryFile):
    """The parser's temp file, recording how much was written to it and whether it was closed."""

    made: list["_Spool"] = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.written = 0
        _Spool.made.append(self)

    def write(self, s) -> int:
        self.written += len(s)
        return super().write(s)


@pytest.mark.parametrize(
    "length",
    [[], [(b"content-length", b"1000")]],  # chunked, or a Content-Length that understates it
    ids=["chunked", "understated"],
)
async def test_an_over_limit_body_without_a_true_length_stops_at_the_limit(
    make_api, monkeypatch, length
):
    from starlette import formparsers

    _Spool.made.clear()
    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", _Spool)
    pulled: list[int] = []
    async with make_api(api={"max_upload_mb": 1, "progress_poll_s": 0.02}) as api:
        project = (await api.client.post("/api/projects", json={"name": "big"})).json()
        status, body, _ = await _post_raw(
            api.app,
            f"/api/projects/{project['id']}/sources",
            [(b"content-type", b"multipart/form-data; boundary=x"), *length],
            _multipart("big.txt", 8 * CHUNK, pulled),
        )
        assert status == 413
        assert body == {
            "detail": "the upload is larger than the 1 MB upload limit (api.max_upload_mb)"
        }
        limit = CHUNK + MULTIPART_ALLOWANCE
        assert limit < sum(pulled) <= limit + _PIECE  # read up to the limit plus one piece
        [spool] = _Spool.made
        assert spool.written <= limit and spool.closed  # nothing past the limit reached temp
        assert not list(api.storage_root.rglob("*"))


async def test_a_chunked_upload_within_the_limit_is_stored(make_api):
    async with make_api(api={"max_upload_mb": 1, "progress_poll_s": 0.02}) as api:
        project = (await api.client.post("/api/projects", json={"name": "big"})).json()
        status, body, _ = await _post_raw(
            api.app,
            f"/api/projects/{project['id']}/sources",
            [(b"content-type", b"multipart/form-data; boundary=x")],
            _multipart("exact.txt", CHUNK, []),
        )
        assert status == 201, body
        [stored] = api.storage_root.rglob("exact.txt")
        assert stored.read_bytes() == b"x" * CHUNK


async def test_the_count_passes_a_disconnect_through_uncounted():
    messages = iter(
        [{"type": "http.request", "body": b"ab", "more_body": True}, {"type": "http.disconnect"}]
    )

    async def receive() -> dict:
        return next(messages)

    counting = _CountingReceive(receive, limit=2)
    assert (await counting())["body"] == b"ab"
    assert await counting() == {"type": "http.disconnect"}
    assert not counting.passed


async def test_a_known_size_over_the_limit_is_refused_without_reading():
    upload = _Watched(b"x" * (2 * CHUNK), filename="big.txt")
    try:
        with pytest.raises(UploadTooLargeError, match="^big.txt is larger than the 1 MB"):
            await read_upload(upload, max_mb=1)
        assert upload.reads == []
    finally:
        await upload.close()


async def test_a_known_size_within_the_limit_is_returned_rewound_without_reading():
    upload = _Watched(b"abc")
    try:
        await upload.read(1)
        upload.reads.clear()
        got = await read_upload(upload, max_mb=1)
        assert got is upload.file and got.tell() == 0 and got.read() == b"abc"
        assert upload.reads == []
    finally:
        await upload.close()


# CRL-99: a file the parser cannot read is a 422 and leaves nothing in storage.


@pytest.mark.parametrize("name", ["deep.json", "broken.csv"])
async def test_an_unreadable_file_answers_422_and_stores_nothing(make_api, monkeypatch, name):
    import csv

    from corelata.ingest import tabular

    # The csv field limit is never lowered in production; force one the CSV's cell exceeds.
    monkeypatch.setattr(tabular, "_allow_fields_up_to", lambda chars: None)
    previous = csv.field_size_limit(1000)
    try:
        if name.endswith(".json"):
            body = b"[" * 100_000 + b"]" * 100_000
        else:
            body = b"note\n" + b"x" * 5000 + b"\n"
        async with make_api(api={"progress_poll_s": 0.02}) as api:
            project = (await api.client.post("/api/projects", json={"name": "bad"})).json()
            response = await api.client.post(
                f"/api/projects/{project['id']}/sources",
                files={"file": (name, body, "text/plain")},
            )
            assert response.status_code == 422, response.text
            assert name in response.json()["detail"]
            assert not [p for p in api.storage_root.rglob("*") if p.is_file()]
    finally:
        csv.field_size_limit(previous)
