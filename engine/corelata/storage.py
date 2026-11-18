"""Stored files (spec §4.2 `storage`, §11): uploaded sources, the reference document of a run and
the worker's exports, behind a Storage interface with a local-volume implementation and an S3
one (the hosted demo, copied from Coglossa). Keys are relative '/'-separated paths; nothing
outside the storage root is reachable. Every call blocks: callers on the event loop run them
through `storage_call`."""

import asyncio
import contextlib
import contextvars
import functools
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol

from corelata.config import S3StorageConfig, StorageConfig


class StorageError(Exception):
    """A storage operation failed; the message is safe to show to an operator."""


class ProbeLeftover(StorageError):
    """The bucket is writable but the check's probe could not be deleted and stays at `key`."""

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"storage check probe {key} was written but not deleted: {reason}")
        self.key = key


class Storage(Protocol):
    def put(self, key: str, data: bytes | BinaryIO) -> None:
        """Store `data` under `key`: bytes, or a binary file read from where it stands to its
        end, a piece at a time (an upload, from the file it was spooled to: CRL-73). The file is
        spent afterwards and a store may close it (S3's transfer closes one under 8 MiB)."""
        ...

    def get(self, key: str) -> bytes: ...

    def local_file(self, key: str) -> AbstractContextManager[Path]: ...

    def delete_prefix(self, prefix: str) -> None: ...

    def list_keys(self, prefix: str) -> list[str]: ...

    def check_writable(self) -> None: ...


async def storage_call[T](fn: Callable[..., T], *args: Any) -> T:
    """`fn(*args)` (a Storage method) in a thread, off the event loop: on the hosted demo each
    call is a request to S3. It is waited for to its end even when the awaiting task is cancelled
    meanwhile, and the cancellation is raised after it, so a cleanup that follows (a
    `delete_prefix` in an `except BaseException`) never runs beside the `put` it undoes, and no
    cancellation can stop a cleanup half way (R-M15-3, R-M19-4)."""
    # An executor future, not a Task (as asyncio.to_thread makes): the cancelling of every task
    # when asyncio.run shuts a loop down cannot reach it, so the wait below holds then too.
    call = asyncio.get_running_loop().run_in_executor(
        None, functools.partial(contextvars.copy_context().run, fn, *args)
    )
    cancelled: asyncio.CancelledError | None = None
    while not call.done():
        try:
            await asyncio.shield(call)
        except asyncio.CancelledError as e:
            cancelled = e  # the thread cannot be stopped: wait for it, then pass this on
        except Exception:  # noqa: BLE001 - the call's own error, raised by result() below
            pass
    if cancelled is not None:
        call.exception()  # retrieved: a failure of the call is not reported as unhandled
        raise cancelled
    return call.result()


_COPY_CHUNK = 1024 * 1024  # S3Storage.local_file copies an object to disk this much at a time
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(name: str) -> str:
    """A storage-safe basename that keeps the extension (ingestors pick a format by it)."""
    base = PurePosixPath(name.replace("\\", "/")).name
    cleaned = _UNSAFE.sub("_", base).strip(".")
    return cleaned or "document"


# Group-readable, so an API and a worker that run as different users in one group can share
# the volume; the storage root's own permissions keep everyone else out.
FILE_MODE = 0o640


_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def display_name(name: str) -> str:
    """The name to show for an uploaded file: no directories, no NUL, each run of other control
    characters (CR, LF, TAB...) a single space, so it fits a one-line message or a header."""
    base = PurePosixPath(name.replace("\x00", "").replace("\\", "/")).name
    return _CONTROL.sub(" ", base).strip()


def check_key(key: str) -> list[str]:
    """The key's parts; raises StorageError for a key that could escape the storage root."""
    parts = key.split("/")
    if not key or key.startswith("/") or "\\" in key or any(p in ("", ".", "..") for p in parts):
        raise StorageError(f"invalid storage key: {key!r}")
    return parts


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*check_key(key))

    def put(self, key: str, data: bytes | BinaryIO) -> None:
        path = self._path(key)
        tmp: str | None = None
        try:
            for attempt in (1, 2):
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
                    break
                except FileNotFoundError:
                    # a concurrent delete_prefix pruned the directory just made: make it again
                    if attempt == 2:
                        raise
            try:
                os.fchmod(fd, FILE_MODE)
                f = os.fdopen(fd, "wb")
            except BaseException:
                os.close(fd)
                raise
            with f:
                if isinstance(data, bytes):
                    f.write(data)
                else:
                    shutil.copyfileobj(data, f)
                f.flush()
                os.fsync(f.fileno())  # the data is on disk before the name points to it
            os.replace(tmp, path)
        except BaseException as e:  # a file-like can fail with more than OSError: no .tmp stays
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            if isinstance(e, OSError):
                raise StorageError(f"cannot store {key}: {e.strerror or e}") from e
            raise

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as e:
            raise StorageError(f"stored file not found: {key}") from e
        except OSError as e:
            raise StorageError(f"cannot read {key}: {e.strerror or e}") from e

    @contextlib.contextmanager
    def local_file(self, key: str) -> Iterator[Path]:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"stored file not found: {key}")
        yield path

    def delete_prefix(self, prefix: str) -> None:
        """Remove a stored file or a whole key prefix, then every directory that is left empty
        above it (never the root): a rejected upload or a restarted run leaves nothing behind."""
        target = self._path(prefix.rstrip("/"))
        try:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            parent = target.parent
            while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except OSError as e:
            raise StorageError(f"cannot delete {prefix}: {e.strerror or e}") from e

    def list_keys(self, prefix: str) -> list[str]:
        """Keys under a prefix, sorted; [] when nothing is stored there."""
        target = self._path(prefix.rstrip("/"))
        if not target.is_dir():
            return []
        return sorted(
            str(p.relative_to(self.root)).replace("\\", "/")
            for p in target.rglob("*")
            if p.is_file()
        )

    def check_writable(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".corelata-check-"):
                pass
        except OSError as e:
            raise StorageError(
                f"storage path {self.root} is not writable: {e.strerror or e}"
            ) from e


class S3Storage:
    """Files in an S3-compatible bucket. boto3 comes with the `s3` extra and is imported here,
    so a local-storage install neither needs nor loads it (the air-gapped image has none).
    Supabase Storage needs path-style addressing. Copied from Coglossa; `list_keys` is
    Corelata's (the worker clears a restarted run's stale exports with it)."""

    def __init__(self, cfg: S3StorageConfig, *, client: Any | None = None) -> None:
        self.cfg = cfg
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as e:
                raise StorageError("S3 storage needs the s3 extra: install corelata[s3]") from e

            keys = {}
            for field, var in (
                ("aws_access_key_id", cfg.access_key_id_env),
                ("aws_secret_access_key", cfg.secret_access_key_env),
            ):
                value = os.environ.get(var)
                if not value:
                    raise StorageError(f"environment variable {var} is not set")
                keys[field] = value
            # its own session: boto3's default one is not thread-safe to create clients from, and
            # storage calls run in asyncio.to_thread (CRL-59)
            client = boto3.session.Session().client(
                "s3",
                endpoint_url=cfg.endpoint_url,
                region_name=cfg.region,
                config=Config(
                    s3={"addressing_style": "path"},
                    retries={"mode": "standard"},
                    # boto3 1.36+ adds checksums to every upload by default, which some
                    # S3-compatible stores refuse; send and check them only where S3 requires
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
                **keys,
            )
        self._s3 = client

    def _key(self, key: str) -> str:
        check_key(key)
        prefix = self.cfg.prefix.strip("/")
        return f"{prefix}/{key}" if prefix else key

    def _under(self, prefix: str) -> list[str]:
        """Every object key under `prefix` + "/", as stored (with the configured prefix)."""
        pages = self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.cfg.bucket, Prefix=prefix + "/"
        )
        return [o["Key"] for page in pages for o in page.get("Contents", [])]

    def put(self, key: str, data: bytes | BinaryIO) -> None:
        try:
            if isinstance(data, bytes):
                self._s3.put_object(Bucket=self.cfg.bucket, Key=self._key(key), Body=data)
            else:
                # in parts past 8 MiB; with request_checksum_calculation="when_required" the
                # transfer adds no checksum either (s3transfer's _add_operation_defaults)
                self._s3.upload_fileobj(data, self.cfg.bucket, self._key(key))
        except _s3_errors() as e:
            raise StorageError(f"cannot store {key}: {_reason(e)}") from e

    @contextlib.contextmanager
    def _reading(self, key: str) -> Iterator[BinaryIO]:
        """The object's body as a stream; an S3 error while opening or reading it is a
        StorageError (a missing key says so)."""
        try:
            got = self._s3.get_object(Bucket=self.cfg.bucket, Key=self._key(key))
            with contextlib.closing(got["Body"]) as body:
                yield body
        except _s3_errors() as e:
            if _code(e) in ("NoSuchKey", "404"):
                raise StorageError(f"stored file not found: {key}") from e
            raise StorageError(f"cannot read {key}: {_reason(e)}") from e

    def get(self, key: str) -> bytes:
        with self._reading(key) as body:
            return body.read()

    @contextlib.contextmanager
    def local_file(self, key: str) -> Iterator[Path]:
        # ingestors pick a format by the suffix, so the temp file keeps it; the body is copied
        # in chunks so an upload is never held in memory whole (CRL-85)
        check_key(key)
        fd, name = tempfile.mkstemp(suffix=PurePosixPath(key).suffix, prefix="corelata-")
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as f, self._reading(key) as body:
                shutil.copyfileobj(body, f, _COPY_CHUNK)
            yield path
        finally:
            path.unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        base = self._key(prefix.rstrip("/"))
        try:
            # One DeleteObject per key, not DeleteObjects: Supabase's S3 API refuses that with
            # a bare 400 whatever its parameters, and a run or a source holds a handful of files.
            for key in [base, *self._under(base)]:
                self._s3.delete_object(Bucket=self.cfg.bucket, Key=key)
        except _s3_errors() as e:
            raise StorageError(f"cannot delete {prefix}: {_reason(e)}") from e

    def list_keys(self, prefix: str) -> list[str]:
        """Keys under a prefix, sorted and without the configured prefix, as LocalStorage gives
        them; [] when nothing is stored there."""
        base = self._key(prefix.rstrip("/"))
        own = len(base) - len(prefix.rstrip("/"))  # the configured prefix and its "/"
        try:
            return sorted(key[own:] for key in self._under(base))
        except _s3_errors() as e:
            raise StorageError(f"cannot list {prefix}: {_reason(e)}") from e

    def check_writable(self) -> None:
        probe = self._key(f".corelata-check-{uuid.uuid4().hex}")
        try:
            self._s3.put_object(Bucket=self.cfg.bucket, Key=probe, Body=b"")
        except _s3_errors() as e:
            raise StorageError(
                f"storage bucket {self.cfg.bucket} at {self.cfg.endpoint_url or 'AWS S3'} "
                f"is not writable: {_reason(e)}"
            ) from e
        try:
            self._s3.delete_object(Bucket=self.cfg.bucket, Key=probe)
        except _s3_errors() as e:
            raise ProbeLeftover(probe, _reason(e)) from e


def _s3_errors() -> tuple[type[Exception], ...]:
    from botocore.exceptions import BotoCoreError, ClientError

    return (BotoCoreError, ClientError)


def _code(e: Exception) -> str:
    return str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))


def _reason(e: Exception) -> str:
    error = getattr(e, "response", {}).get("Error", {})
    if error:
        return f"{error.get('Code', '')}: {error.get('Message', '')}".strip(": ")
    return " ".join(str(e).split())


def describe_storage(cfg: StorageConfig | S3StorageConfig) -> str:
    """Where files are kept, for doctor and the logs: the path, or s3://bucket[/prefix] [at
    endpoint]."""
    if isinstance(cfg, StorageConfig):
        return str(cfg.path)
    prefix = cfg.prefix.strip("/")
    where = f"s3://{cfg.bucket}" + (f"/{prefix}" if prefix else "")
    return f"{where} at {cfg.endpoint_url}" if cfg.endpoint_url else where


def build_storage(cfg: StorageConfig | S3StorageConfig) -> Storage:
    if isinstance(cfg, S3StorageConfig):
        return S3Storage(cfg)
    return LocalStorage(cfg.path)
