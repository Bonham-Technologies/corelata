import pytest

from corelata.schema import BlockKind, Source, SourceKind, SourceUnit, split_ref, unit_ref


def test_unit_ref_roundtrip():
    assert unit_ref("src1", "u3") == "src1/u3"
    assert split_ref("src1/u3") == ("src1", "u3")


@pytest.mark.parametrize("bad", ["u3", "src1/", "/u3", "a/b/c", ""])
def test_split_ref_rejects_malformed(bad):
    with pytest.raises(ValueError, match="unit ref"):
        split_ref(bad)


def test_source_refs():
    src = Source(
        id="src1",
        kind=SourceKind.FILE,
        name="a.txt",
        format="txt",
        sha256="00",
        units=[SourceUnit(id="u1", text="x", locator="para 1", kind=BlockKind.PARAGRAPH)],
    )
    assert src.refs() == ["src1/u1"]
