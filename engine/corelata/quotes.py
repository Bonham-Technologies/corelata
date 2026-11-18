"""Quote-anchored claim evidence (CRL-93): does a claim's quote appear in the unit it cites?

A quote and a unit are compared as words: both are NFKC-normalised and casefolded and split into
runs of letters and digits, so case, whitespace, quote marks (straight or curly) and other
punctuation never decide a match. With `threshold` 1.0 (the default) the quote's words must
appear in the unit as one unbroken run, in order. Below 1.0 the best window of the unit's words
as long as the quote must share at least that ratio of the quote's words in order
(`difflib.SequenceMatcher`); that tolerates OCR noise and a dropped word, and also a changed
figure, which is why exact is the default."""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher

from corelata.schema.report import Claim, ReportBody

_WORDS = re.compile(r"\w+")


def quote_words(text: str) -> list[str]:
    return _WORDS.findall(unicodedata.normalize("NFKC", text).casefold())


def _contains(words: list[str], quote: list[str]) -> bool:
    n = len(quote)
    first = quote[0]
    return any(words[i] == first and words[i : i + n] == quote for i in range(len(words) - n + 1))


def _fuzzy(words: list[str], quote: list[str], threshold: float) -> bool:
    n = len(quote)
    need = math.ceil(threshold * n)
    wanted = Counter(quote)
    window: Counter[str] = Counter()
    for i, w in enumerate(words):  # a sliding window of n words; skip any too unlike the quote
        window[w] += 1
        if i >= n:
            window[words[i - n]] -= 1
        if i < n - 1 or sum((window & wanted).values()) < need:
            continue
        span = words[i - n + 1 : i + 1]
        if SequenceMatcher(None, span, quote, autojunk=False).ratio() >= threshold:
            return True
    return False


def quote_found(quote: str, unit_text: str, threshold: float = 1.0) -> bool:
    """`quote` appears in `unit_text` (module docstring). A quote with no words is never found."""
    q = quote_words(quote)
    if not q:
        return False
    words = quote_words(unit_text)
    if _contains(words, q):
        return True
    if threshold >= 1.0 or len(words) < len(q):  # a quote longer than its unit never matches
        return False
    return _fuzzy(words, q, threshold)


@dataclass(frozen=True)
class QuoteCheck:
    """What the engine needs to check quotes for one run (`StageContext.quote_check`)."""

    required: bool  # pipeline.evidence_quotes is `required`
    threshold: float  # pipeline.quote_match_threshold
    unit_text: Callable[[str], str | None]  # None: not a unit of this run
    needs_quote: Callable[[str], bool]  # False for a unit the writer saw only as a digest


def quote_problems(draft: ReportBody, check: QuoteCheck) -> dict[str, list[str]]:
    """Claim id → what is wrong with its quotes, in claim order; claims without problems are
    left out. Each entry is a finding's evidence phrase: "quote not found in src2/u14 (c3)",
    or with `required` "no quote from src1/u2 (c3)"."""
    out: dict[str, list[str]] = {}
    for claim in draft.claims:
        problems = _claim_problems(claim, check)
        if problems:
            out[claim.id] = problems
    return out


def _claim_problems(claim: Claim, check: QuoteCheck) -> list[str]:
    problems: list[str] = []
    for q in claim.quotes:
        text = check.unit_text(q.ref)
        if text is None or not quote_found(q.text, text, check.threshold):
            problems.append(f"quote not found in {q.ref} ({claim.id})")
    if check.required:
        quoted = {q.ref for q in claim.quotes}
        problems += [
            f"no quote from {ref} ({claim.id})"
            for ref in dict.fromkeys(claim.evidence)
            if ref not in quoted and check.needs_quote(ref)
        ]
    return problems
