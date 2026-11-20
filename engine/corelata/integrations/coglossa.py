"""Fetch a run's export from a Coglossa deployment (spec §5.3) so an analyst can import a
translation by run id instead of uploading the file. The adapter path after the fetch is the
same as for an upload (`service.add_source(..., coglossa_export=True)`)."""

import json
import os
import re

import httpx

from corelata.config import CoglossaIntegration

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
USER_HEADER = "X-Remote-User"  # Coglossa's trusted header (its default auth.header)
MAX_EXPORT_BYTES = 50 * 1024 * 1024
# An error answer is read only this far: its detail is cut to 200 characters anyway (CRL-114).
MAX_ERROR_BODY_BYTES = 64 * 1024
UNREACHABLE = "cannot reach Coglossa; the operator's log has the reason"


class CoglossaFetchError(Exception):
    """The export could not be fetched; `status` is the HTTP status the API answers with. The
    message is what the client sees; `log_detail`, when set, is what only the log gets, since it
    names Coglossa's address (CRL-114, the rule of CRL-75 and CRL-86)."""

    def __init__(self, message: str, *, status: int, log_detail: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.log_detail = log_detail


async def _read_error_body(response: httpx.Response) -> bytes:
    """At most MAX_ERROR_BODY_BYTES of an error answer; the rest is never read."""
    body = b""
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) >= MAX_ERROR_BODY_BYTES:
            return body[:MAX_ERROR_BODY_BYTES]
    return body


def _detail(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    text = detail if isinstance(detail, str) else text
    return " ".join(text.split())[:200]


class CoglossaClient:
    def __init__(
        self,
        cfg: CoglossaIntegration,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 30.0,
        max_bytes: int = MAX_EXPORT_BYTES,
    ) -> None:
        self.max_bytes = max_bytes
        self.cfg = cfg
        self.transport = transport
        self.timeout_s = timeout_s

    def _headers(self, user: str | None) -> dict[str, str | bytes]:
        headers: dict[str, str | bytes] = {"Accept": "application/json"}
        if self.cfg.api_key_env:
            key = os.environ.get(self.cfg.api_key_env)
            if not key:
                raise CoglossaFetchError(
                    f"integrations.coglossa.api_key_env {self.cfg.api_key_env} is not set in the "
                    "API's environment",
                    status=409,
                )
            headers["Authorization"] = f"Bearer {key}"
        if user:
            headers[USER_HEADER] = user.encode(
                "utf-8"
            )  # the caller's identity, for Coglossa's own auth
        return headers

    async def fetch_export(self, run_id: str, *, user: str | None) -> bytes:
        """The JSON export of a completed Coglossa run, as bytes for the adapter."""
        if not _RUN_ID.fullmatch(run_id):
            raise CoglossaFetchError(
                "a Coglossa run id is 1-64 letters, digits, dots, dashes or underscores",
                status=422,
            )
        base = self.cfg.base_url.rstrip("/")
        url = f"{base}/api/runs/{run_id}/exports/json"
        try:
            async with (
                httpx.AsyncClient(transport=self.transport, timeout=self.timeout_s) as c,
                c.stream("GET", url, headers=self._headers(user)) as response,
            ):
                if response.status_code == 200:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise CoglossaFetchError(
                                f"Coglossa run {run_id}: the export is larger than "
                                f"{self.max_bytes} bytes; export it by hand and upload it",
                                status=502,
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
                body = await _read_error_body(response)
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise CoglossaFetchError(
                UNREACHABLE,
                status=502,
                log_detail=(
                    f"cannot reach Coglossa at {self.cfg.base_url}: {str(e) or type(e).__name__}"
                ),
            ) from e
        if response.status_code == 404:
            raise CoglossaFetchError(f"Coglossa run {run_id} not found", status=404)
        if response.status_code == 409:
            raise CoglossaFetchError(
                f"Coglossa run {run_id} is not complete: {_detail(body)}", status=409
            )
        raise CoglossaFetchError(
            f"Coglossa answered {response.status_code} for run {run_id}: {_detail(body)}",
            status=502,
        )
