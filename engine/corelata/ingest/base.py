"""Shared ingestion helpers and the Ingestor protocol."""

import hashlib
import re
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


def make_blocks(source_path: str, items: list[tuple[BlockKind, str, str | None]]) -> list[Block]:
    return [
        Block(
            id=f"b{i + 1}",
            kind=kind,
            text=text,
            provenance=Provenance(source_path=source_path, index=i, locator=locator),
        )
        for i, (kind, text, locator) in enumerate(items)
    ]
