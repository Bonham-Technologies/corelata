import re
from pathlib import Path

import pytest

from corelata.ingest import registry
from corelata.ingest.base import IngestError, UnsupportedFormatError
from corelata.schema import SourceDocument


def test_dispatches_by_extension_case_insensitively(tmp_path):
    path = tmp_path / "A.TXT"
    path.write_text("Hello.", encoding="utf-8")
    assert registry.ingest_file(path).format == "txt"


def test_unsupported_extension(tmp_path):
    path = tmp_path / "scan.odt"
    path.write_bytes(b"x")
    with pytest.raises(UnsupportedFormatError, match=r"unsupported file type '\.odt'"):
        registry.ingest_file(path)


def test_missing_file(tmp_path):
    with pytest.raises(IngestError, match="not found"):
        registry.ingest_file(tmp_path / "nope.txt")


def test_document_without_text_is_rejected(tmp_path):
    path = tmp_path / "breaks.txt"
    path.write_text("* * *\n\n---\n", encoding="utf-8")
    with pytest.raises(IngestError, match="no usable text"):
        registry.ingest_file(path)


def test_plugin_ingestors(tmp_path, monkeypatch):
    class OdtIngestor:
        format = "odt"
        extensions = (".odt",)

        def ingest(self, path):
            return SourceDocument(source_path=str(path), format="odt", sha256="0", blocks=[])

    class EP:
        name = "odt"

        def load(self):
            return OdtIngestor

    monkeypatch.setattr(registry, "entry_points", lambda group: [EP()])
    path = tmp_path / "x.odt"
    path.write_bytes(b"")
    with pytest.raises(IngestError, match="no usable text"):
        registry.ingest_file(path)


def test_unreadable_file_is_ingest_error(tmp_path, monkeypatch):
    path = tmp_path / "locked.txt"
    path.write_text("Hello.", encoding="utf-8")

    def deny(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_bytes", deny)
    with pytest.raises(IngestError, match="cannot be read: Permission denied") as exc_info:
        registry.ingest_file(path)
    assert isinstance(exc_info.value.__cause__, PermissionError)


def test_nul_characters_are_removed_from_text_files(tmp_path):
    path = tmp_path / "nul.txt"
    path.write_text("Le chat\x00 dort.\n\n\x00\n\nIl pleut.", encoding="utf-8")
    doc = registry.ingest_file(path)
    assert [b.text for b in doc.blocks] == ["Le chat dort.", "Il pleut."]


def test_control_characters_are_cleaned_from_every_block(tmp_path):
    path = tmp_path / "controls.txt"
    path.write_text("Le chat\x0cdort.\x01\n\nIl\x0bpleut.\x1f", encoding="utf-8")
    doc = registry.ingest_file(path)
    assert [b.text for b in doc.blocks] == ["Le chat\ndort.", "Il\npleut."]


def test_nul_characters_are_removed_from_plugin_ingestor_blocks(tmp_path, monkeypatch):
    from corelata.ingest.base import make_blocks
    from corelata.schema import BlockKind

    class OdtIngestor:
        format = "odt"
        extensions = (".odt",)

        def ingest(self, path):
            blocks = make_blocks(str(path), [(BlockKind.PARAGRAPH, "Bon\x00jour\x0c.", None)])
            return SourceDocument(source_path=str(path), format="odt", sha256="0", blocks=blocks)

    class EP:
        name = "odt"

        def load(self):
            return OdtIngestor

    monkeypatch.setattr(registry, "entry_points", lambda group: [EP()])
    path = tmp_path / "x.odt"
    path.write_bytes(b"")
    assert [b.text for b in registry.ingest_file(path).blocks] == ["Bonjour\n."]


def _broken_ingestor(monkeypatch, error):
    class Broken:
        format = "odt"
        extensions = (".odt",)

        def ingest(self, path):
            raise error(path) if callable(error) else error

    monkeypatch.setattr(registry, "available_ingestors", lambda: [Broken()])


def test_any_other_ingestor_exception_becomes_an_ingest_error(tmp_path, monkeypatch):
    _broken_ingestor(monkeypatch, ValueError("bad header"))
    path = tmp_path / "scan.odt"
    path.write_bytes(b"x")
    message = r"^scan\.odt could not be read \(ValueError: bad header\)$"
    with pytest.raises(IngestError, match=message):
        registry.ingest_file(path)


def test_an_ingestor_exception_without_a_message_names_its_type(tmp_path, monkeypatch):
    _broken_ingestor(monkeypatch, KeyError())
    path = tmp_path / "scan.odt"
    path.write_bytes(b"x")
    with pytest.raises(IngestError, match=r"^scan\.odt could not be read \(KeyError\)$"):
        registry.ingest_file(path)


def test_an_ingestor_exception_never_names_the_servers_path(tmp_path, monkeypatch):
    _broken_ingestor(monkeypatch, lambda path: ValueError(f"cannot identify file '{path}'"))
    path = tmp_path / "scan.odt"
    path.write_bytes(b"x")
    with pytest.raises(IngestError) as caught:
        registry.ingest_file(path)
    assert str(tmp_path) not in str(caught.value)
    assert "cannot identify file 'scan.odt'" in str(caught.value)


def test_memory_error_from_an_ingestor_is_not_blamed_on_the_file(tmp_path, monkeypatch):
    _broken_ingestor(monkeypatch, MemoryError())
    path = tmp_path / "scan.odt"
    path.write_bytes(b"x")
    with pytest.raises(MemoryError):
        registry.ingest_file(path)


def test_the_web_upload_picker_accepts_exactly_the_built_in_extensions(monkeypatch):
    """CRL-109: the browser's ACCEPTED list is pinned to the registry, so neither drifts."""
    monkeypatch.setattr(registry, "entry_points", lambda group: [])  # built-ins only
    built_in = {e for i in registry.available_ingestors() for e in i.extensions}
    page = Path(__file__).parents[3] / "web" / "src" / "pages" / "new" / "AddSources.tsx"
    found = re.search(r"export const ACCEPTED = \[([^\]]*)\];", page.read_text(encoding="utf-8"))
    assert found, f"ACCEPTED not found in {page}"
    accepted = re.findall(r'"([^"]+)"', found.group(1))
    assert len(accepted) == len(set(accepted))
    assert set(accepted) == built_in
