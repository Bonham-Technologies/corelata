"""The engine's check of a judgment's uncertainty wording (CRL-136, ICD 203 D.6.e(2)(a)-(b)).

ICD 203's rules on expressing uncertainty are mechanical: use the terms of one row of the
likelihood table, and never put a confidence level and a degree of likelihood in the same
sentence. With the lexicon's `likelihood_alternates`, `unlisted_probability_words` or
`confidence_phrases` the engine checks every key judgment and every `judgment` claim, and
`audit.apply_engine_checks` fails icd203.tc.2 on what it finds.

Matching ignores case, treats any run of whitespace as one space and takes whole words only, so
"likely" is not found inside "unlikely". At each place in the text the longest listed phrase
wins, so "very likely" is one term, not "likely", and "almost certainly" is the lexicon's
"almost certain" rather than the unlisted "certainly". A likelihood term or alternate also
matches its adverb ("almost certain" -> "almost certainly", "probable" -> "probably"), the
"(ly)" forms of the ICD 203 table. A sentence ends at ".", "!" or "?" followed by whitespace; a
claim's text is checked as stored, one sentence or several."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from corelata.schema import ClaimKind, ReportBody
from corelata.standards.schema import Lexicon

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class WordKind(StrEnum):
    TERM = "term"  # a likelihood term of the lexicon
    ALTERNATE = "alternate"
    UNLISTED = "unlisted"
    CONFIDENCE = "confidence"


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _adverb(term: str) -> str | None:
    """The "-ly" form ICD 203's table writes as "(ly)"; None when the term already is one."""
    if term.endswith("ly"):
        return None
    return term[:-1] + "y" if term.endswith("ble") else term + "ly"


@dataclass(frozen=True)
class Found:
    kind: WordKind
    phrase: str  # the listed phrase, normalised (a term's adverb is reported as the term)


class WordingCheck:
    """The lexicon's listed wording, compiled into one whole-word, longest-first pattern."""

    def __init__(self, lexicon: Lexicon) -> None:
        forms: dict[str, Found] = {}
        listed = [
            (WordKind.TERM, [t.term for t in lexicon.likelihood], True),
            (WordKind.ALTERNATE, lexicon.likelihood_alternates, True),
            (WordKind.UNLISTED, lexicon.unlisted_probability_words, False),
            (WordKind.CONFIDENCE, lexicon.confidence_phrases, False),
        ]
        for kind, phrases, with_adverb in listed:  # earlier lists win a phrase listed twice
            for phrase in map(_norm, phrases):
                adverb = _adverb(phrase) if with_adverb else None
                for form in (phrase, adverb):
                    if form:
                        forms.setdefault(form, Found(kind, phrase))
        self.forms = forms
        alternatives = [
            r"\s+".join(map(re.escape, form.split()))
            for form in sorted(forms, key=lambda f: (-len(f), f))
        ]
        self.pattern = re.compile(rf"(?<!\w)(?:{'|'.join(alternatives)})(?!\w)", re.IGNORECASE)

    def find(self, text: str) -> list[Found]:
        """The listed wording in `text`, in order, each place matched once."""
        return [self.forms[_norm(m.group())] for m in self.pattern.finditer(text)]

    def problems(self, text: str, likelihood_term: str | None = None) -> list[str]:
        """What is wrong with one judgment's wording, each problem a phrase completing its name:
        a confidence phrase in a sentence with a likelihood, wording off the lexicon's row, and
        (for a claim) a likelihood term its text does not use."""
        out: list[str] = []
        for sentence in _SENTENCE_END.split(text):
            found = self.find(sentence)
            confidence = _unique(f.phrase for f in found if f.kind is WordKind.CONFIDENCE)
            likelihood = _unique(f.phrase for f in found if f.kind is not WordKind.CONFIDENCE)
            if confidence and likelihood:
                out.append(
                    "puts a confidence level and a likelihood in one sentence "
                    f"({_quoted(confidence + likelihood)})"
                )
        found = self.find(text)
        off = _unique(f.phrase for f in found if f.kind in (WordKind.ALTERNATE, WordKind.UNLISTED))
        if off:
            out.append(f"uses probability wording outside the lexicon ({_quoted(off)})")
        terms = {f.phrase for f in found if f.kind is WordKind.TERM}
        if likelihood_term is not None and _norm(likelihood_term) not in terms:
            out.append(f"does not use its likelihood term '{likelihood_term}' in its text")
        return out


def _unique(phrases: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(phrases))


def _quoted(phrases: list[str]) -> str:
    return ", ".join(f"'{p}'" for p in phrases)


@dataclass
class WordingProblems:
    problems: list[str]  # "key judgment 1 ..." or "c3 ...", in report order
    claim_ids: list[str]  # the claims named, in report order


def wording_problems(draft: ReportBody, lexicon: Lexicon) -> WordingProblems:
    """Every key judgment's and `judgment` claim's wording problems (CRL-136); none for a
    lexicon without the wording lists, which the engine does not check."""
    if not lexicon.checks_wording:
        return WordingProblems([], [])
    check = WordingCheck(lexicon)
    problems: list[str] = []
    for n, kj in enumerate(draft.key_judgments, start=1):
        problems += [f"key judgment {n} {p}" for p in check.problems(kj.text)]
    claim_ids: list[str] = []
    for c in draft.claims:
        if c.kind is not ClaimKind.JUDGMENT:
            continue
        found = check.problems(c.text, c.likelihood_term)
        if found:
            claim_ids.append(c.id)
            problems += [f"{c.id} {p}" for p in found]
    return WordingProblems(problems, claim_ids)
