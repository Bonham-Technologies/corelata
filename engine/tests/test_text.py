import pytest

from corelata.text import clean_text, key_terms


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("plain", "plain"),
        ("a\x00b", "ab"),
        ("a\x0cb", "a\nb"),
        ("tab\tand\nnewline\r", "tab\tand\nnewline\r"),
        ("\ud800x", "x"),
    ],
)
def test_clean_text(raw, cleaned):
    assert clean_text(raw) == cleaned


def test_key_terms_dedupes_and_folds():
    assert key_terms("The Port of Varna, the port!") == ["port", "varna"]
