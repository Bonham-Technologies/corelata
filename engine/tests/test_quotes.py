import pytest

from corelata.quotes import QuoteCheck, quote_found, quote_problems, quote_words
from corelata.schema import ReportBody

UNIT = (
    "Tarvos Port Authority, quarterly bulletin, 3 July 2026. The second container terminal at "
    "Tarvos (Terminal B) entered full service on 12 May 2026, raising the port's annual\n"
    "handling capacity from 1.1 million to 1.9 million TEU."
)


def test_words_set_aside_case_whitespace_quote_marks_and_punctuation():
    assert quote_words("  The “port’s”\n\tCAPACITY, ") == ["the", "port", "s", "capacity"]
    assert quote_words(" Ｔｅｒｍｉｎａｌ") == ["terminal"]  # NFKC: no-break space, full width


@pytest.mark.parametrize(
    "quote",
    [
        "entered full service on 12 May 2026",
        "ENTERED   full\nservice",
        "“the port’s annual handling capacity”",
        '"Terminal B" entered full service',
        "from 1.1 million to 1.9 million TEU",
        "Tarvos Port Authority",
    ],
)
def test_a_quote_in_the_unit_is_found(quote):
    assert quote_found(quote, UNIT)


@pytest.mark.parametrize(
    "quote",
    [
        "will shut the oil terminal for the whole winter",  # fabricated
        "entered full service on 21 May 2026",  # a changed figure
        "entered service on 12 May 2026",  # a dropped word
        "terminal entered full service",  # words of the unit, not a run of them
        "",
        "“ ”",
        UNIT + " And more.",  # longer than the unit
    ],
)
def test_a_quote_not_in_the_unit_is_not_found_exactly(quote):
    assert not quote_found(quote, UNIT)


def test_below_one_the_threshold_tolerates_a_word_but_not_a_different_passage():
    dropped = "the second container terminal at Tarvos Terminal B entered service on 12 May 2026"
    assert not quote_found(dropped, UNIT)
    assert quote_found(dropped, UNIT, threshold=0.85)
    assert not quote_found(dropped, UNIT, threshold=0.99)
    assert not quote_found("will shut the oil terminal for the whole winter", UNIT, 0.5)
    assert not quote_found(UNIT + " And more.", UNIT, 0.5)  # longer than the unit


def _draft(claims: list[dict]) -> ReportBody:
    return ReportBody.model_validate(
        {
            "title": "t",
            "handling_marking": "UNCLASSIFIED",
            "key_judgments": [],
            "scope_note": "s",
            "sources": [],
            "analysis": [],
            "alternatives": [],
            "gaps_and_indicators": [],
            "claims": claims,
        }
    )


def _check(required: bool, digested: frozenset[str] = frozenset()) -> QuoteCheck:
    units = {"src1/u1": UNIT, "src2/u1": "Kelmar volumes fell 22 percent in June."}
    return QuoteCheck(
        required=required,
        threshold=1.0,
        unit_text=units.get,
        needs_quote=lambda ref: ref.split("/")[0] not in digested,
    )


def test_quote_problems_name_the_unit_and_the_claim_in_claim_order():
    draft = _draft(
        [
            {"id": "c1", "text": "t", "kind": "fact", "evidence": ["src1/u1"]},
            {
                "id": "c2",
                "text": "t",
                "kind": "fact",
                "evidence": ["src1/u1", "src2/u1"],
                "quotes": [
                    {"ref": "src2/u1", "text": "volumes fell 40 percent"},
                    {"ref": "src9/u1", "text": "anything"},
                    {"ref": "src1/u1", "text": "Terminal B"},
                ],
            },
            {"id": "c3", "text": "t", "kind": "fact", "evidence": []},
        ]
    )
    assert quote_problems(draft, _check(required=False)) == {
        "c2": ["quote not found in src2/u1 (c2)", "quote not found in src9/u1 (c2)"]
    }
    assert quote_problems(draft, _check(required=True)) == {
        "c1": ["no quote from src1/u1 (c1)"],
        "c2": ["quote not found in src2/u1 (c2)", "quote not found in src9/u1 (c2)"],
    }
    assert quote_problems(draft, _check(required=True, digested=frozenset({"src1"}))) == {
        "c2": ["quote not found in src2/u1 (c2)", "quote not found in src9/u1 (c2)"]
    }
