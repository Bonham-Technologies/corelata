"""JSON and CSV ingestion (spec §5.2): one unit per record or row, readable on its own."""

import csv
import io
import json
import threading
from pathlib import Path

from corelata.ingest.base import IngestError, file_sha256, make_blocks, read_utf8, strip_nul
from corelata.schema import BlockKind, SourceDocument

Item = tuple[BlockKind, str, str | None]

_FIELD_LIMIT_LOCK = threading.Lock()


def _allow_fields_up_to(chars: int) -> None:
    """Raise the csv module's field limit (process-wide) to at least `chars`. It is never
    lowered or restored: the API parses uploads in worker threads, and another thread's parse
    may be relying on a limit this one raised (CRL-99)."""
    with _FIELD_LIMIT_LOCK:
        if csv.field_size_limit() < chars:
            csv.field_size_limit(chars)


def _scalar(value: object) -> str:
    if isinstance(value, str):
        return strip_nul(value)
    return json.dumps(value, ensure_ascii=False)


def _record_text(record: object) -> str:
    if isinstance(record, dict):
        return "; ".join(f"{k}: {_scalar(v)}" for k, v in record.items())
    return _scalar(record)


class JsonIngestor:
    format = "json"
    extensions = (".json",)

    def ingest(self, path: Path) -> SourceDocument:
        try:
            data = json.loads(read_utf8(path))
        except json.JSONDecodeError as e:
            raise IngestError(f"{path.name} is not valid JSON (line {e.lineno}: {e.msg})") from e
        except RecursionError as e:
            raise IngestError(f"{path.name} is nested too deeply to read") from e
        items: list[Item] = []
        if isinstance(data, list):
            items = [
                (BlockKind.TABLE_CELL, _record_text(r), f"record {i}")
                for i, r in enumerate(data, start=1)
            ]
        elif isinstance(data, dict):
            items = [
                (BlockKind.TABLE_CELL, f"{k}: {_scalar(v)}", f"key {k}") for k, v in data.items()
            ]
        else:
            items = [(BlockKind.TABLE_CELL, _scalar(data), "value")]
        items = [it for it in items if it[1].strip()]
        return SourceDocument(
            source_path=str(path),
            format=self.format,
            sha256=file_sha256(path),
            blocks=make_blocks(str(path), items),
        )


class CsvIngestor:
    format = "csv"
    extensions = (".csv",)

    def ingest(self, path: Path) -> SourceDocument:
        text = read_utf8(path)
        # A field may be as long as the file (itself bounded by api.max_upload_mb on uploads).
        _allow_fields_up_to(len(text) + 1)
        reader = csv.reader(io.StringIO(text))
        try:
            rows = [[strip_nul(c).strip() for c in row] for row in reader]
        except csv.Error as e:
            raise IngestError(
                f"{path.name} is not a readable CSV file (row {reader.line_num}: {e})"
            ) from e
        header = rows[0] if rows else []
        items: list[Item] = []
        for number, row in enumerate(rows[1:], start=2):
            pairs = [
                f"{header[i] if i < len(header) else f'col{i + 1}'}: {cell}"
                for i, cell in enumerate(row)
                if cell
            ]
            if pairs:
                items.append((BlockKind.TABLE_CELL, "; ".join(pairs), f"row {number}"))
        return SourceDocument(
            source_path=str(path),
            format=self.format,
            sha256=file_sha256(path),
            blocks=make_blocks(str(path), items),
        )
