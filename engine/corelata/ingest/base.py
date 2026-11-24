"""Shared ingestion helpers and the Ingestor protocol."""

import hashlib
import re
from collections.abc import Collection
from pathlib import Path
from typing import Protocol

from corelata.schema import Block, BlockKind, Provenance, SourceDocument


class IngestError(ValueError):
    """The file cannot be turned into translatable text; message is user-facing."""


class UnsupportedFormatError(IngestError):
    pass


class Ingestor(Protocol):
    format: str
    extensions: tuple[str, ...]

    def ingest(self, path: Path) -> SourceDocument: ...


_SCENE_BREAK_RE = re.compile(r"^\s*(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,}|~{3,}|#|§)\s*$")
_BLANK_LINES_RE = re.compile(r"\n\s*\n")


def is_scene_break(text: str) -> bool:
    return bool(_SCENE_BREAK_RE.match(text))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_utf8(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise IngestError(
            f"{path.name} is not valid UTF-8 (byte {e.start}); re-save it as UTF-8 and retry"
        ) from e


def error_reason(e: BaseException) -> str:
    """A library exception's message on one line, for "not a readable … file (…)". A KeyError's
    str() quotes its message; its first argument does not."""
    reason = e.args[0] if isinstance(e, KeyError) and e.args else e
    return " ".join(str(reason).split())


def strip_nul(text: str) -> str:
    """NUL characters carry no text and Postgres cannot store them."""
    return text.replace("\x00", "")


def split_paragraphs(text: str) -> list[str]:
    normalized = strip_nul(text).replace("\r\n", "\n").replace("\r", "\n")
    return [p.strip() for p in _BLANK_LINES_RE.split(normalized) if p.strip()]


def make_blocks(
    source_path: str,
    items: list[tuple[BlockKind, str, str | None]],
    hidden: Collection[int] = (),
) -> list[Block]:
    """`hidden`: the indexes of the items whose text the document hides from its reader
    (CRL-137)."""
    return [
        Block(
            id=f"b{i + 1}",
            kind=kind,
            text=text,
            provenance=Provenance(
                source_path=source_path, index=i, locator=locator, hidden=i in hidden
            ),
        )
        for i, (kind, text, locator) in enumerate(items)
    ]


_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$")


# The `SourceDocument.meta` keys (CRL-96), which become the source's provenance: what the file
# says about when it was issued and who originated it, offered to the writer as hints.
HINT_KEYS = ("date", "origin")

# A hint comes from the file's own metadata, which anyone can write: past this many characters
# it is not a date or a name, and it would otherwise reach the writer and the report whole.
HINT_MAX_CHARS = 200


# C0 and C1 control characters and DEL, less the ones `str.split` reads as whitespace (tab, line
# feed, vertical tab, form feed, carriage return, the four separators and NEL): they carry no
# text, and python-docx refuses them, so one in a hint would cost the run its DOCX export.
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1b\x7f-\x84\x86-\x9f]")


def _hint(value: str | None) -> str:
    text = " ".join(_CONTROL.sub("", value or "").split())
    return text if len(text) <= HINT_MAX_CHARS else text[: HINT_MAX_CHARS - 1].rstrip() + "…"


def source_meta(date: str | None, origin: str | None) -> dict[str, str]:
    """The `SourceDocument.meta` hints (CRL-96): blanks left out, an ISO 8601 timestamp cut to
    its date, anything else kept as the file wrote it, whitespace collapsed to single spaces,
    control characters dropped and cut to `HINT_MAX_CHARS`."""
    meta: dict[str, str] = {}
    date = _hint(date)
    if date:
        match = _ISO_DATE.match(date)
        meta["date"] = match.group(1) if match else date
    origin = _hint(origin)
    if origin:
        meta["origin"] = origin
    return meta
