"""Text that every layer can store and export: XML 1.0 (DOCX) and Postgres refuse some
characters that documents, model replies and pasted edits can carry."""

import re

_LINE_BREAKS = str.maketrans({"\x0b": "\n", "\x0c": "\n"})  # vertical tab, form feed
# NUL and the other C0 controls except tab, line feed and carriage return; the two
# non-characters U+FFFE and U+FFFF; lone surrogates.
_ILLEGAL = re.compile("[\x00-\x08\x0e-\x1f￾￿\ud800-\udfff]")


def clean_text(text: str) -> str:
    """`text` with vertical tabs and form feeds as line breaks and every character XML 1.0
    forbids removed; tabs, line feeds and carriage returns stay."""
    return _ILLEGAL.sub("", text.translate(_LINE_BREAKS))


_WORD = re.compile(r"[A-Za-z][A-Za-z\-']{3,}")


def key_terms(statement: str) -> list[str]:
    """Distinct casefolded words of four letters or more, in order of first appearance."""
    seen: dict[str, None] = {}
    for w in _WORD.findall(statement):
        seen.setdefault(w.casefold(), None)
    return list(seen)
